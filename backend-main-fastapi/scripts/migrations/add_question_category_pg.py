#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quiz_questions 四分类筛选列迁移（PG）。

执行 core/sql/117_quiz_category_columns.sql：
  * 建 question_category 枚举（真题/练习题/习题/考研题）
  * 加 question_category / exam_type / source_platform / source_url 四列
  * 按 source_kind 启发式回填存量 question_category
  * 建筛选索引

SQL 全部 IF NOT EXISTS / 幂等 DO 块，可反复重跑。默认直接执行（--dry-run 只打印 SQL）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts._conn import pg_connect

SQL_FILE = Path(__file__).resolve().parent.parent.parent / "core" / "sql" / "117_quiz_category_columns.sql"


def main() -> int:
    parser = argparse.ArgumentParser(description="quiz_questions 四分类筛选列迁移")
    parser.add_argument("--dry-run", action="store_true", help="只打印 SQL，不执行")
    args = parser.parse_args()

    sql = SQL_FILE.read_text(encoding="utf-8")
    if args.dry_run:
        print(sql)
        return 0

    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT question_category, count(*) FROM quiz_questions "
                "GROUP BY question_category ORDER BY question_category"
            )
            for row in cur.fetchall():
                print(f"  {row[0]}: {row[1]}")
        print("迁移完成（117_quiz_category_columns.sql）")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
