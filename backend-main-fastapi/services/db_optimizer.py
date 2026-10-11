"""
V3.0 数据库性能优化模块
- 缺失索引自动补全
- 查询缓存（内存LRU）
- 连接池优化
- 常用查询预编译
"""
import time
import logging
from collections import OrderedDict
from typing import Any, Callable, Optional, Dict, List
from functools import wraps

from sqlalchemy import text, Index
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LRU 缓存实现
# ---------------------------------------------------------------------------
class LRUCache:
    """简单的LRU缓存，用于缓存常用查询结果。"""

    def __init__(self, max_size: int = 1000, ttl: int = 60):
        self.max_size = max_size
        self.ttl = ttl  # 生存时间（秒）
        self.cache: OrderedDict[str, tuple] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存，过期返回None。"""
        if key not in self.cache:
            return None
        value, expire_time = self.cache[key]
        if time.time() > expire_time:
            del self.cache[key]
            return None
        self.cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """设置缓存。"""
        expire_time = time.time() + (ttl or self.ttl)
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (value, expire_time)
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def invalidate(self, key: str = None):
        """失效缓存，key为None时清空所有。"""
        if key is None:
            self.cache.clear()
        elif key in self.cache:
            del self.cache[key]

    def invalidate_prefix(self, prefix: str):
        """失效指定前缀的缓存。"""
        keys_to_delete = [k for k in self.cache if k.startswith(prefix)]
        for k in keys_to_delete:
            del self.cache[k]


# 全局缓存实例
_query_cache = LRUCache(max_size=2000, ttl=30)  # 查询缓存30秒
_stats_cache = LRUCache(max_size=500, ttl=300)   # 统计缓存5分钟


# ---------------------------------------------------------------------------
# 缓存装饰器
# ---------------------------------------------------------------------------
def cached(cache_instance: LRUCache = _query_cache, ttl: int = None):
    """缓存装饰器，用于缓存函数返回值。

    注意：被装饰的函数第一个参数必须是db（Session），缓存key会忽略db。
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(db: Session, *args, **kwargs):
            # 构建缓存key（忽略db参数）
            key_parts = [func.__name__]
            key_parts.extend([str(a) for a in args])
            key_parts.extend([f"{k}={v}" for k, v in sorted(kwargs.items())])
            cache_key = "|".join(key_parts)

            # 尝试从缓存获取
            cached_result = cache_instance.get(cache_key)
            if cached_result is not None:
                return cached_result

            # 执行函数
            result = func(db, *args, **kwargs)

            # 存入缓存
            cache_instance.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 缺失索引补全
# ---------------------------------------------------------------------------
MISSING_INDEXES = [
    # words表：复习查询常用
    ("words", "ix_words_status", "status"),
    ("words", "ix_words_due_date", "due_date"),
    ("words", "ix_words_status_due", "status, due_date"),

    # quiz_questions表：刷题查询常用
    ("quiz_questions", "ix_quiz_source", "source"),
    ("quiz_questions", "ix_quiz_type", "question_type"),
    ("quiz_questions", "ix_quiz_difficulty", "difficulty"),

    # knowledge_chunks表：RAG检索常用
    ("knowledge_chunks", "ix_chunks_created_at", "created_at"),
    ("knowledge_chunks", "ix_chunks_subject_doc", "subject, document_id"),

    # documents表：文档查询常用
    ("documents", "ix_documents_created_at", "created_at"),
    ("documents", "ix_documents_status", "index_status"),

    # 课表/番茄钟索引已随功能移除（2026-09），pomodoro_sessions 表已删除，
    # 残留定义会在启动时产生告警，已从 MISSING_INDEXES 移除。

    # tasks表：任务查询常用
    ("tasks", "ix_tasks_status", "status"),
    ("tasks", "ix_tasks_due_date", "due_date"),
    ("tasks", "ix_tasks_status_due", "status, due_date"),

    # error_records表：错题查询常用（掌握度字段为 accuracy，非 mastery）
    ("error_records", "ix_error_status", "status"),

    # flashcards表：记忆卡片查询常用（SM-2 调度字段为 next_review / mastery）
    ("flashcards", "ix_flashcards_mastery", "mastery"),
    ("flashcards", "ix_flashcards_next_review", "next_review"),
]


def create_missing_indexes(db: Session):
    """创建缺失的索引（如果不存在）。"""
    created_count = 0
    for table_name, index_name, columns in MISSING_INDEXES:
        try:
            # 检查索引是否已存在
            check_sql = text(f"""
                SELECT name FROM sqlite_master
                WHERE type='index' AND name=:index_name AND tbl_name=:table_name
            """)
            result = db.execute(check_sql, {"index_name": index_name, "table_name": table_name}).fetchone()
            if result:
                continue

            # 创建索引
            create_sql = text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns})")
            db.execute(create_sql)
            created_count += 1
            logger.info(f"创建索引: {index_name} ON {table_name} ({columns})")
        except Exception as e:
            logger.warning(f"创建索引失败 {index_name}: {e}")

    if created_count > 0:
        db.commit()
        logger.info(f"共创建 {created_count} 个缺失索引")
    return created_count


