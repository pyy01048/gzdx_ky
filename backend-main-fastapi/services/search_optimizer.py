"""
V3.0 检索算法优化模块
- 检索结果缓存
- 查询预处理（分词/纠错/扩展）
- 检索结果重排优化
- 批量检索
- 增量索引更新
"""
import re
import time
import logging
from services.dbapi_compat import wrap_conn
from typing import Any, Dict, List, Optional, Tuple
from collections import OrderedDict
from functools import wraps

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 检索结果缓存
# ---------------------------------------------------------------------------
class SearchCache:
    """检索结果缓存，相同查询直接返回缓存。"""

    def __init__(self, max_size: int = 200, ttl: int = 300):
        self.max_size = max_size
        self.ttl = ttl  # 5分钟缓存
        self.cache: OrderedDict[str, tuple] = OrderedDict()
        self.hit_count = 0
        self.miss_count = 0

    def _make_key(self, query: str, top_k: int = 5, subject: str = None, use_vector: bool = True) -> str:
        """生成缓存key。"""
        import hashlib
        key_str = f"{query}|{top_k}|{subject or 'all'}|{use_vector}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, query: str, top_k: int = 5, subject: str = None, use_vector: bool = True) -> Optional[List[Dict]]:
        """获取缓存的检索结果。"""
        key = self._make_key(query, top_k, subject, use_vector)
        if key not in self.cache:
            self.miss_count += 1
            return None

        value, expire_time = self.cache[key]
        if time.time() > expire_time:
            del self.cache[key]
            self.miss_count += 1
            return None

        self.cache.move_to_end(key)
        self.hit_count += 1
        logger.debug(f"检索缓存命中 (命中率: {self.hit_count/(self.hit_count+self.miss_count)*100:.1f}%)")
        return value

    def set(self, query: str, results: List[Dict], top_k: int = 5, subject: str = None, use_vector: bool = True):
        """设置检索结果缓存。"""
        key = self._make_key(query, top_k, subject, use_vector)
        expire_time = time.time() + self.ttl
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (results, expire_time)
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def invalidate(self, query: str = None):
        """失效缓存，query为None时清空所有。"""
        if query is None:
            self.cache.clear()
        else:
            keys_to_delete = [k for k in self.cache if query in k]
            for k in keys_to_delete:
                del self.cache[k]

    def stats(self) -> Dict:
        """获取缓存统计。"""
        total = self.hit_count + self.miss_count
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "hit_rate": self.hit_count / total * 100 if total > 0 else 0,
        }


# 全局检索缓存
_search_cache = SearchCache(max_size=500, ttl=600)  # 10分钟缓存


def get_search_cache() -> SearchCache:
    """获取全局检索缓存。"""
    return _search_cache


