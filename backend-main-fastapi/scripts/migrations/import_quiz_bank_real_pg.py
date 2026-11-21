#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实题库导入（PostgreSQL）。

读取 scripts/data/qbank/qb_real_*.py 中 QUESTIONS，在标准字段基础上支持
题库四分类与来源留痕：question_category / exam_type / source_platform /
source_url / year / paper / question_no。按 subject 名称解析 subject_id
（缺失且在 subject_catalog 中则建科，库内已有专业科目则直接复用），内容指纹
去重，默认 dry-run，--apply 写库。

来源诚实标注：每题带 source_platform / source_url / source_label，不伪装。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import psycopg
from scripts._conn import dsn
from scripts.data.subject_catalog import SUBJECT_CATALOG

QBANK_DIR = Path(__file__).resolve().parent.parent / "data" / "qbank"
BACKUP_DIR = Path(r"D:\研途\题库建设\backup")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_quiz_bank_real")

stats = {"parsed": 0, "valid": 0, "invalid": 0, "duplicate": 0, "inserted": 0}
by_subject = Counter()
by_category = Counter()
invalid_cache: list = []


def clean_text(s) -> str:
    if s is None:
        return ""
    s = str(s)
    s = "".join(ch for ch in s if ch >= "\u0001" or ch in ("\n", "\t", "\r"))
    s = (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return " ".join(s.split()).strip()


def content_fingerprint(stem: str, options: list) -> str:
    parts = [stem.strip()]
    for o in options or []:
        if isinstance(o, dict):
            parts.append(str(o.get("text", "")).strip())
        else:
            parts.append(str(o).strip())
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def validate_question(rec: dict) -> tuple[bool, str]:
    content = clean_text(rec.get("content", ""))
    if len(content) < 4:
        return False, "stem_too_short"
    options = rec.get("options")
    if not isinstance(options, list) or len(options) != 4:
        return False, "options_not_four"
    keys, texts = [], []
    for o in options:
        if not isinstance(o, dict) or not o.get("key") or not str(o.get("text", "")).strip():
            return False, "option_malformed"
        keys.append(str(o["key"]).strip().upper())
        texts.append(clean_text(str(o.get("text", ""))))
    if len(set(keys)) != 4:
        return False, "option_key_duplicate"
    answer = clean_text(str(rec.get("answer", ""))).upper()
    if not answer or answer not in keys:
        return False, "answer_not_in_options"
    if not clean_text(rec.get("analysis", "")):
        return False, "missing_analysis"
    if not clean_text(rec.get("subject", "")):
        return False, "missing_subject"
    category = clean_text(str(rec.get("question_category", "习题")))
    if category not in ("真题", "练习题", "习题", "考研题"):
        return False, "invalid_question_category"
    rec["_content"] = content
    rec["_options"] = [{"key": k, "text": t} for k, t in zip(keys, texts, strict=False)]
    rec["_answer"] = answer
    rec["_category"] = category
    return True, "ok"


def resolve_subject_id(conn, subject: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM subjects WHERE name = %s", (subject,))
        row = cur.fetchone()
        if row:
            return int(row[0])
    for e in SUBJECT_CATALOG:
        if e["name"] == subject:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO subjects (code, name, short_name, category, "
                    "description, sort_order, is_active, is_custom) "
                    "VALUES (%s, %s, %s, %s, %s, 0, TRUE, TRUE) "
                    "ON CONFLICT (code) DO NOTHING RETURNING id",
                    (e["code"], e["name"], e["short_name"], e["category"], e["description"]),
                )
                r = cur.fetchone()
                if r:
                    return int(r[0])
                cur.execute("SELECT id FROM subjects WHERE code = %s", (e["code"],))
                r2 = cur.fetchone()
                return int(r2[0]) if r2 else None
    return None


def load_questions() -> list:
    records = []
    for fp in sorted(QBANK_DIR.glob("qb_real_*.py")):
        mod_name = f"scripts.data.qbank.{fp.stem}"
        mod = importlib.import_module(mod_name)
        for idx, item in enumerate(getattr(mod, "QUESTIONS", []), 1):
            stats["parsed"] += 1
            ok, reason = validate_question(item)
            if not ok:
                stats["invalid"] += 1
                invalid_cache.append(
                    {"file": fp.stem, "idx": idx, "reason": reason, "content": item.get("content", "")[:40]}
                )
                continue
            stats["valid"] += 1
            source_kind = clean_text(str(item.get("source_kind", "external_import")))
            year = item.get("year")
            if source_kind == "past_exam" and not year:
                # 数据库约束要求 past_exam 必须有 year；从来源文本中保守提取“YYYY年”，
                # 找不到明确年份时退为 external_import，避免伪造年份。
                hay = clean_text(str(item.get("source_label", ""))) + " " + clean_text(str(item.get("paper", "")))
                m = re.search(r"(?:19|20)\d{2}年", hay)
                if m:
                    year = int(m.group(0)[:4])
                else:
                    source_kind = "external_import"
            rec = {
                "subject": clean_text(item["subject"]),
                "chapter": clean_text(item.get("chapter", "")),
                "content": item["_content"],
                "options": item["_options"],
                "answer": item["_answer"],
                "analysis": clean_text(item.get("analysis", "")),
                "difficulty": int(item.get("difficulty", 3) or 3),
                "question_category": item["_category"],
                "source_kind": source_kind,
                "source_platform": clean_text(str(item.get("source_platform", ""))),
                "source_url": clean_text(str(item.get("source_url", ""))),
                "source_label": clean_text(str(item.get("source_label", ""))),
                "exam_type": clean_text(str(item.get("exam_type", ""))),
                "year": year,
                "paper": clean_text(str(item.get("paper", ""))),
                "question_no": item.get("question_no"),
            }
            rec["_fp"] = content_fingerprint(rec["content"], rec["options"])
            rec["_file"] = fp.stem
            records.append(rec)
    return records


def make_record(subject: str, subject_id: int, rec: dict, seq: int) -> dict:
    external_id = f"real_sub{subject_id:04d}_{seq:04d}"
    return {
        "content": rec["content"],
        "options": rec["options"],
        "answer": rec["answer"],
        "analysis": rec["analysis"],
        "question_type": "single",
        "answer_type": "objective",
        "difficulty": rec["difficulty"],
        "source_kind": rec["source_kind"],
        "source_label": rec["source_label"] or f"联网真实题库·{subject}（{rec['question_category']}）",
        "year": rec["year"],
        "paper": rec["paper"],
        "source_paper": None,
        "question_no": rec["question_no"],
        "external_id": external_id,
        "subject_id": subject_id,
        "subject": subject,
        "chapter_id": None,
        "chapter": rec["chapter"] or None,
        "knowledge_point": None,
        "question_category": rec["question_category"],
        "exam_type": rec["exam_type"] or None,
        "source_platform": rec["source_platform"] or None,
        "source_url": rec["source_url"] or None,
    }


INSERT_SQL = """
INSERT INTO quiz_questions (
    content, options, answer, analysis, rubric, max_score,
    question_type, answer_type, difficulty, source_kind,
    source_label, year, paper, source_paper, external_id,
    subject_id, subject, chapter_id, chapter, knowledge_point,
    confidence, quality, ai_generated, verified, variant_group,
    answer_source, answer_confidence, is_available, is_junk, is_retest,
    figure_missing, validation_status, validation_errors, validated_at,
    created_at, updated_at, classify_confidence, classify_source,
    needs_review, images, question_category, exam_type, source_platform, source_url
) VALUES (
    %(content)s, CAST(%(options)s AS jsonb), %(answer)s, %(analysis)s,
    NULL, NULL, 'single', 'objective', %(difficulty)s, %(source_kind)s,
    %(source_label)s, %(year)s, %(paper)s, NULL, %(external_id)s,
    %(subject_id)s, %(subject)s, %(chapter_id)s, %(chapter)s, %(knowledge_point)s,
    'high', NULL, TRUE, TRUE, NULL,
    'source_extract', 0.95, TRUE, FALSE, FALSE, 0, 'pending', '[]', NULL,
    NOW(), NOW(), 0.95, 'external_import', FALSE, '[]',
    %(question_category)s::question_category, %(exam_type)s, %(source_platform)s, %(source_url)s
)
ON CONFLICT (external_id) DO NOTHING
"""


def backup_quiz_questions(conn, stamp: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"quiz_questions_real_{stamp}.jsonl"
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM quiz_questions")
        cols = [d.name for d in cur.description]
        with path.open("w", encoding="utf-8") as f:
            while True:
                rows = cur.fetchmany(1000)
                if not rows:
                    break
                for row in rows:
                    f.write(json.dumps(dict(zip(cols, row, strict=False)), ensure_ascii=False, default=str) + "\n")
    return path


def write_records(conn, records: list) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for rec in records:
            params = {
                "content": rec["content"],
                "options": json.dumps(rec["options"], ensure_ascii=False),
                "answer": rec["answer"],
                "analysis": rec["analysis"],
                "difficulty": rec["difficulty"],
                "source_kind": rec["source_kind"],
                "source_label": rec["source_label"],
                "year": rec["year"],
                "paper": rec["paper"] or None,
                "external_id": rec["external_id"],
                "subject_id": rec["subject_id"],
                "subject": rec["subject"],
                "chapter_id": rec["chapter_id"],
                "chapter": rec["chapter"],
                "knowledge_point": rec["knowledge_point"],
                "question_category": rec["question_category"],
                "exam_type": rec["exam_type"],
                "source_platform": rec["source_platform"],
                "source_url": rec["source_url"],
            }
            try:
                cur.execute(INSERT_SQL, params)
                if cur.rowcount > 0:
                    conn.commit()
                    inserted += 1
                    stats["inserted"] += 1
                    by_subject[rec["subject"]] += 1
                    by_category[rec["question_category"]] += 1
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                stats["duplicate"] += 1
            except Exception as exc:
                conn.rollback()
                log.warning("写入失败 %s: %s", rec.get("external_id"), exc)
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="导入联网真实题库（四分类）")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = parser.parse_args()

    records = load_questions()
    log.info("解析 %d 题，校验通过 %d 题，无效 %d 题", stats["parsed"], stats["valid"], stats["invalid"])

    conn = psycopg.connect(dsn(), connect_timeout=10)
    try:
        existing = set()
        with conn.cursor() as cur:
            cur.execute("SELECT content, options FROM quiz_questions")
            for content, options in cur.fetchall():
                opts = options
                if isinstance(opts, str):
                    try:
                        opts = json.loads(opts)
                    except ValueError:
                        opts = []
                existing.add(content_fingerprint(content or "", opts or []))
        log.info("库内已有题目指纹 %d 个", len(existing))

        seen_subjects: dict = {}
        seq_by_subject = Counter()
        prepared = []
        for rec in records:
            if rec["_fp"] in existing:
                stats["duplicate"] += 1
                continue
            subject = rec["subject"]
            if subject not in seen_subjects:
                seen_subjects[subject] = resolve_subject_id(conn, subject)
            sid = seen_subjects[subject]
            if sid is None:
                stats["invalid"] += 1
                invalid_cache.append({"reason": "unknown_subject", "content": rec["content"][:40]})
                continue
            seq_by_subject[subject] += 1
            prepared.append(make_record(subject, sid, rec, seq_by_subject[subject]))
        conn.commit()
        log.info("去重+建科后待写入 %d 题（重复弃 %d）", len(prepared), stats["duplicate"])

        if not args.apply:
            print("\n===== DRY-RUN 预览 =====")
            print(f"待写入: {len(prepared)} 题")
            print("\n按四分类:")
            for cat, cnt in Counter(r["question_category"] for r in prepared).most_common():
                print(f"  {cat}: {cnt}")
            print("\n按科目:")
            for subj, cnt in Counter(r["subject"] for r in prepared).most_common():
                print(f"  {subj}: {cnt}")
            print("\n样例（前 3 题）:")
            for r in prepared[:3]:
                print(f"  [{r['question_category']}/{r['subject']}] {r['content'][:42]} -> {r['answer']}")
            print("\n（dry-run，未写库；确认后加 --apply）")
            return 0

        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = backup_quiz_questions(conn, stamp)
        log.info("已备份 quiz_questions -> %s", backup)
        inserted = write_records(conn, prepared)
        print("\n===== 导入完成 =====")
        print(f"备份: {backup}")
        print(f"成功插入: {inserted} 题")
    finally:
        conn.close()

    print("\n按科目:")
    for subj, cnt in by_subject.most_common():
        print(f"  {subj}: {cnt}")
    print("\n按四分类:")
    for cat, cnt in by_category.most_common():
        print(f"  {cat}: {cnt}")
    print("\n无效明细:")
    for item in invalid_cache:
        print("  ", item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