# ---------------------------------------------------------------------------
# SQLite 性能优化配置
# ---------------------------------------------------------------------------
def optimize_sqlite_connection(db: Session):
    """优化SQLite连接性能参数。"""
    optimizations = [
        ("PRAGMA journal_mode=WAL", "WAL模式（并发读写）"),
        ("PRAGMA synchronous=NORMAL", "正常同步（平衡安全和性能）"),
        ("PRAGMA cache_size=-64000", "缓存大小64MB"),
        ("PRAGMA temp_store=MEMORY", "临时表存内存"),
        ("PRAGMA mmap_size=268435456", "内存映射256MB"),
        ("PRAGMA busy_timeout=5000", "忙等待超时5秒"),
    ]

    for sql, desc in optimizations:
        try:
            db.execute(text(sql))
        except Exception as e:
            logger.debug(f"SQLite优化失败 {desc}: {e}")

    db.commit()


# ---------------------------------------------------------------------------
# 常用查询优化函数
# ---------------------------------------------------------------------------
@cached(_stats_cache, ttl=300)
def get_study_stats_cached(db: Session) -> Dict[str, Any]:
    """缓存的学习统计查询（5分钟缓存）。

    注意：番茄钟（pomodoro_sessions）模块已移除，学习时长统计
    以 study_sessions 表为准，此处不再统计番茄钟次数。
    """
    from models import Task, QuizQuestion, ErrorRecord, Word, StudySession
    from sqlalchemy import func

    stats = {
        "total_tasks": db.query(func.count(Task.id)).scalar() or 0,
        "completed_tasks": db.query(func.count(Task.id)).filter(Task.status == "done").scalar() or 0,
        "total_questions": db.query(func.count(QuizQuestion.id)).scalar() or 0,
        "total_errors": db.query(func.count(ErrorRecord.id)).scalar() or 0,
        "active_errors": db.query(func.count(ErrorRecord.id)).filter(ErrorRecord.status == "active").scalar() or 0,
        "total_words": db.query(func.count(Word.id)).scalar() or 0,
        "mastered_words": db.query(func.count(Word.id)).filter(Word.status == "mastered").scalar() or 0,
        "total_study_sessions": db.query(func.count(StudySession.id)).scalar() or 0,
    }
    return stats


@cached(_query_cache, ttl=60)
def get_due_words_cached(db: Session, limit: int = 50) -> List[Any]:
    """缓存的到期单词查询（60秒缓存）。"""
    from models import Word
    from datetime import date
    today = date.today()
    return db.query(Word).filter(
        Word.status != "mastered",
        Word.due_date <= today,
    ).order_by(Word.due_date.asc()).limit(limit).all()


def invalidate_word_cache():
    """失效单词相关缓存（单词增删改后调用）。"""
    _query_cache.invalidate_prefix("get_due_words_cached")
    _stats_cache.invalidate_prefix("get_study_stats_cached")


def invalidate_question_cache():
    """失效题目相关缓存（题目增删改后调用）。"""
    _stats_cache.invalidate_prefix("get_study_stats_cached")


# ---------------------------------------------------------------------------
# 查询性能监控
# ---------------------------------------------------------------------------
class QueryTimer:
    """查询性能计时器，用于监控慢查询。"""

    def __init__(self, threshold_ms: int = 100):
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


# ---------------------------------------------------------------------------
# 批量操作优化
# ---------------------------------------------------------------------------
def bulk_insert_with_chunks(db: Session, objects: List[Any], chunk_size: int = 100):
    """分块批量插入，避免单次插入过多导致性能问题。"""
    total = len(objects)
    for i in range(0, total, chunk_size):
        chunk = objects[i:i + chunk_size]
        db.bulk_save_objects(chunk)
        db.commit()
        logger.debug(f"批量插入: {i + len(chunk)}/{total}")
    return total


def bulk_update_with_chunks(db: Session, model: Any, updates: List[Dict], chunk_size: int = 50):
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


# ---------------------------------------------------------------------------
# 初始化函数
# ---------------------------------------------------------------------------
def init_database_optimization(db: Session):
    """初始化数据库优化（启动时调用）。"""
    logger.info("开始数据库性能优化初始化...")

    # 1. 优化SQLite连接
    optimize_sqlite_connection(db)

    # 2. 创建缺失索引
    index_count = create_missing_indexes(db)

    logger.info(f"数据库优化完成: 创建{index_count}个索引")
    return {
        "indexes_created": index_count,
        "cache_enabled": True,
        "wal_mode": True,
    }