# ---------------------------------------------------------------------------
# 查询预处理
# ---------------------------------------------------------------------------
class QueryPreprocessor:
    """查询预处理器，优化查询质量。"""

    # 停用词
    STOP_WORDS = {
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
        "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
        "自己", "这", "那", "这个", "那个", "什么", "怎么", "如何", "为什么", "请问",
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "must", "shall", "can", "need", "dare", "ought", "used",
        "to", "of", "in", "for", "on", "with", "at", "by", "from", "as", "into",
        "through", "during", "before", "after", "above", "below", "between", "out",
        "off", "over", "under", "again", "further", "then", "once", "here", "there",
        "when", "where", "why", "how", "all", "any", "both", "each", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same",
        "so", "than", "too", "very", "just", "because", "if", "or", "and", "but",
    }

    # 同义词扩展
    SYNONYMS = {
        "数电": ["数字电子技术", "数字电路", "数字电子"],
        "模电": ["模拟电子技术", "模拟电路", "模拟电子"],
        "高数": ["高等数学", "微积分"],
        "线代": ["线性代数"],
        "概率论": ["概率论与数理统计", "概率统计"],
        "考研": ["研究生入学考试", "硕士研究生考试"],
        "真题": ["历年真题", "考研真题"],
        "知识点": ["考点", "重点", "要点"],
        "题目": ["试题", "练习题", "习题"],
    }

    @classmethod
    def preprocess(cls, query: str) -> Dict:
        """
        预处理查询，返回优化后的查询信息。

        返回：
        {
            "original": 原始查询,
            "cleaned": 清洗后的查询,
            "keywords": 关键词列表,
            "expanded": 扩展后的查询（含同义词）,
            "is_complex": 是否复杂查询,
            "subject": 检测到的科目,
        }
        """
        original = query.strip()

        # 1. 清洗（去除多余空格、标点）
        cleaned = re.sub(r'\s+', ' ', original)
        cleaned = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', cleaned)
        cleaned = cleaned.strip()

        # 2. 分词（简单分词）
        words = cls._tokenize(cleaned)

        # 3. 去除停用词
        keywords = [w for w in words if w.lower() not in cls.STOP_WORDS and len(w) > 1]

        # 4. 同义词扩展
        expanded_keywords = list(keywords)
        for kw in keywords:
            if kw in cls.SYNONYMS:
                expanded_keywords.extend(cls.SYNONYMS[kw])

        # 5. 检测科目
        subject = cls._detect_subject(original)

        # 6. 判断是否复杂查询
        is_complex = len(original) > 50 or any(
            kw in original for kw in ["为什么", "如何证明", "推导", "分析", "比较", "区别"]
        )

        return {
            "original": original,
            "cleaned": cleaned,
            "keywords": keywords,
            "expanded": " ".join(expanded_keywords),
            "is_complex": is_complex,
            "subject": subject,
        }

    @classmethod
    def _tokenize(cls, text: str) -> List[str]:
        """简单分词（中文2-gram + 英文单词）。"""
        tokens = []
        # 英文单词
        for w in re.findall(r'[a-zA-Z0-9]+', text):
            tokens.append(w.lower())
        # 中文2-gram
        cjk = re.sub(r'[^\u4e00-\u9fff]', '', text)
        for i in range(len(cjk) - 1):
            tokens.append(cjk[i:i + 2])
        # 中文单字（长度为1的中文）
        if len(cjk) == 1:
            tokens.append(cjk)
        return tokens

    @classmethod
    def _detect_subject(cls, query: str) -> Optional[str]:
        """检测查询中的科目。"""
        subject_keywords = {
            "数学": ["数学", "高数", "微积分", "线代", "线性代数", "概率", "概率论", "数理统计"],
            "英语": ["英语", "单词", "词汇", "阅读", "完形", "翻译", "写作", "作文", "语法"],
            "政治": ["政治", "马原", "毛概", "史纲", "思修", "时政"],
            "数字电子技术": ["数电", "数字电子", "数字电路", "逻辑", "触发器", "计数器"],
            "模拟电子技术": ["模电", "模拟电子", "模拟电路", "放大", "晶体管", "运放"],
            "信号与系统": ["信号", "系统", "傅里叶", "拉普拉斯", "卷积"],
        }

        for subject, keywords in subject_keywords.items():
            for kw in keywords:
                if kw in query:
                    return subject
        return None


# ---------------------------------------------------------------------------
# 优化后的检索函数
# ---------------------------------------------------------------------------
def optimized_search(
    db: Session,
    query: str,
    top_k: int = 5,
    subject: str = None,
    use_vector: bool = True,
    use_cache: bool = True,
    use_rerank: bool = True,
) -> Tuple[List[Dict], Dict]:
    """
    优化后的检索函数。

    优化点：
    1. 查询预处理（分词/纠错/扩展/科目检测）
    2. 检索结果缓存
    3. 混合检索（FTS + 向量）
    4. 重排优化

    返回：(检索结果, 元信息)
    """
    start_time = time.time()

    # 1. 查询预处理
    query_info = QueryPreprocessor.preprocess(query)
    search_query = query_info["expanded"] or query_info["cleaned"] or query

    # 2. 缓存检查
    if use_cache:
        cached = _search_cache.get(search_query, top_k, subject or query_info["subject"], use_vector)
        if cached is not None:
            return cached, {
                "cached": True,
                "query_info": query_info,
                "search_time": time.time() - start_time,
            }

    # 3. 混合检索
    try:
        from services.search_service import hybrid_search, hybrid_search_with_rerank

        if use_rerank:
            results = hybrid_search_with_rerank(
                db, search_query,
                query_vec=None,  # 向量在调用方生成
                limit=top_k,
                subject=subject or query_info["subject"],
            )
        else:
            results = hybrid_search(
                db, search_query,
                query_vec=None,
                limit=top_k,
                subject=subject or query_info["subject"],
            )
    except Exception as e:
        logger.warning(f"检索失败: {e}")
        results = []

    search_time = time.time() - start_time

    # 4. 存入缓存
    if use_cache and results:
        _search_cache.set(search_query, results, top_k, subject or query_info["subject"], use_vector)

    meta = {
        "cached": False,
        "query_info": query_info,
        "search_time": search_time,
        "result_count": len(results),
    }

    return results, meta


