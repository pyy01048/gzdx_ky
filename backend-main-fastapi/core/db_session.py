"""数据库会话与引擎工厂：PostgreSQL / SQLite 双后端。

后端开关（环境变量驱动，读 .env 亦可）：
    DATABASE_BACKEND = postgresql | sqlite         默认 postgresql
    VECTOR_BACKEND   = pgvector   | python          默认 pgvector（不可用时自动降级）
    DATABASE_URL     = 完整连接串，给定时优先于分项配置
    DATABASE_PATH    = SQLite 文件路径（仅 sqlite 后端），默认 data/kaoyan.db

PostgreSQL 连接参数：
    PG_HOST / PG_PORT / PG_USER / PG_PASSWORD / PG_DATABASE
    默认 127.0.0.1 / 5432 / postgres / postgres / kaoyan
    （对齐免安装便携版：D:\\pgsql，端口 5432）

其它：
    DB_POOL_SIZE / DB_MAX_OVERFLOW / DB_POOL_TIMEOUT / DB_STATEMENT_TIMEOUT_MS

设计要点：
  - 模块导入即建引擎，但**不建连接**；连接按需建立，pool_pre_ping 兜住断连。
  - SQLite 后端保留 WAL / busy_timeout / foreign_keys 等 PRAGMA（等价于原 database.py）。
  - PG 后端通过 connect_args 注入 statement_timeout 与 application_name，
    并对每个连接强制 UTC 时区，保证 TIMESTAMPTZ 语义一致。
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 环境变量加载（幂等，供独立脚本直接导入时使用）
# --------------------------------------------------------------------------- #
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    # 项目实际 .env 位于 backend-main-fastapi 根目录，兼容独立脚本与服务启动。
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:  # pragma: no cover - dotenv 缺失不影响运行
    pass

#: core 包所在目录（本文件就在 core/ 下）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
#: 后端根目录。data/ 留在后端根下，与迁移前 database.py 的默认 SQLite 路径保持一致，
#: 避免切换后找不到原有 kaoyan.db。
BACKEND_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(BACKEND_DIR, "data")


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key, "") or "").strip() or default


def _env_int(key: str, default: int) -> int:
    raw = _env(key, "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def database_backend() -> str:
    """当前数据库后端：postgresql | sqlite。"""
    return _env("DATABASE_BACKEND", "postgresql").lower()


def vector_backend() -> str:
    """当前向量后端：pgvector | python。"""
    return _env("VECTOR_BACKEND", "pgvector").lower()


def build_database_url() -> str:
    """按环境变量拼出 SQLAlchemy 连接串。"""
    explicit = _env("DATABASE_URL", "")
    if explicit:
        return explicit
    if database_backend() == "sqlite":
        path = _env("DATABASE_PATH", os.path.join(DATA_DIR, "kaoyan.db"))
        db_dir = os.path.dirname(path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        return f"sqlite:///{path}"
    host = _env("PG_HOST", "127.0.0.1")
    port = _env("PG_PORT", "5432")
    user = _env("PG_USER", "postgres")
    password = _env("PG_PASSWORD", "postgres")
    database = _env("PG_DATABASE", "kaoyan")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"


SQLALCHEMY_DATABASE_URL = build_database_url()
IS_POSTGRES = SQLALCHEMY_DATABASE_URL.startswith("postgresql")


def _connect_args() -> dict[str, Any]:
    """按后端给出连接参数。

    PG：注入语句超时与应用名，避免慢查询拖垮连接池。
    SQLite：check_same_thread=False 是 FastAPI 多线程场景的必需项。
    """
    if IS_POSTGRES:
        timeout_ms = _env_int("DB_STATEMENT_TIMEOUT_MS", 30000)
        options = f"-c statement_timeout={timeout_ms} -c timezone=UTC"
        return {
            "options": options,
            "application_name": _env("PG_APP_NAME", "kaoyan-backend"),
        }
    return {"check_same_thread": False, "timeout": 30}


def _engine_kwargs() -> dict[str, Any]:
    return {
        "echo": _env("SQL_ECHO", "").lower() in ("1", "true", "yes"),
        "pool_size": _env_int("DB_POOL_SIZE", 10),
        "max_overflow": _env_int("DB_MAX_OVERFLOW", 20),
        "pool_timeout": _env_int("DB_POOL_TIMEOUT", 30),
        "pool_recycle": _env_int("DB_POOL_RECYCLE", 3600),
        "pool_pre_ping": True,
    }


engine: Engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args=_connect_args(), **_engine_kwargs()
)


# --------------------------------------------------------------------------- #
# 连接级初始化
# --------------------------------------------------------------------------- #
@event.listens_for(engine, "connect")
def _on_sqlite_connect(dbapi_connection, connection_record) -> None:
    """SQLite PRAGMA：对齐原 database.py 的性能与并发设置。"""
    if IS_POSTGRES:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")     # WAL：读写不互斥
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-64000")   # 64MB 缓存
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=268435456")  # 256MB 内存映射
        cursor.execute("PRAGMA busy_timeout=5000")    # 等价于 PG 的锁等待
        cursor.execute("PRAGMA foreign_keys=ON")      # 与 PG 外键行为一致
    except Exception as exc:  # pragma: no cover
        logger.debug("SQLite PRAGMA 设置失败: %s", exc)
    finally:
        cursor.close()


@event.listens_for(engine, "connect")
def _on_postgres_connect(dbapi_connection, connection_record) -> None:
    """PG 连接级设置：统一 UTC 时区，避免 TIMESTAMPTZ 出现本地时区偏差。"""
    if not IS_POSTGRES:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute("SET default_text_search_config = 'simple'")
    except Exception as exc:  # pragma: no cover
        logger.debug("PG 连接级设置失败: %s", exc)
    finally:
        cursor.close()


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # 提交后不过期，避免异步场景下的额外查询
)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖注入：请求结束后自动关闭会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_session() -> Iterator[Session]:
    """上下文管理器：自动提交 / 回滚 / 关闭，供非 FastAPI 场景使用。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 健康检查
