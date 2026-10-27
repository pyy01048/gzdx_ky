"""
V3.0 后端服务优化模块
- 后台任务队列
- 异步处理优化
- 限流
- 性能监控

说明：响应压缩由部署层的 nginx gzip 负责（gzip_types 含
application/json 等），应用层不再做假压缩头。
"""
import time
import asyncio
import logging
import os
from typing import Any, Callable, Dict, List, Optional
from collections import deque
from functools import wraps

from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 慢请求日志阈值默认 3000ms：低于此值只记 debug，避免刷屏淹没真正的慢接口。
DEFAULT_SLOW_REQUEST_THRESHOLD_MS = 3000


def _load_slow_threshold_ms() -> int:
    """从环境变量 ``SLOW_REQUEST_THRESHOLD_MS`` 读取慢请求阈值。"""
    raw = os.getenv("SLOW_REQUEST_THRESHOLD_MS", "").strip()
    if not raw:
        return DEFAULT_SLOW_REQUEST_THRESHOLD_MS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            f"SLOW_REQUEST_THRESHOLD_MS={raw!r} 不是合法整数，"
            f"回退默认值 {DEFAULT_SLOW_REQUEST_THRESHOLD_MS}"
        )
        return DEFAULT_SLOW_REQUEST_THRESHOLD_MS
    return value if value > 0 else DEFAULT_SLOW_REQUEST_THRESHOLD_MS


# ---------------------------------------------------------------------------
# 请求计时中间件
# ---------------------------------------------------------------------------
class RequestTimer:
    """请求计时器中间件，记录慢请求。

    阈值默认 **3000ms**（可通过环境变量 ``SLOW_REQUEST_THRESHOLD_MS`` 覆盖）。
    之前是 500ms，在本机开发时几乎每条请求都刷警告，等于没开。
    调高到 3s 后，日志里出现的才是真正值得关注的慢接口
    （例如 `慢请求: GET /api/storage/scan - 76941.2ms` 这种）。
    """

    def __init__(self, threshold_ms: Optional[int] = None):
        if threshold_ms is None:
            threshold_ms = _load_slow_threshold_ms()
        self.threshold_ms = threshold_ms
        self.slow_requests = deque(maxlen=100)

    async def __call__(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        elapsed = (time.time() - start_time) * 1000

        response.headers["X-Process-Time"] = f"{elapsed:.2f}ms"

        if elapsed > self.threshold_ms:
            self.slow_requests.append({
                "path": request.url.path,
                "method": request.method,
                "elapsed_ms": elapsed,
                "timestamp": time.time(),
            })
            logger.warning(
                f"慢请求: {request.method} {request.url.path} - {elapsed:.1f}ms "
                f"(阈值 {self.threshold_ms}ms)"
            )
        else:
            logger.debug(f"请求耗时: {request.method} {request.url.path} - {elapsed:.1f}ms")

        return response

    def get_slow_requests(self) -> List[Dict]:
        """获取慢请求列表。"""
        return list(self.slow_requests)


request_timer = RequestTimer()  # 阈值默认 3000ms，可用 SLOW_REQUEST_THRESHOLD_MS 覆盖


# ---------------------------------------------------------------------------
# 后台任务队列
# ---------------------------------------------------------------------------
class BackgroundTaskQueue:
    """后台任务队列，避免阻塞主请求。"""

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self.queue = asyncio.Queue()
        self.workers = []
        self.running = False
        self.completed_tasks = 0
        self.failed_tasks = 0

    async def start(self):
        """启动工作线程。"""
        if self.running:
            return
        self.running = True
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(f"worker-{i}"))
            self.workers.append(worker)
        logger.info(f"后台任务队列已启动，{self.max_workers}个工作线程")

    async def stop(self):
        """停止工作线程。"""
        self.running = False
        for worker in self.workers:
            worker.cancel()
        self.workers = []
        logger.info("后台任务队列已停止")

    async def _worker(self, name: str):
        """工作线程。"""
        while self.running:
            try:
                task = await self.queue.get()
                if task is None:
                    break
                try:
                    await task["coro"]()
                    self.completed_tasks += 1
                    logger.debug(f"[{name}] 任务完成: {task.get('name', 'unknown')}")
                except Exception as e:
                    self.failed_tasks += 1
                    logger.error(f"[{name}] 任务失败: {task.get('name', 'unknown')}: {e}")
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{name}] 工作线程异常: {e}")

    async def add_task(self, coro, name: str = None):
        """添加后台任务。"""
        await self.queue.put({"coro": coro, "name": name})
        logger.debug(f"任务已加入队列: {name}")

    def stats(self) -> Dict:
        """获取队列统计。"""
        return {
            "queue_size": self.queue.qsize(),
            "completed": self.completed_tasks,
            "failed": self.failed_tasks,
            "workers": len(self.workers),
            "running": self.running,
        }


