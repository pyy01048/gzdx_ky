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

# 数据库路径配置化：优先使用 .env / 环境变量 DATABASE_PATH（第二轮升级：database 专门文件夹）
_configured_db = os.environ.get("DATABASE_PATH", "").strip()
if _configured_db:
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{_configured_db}"
    _db_dir = os.path.dirname(_configured_db)
    if _db_dir:
        os.makedirs(_db_dir, exist_ok=True)
else:
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'kaoyan.db')}"

# --------------------------------------------------------------------------- #
# 引擎与会话（V3.0 性能优化）
# --------------------------------------------------------------------------- #
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

# SQLite 性能优化（连接创建时执行）
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
# 依赖注入
# --------------------------------------------------------------------------- #
def get_db():
    """FastAPI 依赖注入：获取数据库会话，请求结束后自动关闭。"""
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
