"""外部算力节点（PaddleOCR / bge-reranker / Ollama）的地址、鉴权头与探活。

云端部署时三者跑在家中节点，经 Tailscale/frp 暴露给主后端：地址一律走 env，
旁路服务若设了 COMPUTE_SERVICE_TOKEN，主后端调用时带 X-Service-Token。
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List

SERVICE_TOKEN_HEADER = "X-Service-Token"


def _env_url(*keys: str, default: str) -> str:
    for k in keys:
        v = (os.getenv(k) or "").strip()
        if v:
            return v.rstrip("/")
    return default


def ocr_service_url() -> str:
    # PADDLE_OCR_URL 是历史变量名，保留兼容
    return _env_url("OCR_SERVICE_URL", "PADDLE_OCR_URL", default="http://127.0.0.1:8888")


def reranker_url() -> str:
    return _env_url("BGE_RERANKER_URL", default="http://127.0.0.1:8140")


def ollama_base() -> str:
    return _env_url("OLLAMA_BASE", default="http://127.0.0.1:11434")


def service_headers() -> Dict[str, str]:
    token = (os.getenv("COMPUTE_SERVICE_TOKEN") or "").strip()
    return {SERVICE_TOKEN_HEADER: token} if token else {}


_NODES = (
    ("ocr", "PaddleOCR 识别", ocr_service_url, "/health", "降级到云端 RapidOCR（CPU）"),
    ("reranker", "bge 重排", reranker_url, "/health", "跳过精排 / LLM 打分回退"),
    ("ollama", "Ollama 本地模型", ollama_base, "/api/tags", "降级到云端大模型 API"),
)


def probe_nodes(timeout: float | None = None) -> List[Dict[str, Any]]:
    """并行探活；任何异常都折算为 unavailable，绝不抛。

    为什么并行（2026-10-18 修正）：旧实现逐个串行探测，家里节点关机时
    3 × (connect+read) 最坏可到 17.5s（httpx 的标量 timeout 对
    connect/read/write/pool **各自**生效，不是总预算），管理端健康灯
    整个挂住，契约测试 5s 预算必炸。改 ThreadPoolExecutor 并行后
    总耗时 ≈ 最慢单节点，与节点数脱钩。

    connect 单独收紧到 1.5s：Tailscale 对离线节点的 DERP 中转会让
    connect 阶段空等，而 read 超时只在那之后才开始计。

    timeout 可经 ``COMPUTE_PROBE_TIMEOUT``（秒）覆盖：云端到家节点走
    Tailscale，高负载时 2s 可能偏紧，运维可按实测调整而不用改代码。
    """
    if timeout is None:
        try:
            timeout = float(os.getenv("COMPUTE_PROBE_TIMEOUT", "") or 2.0)
        except ValueError:
            timeout = 2.0
    import httpx
    from concurrent.futures import ThreadPoolExecutor

    headers = service_headers()
    limits = httpx.Timeout(timeout, connect=min(timeout, 1.5))

    def _one(node) -> Dict[str, Any]:
        key, label, url_fn, path, fallback = node
        base = url_fn()
        started = time.perf_counter()
        try:
            r = httpx.get(f"{base}{path}", headers=headers, timeout=limits)
            ok = r.status_code == 200
            error = None if ok else f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            ok, error = False, type(e).__name__
        return {
            "key": key,
            "label": label,
            "status": "online" if ok else "unavailable",
            "latency_ms": round((time.perf_counter() - started) * 1000) if ok else None,
            "error": error,
            "fallback": fallback,
        }

    with ThreadPoolExecutor(max_workers=len(_NODES)) as pool:
        return list(pool.map(_one, _NODES))
