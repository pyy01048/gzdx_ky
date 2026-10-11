"""
V3.0 AI调用优化模块
- 响应缓存（相同问题直接返回缓存）
- 超时优化（自适应超时）
- 批量处理
- 流式响应优化
- 请求合并
"""
import time
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple
from collections import OrderedDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AI响应缓存
# ---------------------------------------------------------------------------
class AIResponseCache:
    """AI响应缓存，相同问题直接返回缓存，避免重复调用。"""

    def __init__(self, max_size: int = 500, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl  # 缓存1小时
        self.cache: OrderedDict[str, tuple] = OrderedDict()
        self.hit_count = 0
        self.miss_count = 0

    def _make_key(self, messages: List[Dict], provider: str = None, model: str = None) -> str:
        """生成缓存key。"""
        key_parts = []
        for msg in messages:
            key_parts.append(f"{msg.get('role', '')}:{msg.get('content', '')}")
        key_parts.append(f"provider:{provider or 'default'}")
        key_parts.append(f"model:{model or 'default'}")
        key_str = "|".join(key_parts)
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, messages: List[Dict], provider: str = None, model: str = None) -> Optional[Dict]:
        """获取缓存的AI响应。"""
        key = self._make_key(messages, provider, model)
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
        logger.debug(f"AI缓存命中 (命中率: {self.hit_count/(self.hit_count+self.miss_count)*100:.1f}%)")
        return value

    def set(self, messages: List[Dict], response: Dict, provider: str = None, model: str = None, ttl: int = None):
        """设置AI响应缓存。"""
        key = self._make_key(messages, provider, model)
        expire_time = time.time() + (ttl or self.ttl)
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (response, expire_time)
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def clear(self):
        """清空缓存。"""
        self.cache.clear()
        self.hit_count = 0
        self.miss_count = 0

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


# 全局AI响应缓存
_ai_cache = AIResponseCache(max_size=1000, ttl=1800)  # 30分钟缓存


def get_ai_cache() -> AIResponseCache:
    """获取全局AI响应缓存。"""
    return _ai_cache


# ---------------------------------------------------------------------------
# 自适应超时
# ---------------------------------------------------------------------------
class AdaptiveTimeout:
    """自适应超时，根据问题复杂度和历史响应时间调整超时。"""

    def __init__(self, base_timeout: int = 30, max_timeout: int = 120, min_timeout: int = 10):
        self.base_timeout = base_timeout
        self.max_timeout = max_timeout
        self.min_timeout = min_timeout
        self.response_times: List[float] = []

    def estimate_timeout(self, question: str, is_complex: bool = False) -> int:
        """估算超时时间。"""
        timeout = self.base_timeout

        # 问题长度调整
        if len(question) > 200:
            timeout += 10
        if len(question) > 500:
            timeout += 15

        # 复杂问题调整
        if is_complex:
            timeout += 20

        # 历史平均响应时间调整
        if self.response_times:
            avg_time = sum(self.response_times[-10:]) / min(10, len(self.response_times))
            timeout = max(timeout, int(avg_time * 1.5))

        return min(self.max_timeout, max(self.min_timeout, timeout))

    def record_response_time(self, response_time: float):
        """记录响应时间。"""
        self.response_times.append(response_time)
        if len(self.response_times) > 100:
            self.response_times = self.response_times[-100:]


# 全局自适应超时
_adaptive_timeout = AdaptiveTimeout()


def get_adaptive_timeout() -> AdaptiveTimeout:
    """获取全局自适应超时。"""
    return _adaptive_timeout


# ---------------------------------------------------------------------------
# 请求合并（批量处理）
# ---------------------------------------------------------------------------
class RequestBatcher:
    """请求合并器，将多个小请求合并为一个批量请求。"""

    def __init__(self, batch_size: int = 5, max_wait_ms: int = 100):
        self.batch_size = batch_size
        self.max_wait_ms = max_wait_ms
        self.pending: List[Dict] = []
        self.last_flush = time.time()

    def add(self, request: Dict) -> Optional[int]:
        """添加请求，返回批次ID（如果立即刷新）。"""
        self.pending.append(request)
        if len(self.pending) >= self.batch_size or (time.time() - self.last_flush) * 1000 >= self.max_wait_ms:
            return self.flush()
        return None

    def flush(self) -> int:
        """刷新批次，返回批次大小。"""
        batch_size = len(self.pending)
        self.pending = []
        self.last_flush = time.time()
        return batch_size


# ---------------------------------------------------------------------------
# 流式响应优化
# ---------------------------------------------------------------------------
class StreamOptimizer:
    """流式响应优化器，减少首字延迟和卡顿。"""

    def __init__(self, chunk_size: int = 10, min_interval_ms: int = 10):
        self.chunk_size = chunk_size
        self.min_interval_ms = min_interval_ms
        self.buffer: List[str] = []
        self.last_send = time.time()

    def add_chunk(self, chunk: str) -> Optional[List[str]]:
        """添加chunk，返回应该发送的chunks（如果达到阈值）。"""
        self.buffer.append(chunk)
        now = time.time()
        if len(self.buffer) >= self.chunk_size or (now - self.last_send) * 1000 >= self.min_interval_ms:
            chunks_to_send = self.buffer
            self.buffer = []
            self.last_send = now
            return chunks_to_send
        return None

    def flush(self) -> List[str]:
        """刷新缓冲区。"""
        chunks = self.buffer
        self.buffer = []
        return chunks


