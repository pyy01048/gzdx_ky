"""
V3.0 数据库连接与会话管理模块（性能优化版）
- 连接池配置
- WAL模式
- 超时优化
- 会话管理
"""

import os
import time
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 路径配置
# --------------------------------------------------------------------------- #
# 幂等加载 .env（供独立脚本直接导入时使用）
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 数据库路径配置化：后端类型与连接串统一由 core.db_session 决定。
# 变更原因（2026-10-14）：本模块此前**只认 DATABASE_PATH、永远建 SQLite URL**，
# 完全不读 DATABASE_BACKEND，导致"切到 PG"只改 .env 毫无效果（实测后端仍连 SQLite）。
def _resolve_database_url() -> tuple[str, bool]:
    """解析连接串与后端类型，与 core.db_session 保持单一来源。"""
    try:
        from core.db_session import build_database_url, IS_POSTGRES
        return build_database_url(), IS_POSTGRES
    except Exception as exc:  # pragma: no cover - core 不可用时退回 SQLite
        logger.warning("core.db_session 不可用，退回 SQLite：%s", exc)
        configured = os.environ.get("DATABASE_PATH", "").strip()
        path = configured or os.path.join(DATA_DIR, "kaoyan.db")
        db_dir = os.path.dirname(path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        return f"sqlite:///{path}", False


SQLALCHEMY_DATABASE_URL, IS_POSTGRES = _resolve_database_url()

# --------------------------------------------------------------------------- #
# 引擎与会话（V3.0 性能优化）
# --------------------------------------------------------------------------- #
if IS_POSTGRES:
    # PG：不用 SQLite 的 connect_args；强制连接时区 UTC，与 TIMESTAMPTZ 语义一致
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        echo=False,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True,
        connect_args={"options": "-c timezone=UTC"},
    )
else:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={
            "check_same_thread": False,
            "timeout": 30,  # 连接超时30秒
        },
        echo=False,
        # 连接池配置
        poolclass=QueuePool,
        pool_size=10,           # 连接池大小
        max_overflow=20,         # 最大溢出连接数
        pool_timeout=30,         # 获取连接超时
        pool_recycle=3600,       # 连接回收时间（1小时）
        pool_pre_ping=True,      # 连接前检查（避免断连）
    )

# SQLite 性能优化（连接创建时执行）—— 仅 SQLite 后端生效。
# PG 连接上执行 PRAGMA 会直接报语法错误，故必须按后端分流注册。
if not IS_POSTGRES:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")        # WAL模式（并发读写）
            cursor.execute("PRAGMA synchronous=NORMAL")       # 正常同步
            cursor.execute("PRAGMA cache_size=-64000")        # 64MB缓存
            cursor.execute("PRAGMA temp_store=MEMORY")         # 临时表存内存
            cursor.execute("PRAGMA mmap_size=268435456")      # 256MB内存映射
            cursor.execute("PRAGMA busy_timeout=5000")         # 忙等待5秒
            cursor.execute("PRAGMA foreign_keys=ON")            # 启用外键
        except Exception as e:
            logger.debug(f"SQLite PRAGMA设置失败: {e}")
        finally:
            cursor.close()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,  # 提交后不过期（提升性能）
)

Base = declarative_base()


# --------------------------------------------------------------------------- #
# ORM 旧属性名兼容别名
#
# 注意：**不能在此 import models** —— models.py 需要 `from database import Base`，
# 在此处反向 import 会形成循环导入（实测报 module 'models' has no attribute
# 'QuizQuestion'）。故别名安装由业务入口负责：main.py 在 import models 之后
# 调用 orm_aliases.install()。
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 依赖注入
# --------------------------------------------------------------------------- #
_orm_compat_applied = False


def _ensure_orm_compat() -> None:
    """一次性安装 ORM 兼容别名与 PG 枚举类型适配（幂等）。

    为什么放在 get_db() 里懒执行，而不是模块导入时：
    `models.py` 的映射类由**各 router 在导入时**逐个注册（main.py 的
    `from models import (...)` 只导入了一部分）。若在 database.py 模块级执行，
    大量模型尚未注册，适配会漏。放在每个请求的会话创建前做一次，
    此时全部模型必已注册完毕。

    不做会怎样（实测）：PG 原生枚举不能与 varchar 直接比较，
    `Task.status == "doing"` 抛 `operator does not exist: task_status = character varying`。
    """
    global _orm_compat_applied
    if _orm_compat_applied:
        return
    try:
        import orm_aliases
        orm_aliases.install()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ORM 兼容适配安装失败：%s", exc)
    _orm_compat_applied = True


def get_db():
    """FastAPI 依赖注入：获取数据库会话，请求结束后自动关闭。"""
    _ensure_orm_compat()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 上下文管理器（用于非FastAPI场景）
# --------------------------------------------------------------------------- #
@contextmanager
def get_session():
    """上下文管理器：自动管理会话生命周期。"""
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
# 查询性能监控
# --------------------------------------------------------------------------- #
class QueryProfiler:
    """查询性能分析器，用于监控慢查询。"""

    def __init__(self, threshold_ms=100):
        self.threshold_ms = threshold_ms
        self.slow_queries = []

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (time.time() - self.start) * 1000
        if elapsed > self.threshold_ms:
            self.slow_queries.append({
                "time": time.time(),
                "elapsed_ms": elapsed,
            })
            logger.warning(f"慢查询: {elapsed:.1f}ms")
        return False


# --------------------------------------------------------------------------- #
# 批量操作工具
# --------------------------------------------------------------------------- #
def bulk_insert(db, model, objects, chunk_size=100):
    """分块批量插入。"""
    total = len(objects)
    for i in range(0, total, chunk_size):
        chunk = objects[i:i + chunk_size]
        db.bulk_save_objects(chunk)
        db.commit()
        logger.debug(f"批量插入: {i + len(chunk)}/{total}")
    return total


def bulk_update(db, model, updates, chunk_size=50):
    """分块批量更新。"""
    total = len(updates)
    for i in range(0, total, chunk_size):
        chunk = updates[i:i + chunk_size]
        for update in chunk:
            obj_id = update.pop("id", None)
            if obj_id:
                db.query(model).filter(model.id == obj_id).update(update)
        db.commit()
    return total


# --------------------------------------------------------------------------- #
# 数据库健康检查
# --------------------------------------------------------------------------- #
def check_database_health():
    """检查数据库健康状态。

    SQLAlchemy 2.x 要求文本 SQL 显式声明为 text()，否则 execute() 抛
    ArgumentError 并被下面 except 吞掉，导致健康检查永远返回 unhealthy。
    """
    db = None
    try:
        db = SessionLocal()
        result = db.execute(text("SELECT 1")).fetchone()
        return {
            "status": "healthy",
            "response": result[0] if result else None,
        }
    except Exception as e:
        logger.warning("数据库健康检查失败: %s", e)
        return {
            "status": "unhealthy",
            "error": str(e),
        }
    finally:
        # SessionLocal() 成功后必须释放，避免连接池泄漏
        if db is not None:
            try:
                db.close()
            except Exception:  # pragma: no cover - 关闭失败不影响健康检查结论
                pass
