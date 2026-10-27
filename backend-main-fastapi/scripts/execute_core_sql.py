"""执行 core/sql 单个编号 SQL（PG 线）。

背景：core/sql 的编号脚本此前"靠人工按序执行"（B-auth.md B5），没有执行器。
本脚本补一个最小执行入口：按分号切分、跳过纯注释段、逐条执行并报错定位。

用法：
    cd backend-main-fastapi
    .venv/Scripts/python scripts/execute_core_sql.py core/sql/108_user_data_isolation.sql

说明：
    - 仅面向 DATABASE_BACKEND=postgresql（SQLite 线走 migrate.py 的 ensure_schema_columns）。
    - 脚本本身必须幂等（IF NOT EXISTS / ON CONFLICT），可重复执行。
    - 不含 DO $$ 块的解析：需要 PL/pgSQL 的脚本请继续人工执行（当前 108 不需要）。
"""
from __future__ import annotations

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core.db_session import IS_POSTGRES, build_database_url  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


def split_statements(sql: str) -> list[str]:
    """按分号切分；丢弃纯注释段，保留带语句的段的前置注释行剥离。"""
    out: list[str] = []
    for seg in sql.split(";"):
        lines = [
            ln for ln in seg.splitlines()
            if ln.strip() and not ln.strip().startswith("--")
        ]
        if lines:
            out.append("\n".join(lines).strip())
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python scripts/execute_core_sql.py <core/sql/xxx.sql>")
        return 2
    if not IS_POSTGRES:
        print("[x] 当前 DATABASE_BACKEND 不是 postgresql；SQLite 线请用 migrate.py")
        return 2

    path = os.path.join(BASE, sys.argv[1]) if not os.path.isabs(sys.argv[1]) else sys.argv[1]
    if not os.path.isfile(path):
        print(f"[x] SQL 文件不存在：{path}")
        return 2

    with open(path, encoding="utf-8") as f:
        stmts = split_statements(f.read())
    if not stmts:
        print("[!] 无可执行语句")
        return 0

    engine = create_engine(build_database_url())
    failed = 0
    results: list[tuple[int, str, bool, str]] = []
    # 逐语句独立事务：单条失败不影响后续语句（且每条都是幂等 DDL，重跑安全）。
    # 之前放在单个 engine.begin() 里，一条失败会把整个事务拖进 aborted 状态。
    for i, stmt in enumerate(stmts, 1):
        head = " ".join(stmt.split())[:72]
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            results.append((i, head, True, ""))
            print(f"[{i:>2}/{len(stmts)}] OK   {head}")
        except Exception as exc:  # noqa: BLE001 —— 逐条报错并继续统计
            failed += 1
            results.append((i, head, False, str(exc)))
            print(f"[{i:>2}/{len(stmts)}] FAIL {head}\n      {exc}")
    print(f"[{'✓' if failed == 0 else 'x'}] 完成：{len(stmts) - failed}/{len(stmts)} 成功")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
