# -*- coding: utf-8 -*-
"""数据脚本统一连接入口：与主应用同源解析 .env，禁止硬编码口令。

背景（docs/完善方案/02-密钥与敏感信息治理.md §3.2）：此前 40+ 个数据脚本各自
在源码里写死数据库口令，换口令要改 40 处必然漏改。本模块是唯一
连接来源：参数全部来自 backend-main-fastapi/.env（PG_* 系列）。

用法（任何 scripts/ 下的脚本）：
    from scripts._conn import pg_connect, dsn

    conn = pg_connect()              # psycopg3 连接（conninfo 串）
    # 或需要 SQLAlchemy URL 时：
    from scripts._conn import sqlalchemy_url
    engine = create_engine(sqlalchemy_url())

环境变量（与 core/db_session.py 同口径）：
    PG_HOST（默认 127.0.0.1）
    PG_PORT（默认 5432）
    PG_DATABASE（默认 kaoyan）
    PG_USER（默认 kaoyan）
    PG_PASSWORD（必填——缺失直接 KeyError，绝不静默回退默认口令）
    PG_DATABASE_TEST（fix_all_tests.py 等测试库场景；默认 kaoyan_test）
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover - dotenv 缺失时退回进程环境变量
    pass

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    val = os.environ.get(name, "").strip()
    return val or default


def _password() -> str:
    pw = os.environ.get("PG_PASSWORD", "").strip()
    if not pw:
        raise RuntimeError(
            "PG_PASSWORD 未设置：请复制 backend-main-fastapi/.env.example 为 .env 并填写。"
            "数据脚本不再内置任何默认口令（见 docs/完善方案/02-密钥与敏感信息治理.md）。"
        )
    return pw


def dsn(database: str | None = None) -> str:
    """psycopg3 conninfo 串（keyword/value 形式，口令不出现在打印日志里）。"""
    return (
        f"host={_env('PG_HOST', '127.0.0.1')} "
        f"port={_env('PG_PORT', '5432')} "
        f"dbname={database or _env('PG_DATABASE', 'kaoyan')} "
        f"user={_env('PG_USER', 'kaoyan')} "
        f"password={_password()}"
    )


def pg_connect(database: str | None = None, **kwargs):
    """psycopg3 同步连接。timeout 默认 10s，避免脚本挂死。"""
    import psycopg

    kwargs.setdefault("connect_timeout", 10)
    return psycopg.connect(dsn(database), **kwargs)


def sqlalchemy_url(database: str | None = None) -> str:
    """SQLAlchemy URL（psycopg 方言），供 create_engine 使用。"""
    return (
        f"postgresql+psycopg://{_env('PG_USER', 'kaoyan')}:{_password()}@"
        f"{_env('PG_HOST', '127.0.0.1')}:{_env('PG_PORT', '5432')}/"
        f"{database or _env('PG_DATABASE', 'kaoyan')}"
    )


def test_dsn() -> str:
    """测试库 DSN（fix_all_tests.py 场景）：库名走 PG_DATABASE_TEST。"""
    return dsn(_env("PG_DATABASE_TEST", "kaoyan_test"))