# ---------------------------------------------------------------------------
# 快速回答（简单问题本地快速回答）
# ---------------------------------------------------------------------------
class QuickAnswer:
    """快速回答器，对简单问题进行本地快速回答，避免调用API。"""

    # 常见问题快速回答模板
    QUICK_ANSWERS = {
        "你好": "你好！我是你的考研学习助手，有什么可以帮你的吗？",
        "你是谁": "我是考研学习助手，可以帮你答疑、刷题、制定学习计划。",
        "谢谢": "不客气！祝你考研顺利！",
        "再见": "再见！加油！",
    }

    @classmethod
    def try_quick_answer(cls, question: str) -> Optional[str]:
        """尝试快速回答，返回None表示需要调用AI。"""
        q = question.strip().lower()

        # 精确匹配
        if q in cls.QUICK_ANSWERS:
            return cls.QUICK_ANSWERS[q]

        # 简单问候
        if any(greet in q for greet in ["你好", "hi", "hello", "在吗"]):
            if len(q) < 10:
                return "你好！有什么学习问题可以帮你的吗？"

        # 简单感谢
        if any(thanks in q for thanks in ["谢谢", "感谢", "thanks"]):
            if len(q) < 10:
                return "不客气！继续加油！"

        return None


# ---------------------------------------------------------------------------
# AI调用性能监控
# ---------------------------------------------------------------------------
class AIPerformanceMonitor:
    """AI调用性能监控器。"""

    def __init__(self):
        self.total_calls = 0
        self.total_time = 0
        self.slow_calls = []
        self.provider_stats: Dict[str, Dict] = {}

    def record_call(self, provider: str, model: str, response_time: float, success: bool = True):
        """记录一次AI调用。"""
        self.total_calls += 1
        self.total_time += response_time

        if provider not in self.provider_stats:
            self.provider_stats[provider] = {"calls": 0, "total_time": 0, "success": 0, "fail": 0}
        self.provider_stats[provider]["calls"] += 1
        self.provider_stats[provider]["total_time"] += response_time
        if success:
            self.provider_stats[provider]["success"] += 1
        else:
            self.provider_stats[provider]["fail"] += 1

        if response_time > 10:  # 超过10秒记为慢调用
            self.slow_calls.append({
                "provider": provider,
                "model": model,
                "time": response_time,
                "timestamp": time.time(),
            })
            if len(self.slow_calls) > 100:
                self.slow_calls = self.slow_calls[-100:]

    def stats(self) -> Dict:
        """获取性能统计。"""
        return {
            "total_calls": self.total_calls,
            "avg_response_time": self.total_time / self.total_calls if self.total_calls > 0 else 0,
            "slow_calls": len(self.slow_calls),
            "provider_stats": self.provider_stats,
            "cache_stats": _ai_cache.stats(),
        }


# 全局性能监控
_perf_monitor = AIPerformanceMonitor()


def get_perf_monitor() -> AIPerformanceMonitor:
    """获取全局性能监控器。"""
    return _perf_monitor


# ---------------------------------------------------------------------------
# 优化后的AI调用函数
# ---------------------------------------------------------------------------
async def optimized_ai_call(
    ai_service,
    messages: List[Dict],
    provider: str = None,
    model: str = None,
    use_cache: bool = True,
    stream: bool = False,
) -> Dict:
    """
    优化后的AI调用函数。

    优化点：
    1. 快速回答（简单问题本地回答）
    2. 响应缓存（相同问题直接返回缓存）
    3. 自适应超时
    4. 性能监控
    """
    # 1. 快速回答检查
    if messages and messages[-1].get("role") == "user":
        question = messages[-1].get("content", "")
        quick_answer = QuickAnswer.try_quick_answer(question)
        if quick_answer:
            logger.debug("快速回答命中")
            return {"content": quick_answer, "quick_answer": True}

    # 2. 缓存检查
    if use_cache:
        cached = _ai_cache.get(messages, provider, model)
        if cached:
            return {**cached, "cached": True}

    # 3. 自适应超时
    question = messages[-1].get("content", "") if messages else ""
    is_complex = len(question) > 100 or any(kw in question for kw in ["为什么", "证明", "推导", "分析"])
    timeout = _adaptive_timeout.estimate_timeout(question, is_complex)

    # 4. 调用AI服务
    start_time = time.time()
    try:
        result = await ai_service.chat(
            messages,
            provider_id=provider,
            timeout=timeout,
        )
        response_time = time.time() - start_time

        # 5. 记录性能
        _adaptive_timeout.record_response_time(response_time)
        _perf_monitor.record_call(provider or "default", model or "default", response_time, success=True)

        # 6. 存入缓存
        if use_cache and result.get("content"):
            _ai_cache.set(messages, result, provider, model)

        return {**result, "response_time": response_time, "timeout": timeout}

    except Exception as e:
        response_time = time.time() - start_time
        _perf_monitor.record_call(provider or "default", model or "default", response_time, success=False)
        raise e
