# -*- coding: utf-8 -*-
"""``ensure_notices_schema`` 幂等性回归（P1-4 回滚调查的产物）。

该函数被 ``routers/kaoyan.py``、``routers/kaoyan_ext.py`` 的接口**每次请求**调用。
旧实现把 4 条 ``ALTER TYPE notice_type ADD VALUE`` 直接塞进调用方事务里逐条执行：

1. 标签已存在 → ``duplicate_object`` 报错；
2. PG 里一条报错就**毒化整个事务**，同批后续 3 条全报
   ``current transaction is aborted``（日志里每批 4 条错误即由此而来）；
3. 最后的 ``commit`` 实际执行 ROLLBACK。

后果：库里 36% 的事务是回滚；调用方在调用前若有未提交写入会被静默丢弃。

两条护栏：DDL 必须自带 ``IF NOT EXISTS``；调用不得吞掉调用方未提交的写入。
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from database import SessionLocal
from services.kaoyan.spider_notices import _ENUM_EXTEND_DDL, ensure_notices_schema

SCHOOL = "幂等契约测试校"


def test_ddl_is_idempotent_by_syntax() -> None:
    """DDL 逐条都必须是 IF NOT EXISTS —— 已存在时不报错，事务才不会被毒化。"""
    stmts = [s.strip() for s in _ENUM_EXTEND_DDL.split(";") if "ALTER TYPE" in s]
    assert stmts, "枚举扩展 DDL 里没有 ALTER TYPE 语句"
    for stmt in stmts:
        assert "ADD VALUE IF NOT EXISTS" in stmt.upper(), f"缺少 IF NOT EXISTS，重复执行会毒化事务: {stmt}"
        assert "notice_type" in stmt, f"目标枚举应为 notice_type: {stmt}"


@pytest.fixture()
def db(db_schema):  # noqa: ARG001  依赖 db_schema 确保临时库已建表
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(text("delete from kaoyan_notices where school_name = :s"), {"s": SCHOOL})
        session.commit()
        session.close()


def test_pending_writes_survive_schema_ensure(db) -> None:
    """调用前的未提交写入必须活下来 —— 事务被毒化时它会被静默 ROLLBACK 掉。"""
    ensure_notices_schema(db)

    db.execute(
        text(
            "insert into kaoyan_notices (school_name, title, notice_type, source)"
            " values (:s, '幂等回归题干', '公告', 'test')"
        ),
        {"s": SCHOOL},
    )
    # 不 commit —— 故意留下未提交写入

    ensure_notices_schema(db)  # 第二次调用：DDL 已全部存在，是重复执行路径

    remaining = db.execute(
        text("select count(*) from kaoyan_notices where school_name = :s"), {"s": SCHOOL}
    ).scalar()
    assert remaining == 1, "ensure_notices_schema 吞掉了调用方未提交的写入（事务被毒化）"
