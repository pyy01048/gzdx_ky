#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据治理回填脚本（R11）：幂等可中断的统一回填入口。

覆盖六类回填场景，每个子命令均满足：
  - 幂等：只更新尚未回填的行（WHERE ... IS NULL 或缺失），重复执行 no-op；
  - 可中断恢复：每批 ``--batch N`` 行后写 ``data_governance_runs.last_id`` 游标，
    中断后重跑同命令自动从游标续跑，不重头开始；
  - 审计：每次执行写一条 ``data_governance_runs`` 记录（running→done/failed），
    含 processed/updated/skipped 计数与 summary JSONB。

子命令：
  answers           回填 quiz_questions 缺失答案（从 analysis 启发式提取）
  options           回填 quiz_questions 缺失选项（从 content 启发式提取 A./B./C./D.）
  knowledge-links   题→知识点关联（quiz_questions.knowledge_point 字符串匹配 knowledge_points.name）
  scoreline-majors  分数线→专业映射（kaoyan_scorelines.major_id 按 major_code/major_name 回填）
  doc-metadata      文档四字段（content_kind 走 C-MODELS@1 ContentKind 分类 + size/source_format 补全）
  834-rescue        834 全量结构化（文件名含 834 的文档对应题目字段齐整化）

用法：
  python scripts/backfill_content_quality.py answers --dry-run
  python scripts/backfill_content_quality.py answers --apply --batch 500
  python scripts/backfill_content_quality.py doc-metadata --apply --batch 200

契约消费：C-MODELS@1（ContentKind 枚举，用于 doc-metadata 子命令的 content_kind 分类）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import psycopg

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


from models import ContentKind  # noqa: E402  -- C-MODELS@1
from scripts._conn import dsn  # noqa: E402

LOG = logging.getLogger("backfill_content_quality")

# 单次回填运行的游标与计数状态。
RunState = dict[str, Any]
# 子命令返回的统计结果。
CmdResult = dict[str, int]

# 审计表 DDL（幂等创建）。last_id 是可中断恢复的游标。
_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS data_governance_runs (
    id          BIGSERIAL PRIMARY KEY,
    command     TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'running',
    dry_run     BOOLEAN     NOT NULL DEFAULT TRUE,
    batch_size  INTEGER,
    processed   INTEGER     NOT NULL DEFAULT 0,
    updated     INTEGER     NOT NULL DEFAULT 0,
    skipped     INTEGER     NOT NULL DEFAULT 0,
    last_id     BIGINT      NOT NULL DEFAULT 0,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    summary     JSONB,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS ix_dgr_command_status ON data_governance_runs (command, status);
"""

SUBCOMMANDS: tuple[str, ...] = (
    "answers",
    "options",
    "knowledge-links",
    "scoreline-majors",
    "doc-metadata",
    "834-rescue",
)


# --------------------------------------------------------------------------- #
# 审计与游标
# --------------------------------------------------------------------------- #
def ensure_audit_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(_AUDIT_DDL)
    conn.commit()


def open_run(conn: psycopg.Connection, command: str, dry_run: bool, batch_size: int | None) -> RunState:
    """开一个 run 记录；若有同命令的 running 记录则续跑（可中断恢复）。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, last_id, processed, updated, skipped "
            "FROM data_governance_runs "
            "WHERE command = %s AND status = 'running' AND dry_run = %s "
            "ORDER BY id DESC LIMIT 1",
            (command, dry_run),
        )
        row = cur.fetchone()
        if row:
            LOG.info("续跑 run_id=%s 从 last_id=%s", row[0], row[1])
            return {"id": row[0], "last_id": row[1], "processed": row[2], "updated": row[3], "skipped": row[4]}
        cur.execute(
            "INSERT INTO data_governance_runs (command, dry_run, batch_size) VALUES (%s, %s, %s) RETURNING id",
            (command, dry_run, batch_size),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
        LOG.info("新建 run_id=%s", run_id)
        return {"id": run_id, "last_id": 0, "processed": 0, "updated": 0, "skipped": 0}


def checkpoint(
    conn: psycopg.Connection,
    run: RunState,
    last_id: int,
    processed: int,
    updated: int,
    skipped: int,
) -> None:
    """每批处理后写游标（同事务外独立提交，保证游标可见）。"""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE data_governance_runs SET last_id = %s, processed = %s, updated = %s, skipped = %s WHERE id = %s",
            (last_id, processed, updated, skipped, run["id"]),
        )
    conn.commit()


