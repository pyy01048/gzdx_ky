# -*- coding: utf-8 -*-
"""KB 健康检查服务：数据库连接 / 向量库 / FTS5 / 关键表行数一屏总览。

排障入口：一个接口说清「后端进程活着，但知识库哪一层掉了链子」——
不必再登进服务器开 sqlite3 敲 PRAGMA。

约定（务必遵守）：
    每个探测项独立 try/except —— 单项失败只降级该项，
    绝不让健康检查自己 500。tests/test_api_contract.py 断言
    /api/health 必须返回 200，它是前端「后端是否在线」的探针。
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: 向量检索后端类型。项目用 numpy brute-force（knowledge_chunks_vec 存 BLOB），
#: 不依赖 sqlite-vec(vec0) 扩展；探测时如实标注，避免误报「缺 sqlite-vec」。
VEC_BACKEND = "numpy-brute-force"

#: 关键表（行数异常时给人看的）：表名 -> 中文名
KEY_TABLES = {
    "documents": "文档",
    "knowledge_chunks": "知识分块",
    "quiz_questions": "题目",
    "error_records": "错题",
    "knowledge_points": "知识点",
    "words": "单词",
    "tasks": "任务",
    "papers": "组卷",
    "kaoyan_schools": "院校",
}

#: 向量表 / FTS5 表名（口径与 services/search_service.py 的建表 DDL 一致）
VEC_TABLE = "knowledge_chunks_vec"
FTS_TABLE = "knowledge_chunks_fts"
CHUNK_TABLE = "knowledge_chunks"


def _existing_tables(conn) -> set:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    return {r[0] for r in rows}


def _count(conn, table: str) -> int:
    # 表名来自内部白名单（KEY_TABLES / VEC_TABLE / FTS_TABLE），非用户输入，无注入面
    return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).fetchone()[0])


def _probe_vector_store(conn, existing: set) -> dict:
    """向量库探测：表存在性 + 已向量化覆盖率 + 维度分布。"""
    if VEC_TABLE not in existing:
        return {
            "backend": VEC_BACKEND,
            "table": VEC_TABLE,
            "status": "missing",
            "rows": 0,
            "with_embedding": 0,
            "dims": [],
            "detail": "向量表未创建（首次检索/入库时自动建立）",
        }
    rows = _count(conn, VEC_TABLE)
    with_emb = int(
        conn.execute(text(f'SELECT COUNT(*) FROM "{VEC_TABLE}" WHERE embedding IS NOT NULL'))
        .fetchone()[0]
    )
    dims = [
        r[0]
        for r in conn.execute(text(f'SELECT DISTINCT dim FROM "{VEC_TABLE}" WHERE dim IS NOT NULL'))
        .fetchall()
    ]
    if rows == 0:
        status = "empty"
    elif with_emb == rows:
        status = "ok"
    else:
        status = "partial"
    return {
        "backend": VEC_BACKEND,
        "table": VEC_TABLE,
        "status": status,
        "rows": rows,
        "with_embedding": with_emb,
        "dims": sorted(d for d in dims if d),
    }


def _probe_fts(conn, existing: set, chunk_rows: int) -> dict:
    """FTS5 探测：表存在性 + 索引条数 + 与分块表的差额（差额=漏召回）。"""
    if FTS_TABLE not in existing:
        return {
            "table": FTS_TABLE,
            "status": "missing",
            "rows": 0,
            "pending": chunk_rows,
            "detail": "FTS5 索引未建立（首次检索时自动建立并同步）",
        }
    rows = _count(conn, FTS_TABLE)
    pending = max(0, chunk_rows - rows)
    return {
        "table": FTS_TABLE,
        "status": "ok" if pending == 0 else "partial",
        "rows": rows,
        "pending": pending,
    }


def _probe_tables(conn, existing: set) -> dict:
    out = {}
    for table, label in KEY_TABLES.items():
        if table not in existing:
            out[table] = {"label": label, "exists": False, "rows": None}
        else:
            out[table] = {"label": label, "exists": True, "rows": _count(conn, table)}
    return out


def kb_health_snapshot() -> dict:
    """一屏总览：database / vector_store / fts5 / tables + 汇总 status。

    status 取值：ok（全部就绪）| degraded（数据库不可用或向量/FTS 有缺口）。
    """
    from database import check_database_health, engine

    database = check_database_health()
    snapshot = {
        "status": "ok",
        "database": database,
        "vector_store": {"backend": VEC_BACKEND, "status": "unknown"},
        "fts5": {"status": "unknown"},
        "tables": {},
    }

    if database.get("status") != "healthy":
        snapshot["status"] = "degraded"
        snapshot["vector_store"]["detail"] = "数据库不可用，跳过探测"
        snapshot["fts5"]["detail"] = "数据库不可用，跳过探测"
        return snapshot

    try:
        with engine.connect() as conn:
            existing = _existing_tables(conn)
            chunk_rows = _count(conn, CHUNK_TABLE) if CHUNK_TABLE in existing else 0
            snapshot["vector_store"] = _probe_vector_store(conn, existing)
            snapshot["fts5"] = _probe_fts(conn, existing, chunk_rows)
            snapshot["tables"] = _probe_tables(conn, existing)
    except Exception as e:  # noqa: BLE001
        logger.warning("KB 健康探测失败: %s", e)
        snapshot["status"] = "degraded"
        snapshot["error"] = f"{type(e).__name__}: {e}"
        return snapshot

    # 汇总降级判定：向量库 / FTS5 任一 missing / partial 即 degraded
    for key in ("vector_store", "fts5"):
        if snapshot[key].get("status") in ("missing", "partial"):
            snapshot["status"] = "degraded"
    return snapshot
