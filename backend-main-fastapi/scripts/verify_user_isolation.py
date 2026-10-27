"""B4 隔离迁移结果验证（108 落地后跑一次）。

用法：.venv/Scripts/python scripts/verify_user_isolation.py
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.db_session import build_database_url  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

EXPECTED_TABLES = {
    "goals", "tasks", "review_schedules", "review_records", "error_records",
    "error_knowledge_links", "flashcards", "words", "word_decks", "favorites",
    "study_sessions", "study_events", "study_stats", "answer_records",
    "quiz_sessions", "quiz_attempts", "daily_plans", "week_plans", "month_plans",
    "ebbinghaus_items", "early_bird_records", "phase_plans",
}


def main() -> int:
    engine = create_engine(build_database_url())
    with engine.connect() as c:
        cols = {
            r[0] for r in c.execute(text(
                "select table_name from information_schema.columns "
                "where table_schema='public' and column_name='user_id'"))
        }
        missing = EXPECTED_TABLES - cols
        print(f"[1] user_id 列：{len(cols & EXPECTED_TABLES)}/{len(EXPECTED_TABLES)} 张表就绪"
              + (f"；缺失：{sorted(missing)}" if missing else " ✓"))

        nulls = c.execute(text(
            "select 'goals', count(*) from goals where user_id is null union all "
            "select 'tasks', count(*) from tasks where user_id is null union all "
            "select 'error_records', count(*) from error_records where user_id is null union all "
            "select 'favorites', count(*) from favorites where user_id is null union all "
            "select 'study_sessions', count(*) from study_sessions where user_id is null union all "
            "select 'flashcards', count(*) from flashcards where user_id is null"
        )).fetchall()
        residual = [(t, n) for t, n in nulls if n]
        print(f"[2] 存量回填后残留 NULL：{residual if residual else '无 ✓'}")

        has_notice = c.execute(text(
            "select exists (select 1 from information_schema.tables "
            "where table_schema='public' and table_name='notice_user_states')"
        )).scalar()
        n_states = c.execute(text("select count(*) from notice_user_states")).scalar() if has_notice else -1
        print(f"[3] notice_user_states 表：{'✓' if has_notice else '缺失'}，行数={n_states}")

        for table, expect in (("review_schedules", 1), ("daily_plans", 1), ("favorites", 1)):
            names = [r[0] for r in c.execute(text(
                f"select conname from pg_constraint where conrelid='{table}'::regclass and contype='u'"))]
            print(f"[4] {table} 唯一约束：{names}")

        deck_idx = [r[0] for r in c.execute(text(
            "select indexname from pg_indexes where tablename='word_decks' and indexname like 'uq_deck%'"))]
        print(f"[5] word_decks 词库名唯一索引：{deck_idx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