def close_run(
    conn: psycopg.Connection,
    run: RunState,
    status: str,
    summary: dict[str, Any],
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE data_governance_runs "
            "SET status = %s, finished_at = now(), summary = %s::jsonb, error = %s "
            "WHERE id = %s",
            (status, json.dumps(summary, ensure_ascii=False), error, run["id"]),
        )
    conn.commit()


def _init_counters(run: RunState) -> tuple[int, int, int, int]:
    """从 run 状态恢复计数器与游标（可中断续跑）。返回 (processed, updated, skipped, last_id)。"""
    return run["processed"], run["processed"], run["processed"], run["last_id"]


def _result(processed: int, updated: int, skipped: int, last_id: int) -> CmdResult:
    """构造子命令返回的统计 dict。"""
    return {"processed": processed, "updated": updated, "skipped": skipped, "last_id": last_id}


# --------------------------------------------------------------------------- #
# 启发式提取器
# --------------------------------------------------------------------------- #
_ANSWER_PATTERNS = [
    re.compile(r"(?:正确答案|参考答案|答案)\s*[:：：]\s*([A-Z]+)", re.I),
    re.compile(r"(?:正确答案|参考答案|答案)\s*[:：：]\s*([对错√×])", re.I),
    re.compile(r"^\s*([A-Z]+)\s*[:：：]", re.M),
]
_OPTION_PATTERN = re.compile(r"([A-D])\s*[.、．:：]\s*([^\n]+?)(?=\s*[A-D]\s*[.、．:：]|\Z)", re.S)


def extract_answer_from_analysis(analysis: str | None) -> str | None:
    if not analysis:
        return None
    for pat in _ANSWER_PATTERNS:
        m = pat.search(analysis)
        if m:
            return m.group(1).strip()
    return None


def extract_options_from_content(content: str | None) -> list[dict[str, str]] | None:
    if not content:
        return None
    matches = _OPTION_PATTERN.findall(content)
    if len(matches) < 2:
        return None
    return [{"key": k, "text": t.strip()} for k, t in matches]


def _norm_name(name: str | None) -> str:
    s = str(name or "").strip().replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", s).lower()


# content_kind 分类（复用 C-MODELS@1 ContentKind 枚举值）
_ENGINEERING_EXTS = {".log", ".tmp", ".bak", ".swp", ".pyc", ".class", ".o", ".so", ".dll", ".exe"}
_STRUCTURED_EXTS = {".csv", ".json", ".xml", ".yaml", ".yml", ".tsv", ".xls", ".xlsx"}


def classify_content_kind_by_filename(file_name: str | None) -> str:
    """按文件名扩展名分流为 ContentKind 四值（C-MODELS@1）。

    与 services/normalize_service.classify_content_kind 同口径；此处仅按文件名，
    因回填场景下文档正文已在 documents.content，不重读字节。
    """
    ext = os.path.splitext(file_name or "")[1].lower()
    if ext in _ENGINEERING_EXTS:
        return ContentKind.engineering_artifact.value
    if ext in _STRUCTURED_EXTS:
        return ContentKind.structured_data.value
    return ContentKind.lecture.value


# --------------------------------------------------------------------------- #
# 子命令实现
# --------------------------------------------------------------------------- #
def _fetch_batch(conn: psycopg.Connection, sql: str, params: tuple, batch: int) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql + " LIMIT %s", params + (batch,))
        return cur.fetchall()


