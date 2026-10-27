# -*- coding: utf-8 -*-
"""真实 PG 上验证 ensure_notices_schema 不再毒化事务（P1-4 修复验收）。

量法：调用前后各取一次 ``pg_stat_database.xact_rollback``，中间连调两次
``ensure_notices_schema`` 并留一笔未提交写入。修复前每次调用都会 +1 回滚；
修复后增量应为 0，且未提交写入必须还在。

用法::

    python scripts/diagnostics/verify_enum_fix.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from services.kaoyan.spider_notices import ensure_notices_schema  # noqa: E402

SCHOOL = "枚举修复验收校"


def _xacts() -> tuple:
    db = SessionLocal()
    try:
        return tuple(
            db.execute(
                text(
                    "select xact_commit, xact_rollback from pg_stat_database"
                    "  where datname = current_database()"
                )
            ).first()
        )
    finally:
        db.close()


def main() -> int:
    from core.db_session import engine

    if engine.dialect.name != "postgresql":
        print("当前底座不是 PG，跳过（该修复只影响 PG 分支）")
        return 0

    before = _xacts()
    print(f"[before] commit={before[0]} rollback={before[1]}")

    db = SessionLocal()
    try:
        ensure_notices_schema(db)
        db.execute(
            text(
                "insert into kaoyan_notices (school_name, title, notice_type, source)"
                " values (:s, '枚举修复验收题干', '公告', 'verify')"
            ),
            {"s": SCHOOL},
        )
        # 故意不提交，留一笔未提交写入给下一次调用去"考验"
        ensure_notices_schema(db)
        remaining = db.execute(
            text("select count(*) from kaoyan_notices where school_name = :s"), {"s": SCHOOL}
        ).scalar()
        print(f"未提交写入存活数 = {remaining}（应为 1）")
    finally:
        db.rollback()
        db.execute(text("delete from kaoyan_notices where school_name = :s"), {"s": SCHOOL})
        db.commit()
        db.close()

    after = _xacts()
    print(f"[after ] commit={after[0]} rollback={after[1]}")
    delta = after[1] - before[1]
    # 计数口径：主会话结尾的显式 rollback() 会落在两次快照之间，算 1 次；
    # 修复前每次 ensure_notices_schema 毒化事务再各 +1（应为 3）。
    print(f"期间回滚增量 = {delta}（≤1 合格：那 1 次是主会话结尾的显式 rollback）")
    ok = delta <= 1
    print("PASS" if ok else "FAIL：仍在产生额外回滚（事务仍被毒化）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