# --------------------------------------------------------------------------- #
def check_database_health() -> dict[str, Any]:
    """检查数据库连通性，并返回当前后端与向量方案。

    SQLAlchemy 2.x 要求文本 SQL 用 text() 包裹，否则 ArgumentError 会被
    except 吞掉，导致健康检查永远返回 unhealthy（原 database.py 的坑）。
    """
    db: Session | None = None
    result: dict[str, Any] = {
        "backend": database_backend(),
        "vector_backend": vector_backend(),
    }
    try:
        db = SessionLocal()
        row = db.execute(text("SELECT 1")).fetchone()
        result["status"] = "healthy"
        result["response"] = row[0] if row else None
        if IS_POSTGRES:
            result["pgvector_enabled"] = bool(
                db.execute(text("SELECT pgvector_available()")).scalar())
    except Exception as exc:
        logger.warning("数据库健康检查失败: %s", exc)
        result["status"] = "unhealthy"
        result["error"] = str(exc)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:  # pragma: no cover
                pass
    return result


# --------------------------------------------------------------------------- #
# 建表：解析 pg_schema.sql 的 \ir 分片并按序执行
# --------------------------------------------------------------------------- #
_SCHEMA_FILE = os.path.join(BASE_DIR, "pg_schema.sql")
_INCLUDE_RE = re.compile(r"^\\ir\s+(?P<target>.+?)\s*$")


def _resolve_sql(path: str, seen: frozenset[str] = frozenset()) -> str:
    """把 psql 的 \\ir 分片内联展开；其余 psql 元命令（\\echo 等）忽略。

    这样同一份 SQL 既能被 psql 直接执行，也能被 Python 侧执行，不养两套脚本。
    """
    resolved = os.path.abspath(path)
    if resolved in seen:
        raise RuntimeError(f"检测到循环引入: {resolved}")
    with open(resolved, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        match = _INCLUDE_RE.match(stripped)
        if match:
            child = os.path.normpath(
                os.path.join(os.path.dirname(resolved), match.group("target")))
            out.append(_resolve_sql(child, seen | {resolved}))
        elif stripped.startswith("\\"):
            continue  # psql 元命令，Python 侧无需处理
        else:
            out.append(line)
    return "\n".join(out)


def apply_schema(schema_file: str | None = None) -> None:
    """执行完整 DDL（幂等，全部使用 IF NOT EXISTS / DO 块容错）。

    注意：PG 的 GENERATED 列、部分索引、触发器函数都只存在于 SQL 里，
    因此建表必须走本函数，不要用 Base.metadata.create_all()。

    历史缺陷（2026-10-14 修复）
    --------------------------
    PG 分支原先用 ``connection.exec_driver_sql(sql_text)``。该路径会把
    整份多语句 SQL 送进 psycopg3 的查询预处理，遇到 psql 方言残留就会抛

        UnicodeDecodeError: 'utf-8' codec can't decode byte 0xef in position 1

    表现为**建表静默失败**，随后所有依赖 SQL-only 表（textbooks /
    notice_alerts / answer_review_queue / gate_logs 等）的接口集体 500 ——
    根因却藏在一次建表调用里，排查成本极高。
    改用**原生 DBAPI 游标 + autocommit**：psycopg3 在 autocommit 下能正确
    执行多语句脚本，且不做参数预处理，绕开该问题。
    """
    target = schema_file or _SCHEMA_FILE
    sql_text = _resolve_sql(target)
    if IS_POSTGRES:
        raw = engine.raw_connection()
        try:
            dbapi_conn = raw.driver_connection
            # 连接池可能交还一个处于事务中的连接，此时不允许切换 autocommit。
            # 先回滚把状态清成 IDLE，再开 autocommit 跑整份 DDL 脚本。
            if not dbapi_conn.autocommit:
                dbapi_conn.rollback()
                dbapi_conn.autocommit = True
            with dbapi_conn.cursor() as cur:
                cur.execute(sql_text)
        finally:
            raw.close()
    else:
        # sqlite3 的 execute 一次只能跑一条语句，需用 executescript
        raw = engine.raw_connection()
        try:
            raw.driver_connection.executescript(sql_text)
            raw.commit()
        finally:
            raw.close()
    logger.info("已应用数据库结构: %s", target)


def dispose_engine() -> None:
    """释放连接池（进程退出 / 测试收尾时调用）。"""
    engine.dispose()