def cmd_answers(conn: psycopg.Connection, run: RunState, batch: int, dry_run: bool) -> CmdResult:
    """回填 quiz_questions.answer 缺失的客观题答案（从 analysis 启发式提取）。"""
    sql = (
        "SELECT id, analysis FROM quiz_questions "
        "WHERE id > %s AND answer IS NULL "
        "  AND answer_type = 'objective' AND analysis IS NOT NULL "
        "ORDER BY id"
    )
    processed, updated, skipped, last_id = _init_counters(run)
    while True:
        rows = _fetch_batch(conn, sql, (last_id,), batch)
        if not rows:
            break
        for qid, analysis in rows:
            processed += 1
            ans = extract_answer_from_analysis(analysis)
            if ans and not dry_run:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE quiz_questions SET answer = %s, updated_at = now() WHERE id = %s AND answer IS NULL",
                        (ans, qid),
                    )
                    if cur.rowcount > 0:
                        updated += 1
                    else:
                        skipped += 1
            elif ans:
                updated += 1
            else:
                skipped += 1
            last_id = qid
        if not dry_run:
            conn.commit()
            checkpoint(conn, run, last_id, processed, updated, skipped)
    return _result(processed, updated, skipped, last_id)


def cmd_options(conn: psycopg.Connection, run: RunState, batch: int, dry_run: bool) -> CmdResult:
    """回填 quiz_questions.options 缺失的客观题选项（从 content 启发式提取 A./B./C./D.）。"""
    sql = (
        "SELECT id, content FROM quiz_questions "
        "WHERE id > %s AND (options IS NULL OR options::text IN ('[]', 'null', '{}')) "
        "  AND answer_type = 'objective' "
        "ORDER BY id"
    )
    processed, updated, skipped, last_id = _init_counters(run)
    while True:
        rows = _fetch_batch(conn, sql, (last_id,), batch)
        if not rows:
            break
        for qid, content in rows:
            processed += 1
            opts = extract_options_from_content(content)
            if opts and not dry_run:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE quiz_questions SET options = %s::jsonb, updated_at = now() "
                        "WHERE id = %s AND (options IS NULL OR options::text IN ('[]', 'null', '{}'))",
                        (json.dumps(opts, ensure_ascii=False), qid),
                    )
                    if cur.rowcount > 0:
                        updated += 1
                    else:
                        skipped += 1
            elif opts:
                updated += 1
            else:
                skipped += 1
            last_id = qid
        if not dry_run:
            conn.commit()
            checkpoint(conn, run, last_id, processed, updated, skipped)
    return _result(processed, updated, skipped, last_id)


def cmd_knowledge_links(conn: psycopg.Connection, run: RunState, batch: int, dry_run: bool) -> CmdResult:
    """题→知识点关联：quiz_questions.knowledge_point 字符串匹配 knowledge_points.name。

    幂等：question_knowledge_links 有 UNIQUE(question_id, knowledge_point_id)，
    ON CONFLICT DO NOTHING。
    """
    sql = (
        "SELECT q.id, q.knowledge_point, q.subject FROM quiz_questions q "
        "WHERE q.id > %s AND q.knowledge_point IS NOT NULL AND q.knowledge_point <> '' "
        "  AND NOT EXISTS (SELECT 1 FROM question_knowledge_links l WHERE l.question_id = q.id) "
        "ORDER BY q.id"
    )
    # 预加载知识点名→ID 索引（一次性，知识点表规模有限）
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM knowledge_points WHERE name IS NOT NULL")
        kp_by_name: dict[str, int] = {}
        for kid, name in cur.fetchall():
            kp_by_name.setdefault(_norm_name(name), int(kid))

    processed, updated, skipped, last_id = _init_counters(run)
    while True:
        rows = _fetch_batch(conn, sql, (last_id,), batch)
        if not rows:
            break
        for qid, kp_text, _subject in rows:
            processed += 1
            kp_id = kp_by_name.get(_norm_name(kp_text))
            if kp_id and not dry_run:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO question_knowledge_links (question_id, knowledge_point_id, role) "
                        "VALUES (%s, %s, 'primary') ON CONFLICT DO NOTHING",
                        (qid, kp_id),
                    )
                    if cur.rowcount > 0:
                        updated += 1
                    else:
                        skipped += 1
            elif kp_id:
                updated += 1
            else:
                skipped += 1
            last_id = qid
        if not dry_run:
            conn.commit()
            checkpoint(conn, run, last_id, processed, updated, skipped)
    return _result(processed, updated, skipped, last_id)


