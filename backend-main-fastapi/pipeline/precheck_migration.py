# -*- coding: utf-8 -*-
"""全量迁移约束预检：量化 SQLite 存量数据有多少行会被 PostgreSQL 的 CHECK 约束拒绝。

只读，不写任何库。输出 JSON 报告供迁移决策使用。

预检项（对应 PG 的硬约束）：
  1. documents.canonical_content 非空        （ck_documents_canonical）
  2. knowledge_chunks.text 非空              （ck_chunks_text）
  3. quiz_questions.options 规范数组          （ck_quiz_questions_options）
  4. quiz_questions.source_kind=past_exam 必须有 year（ck_quiz_questions_past_exam_year）
  5. knowledge_points.exam_frequency 0..5 / difficulty 1..5 / ease_factor 1.3..3.5
  6. knowledge_point_relations 自引用（source_kp_id = target_kp_id）
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline.config import read_only_sqlite_uri  # noqa: E402
from pipeline.question_schema import normalize_options  # noqa: E402

OUT = BASE_DIR.parent / "data" / "migration_precheck.json"


def _cols(conn, table):
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def main() -> int:
    conn = sqlite3.connect(read_only_sqlite_uri(), uri=True)
    report: dict = {}

    # --- 1. documents.canonical_content 非空 ---
    try:
        cols = _cols(conn, "documents")
        has_content = "content" in cols
        total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        if has_content:
            empty = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE content IS NULL OR TRIM(content) = ''"
            ).fetchone()[0]
        else:
            empty = total
        report["documents"] = {
            "total": total,
            "content_column_exists": has_content,
            "empty_content_will_be_rejected": empty,
            "note": "canonical_content 由 content 回填；空 content 行会被 ck_documents_canonical 拒绝",
        }
    except sqlite3.Error as exc:
        report["documents"] = {"error": str(exc)}

    # --- 2. knowledge_chunks.text 非空 ---
    try:
        total = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        empty = conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE text IS NULL OR TRIM(text) = ''"
        ).fetchone()[0]
        report["knowledge_chunks"] = {"total": total, "empty_text_will_be_rejected": empty}
    except sqlite3.Error as exc:
        report["knowledge_chunks"] = {"error": str(exc)}

    # --- 3+4. quiz_questions 选项规范 / 真题年份 ---
    try:
        cols = _cols(conn, "quiz_questions")
        total = conn.execute("SELECT COUNT(*) FROM quiz_questions").fetchone()[0]
        rows = conn.execute("SELECT id, options, question_type, source FROM quiz_questions").fetchall()
        bad_opts = 0
        bad_opts_ids: list[int] = []
        for qid, raw, qtype, source in rows:
            # 主观题不要求选项
            qt = (qtype or "").strip().lower()
            if qt in {"calc", "essay", "proof", "draw", "other"}:
                continue
            try:
                parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
            except Exception:
                parsed = None
            opts, _ = normalize_options(parsed)
            # PG 要求：NULL 或 2-10 个 {key,text} 对象
            if isinstance(opts, list) and 0 < len(opts) < 2:
                bad_opts += 1
                if len(bad_opts_ids) < 20:
                    bad_opts_ids.append(qid)
        report["quiz_questions"] = {
            "total": total,
            "options_column_type_sample": str(
                conn.execute("SELECT typeof(options) FROM quiz_questions WHERE options IS NOT NULL LIMIT 1").fetchone()
            ),
            "malformed_options_will_be_rejected": bad_opts,
            "malformed_options_sample_ids": bad_opts_ids,
            "past_exam_without_year": None,
        }
        # 真题年份：SQLite 无 source_kind / year 列，需从 source 前缀与其它列推断
        if "year" in cols:
            pe_no_year = conn.execute(
                "SELECT COUNT(*) FROM quiz_questions WHERE source LIKE '真题%' AND year IS NULL"
            ).fetchone()[0]
            report["quiz_questions"]["past_exam_without_year"] = pe_no_year
        else:
            pe = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE source LIKE '真题%'").fetchone()[0]
            report["quiz_questions"]["past_exam_prefix_rows"] = pe
            report["quiz_questions"]["year_column_exists"] = False
    except sqlite3.Error as exc:
        report["quiz_questions"] = {"error": str(exc)}

    # --- 5+6. knowledge_points / relations 约束 ---
    try:
        total = conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
        bad = conn.execute(
            "SELECT COUNT(*) FROM knowledge_points WHERE "
            "(exam_frequency IS NOT NULL AND (exam_frequency < 0 OR exam_frequency > 5)) OR "
            "(difficulty IS NOT NULL AND (difficulty < 1 OR difficulty > 5)) OR "
            "(ease_factor IS NOT NULL AND (ease_factor < 1.3 OR ease_factor > 3.5))"
        ).fetchone()[0]
        report["knowledge_points"] = {"total": total, "constraint_violations": bad}
    except sqlite3.Error as exc:
        report["knowledge_points"] = {"error": str(exc)}

    try:
        total = conn.execute("SELECT COUNT(*) FROM knowledge_point_relations").fetchone()[0]
        self_ref = conn.execute(
            "SELECT COUNT(*) FROM knowledge_point_relations WHERE source_kp_id = target_kp_id"
        ).fetchone()[0]
        report["knowledge_point_relations"] = {"total": total, "self_reference_violations": self_ref}
    except sqlite3.Error as exc:
        report["knowledge_point_relations"] = {"error": str(exc)}

    conn.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n报告已写入 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
