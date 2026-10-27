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


def _is_pg_conn(conn) -> bool:
    """连接是否 PostgreSQL —— 对 Session / Engine / Connection / 裸 DBAPI 都可靠。

    踩坑记录：**不能**用 `hasattr(conn, "connection")` 判 —— SQLAlchemy 的
    `Session.connection` 是个**方法**，hasattr 一样为真，于是取到的
    `is_postgres(<bound method>)` 抛异常，被兜底吞掉后静默走回 SQLite 分支，
    结果是 PG 上健康面板永远显示"向量表未创建"（实测）。
    正解是看 SQLAlchemy 的 `dialect.name`。
    """
    try:
        bind = conn.get_bind() if hasattr(conn, "get_bind") else conn
        dialect = getattr(bind, "dialect", None)
        if dialect is not None:
            return getattr(dialect, "name", "") == "postgresql"
    except Exception:  # noqa: BLE001
        pass
    # 裸 DBAPI 连接：交给 dbapi_compat 按模块名判
    try:
        from services.dbapi_compat import is_postgres

        raw = conn
        if hasattr(conn, "connection") and callable(getattr(conn, "connection")):
            raw = conn.connection()
        return is_postgres(raw)
    except Exception:  # noqa: BLE001
        return False


def _existing_tables(conn) -> set:
    """全部表名（跨方言）。

    PostgreSQL 迁移修正（2026-10-14）：`sqlite_master` 是 SQLite 专有目录表，
    PG 下报 `relation "sqlite_master" does not exist`，使 /api/health 探针恒 degraded。
    改用 dbapi_compat.list_tables，内部按连接方言走 information_schema。
    """
    try:
        from services.dbapi_compat import list_tables

        # Session/Connection → 取底层 DBAPI；注意 connection 可能是**方法**
        raw = conn
        if hasattr(conn, "connection") and callable(getattr(conn, "connection")):
            raw = conn.connection()
        if hasattr(raw, "connection") and not callable(getattr(raw, "connection")):
            raw = raw.connection
        return set(list_tables(raw))
    except Exception:  # noqa: BLE001
        # 兜底：SQLAlchemy 层探测（不依赖任何一方的目录表）
        try:
            from sqlalchemy import inspect as _sa_inspect
            return set(_sa_inspect(conn).get_table_names())
        except Exception:  # noqa: BLE001
            return set()


def _count(conn, table: str) -> int:
    # 表名来自内部白名单（KEY_TABLES / VEC_TABLE / FTS_TABLE），非用户输入，无注入面
    return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).fetchone()[0])


def _probe_vector_store(conn, existing: set) -> dict:
    """向量库探测：表存在性 + 已向量化覆盖率 + 维度分布。

    两条路径（曾因此让 /api/health 恒报 degraded）：

      * **PostgreSQL**：权威表 `chunk_vectors`，向量列 `embedding_f32`
        （pgvector `vector(512)` + HNSW 索引 `idx_chunk_vectors_hnsw`）；
        `knowledge_chunks_vec` 在 PG 侧**不存在**。
      * **SQLite**：BLOB 镜像表 `knowledge_chunks_vec`，向量列 `embedding`。
    """
    if _is_pg_conn(conn):
        return _probe_vector_store_pg(conn, existing)

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


def _probe_vector_store_pg(conn, existing: set) -> dict:
    """PostgreSQL 向量库探测：`chunk_vectors` + pgvector。

    与 SQLite 分支的差别不只是表名 —— **向量列名也不同**
    （`embedding_f32` vs `embedding`），写错会静默得到 0 行。
    """
    table = "chunk_vectors"
    if table not in existing:
        return {
            "backend": VEC_BACKEND,
            "table": table,
            "status": "missing",
            "rows": 0,
            "with_embedding": 0,
            "dims": [],
            "detail": "向量表未创建（应由 core/sql/020 分片建立）",
        }
    rows = _count(conn, table)
    with_emb = int(conn.execute(text(
        f'SELECT COUNT(*) FROM "{table}" WHERE embedding_f32 IS NOT NULL'
    )).fetchone()[0])
    dims = [
        r[0] for r in conn.execute(text(
            f'SELECT DISTINCT dim FROM "{table}" WHERE dim IS NOT NULL'
        )).fetchall()
    ]
    if rows == 0:
        status = "empty"
    elif with_emb == rows:
        status = "ok"
    else:
        status = "partial"
    return {
        # 真实实现：pgvector + HNSW 索引（不是 numpy 暴力检索）
        "backend": "pgvector-hnsw",
        "table": table,
        "status": status,
        "rows": rows,
        "with_embedding": with_emb,
        "dims": sorted(d for d in dims if d),
    }


def _probe_fts(conn, existing: set, chunk_rows: int) -> dict:
    """FTS5 / 原生全文检索探测：索引条数 + 与分块表的差额（差额=漏召回）。

    PostgreSQL 没有 FTS5 虚表，全文检索走 `knowledge_chunks.search_vector`
    原生列（GIN 索引）；SQLite 才用 `knowledge_chunks_fts` 虚表。
    """
    if _is_pg_conn(conn):
        try:
            rows = int(conn.execute(text(
                'SELECT COUNT(*) FROM "knowledge_chunks" WHERE search_vector IS NOT NULL'
            )).fetchone()[0])
            pending = max(0, chunk_rows - rows)
            return {
                "table": "knowledge_chunks.search_vector",
                "status": "ok" if pending == 0 else "partial",
                "rows": rows,
                "pending": pending,
            }
        except Exception as exc:  # noqa: BLE001
            # 不静默：探测异常会让健康面板给出错误结论（说"未建立"实则已建立）
            logging.getLogger(__name__).warning(
                "FTS 探测（PG 分支）失败，回退 SQLite 口径: %s", str(exc)[:160]
            )

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
