#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用题库导入（PostgreSQL）。

读取 scripts/data/qbank/qb_*.py 中的 QUESTIONS（字段：subject/chapter/content/
options/answer/analysis/difficulty），按 subject 名称解析 subject_id（缺失则按
subject_catalog 自动建科），逐题校验、内容指纹去重、默认 dry-run 预览，
--apply 时备份 quiz_questions 为 JSONL 并单事务写入。

来源诚实标注 source_kind='chapter_exercise'，不伪装历年真题。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import psycopg
from scripts._conn import dsn
from scripts.data.subject_catalog import PUBLIC_COURSES, SUBJECT_CATALOG

QBANK_DIR = Path(__file__).resolve().parent.parent / "data" / "qbank"
BACKUP_DIR = Path(r"D:\研途\题库建设\backup")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_quiz_bank")

stats = {"parsed": 0, "valid": 0, "invalid": 0, "duplicate": 0, "inserted": 0}
by_subject = Counter()
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
    rec["_content"] = content
    rec["_options"] = [{"key": k, "text": t} for k, t in zip(keys, texts, strict=False)]
    rec["_answer"] = answer
    return True, "ok"


def slug_for(subject: str) -> str:
    if subject in PUBLIC_COURSES:
        return PUBLIC_COURSES[subject]
    for e in SUBJECT_CATALOG:
        if e["name"] == subject:
            return e["slug"]
    return "unknown"


def resolve_subject_id(conn, subject: str) -> int | None:
    """按名称查 id；不存在则按 catalog 建科。"""
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
    for fp in sorted(QBANK_DIR.glob("qb_*.py")):
        if fp.name.startswith("_"):
            continue
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
            rec = {
                "subject": clean_text(item["subject"]),
                "chapter": clean_text(item.get("chapter", "")),
                "content": item["_content"],
                "options": item["_options"],
                "answer": item["_answer"],
                "analysis": clean_text(item.get("analysis", "")),
                "difficulty": int(item.get("difficulty", 3) or 3),
            }
            rec["_fp"] = content_fingerprint(rec["content"], rec["options"])
            rec["_file"] = fp.stem
            records.append(rec)
    return records


def make_record(subject: str, subject_id: int, rec: dict, seq: int) -> dict:
    slug = slug_for(subject)
    external_id = f"08bank_{slug}_{seq:04d}"
    return {
        "content": rec["content"],
        "options": rec["options"],
        "answer": rec["answer"],
        "analysis": rec["analysis"],
        "question_type": "single",
        "answer_type": "objective",
        "difficulty": rec["difficulty"],
        "source_kind": "chapter_exercise",
        "source_label": f"自建标准题库·{subject}（章节习题）",
        "year": None,
        "paper": None,
        "source_paper": None,
        "external_id": external_id,
        "subject_id": subject_id,
        "subject": subject,
        "chapter_id": None,
        "chapter": rec["chapter"] or None,
        "knowledge_point": None,
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
    needs_review, images
) VALUES (
    %(content)s, CAST(%(options)s AS jsonb), %(answer)s, %(analysis)s,
    NULL, NULL, 'single', 'objective', %(difficulty)s, 'chapter_exercise',
    %(source_label)s, NULL, NULL, NULL, %(external_id)s,
    %(subject_id)s, %(subject)s, %(chapter_id)s, %(chapter)s, %(knowledge_point)s,
    'high', NULL, TRUE, TRUE, NULL,
    'llm_generated', 0.9, TRUE, FALSE, FALSE, 0, 'pending', '[]', NULL,
    NOW(), NOW(), 0.9, 'external_import', FALSE, '[]'
)
ON CONFLICT (external_id) DO NOTHING
"""


def backup_quiz_questions(conn, stamp: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"quiz_questions_{stamp}.jsonl"
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
                "source_label": rec["source_label"],
                "external_id": rec["external_id"],
                "subject_id": rec["subject_id"],
                "subject": rec["subject"],
                "chapter_id": rec["chapter_id"],
                "chapter": rec["chapter"],
                "knowledge_point": rec["knowledge_point"],
            }
            try:
                cur.execute(INSERT_SQL, params)
                if cur.rowcount > 0:
                    inserted += 1
                    stats["inserted"] += 1
                    by_subject[rec["subject"]] += 1
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                stats["duplicate"] += 1
            except Exception as exc:
                conn.rollback()
                log.warning("写入失败 %s: %s", rec.get("external_id"), exc)
        conn.commit()
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 08 工学 + 公共课题库")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = parser.parse_args()

    records = load_questions()
    log.info("解析 %d 题，校验通过 %d 题，无效 %d 题", stats["parsed"], stats["valid"], stats["invalid"])

    conn = psycopg.connect(dsn(), connect_timeout=10)
    try:
        # 去重：库内已有题干+选项指纹
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

        # 解析 subject_id
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
            for subj, cnt in Counter(r["subject"] for r in prepared).most_common():
                print(f"  {subj}: {cnt}")
            print("\n样例（前 3 题）:")
            for r in prepared[:3]:
                print(f"  [{r['subject']}] {r['content'][:42]} -> {r['answer']}")
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
    print("\n无效明细:")
    for item in invalid_cache:
        print("  ", item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
