# -*- coding: utf-8 -*-
"""热点统计端点的**短期 TTL 内存缓存**。

背景：``GET /api/errors/stats`` 与 ``GET /api/quiz/stats`` 每次请求都要跑
6~12 条聚合 count（error_records / answer_records / quiz_questions 都是全站
大表），而前端仪表盘 / 错题本 / 刷题中心会周期性轮询这些端点。对"同一组
参数"的结果做秒级缓存，可把重复轮询的数据库压力降到零。

隔离铁律（测试绝不被缓存污染）
--------------------------------
- **pytest 环境下自动禁用**：检测 ``PYTEST_CURRENT_TEST`` 环境变量或
  ``sys.modules`` 中的 pytest。测试里大量"先写后读"断言（如
  ``test_active_matches_db``：写错题 → 读 /api/errors/stats → 对账），
  缓存一旦跨用例复用就会造成假失败；
- 可用 ``KAOYAN_STATS_CACHE_TTL``（秒）覆盖默认 TTL，置 ``0`` 永久关闭；
- 线程安全：FastAPI 同步端点跑在线程池里，字典读写加锁；
- 条目数上限 + FIFO 淘汰，避免长跑进程无界增长。
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Callable, Dict

#: 默认 TTL（秒）。仅覆盖"轮询窗口"，不改变数据的最终一致性语义。
_DEFAULT_TTL = 3.0
#: 缓存条目上限（不同参数组合的数量级：科目 × 来源大类 × include_junk）
_MAX_ENTRIES = 256

_lock = threading.Lock()
_store: Dict[str, tuple[float, Any]] = {}


def _running_under_pytest() -> bool:
    """当前进程是否处于 pytest 之下（禁用缓存的判据）。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


def ttl() -> float:
    """当前生效的 TTL（秒）；``<= 0`` 表示缓存禁用。"""
    raw = (os.environ.get("KAOYAN_STATS_CACHE_TTL") or "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            return _DEFAULT_TTL
    return 0.0 if _running_under_pytest() else _DEFAULT_TTL


def cached(key: str, producer: Callable[[], Any]) -> Any:
    """取 ``key`` 的缓存值；未命中 / 已过期则执行 ``producer()`` 并回填。"""
    ttl_seconds = ttl()
    if ttl_seconds <= 0:
        return producer()

    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]

    value = producer()  # 在锁外计算，避免慢查询堵住其他线程的缓存读取

    with _lock:
        if len(_store) >= _MAX_ENTRIES:
            # FIFO 淘汰最旧的一批（dict 保插入序）
            for stale in list(_store.keys())[: max(1, _MAX_ENTRIES // 4)]:
                _store.pop(stale, None)
        _store[key] = (now + ttl_seconds, value)
    return value


async def cached_async(key: str, producer: Callable[[], Any]) -> Any:
    """``cached`` 的异步版：``producer`` 是协程函数时用这个。

    背景（2026-10-15 实测）：``GET /api/quiz/stats`` 的 payload 生产者
    ``_quiz_stats_payload`` 是 ``async def``，但调用侧用了同步的 ``cached()``，
    于是缓存层直接返回**协程对象**，FastAPI 序列化时炸：
        ValueError: [TypeError("'coroutine' object is not iterable")]
    表现为该端点恒 500（pytest 下缓存禁用时同样炸）。
    """
    ttl_seconds = ttl()
    if ttl_seconds <= 0:
        return await producer()

    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]

    value = await producer()  # 锁外计算，避免慢查询堵住其他协程

    with _lock:
        if len(_store) >= _MAX_ENTRIES:
            for stale in list(_store.keys())[: max(1, _MAX_ENTRIES // 4)]:
                _store.pop(stale, None)
        _store[key] = (now + ttl_seconds, value)
    return value


def clear() -> None:
    """清空全部缓存（测试收尾 / 运维手动刷新用）。"""
    with _lock:
        _store.clear()
