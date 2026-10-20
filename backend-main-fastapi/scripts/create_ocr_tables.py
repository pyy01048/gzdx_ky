# -*- coding: utf-8 -*-
"""幂等建表脚本：OCR/采集管线的新表（docx/34 §6）。

建 6 张表：
    document_pages / document_blocks / question_images
    crawl_jobs / crawl_pages / crawl_dead_letters

特点
----
1. **单一真源**：DDL 放在 ``core/sql/111_ocr_pipeline_tables.sql``（生产 schema 链
   与测试沙箱库都会自动执行它），本脚本**只负责读 + 执行**，不另抄一份 SQL，
   杜绝「脚本与分片漂移」。
2. **幂等**：分片里全部是 ``CREATE TABLE IF NOT EXISTS`` + ``CREATE INDEX IF NOT EXISTS``，
   重复执行不会报错、不会动已有数据。
3. **--dry-run** 只打印 SQL；**--verify** 只查表结构与行数；默认执行 DDL。

用法
----
    D:/Anaconda/python.exe scripts/create_ocr_tables.py --dry-run
    D:/Anaconda/python.exe scripts/create_ocr_tables.py --apply
    D:/Anaconda/python.exe scripts/create_ocr_tables.py --verify
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List

# 允许从仓库任意位置执行：把后端根目录塞进 sys.path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

#: DDL 真源（core/sql 分片，与生产 schema 链同源）
SHARD_PATH = os.path.join(BACKEND_DIR, "core", "sql", "111_ocr_pipeline_tables.sql")

TARGET_TABLES = [
    "document_pages",
    "document_blocks",
    "question_images",
    "crawl_jobs",
    "crawl_pages",
    "crawl_dead_letters",
]


# --------------------------------------------------------------------------- #
# 读 DDL
# --------------------------------------------------------------------------- #
def read_statements(path: str = SHARD_PATH) -> List[str]:
    """把分片拆成一条条可执行的语句（跳过 ``--`` 注释与空行）。"""
    if not os.path.isfile(path):
        raise SystemExit(f"找不到 DDL 分片：{path}")
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    # 去掉整行注释（分片里没有字符串内含 "--" 的写法）
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    statements = []
    for chunk in body.split(";"):
        stmt = chunk.strip()
        if stmt:
            statements.append(stmt)
    return statements


# --------------------------------------------------------------------------- #
# 连接
# --------------------------------------------------------------------------- #
def _dsn() -> str:
    """从应用配置里取连接串（与后端 ORM 单一来源），转成 psycopg 认识的格式。"""
    override = os.environ.get("OCR_TABLES_DSN", "").strip()
    if override:
        return override
    from core.db_session import SQLALCHEMY_DATABASE_URL

    dsn = SQLALCHEMY_DATABASE_URL
    if dsn.startswith("postgresql+psycopg://"):
        dsn = "postgresql://" + dsn[len("postgresql+psycopg://"):]
    elif dsn.startswith("sqlite:///"):
        raise SystemExit("当前后端是 SQLite，本脚本只支持 PostgreSQL")
    return dsn


def _connect():
    import psycopg

    return psycopg.connect(_dsn())


# --------------------------------------------------------------------------- #
# 三个动作
# --------------------------------------------------------------------------- #
def apply_ddl(verbose: bool = True) -> int:
    """执行幂等 DDL。返回执行的语句条数。"""
    statements = read_statements()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
                if verbose:
                    print(f"  [OK] {stmt.splitlines()[0][:88]}")
        conn.commit()
    finally:
        conn.close()
    return len(statements)


def verify(verbose: bool = True) -> int:
    """只检查：表是否存在、列结构、当前行数。返回缺失的表数（0 = 全部就绪）。"""
    conn = _connect()
    missing = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(%s)",
                (TARGET_TABLES,),
            )
            existing = {r[0] for r in cur.fetchall()}
            for table in TARGET_TABLES:
                if table not in existing:
                    missing += 1
                    print(f"[缺失] {table}")
                    continue
                cur.execute(
                    "SELECT column_name, data_type, character_maximum_length, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s "
                    "ORDER BY ordinal_position",
                    (table,),
                )
                cols = cur.fetchall()
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                if verbose:
                    print(f"\n=== {table}（行数 {count}）===")
                    for name, dtype, maxlen, nullable in cols:
                        t = dtype
                        if maxlen:
                            t = f"{dtype}({maxlen})"
                        print(f"  {name:<16} {t:<28} null={nullable}")
        conn.rollback()
    finally:
        conn.close()
    return missing


def print_sql() -> None:
    print(f"-- DDL 真源：{SHARD_PATH}")
    for stmt in read_statements():
        print(stmt.rstrip() + ";")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OCR/采集管线建表脚本（幂等）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="只打印 SQL，不连库")
    group.add_argument("--verify", action="store_true", help="只检查表结构与行数")
    group.add_argument("--apply", action="store_true", help="执行建表（默认动作）")
    args = parser.parse_args(argv)

    if args.dry_run:
        print_sql()
        return 0

    if args.verify:
        missing = verify()
        print("\n[结论]" + ("全部表已就绪" if missing == 0 else f"缺 {missing} 张表，请先 --apply"))
        return 0 if missing == 0 else 1

    print("执行建表 …")
    n = apply_ddl()
    print(f"\n[OK] 执行 {n} 条幂等 DDL")
    missing = verify()
    print("\n[结论]" + ("全部表已就绪" if missing == 0 else f"缺 {missing} 张表"))
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