def cmd_scoreline_majors(conn: psycopg.Connection, run: RunState, batch: int, dry_run: bool) -> CmdResult:
    """分数线→专业映射：kaoyan_scorelines.major_id IS NULL 时按 major_code 精确匹配同校 kaoyan_majors.code。

    幂等：WHERE major_id IS NULL 确保只回填未映射行；重复执行已映射行不再命中。
    """
    sql = (
        "SELECT s.id, s.school_id, s.major_code, s.major_name "
        "FROM kaoyan_scorelines s "
        "WHERE s.id > %s AND s.major_id IS NULL AND s.major_code IS NOT NULL "
        "ORDER BY s.id"
    )
    processed, updated, skipped, last_id = _init_counters(run)
    while True:
        rows = _fetch_batch(conn, sql, (last_id,), batch)
        if not rows:
            break
        for sid, school_id, major_code, _major_name in rows:
            processed += 1
            # 精确匹配同校专业代码
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM kaoyan_majors WHERE school_id = %s AND code = %s LIMIT 1",
                    (school_id, major_code),
                )
                row = cur.fetchone()
                major_id = row[0] if row else None
            if major_id and not dry_run:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE kaoyan_scorelines SET major_id = %s WHERE id = %s AND major_id IS NULL",
                        (major_id, sid),
                    )
                    if cur.rowcount > 0:
                        updated += 1
                    else:
                        skipped += 1
            elif major_id:
                updated += 1
            else:
                skipped += 1
            last_id = sid
        if not dry_run:
            conn.commit()
            checkpoint(conn, run, last_id, processed, updated, skipped)
    return _result(processed, updated, skipped, last_id)


def cmd_doc_metadata(conn: psycopg.Connection, run: RunState, batch: int, dry_run: bool) -> CmdResult:
    """文档四字段回填：content_kind（C-MODELS@1 ContentKind 分类）+ size/source_format/index_status 补全。

    幂等：每字段 WHERE 该字段 IS NULL，已回填行不再命中。
    """
    sql = (
        "SELECT id, file_name, file_path, content_kind, size, source_format, index_status "
        "FROM documents WHERE id > %s ORDER BY id"
    )
    processed, updated, skipped, last_id = _init_counters(run)
    while True:
        rows = _fetch_batch(conn, sql, (last_id,), batch)
        if not rows:
            break
        for doc_id, file_name, file_path, ckind, size, src_fmt, idx_status in rows:
            processed += 1
            updates: dict[str, object] = {}
            if ckind is None:
                updates["content_kind"] = classify_content_kind_by_filename(file_name)
            if size is None and file_path:
                try:
                    updates["size"] = os.path.getsize(file_path)
                except OSError:
                    pass
            if src_fmt is None and file_name:
                ext = os.path.splitext(file_name)[1].lstrip(".").lower() or "other"
                updates["source_format"] = ext
            if idx_status is None:
                updates["index_status"] = "pending"
            if not updates:
                skipped += 1
            elif dry_run:
                updated += 1
            else:
                set_clause = ", ".join(f"{k} = %s" for k in updates)
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE documents SET {set_clause}, updated_at = now() WHERE id = %s",
                        (*updates.values(), doc_id),
                    )
                    if cur.rowcount > 0:
                        updated += 1
                    else:
                        skipped += 1
            last_id = doc_id
        if not dry_run:
            conn.commit()
            checkpoint(conn, run, last_id, processed, updated, skipped)
    return _result(processed, updated, skipped, last_id)


