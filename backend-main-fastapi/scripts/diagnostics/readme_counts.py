# -*- coding: utf-8 -*-
"""README 数据口径核对：把过时的宣传数字换成库里的真实计数。

审计发现 README 仍写「9,171 道题 / 4,569 词」，与库中真实规模差 20~30 倍
（迁移 PG 后只导入了子集）。本脚本打印可直接粘进 README 的数字。

用法::

    python scripts/diagnostics/readme_counts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402


def _count(db, table: str, where: str = "1=1") -> int | None:
    try:
        return int(db.execute(text(f"select count(*) from {table} where {where}")).scalar())
    except Exception:  # noqa: BLE001 表不存在 → None
        return None


def main() -> int:
    from database import SessionLocal

    db = SessionLocal()
    try:
        tables = {
            r[0]
            for r in db.execute(
                text("select table_name from information_schema.tables where table_schema='public'")
            )
        }
        print("== 核心计数 ==")
        # 题目表真实名为 quiz_questions（历史名 questions 在 PG 迁移后不存在）
        qtable = next(
            (t for t in ("questions", "quiz_questions") if t in tables), None
        )
        questions = _count(db, qtable) if qtable else None
        print(f"questions(table={qtable}) = {questions}")
        for col, label in (("origin_document_id", "真题文档归属"), ("year", "有年份"), ("answer", "有答案")):
            if questions is not None and col in {
                c[0]
                for c in db.execute(
                    text(
                        "select column_name from information_schema.columns"
                        "  where table_name=:t and table_schema='public'"
                    ),
                    {"t": qtable},
                )
            }:
                n = _count(db, qtable, f"{col} is not null")
                print(f"  其中{label} = {n}")
        for name in ("words", "wordbook", "vocabulary", "word_cards"):
            if name in tables:
                print(f"{name} = {_count(db, name)}")
        print("== 相关表清单（含 'word' / 'question'）==")
        for t in sorted(tables):
            if "word" in t or "question" in t:
                print(f"  {t} = {_count(db, t)}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