# 全局后台任务队列
_task_queue = BackgroundTaskQueue(max_workers=3)


def get_task_queue() -> BackgroundTaskQueue:
    """获取全局后台任务队列。"""
    return _task_queue


# ---------------------------------------------------------------------------
# 限流装饰器
# ---------------------------------------------------------------------------
class RateLimiter:
    """简单的限流器（基于令牌桶）。"""

    def __init__(self, max_calls: int = 10, period: int = 60):
        self.max_calls = max_calls
        self.period = period
        self.calls = {}

    def is_allowed(self, key: str) -> bool:
        """检查是否允许调用。"""
        now = time.time()
        if key not in self.calls:
            self.calls[key] = []

        # 清理过期的调用记录
        self.calls[key] = [t for t in self.calls[key] if now - t < self.period]

        if len(self.calls[key]) >= self.max_calls:
            return False

        self.calls[key].append(now)
        return True

    def reset(self, key: str = None):
        """重置限流。"""
        if key:
            self.calls.pop(key, None)
        else:
            self.calls.clear()


# 全局限流器
_rate_limiter = RateLimiter(max_calls=30, period=60)  # 每分钟30次


def rate_limit(max_calls: int = 30, period: int = 60):
    """限流装饰器。"""
    limiter = RateLimiter(max_calls, period)

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 使用第一个参数作为key（通常是request或user_id）
            key = str(args[0]) if args else "default"
            if not limiter.is_allowed(key):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "请求过于频繁，请稍后再试"},
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 缓存装饰器（用于路由）
# ---------------------------------------------------------------------------
def cache_response(ttl: int = 60):
    """路由响应缓存装饰器。"""
    cache = {}

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            if cache_key in cache:
                data, expire_time = cache[cache_key]
                if time.time() < expire_time:
                    return data
            result = await func(*args, **kwargs)
            cache[cache_key] = (result, time.time() + ttl)
            # 限制缓存大小
            if len(cache) > 100:
                oldest_key = min(cache.keys(), key=lambda k: cache[k][1])
                del cache[oldest_key]
            return result
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 性能监控
# ---------------------------------------------------------------------------
class PerformanceMonitor:
    """全局性能监控器。"""

    def __init__(self):
        self.metrics = {
            "total_requests": 0,
            "total_response_time": 0,
            "errors": 0,
            "start_time": time.time(),
        }

    def record_request(self, response_time: float, success: bool = True):
        """记录请求。"""
        self.metrics["total_requests"] += 1
        self.metrics["total_response_time"] += response_time
        if not success:
            self.metrics["errors"] += 1

    def get_stats(self) -> Dict:
        """获取性能统计。"""
        total = self.metrics["total_requests"]
        return {
            "total_requests": total,
            "avg_response_time": self.metrics["total_response_time"] / total if total > 0 else 0,
            "errors": self.metrics["errors"],
            "error_rate": self.metrics["errors"] / total if total > 0 else 0,
            "uptime": time.time() - self.metrics["start_time"],
            "slow_requests": request_timer.get_slow_requests(),
            "task_queue": _task_queue.stats(),
        }


perf_monitor = PerformanceMonitor()


# ---------------------------------------------------------------------------
# 健康检查端点
# ---------------------------------------------------------------------------
async def health_check_endpoint():
    """健康检查端点。"""
    from database import check_database_health
    return {
        "status": "ok",
        "version": "3.0.0",
        "timestamp": time.time(),
        "database": check_database_health(),
        "performance": perf_monitor.get_stats(),
    }