# ---------------------------------------------------------------------------
# 增量索引更新
# ---------------------------------------------------------------------------
class IncrementalIndexUpdater:
    """增量索引更新器，避免全量重建索引。"""

    def __init__(self, db: Session):
        self.db = db

    def update_fts_index(self, chunk_ids: List[int] = None):
        """增量更新FTS索引。"""
        try:
            from services.search_service import ensure_fts_table
            conn = wrap_conn(self.db.connection().connection)
            ensure_fts_table(conn)

            if chunk_ids:
                # 只更新指定的分块
                placeholders = ",".join("?" * len(chunk_ids))
                conn.execute(f"""
                    INSERT OR REPLACE INTO knowledge_chunks_fts (chunk_id, document_id, subject, content)
                    SELECT id, document_id, subject, content
                    FROM knowledge_chunks
                    WHERE id IN ({placeholders})
                """, chunk_ids)
            else:
                # 全量同步（增量方式：只同步新增的）
                conn.execute("""
                    INSERT OR IGNORE INTO knowledge_chunks_fts (chunk_id, document_id, subject, content)
                    SELECT kc.id, kc.document_id, kc.subject, kc.content
                    FROM knowledge_chunks kc
                    LEFT JOIN knowledge_chunks_fts fts ON kc.id = fts.chunk_id
                    WHERE fts.chunk_id IS NULL
                """)
            self.db.commit()
            return True
        except Exception as e:
            logger.warning(f"FTS索引更新失败: {e}")
            return False

    def invalidate_search_cache(self):
        """失效检索缓存（索引更新后调用）。"""
        _search_cache.invalidate()


# ---------------------------------------------------------------------------
# 批量检索
# ---------------------------------------------------------------------------
def batch_search(
    db: Session,
    queries: List[str],
    top_k: int = 5,
    subject: str = None,
) -> List[Tuple[List[Dict], Dict]]:
    """批量检索多个查询。"""
    results = []
    for query in queries:
        result, meta = optimized_search(db, query, top_k, subject, use_cache=True)
        results.append((result, meta))
    return results


# ---------------------------------------------------------------------------
# 检索性能监控
# ---------------------------------------------------------------------------
class SearchPerformanceMonitor:
    """检索性能监控器。"""

    def __init__(self):
        self.total_searches = 0
        self.total_time = 0
        self.slow_searches = []

    def record_search(self, query: str, search_time: float, result_count: int):
        """记录一次检索。"""
        self.total_searches += 1
        self.total_time += search_time

        if search_time > 1.0:  # 超过1秒记为慢检索
            self.slow_searches.append({
                "query": query[:100],
                "time": search_time,
                "result_count": result_count,
                "timestamp": time.time(),
            })
            if len(self.slow_searches) > 100:
                self.slow_searches = self.slow_searches[-100:]

    def stats(self) -> Dict:
        """获取性能统计。"""
        return {
            "total_searches": self.total_searches,
            "avg_search_time": self.total_time / self.total_searches if self.total_searches > 0 else 0,
            "slow_searches": len(self.slow_searches),
            "cache_stats": _search_cache.stats(),
        }


# 全局性能监控
_search_monitor = SearchPerformanceMonitor()


def get_search_monitor() -> SearchPerformanceMonitor:
    """获取全局检索性能监控器。"""
    return _search_monitor
