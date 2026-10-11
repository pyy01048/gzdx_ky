# -*- coding: utf-8 -*-
"""
SQLite 写锁重试工具（services/db_retry.py）
============================================
后端 uvicorn 进程常驻持有 DB 写锁（WAL 下同时仅一个写者），外部迁移/
批量写脚本可能遇到短暂 "database is locked"。本工具提供有限重试，
幂等迁移与新服务写库统一走此入口。
"""
from __future__ import annotations

import time
from typing import Any, Optional


def exec_retry(
    conn,
    sql: str,
    params: Optional[Any] = None,
    retries: int = 6,
    wait: float = 2.0,
):
    """执行 SQL；遇 database is locked 重试（最多 retries 次，间隔 wait 秒）。"""
    for i in range(retries):
        try:
            if params is None:
                return conn.execute(sql)
            return conn.execute(sql, params)
        except Exception as e:
            if "locked" in str(e).lower() and i < retries - 1:
                time.sleep(wait)
                continue
            raise
