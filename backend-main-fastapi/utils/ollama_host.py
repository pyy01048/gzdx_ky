"""Ollama 客户端地址归一化（全后端唯一入口）。

背景（P0）：本机用户级环境变量 `OLLAMA_HOST=0.0.0.0:11434`（为开放局域网而设）是
**监听地址**（服务端语义），直接当客户端目标用有两处硬伤：

  1. 缺 ``http://`` scheme → httpx/urllib 直接抛
     ``Request URL is missing an 'http://' or 'https://' protocol``，
     表现为 ``/api/ai/local/status`` 恒为 ``available:false, models:[]``；
  2. 即便补了 scheme，Windows 上连 ``0.0.0.0`` 也不可达（Linux 才等价 localhost）。

因此统一：缺 scheme 补 ``http://``；主机名是通配监听地址（``0.0.0.0`` / ``::``）则换
``127.0.0.1``；去掉尾部 ``/``。

历史：`services/kp_extract.py::_resolve_ollama_host` 曾是唯一正确实现，其余模块
（ai_service / ai_router / retrieval_enhance / chunk_classifier / circuit_analysis /
routers/ai 等）各自裸读 ``os.getenv``，全部中招。现统一改调本模块。
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

#: 环境变量缺省（Ollama 默认端口）
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"

#: 只在服务端有意义、客户端连不上的通配监听地址
_WILDCARD_HOSTS = ("0.0.0.0", "::", "[::]")

__all__ = ["DEFAULT_OLLAMA_HOST", "resolve_ollama_host"]


def resolve_ollama_host(raw: str | None = None) -> str:
    """返回可直接用于 HTTP 客户端的 Ollama base URL。

    Args:
        raw: 覆盖值（通常是调用方自己读的环境变量）。为 ``None`` 时读
            环境变量 ``OLLAMA_HOST``。空串/未设置 → 返回默认值。

    Returns:
        归一化后的 URL，形如 ``http://127.0.0.1:11434``。
    """
    if raw is None:
        raw = os.environ.get("OLLAMA_HOST") or ""
    value = raw.strip().rstrip("/")
    if not value:
        return DEFAULT_OLLAMA_HOST
    if "://" not in value:
        # 纯 `0.0.0.0:11434` / `127.0.0.1:11434` / `localhost:11434`
        value = "http://" + value
    parts = urlparse(value)
    if (parts.hostname or "") in _WILDCARD_HOSTS:
        auth = ""
        if parts.username:
            auth = parts.username + (f":{parts.password}" if parts.password else "") + "@"
        port = f":{parts.port}" if parts.port else ""
        path = parts.path or ""
        return f"{parts.scheme}://{auth}127.0.0.1{port}{path}".rstrip("/")
    return value
