# -*- coding: utf-8 -*-
"""检索链路冷启动预热（2026-11-23 性能波）。

问题：``/api/ai/rag-search`` 首请求 ~6.7 秒（本机实测 2.8 秒，审计环境更高），
其中绝大部分不是查询本身，而是**三个只在首请求才发生的懒加载**：

  1. ``services.embedding_service._get_local_model()``：``import fastembed``
     （约 0.66 秒）+ ONNX 会话初始化（bge-small-zh 权重首次载入内存）；
     失败时还要把整条异常链走完才落到离线引擎。
  2. ``services.search_service.segment()`` 的首次 jieba 切词：词典 + 前缀 DAG
     构建（本机实测 0.53 秒，有缓存时 0.45 秒）。检索链里每一路都要分词，
     但只有第一次付这个钱。
  3. ``services.exam_engine.get_exam_index()``：真题 2-gram 倒排 ``index.pkl``
     首载 + idf 预计算（2712 题规模，秒级；缺文件时退化为空索引，同样要跑一遍）。

原先只有 OCR 在启动期预热（``app_lifecycle.lifespan`` 里的
``get_ocr_router()``），这三者都留给第一个用户白吃。本模块把它们挪到启动后台线程，
与 OCR 同一套做法：fire-and-forget 守护线程，不阻塞启动，失败只告警。

关掉方式：``SEARCH_WARMUP=0``（测试/低配机器）。
"""

from __future__ import annotations

import os
import threading
import time

from utils.logger import get_logger

logger = get_logger("services.search_warmup")

_lock = threading.Lock()
_started = False


def _warm_jieba() -> None:
    """触发 jieba 词典加载（切一次即可，之后 ``segment`` 走内存前缀 DAG）。"""
    from services.search_service import segment

    segment("卡诺图化简的原则是什么")


def _warm_embedding() -> None:
    """把 embedding 引擎走到"可用或已判死"的稳态。

    * ``EMBEDDING_BACKEND=bge``（默认）：加载本地 bge 模型并**推理一次**
      —— ONNX 首帧比模型加载还贵，不推一次等于把成本留给首个提问。
      模型缺失/加载失败时 ``_get_local_model`` 会把错误缓存成
      ``_local_model_error``，后续请求即刻回退，不再重复尝试。
    * 无论后端是什么，都顺手把离线哈希引擎过一遍，保证回退路径也是热的。
    """
    import numpy as np  # noqa: F401  确保数值库已载入（ONNX/离线引擎共用）

    backend = os.environ.get("EMBEDDING_BACKEND", "bge").lower()
    if backend == "bge":
        from services.embedding_service import generate_local_embeddings, is_local_model_available

        if is_local_model_available():
            generate_local_embeddings(["预热查询"])

    from services.offline_embedder import OfflineEmbedder

    OfflineEmbedder().embed(["预热查询"])


def _warm_exam_index() -> None:
    """加载真题 2-gram 索引（缺 index.pkl 时内部已退化为空索引，不抛）。"""
    from services.exam_engine import get_exam_index

    idx = get_exam_index()
    if not getattr(idx, "loaded", False):
        logger.info("[预热] 真题索引缺席（第 4 路检索不启用），检索链其余部分不受影响")


def run_search_warmup() -> dict:
    """同步执行三项预热，返回各步耗时（毫秒）。任一步失败都不抛出。"""
    steps = (("jieba", _warm_jieba), ("embedding", _warm_embedding), ("exam_index", _warm_exam_index))
    out: dict[str, float] = {}
    for name, fn in steps:
        t0 = time.perf_counter()
        try:
            fn()
            out[name] = round((time.perf_counter() - t0) * 1000, 1)
        except Exception as e:  # noqa: BLE001 —— 预热失败只是首请求变慢，不能影响服务启动
            out[name] = round((time.perf_counter() - t0) * 1000, 1)
            logger.warning("[预热] 检索链路 %s 失败（首个请求会重试）: %s", name, e)
    return out


def start_search_warmup() -> bool:
    """起守护线程做检索预热（幂等：重复调用只起一次）。返回是否新起了线程。"""
    global _started
    if os.environ.get("SEARCH_WARMUP", "1").lower() in {"0", "false", "no"}:
        logger.info("[预热] SEARCH_WARMUP=0，跳过检索链路预热")
        return False
    with _lock:
        if _started:
            return False
        _started = True

    def _warm() -> None:
        t0 = time.perf_counter()
        steps = run_search_warmup()
        logger.info(
            "[预热] 检索链路完成，用时 %.2fs（jieba %.0fms / embedding %.0fms / 真题索引 %.0fms）",
            time.perf_counter() - t0,
            steps.get("jieba", -1),
            steps.get("embedding", -1),
            steps.get("exam_index", -1),
        )

    threading.Thread(target=_warm, name="search-warmup", daemon=True).start()
    return True
