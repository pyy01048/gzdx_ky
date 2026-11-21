#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""08 工学章节习题题库导入（PostgreSQL）。

数据源：D:\\研途\\题库建设\\08工学\\08_*.json（每题含 subject/subject_id/chapter/
content/options/answer/analysis）。题目为 AI 生成的章节标准习题，来源诚实标注，
不伪装成历年真题。

流程：逐题校验 -> content+options 指纹去重 -> 默认 dry-run 预览 -> --apply 入库。
写库前备份 quiz_questions 为 JSONL，单事务、失败回滚，ON CONFLICT (external_id) DO NOTHING。
字段映射遵循 11 文档质量门：validation_status 由 081 触发器写入 pass。
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import psycopg

from scripts._conn import dsn  # 口令来自 .env / PG_PASSWORD

DATA_DIR = Path(r"D:\研途\题库建设\08工学")
EXT_PREFIX = "08eng"
BACKUP_DIR = Path(r"D:\研途\题库建设\backup")

SUBJECT_PREFIX = {
    "数字电子技术": "de",
    "模拟电子技术": "ae",
    "电路": "circuit",
    "信号与系统": "ss",
    "通信原理": "cp",
    "数字信号处理": "dsp",
    "电磁场与电磁波": "em",
    "自动控制原理": "ac",
    "半导体物理": "sp",
    "传感器技术": "sensor",
    "单片机原理": "mcu",
    "电力电子技术": "pe",
    "微机原理与接口技术": "mc",
    "电机与拖动": "md",
    "电力系统分析": "ps",
    "过程控制": "pc",
    "高电压技术": "hv",
    "电路分析": "ca",
    "测控电路": "mc_circuit",
    "激光原理": "laser",
    "电子技术基础": "eb",
    "光学与工程光学": "oe",
    "光学": "optics",
    "软件工程": "se",
    "Python程序设计": "python",
    "C/C++语言": "ccpp",
    "生物医学工程": "bme",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_08_engineering")

stats = {
    "parsed": 0,
    "valid": 0,
    "invalid": 0,
    "duplicate": 0,
    "inserted": 0,
    "skipped_invalid": 0,
}
by_subject = Counter()
by_file = Counter()
invalid_cache: list = []


def clean_text(s) -> str:
    """去空白、控制字符与常见 HTML 实体，保留中文与符号。"""
    if s is None:
        return ""
    s = str(s)
    s = "".join(ch for ch in s if ch >= "\u0001" or ch in ("\n", "\t", "\r"))
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    s = s.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    s = " ".join(s.split())
    return s.strip()


def content_fingerprint(stem: str, options: list) -> str:
    """题干 + 选项文本指纹，用于跨源去重。"""
    parts = [stem.strip()]
    for o in options or []:
        if isinstance(o, dict):
            parts.append(str(o.get("text", "")).strip())
        else:
            parts.append(str(o).strip())
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def validate_question(rec: dict) -> tuple[bool, str]:
    """逐题质量门：题干、选项、答案、解析、科目与 subject_id 必填。"""
    if not rec.get("subject_id"):
        return False, "missing_subject_id"
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
    rec["_content"] = content
    rec["_options"] = [{"key": k, "text": t} for k, t in zip(keys, texts, strict=False)]
    rec["_answer"] = answer
    return True, "ok"


def make_record(
    subject: str,
    subject_id: int,
    chapter: str,
    content: str,
    options: list,
    answer: str,
    analysis: str,
    external_id: str,
) -> dict:
    source_label = f"自建标准题库·{subject}（08工学章节习题）"
    return {
        "content": content,
        "options": options,
        "answer": answer,
        "analysis": analysis,
        "question_type": "single",
        "answer_type": "objective",
        "difficulty": 3,
        "source_kind": "chapter_exercise",
        "source_label": source_label,
        "year": None,
        "paper": None,
        "source_paper": None,
        "external_id": external_id,
        "subject_id": subject_id,
        "subject": subject,
        "chapter": chapter or None,
        "chapter_id": None,
        "knowledge_point": None,
    }


def load_existing_fingerprints(conn) -> set:
    """读取库内已有题目的题干+选项指纹。"""
    got: set = set()
    with conn.cursor() as cur:
        cur.execute("SELECT content, options FROM quiz_questions")
        for content, options in cur.fetchall():
            opts = options
            if isinstance(opts, str):
                try:
                    opts = json.loads(opts)
                except ValueError:
                    opts = []
            got.add(content_fingerprint(content or "", opts or []))
    return got


def backup_quiz_questions(conn, stamp: str) -> Path:
    """写库前把 quiz_questions 全量导出 JSONL 备份。"""
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
    NULL, NULL, 'single', 'objective', 3, 'chapter_exercise',
    %(source_label)s, NULL, NULL, NULL, %(external_id)s,
    %(subject_id)s, %(subject)s, %(chapter_id)s, %(chapter)s, %(knowledge_point)s,
    'high', NULL, TRUE, TRUE, NULL,
    'llm_generated', 0.9, TRUE, FALSE, FALSE, 0, 'pending', '[]', NULL,
    NOW(), NOW(), 0.9, 'external_import', FALSE, '[]'
)
ON CONFLICT (external_id) DO NOTHING
"""


def write_records(conn, records: list) -> int:
    inserted = 0
    with conn.cursor() as cur:
        for rec in records:
            params = {
                "content": rec["content"],
                "options": json.dumps(rec["options"], ensure_ascii=False),
                "answer": rec["answer"],
                "analysis": rec["analysis"],
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
                    by_file[rec.get("_file", "unknown")] += 1
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                stats["duplicate"] += 1
            except Exception as exc:
                conn.rollback()
                log.warning("写入失败 %s: %s", rec.get("external_id"), exc)
        conn.commit()
    return inserted


def load_files() -> list:
    """读取 08工学 目录下全部 08_*.json，返回校验后的记录列表。"""
    files = sorted(glob.glob(str(DATA_DIR / "08_*.json")))
    if not files:
        log.error("未找到题库 JSON：%s", DATA_DIR)
        return []
    records = []
    for fp in files:
        try:
            data = json.loads(Path(fp).read_text(encoding="utf-8"))
        except Exception as exc:
            log.error("JSON 解析失败 %s: %s", fp, exc)
            continue
        stem = Path(fp).stem
        for idx, item in enumerate(data, 1):
            stats["parsed"] += 1
            ok, reason = validate_question(item)
            if not ok:
                stats["skipped_invalid"] += 1
                invalid_cache.append(
                    {"file": stem, "idx": idx, "reason": reason, "content": item.get("content", "")[:40]}
                )
                continue
            stats["valid"] += 1
            subject = clean_text(item.get("subject", ""))
            prefix = SUBJECT_PREFIX.get(subject)
            if prefix is None:
                stats["skipped_invalid"] += 1
                invalid_cache.append(
                    {"file": stem, "idx": idx, "reason": "unknown_subject", "content": item.get("content", "")[:40]}
                )
                continue
            external_id = f"{EXT_PREFIX}_{prefix}_{Path(fp).stem.split('_')[-1]}_{idx:03d}"
            rec = make_record(
                subject=subject,
                subject_id=int(item["subject_id"]),
                chapter=clean_text(item.get("chapter", "")),
                content=item["_content"],
                options=item["_options"],
                answer=item["_answer"],
                analysis=clean_text(item.get("analysis", "")),
                external_id=external_id,
            )
            rec["_file"] = stem
            rec["_fp"] = content_fingerprint(rec["content"], rec["options"])
            records.append(rec)
    return records


def dedup(records: list, existing: set) -> list:
    kept, seen = [], set(existing)
    for rec in records:
        fp = rec["_fp"]
        if fp in seen:
            stats["duplicate"] += 1
            continue
        seen.add(fp)
        kept.append(rec)
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 08 工学题库到 quiz_questions")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run 预览）")
    args = parser.parse_args()

    records = load_files()
    log.info("解析 %d 题，校验通过 %d 题，无效 %d 题", stats["parsed"], stats["valid"], stats["skipped_invalid"])

    conn = psycopg.connect(dsn(), connect_timeout=10)
    try:
        existing = load_existing_fingerprints(conn)
        log.info("库内已有题目指纹 %d 个", len(existing))
        records = dedup(records, existing)
        log.info("去重后待写入 %d 题（重复弃 %d）", len(records), stats["duplicate"])

        if not args.apply:
            print("\n===== DRY-RUN 预览 =====")
            print(f"待写入: {len(records)} 题")
            for subj, cnt in Counter(r["subject"] for r in records).most_common():
                print(f"  {subj}: {cnt}")
            print("\n样例（前 3 题）:")
            for r in records[:3]:
                print(f"  [{r['subject']}] {r['content'][:42]} -> {r['answer']}")
            print("\n（dry-run，未写库；确认后加 --apply）")
            return 0

        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = backup_quiz_questions(conn, stamp)
        log.info("已备份 quiz_questions -> %s", backup)
        inserted = write_records(conn, records)
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
