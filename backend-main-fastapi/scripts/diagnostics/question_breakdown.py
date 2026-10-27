# -*- coding: utf-8 -*-
"""quiz_questions 细分口径（真题套卷/年份/答案/解析覆盖率），供 README 数据表使用。

用法::

    python scripts/diagnostics/question_breakdown.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402


def main() -> int:
    from database import SessionLocal

    db = SessionLocal()
    try:
        cols = [
            r[0]
            for r in db.execute(
                text(
                    "select column_name from information_schema.columns"
                    "  where table_name='quiz_questions' and table_schema='public'"
                )
            )
        ]
        print("columns:", ", ".join(sorted(cols)))
        total = db.execute(text("select count(*) from quiz_questions")).scalar()
        print(f"total = {total}")
        for col in ("exam_paper_id", "paper_id", "year", "answer", "analysis", "source_kind", "subject"):
            if col in cols:
                # year 等数值列不能和 '' 比较；逐列自适应。
                try:
                    n = db.execute(
                        text(
                            f"select count(*) from quiz_questions"
                            f" where {col} is not null and {col} <> ''"
                        )
                    ).scalar()
                except Exception:  # noqa: BLE001 数值列 → 只看 IS NOT NULL
                    db.rollback()
                    n = db.execute(
                        text(f"select count(*) from quiz_questions where {col} is not null")
                    ).scalar()
                print(f"  {col} 非空 = {n}")
        for table in ("exam_papers", "papers", "quiz_papers"):
            try:
                c = db.execute(text(f"select count(*) from {table}")).scalar()
                print(f"{table} = {c}")
            except Exception:  # noqa: BLE001 表不存在 → 记得回滚，否则会话被毒化
                db.rollback()
        words = db.execute(text("select count(*) from words")).scalar()
        print(f"words = {words}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
