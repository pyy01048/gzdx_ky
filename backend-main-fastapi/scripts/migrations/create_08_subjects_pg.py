#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建缺失的 08 工学一级学科科目（PostgreSQL）。

- 读取 scripts/data/subject_catalog.py 的 SUBJECT_CATALOG。
- 只创建尚不存在的 code，已存在则跳过（保留既有 id）。
- 默认 dry-run 预览；--apply 写库，单事务。
- 附带将考研公共课（数学/英语/政治）的 category 由 professional 修正为 public。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import psycopg
from scripts._conn import dsn
from scripts.data.subject_catalog import SUBJECT_CATALOG


def ensure_subject(conn, entry: dict) -> str:
    """返回 'created' / 'exists' / 'updated'。"""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM subjects WHERE code = %s", (entry["code"],))
        row = cur.fetchone()
        if row:
            return "exists"
        cur.execute(
            """
            INSERT INTO subjects (code, name, short_name, category, description,
                                  sort_order, is_active, is_custom)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE, TRUE)
            ON CONFLICT (code) DO NOTHING
            RETURNING id
            """,
            (
                entry["code"],
                entry["name"],
                entry["short_name"],
                entry["category"],
                entry["description"],
                entry.get("sort_order", 0),
            ),
        )
        if cur.fetchone():
            return "created"
        return "exists"


def fix_public_category(conn) -> int:
    """把数学/英语/政治归入 public 类别。"""
    n = 0
    with conn.cursor() as cur:
        for name in ("数学", "英语", "政治"):
            cur.execute(
                "UPDATE subjects SET category = 'public' WHERE name = %s AND category <> 'public'",
                (name,),
            )
            n += cur.rowcount
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description="创建缺失的 08 工学科目")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = parser.parse_args()

    conn = psycopg.connect(dsn(), connect_timeout=10)
    try:
        if not args.apply:
            print("==== DRY-RUN 预览 ====")
            for e in SUBJECT_CATALOG:
                print(f"  [新建候选] {e['code']}  {e['name']}  ({e['category']})")
            print(f"共 {len(SUBJECT_CATALOG)} 个候选科目；另将数学/英语/政治归为 public。")
            print("（dry-run，未写库；确认后加 --apply）")
            return 0

        created, exists = 0, 0
        for e in SUBJECT_CATALOG:
            state = ensure_subject(conn, e)
            if state == "created":
                created += 1
                print(f"  新建: {e['code']}  {e['name']}")
            else:
                exists += 1
        pub = fix_public_category(conn)
        conn.commit()
        print("\n==== 完成 ====")
        print(f"新建科目 {created} 个，已存在 {exists} 个，公共课类别修正 {pub} 个")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