def cmd_834_rescue(conn: psycopg.Connection, run: RunState, batch: int, dry_run: bool) -> CmdResult:
    """834 全量结构化：文件名含 834 的文档对应题目字段齐整化。

    回填字段（仅当 IS NULL 或空时更新，幂等）：
      - source_kind = 'past_exam'
      - question_category = '真题'
      - subject = '电子技术基础'
      - validation_status = 'pass'
      - is_available = TRUE
    """
    sql = (
        "SELECT q.id FROM quiz_questions q "
        "WHERE q.id > %s "
        "  AND EXISTS (SELECT 1 FROM documents d WHERE d.id = q.origin_document_id "
        "              AND d.file_name LIKE '%834%') "
        "  AND (q.source_kind IS DISTINCT FROM 'past_exam' "
        "       OR q.subject IS DISTINCT FROM '电子技术基础' "
        "       OR q.validation_status IS DISTINCT FROM 'pass') "
        "ORDER BY q.id"
    )
    processed, updated, skipped, last_id = _init_counters(run)
    while True:
        rows = _fetch_batch(conn, sql, (last_id,), batch)
        if not rows:
            break
        for (qid,) in rows:
            processed += 1
            if dry_run:
                updated += 1
                last_id = qid
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE quiz_questions SET "
                    "  source_kind = COALESCE(NULLIF(source_kind::text, '')::source_kind, 'past_exam'::source_kind), "
                    "  question_category = COALESCE(question_category, '真题'::question_category), "
                    "  subject = COALESCE(NULLIF(subject, ''), '电子技术基础'), "
                    "  validation_status = COALESCE(NULLIF(validation_status::text, '')::question_validation_status, "
                    "                                'pass'::question_validation_status), "
                    "  is_available = TRUE, "
                    "  updated_at = now() "
                    "WHERE id = %s "
                    "  AND (source_kind IS DISTINCT FROM 'past_exam' "
                    "       OR subject IS DISTINCT FROM '电子技术基础' "
                    "       OR validation_status IS DISTINCT FROM 'pass')",
                    (qid,),
                )
                if cur.rowcount > 0:
                    updated += 1
                else:
                    skipped += 1
            last_id = qid
        if not dry_run:
            conn.commit()
            checkpoint(conn, run, last_id, processed, updated, skipped)
    return _result(processed, updated, skipped, last_id)


_DISPATCH: dict[str, Any] = {
    "answers": cmd_answers,
    "options": cmd_options,
    "knowledge-links": cmd_knowledge_links,
    "scoreline-majors": cmd_scoreline_majors,
    "doc-metadata": cmd_doc_metadata,
    "834-rescue": cmd_834_rescue,
}


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="数据治理回填脚本（幂等可中断，R11）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("command", choices=SUBCOMMANDS, help="回填子命令")
    ap.add_argument("--dry-run", action="store_true", help="只预览不写库（默认）")
    ap.add_argument("--apply", action="store_true", help="真正写库（与 --dry-run 互斥）")
    ap.add_argument("--batch", type=int, default=500, help="每批处理行数（默认 500）")
    args = ap.parse_args(argv)

    if args.apply and args.dry_run:
        ap.error("--apply 与 --dry-run 互斥")
    dry_run = not args.apply

    conn = psycopg.connect(dsn(), connect_timeout=10)
    try:
        ensure_audit_table(conn)
        run = open_run(conn, args.command, dry_run, args.batch)
        handler = _DISPATCH[args.command]
        try:
            result = handler(conn, run, args.batch, dry_run)
            summary = {
                "command": args.command,
                "dry_run": dry_run,
                "batch_size": args.batch,
                **result,
            }
            close_run(conn, run, "done", summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            LOG.info("完成: %s", summary)
            return 0
        except Exception as exc:  # noqa: BLE001
            close_run(conn, run, "failed", {"command": args.command, "error": str(exc)}, error=str(exc))
            LOG.exception("子命令 %s 失败", args.command)
            return 1
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    raise SystemExit(main())
