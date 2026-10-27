# -*- coding: utf-8 -*-
"""礼貌抓取器：robots 合规 + 单域串行 + 随机间隔 + 指数退避重试 + 编码兜底。

设计要点
--------
- **robots 先查**：用 :mod:`urllib.robotparser` 解析，按 ``scheme://host:port``
  缓存 1 小时；被禁时**不发请求**，直接返回 ``error="robots_disallowed"``。
- **单域并发 1**：进程内按域维护 :class:`threading.Lock` 与最近访问时间，
  同域两次请求间隔 ≥ 随机 delay（默认 2~5 秒）。
- **重试**：默认 3 次重试（总共 4 次尝试），退避 1s/2s/4s + 抖动；
  4xx（429 除外）不重试——重试也不会变好，只会给对方添负担。
- **体积上限**：单页 20MB，超出截断并标 ``error="too_large"``。
- **中文编码**：响应头 charset → HTML meta charset → utf-8 → gb18030 兜底。

本模块不发网络请求的单元测试靠 monkeypatch ``_make_client`` / ``_sleep``。
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

try:  # httpx 是硬依赖，但不让 import 期崩掉整个采集栈
    import httpx
except Exception:  # pragma: no cover - 环境异常时的降级
    httpx = None  # type: ignore

__all__ = ["FetchResult", "PoliteFetcher", "clear_robots_cache", "DEFAULT_USER_AGENT"]

DEFAULT_USER_AGENT = (
    "KaoyanStudyBot/1.0 (personal study use; non-commercial; contact: local-operator)"
)

#: 单页体积上限 20MB
MAX_PAGE_BYTES = 20 * 1024 * 1024

#: robots.txt 缓存 TTL（秒）
ROBOTS_TTL = 3600.0

# --------------------------------------------------------------------------- #
# 进程内共享状态：域名锁 / 最近访问时间 / robots 缓存
# --------------------------------------------------------------------------- #
_STATE_LOCK = threading.Lock()
_DOMAIN_LOCKS: Dict[str, threading.Lock] = {}
_DOMAIN_LAST: Dict[str, float] = {}
_ROBOTS_CACHE: Dict[str, Tuple[float, Optional[RobotFileParser]]] = {}


def clear_robots_cache() -> None:
    """清空 robots 缓存（测试与长跑进程用）。"""
    with _STATE_LOCK:
        _ROBOTS_CACHE.clear()


def _domain_lock(domain: str) -> threading.Lock:
    with _STATE_LOCK:
        lock = _DOMAIN_LOCKS.get(domain)
        if lock is None:
            lock = threading.Lock()
            _DOMAIN_LOCKS[domain] = lock
        return lock


def _make_client(timeout: float, user_agent: str):
    """构造 httpx 客户端（测试里 monkeypatch 这个函数即可拦截所有请求）。"""
    if httpx is None:  # pragma: no cover
        raise RuntimeError("httpx 未安装，无法抓取")
    return httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": user_agent},
    )


def _sleep(seconds: float) -> None:
    """可被 monkeypatch 的睡眠（测试里替换成 no-op）。"""
    if seconds > 0:
        time.sleep(seconds)


def _decode(raw: bytes, content_type: str) -> str:
    """按 响应头 charset → meta charset → utf-8 → gb18030 的顺序解码。"""
    if not raw:
        return ""
    candidates: list[str] = []
    if content_type:
        for part in content_type.split(";"):
            part = part.strip()
            if part.lower().startswith("charset="):
                candidates.append(part.split("=", 1)[1].strip().strip("\"'"))
                break
    head = raw[:4096]
    match = re_search_charset(head)
    if match:
        candidates.append(match)
    candidates += ["utf-8", "gb18030"]
    seen = set()
    for cs in candidates:
        cs = (cs or "").strip().lower()
        if not cs or cs in seen:
            continue
        seen.add(cs)
        try:
            return raw.decode(cs)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "ignore")


def re_search_charset(head: bytes) -> Optional[str]:
    """从 HTML 头部找 ``charset=xxx``（大小写不敏感）。"""
    import re

    m = re.search(rb"charset\s*=\s*[\"']?\s*([A-Za-z0-9_\-]+)", head, re.I)
    if not m:
        return None
    return m.group(1).decode("ascii", "ignore")


@dataclass
class FetchResult:
    """一次抓取的结果。"""

    url: str
    final_url: str
    status: int
    html: str
    content_type: str
    elapsed: float
    error: str = ""
    #: 二进制模式（附件下载）下的原始字节；HTML 模式恒为空
    content: bytes = b""
    #: 是否可重试（内部用）
    retryable: bool = field(default=False, repr=False, compare=False)

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 300


class PoliteFetcher:
    """按域串行、遵守 robots、带退避重试的抓取器。"""

    def __init__(
        self,
        *,
        delay: Tuple[float, float] = (2.0, 5.0),
        timeout: float = 20.0,
        max_retries: int = 3,
        user_agent: str = DEFAULT_USER_AGENT,
        max_bytes: int = MAX_PAGE_BYTES,
        client_factory=None,
        sleep=None,
        rng=None,
    ) -> None:
        self.delay = tuple(delay)
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.user_agent = user_agent
        self.max_bytes = int(max_bytes)
        self._client_factory = client_factory or (
            lambda: _make_client(self.timeout, self.user_agent)
        )
        self._sleep = sleep or _sleep
        self._rng = rng or random.Random()

    # ------------------------------------------------------------------ #
    # robots
    # ------------------------------------------------------------------ #
    def _robots_url(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}/robots.txt"

    def _robots_allows(self, url: str) -> bool:
        """查 robots.txt；拿不到（网络错误/404）时按允许处理。"""
        robots_url = self._robots_url(url)
        key = robots_url.rsplit("/", 1)[0]
        now = time.time()
        with _STATE_LOCK:
            cached = _ROBOTS_CACHE.get(key)
            if cached and (now - cached[0]) < ROBOTS_TTL:
                parser = cached[1]
                if parser is None:
                    return True
                return bool(parser.can_fetch(self.user_agent, url))

        parser: Optional[RobotFileParser] = None
        try:
            client = self._client_factory()
            try:
                resp = client.get(robots_url)
                if getattr(resp, "status_code", 0) == 200:
                    body = _decode(_response_bytes(resp), _header(resp, "content-type"))
                    rp = RobotFileParser()
                    rp.parse(body.splitlines())
                    parser = rp
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
        except Exception:
            parser = None

        with _STATE_LOCK:
            _ROBOTS_CACHE[key] = (time.time(), parser)
        if parser is None:
            return True
        return bool(parser.can_fetch(self.user_agent, url))

    # ------------------------------------------------------------------ #
    # 抓取
    # ------------------------------------------------------------------ #
    def _wait_turn(self, domain: str) -> None:
        """同域节流：距上次访问不足随机 delay 就等。"""
        delay = self._rng.uniform(*self.delay)
        with _STATE_LOCK:
            last = _DOMAIN_LAST.get(domain, 0.0)
        wait = delay - (time.time() - last)
        if wait > 0:
            self._sleep(wait)

    def _mark_visit(self, domain: str) -> None:
        with _STATE_LOCK:
            _DOMAIN_LAST[domain] = time.time()

    def _attempt(self, url: str, binary: bool = False) -> FetchResult:
        """单次尝试（不做重试判断）。

        ``binary=True`` 时不解码，直接返回原始字节（附件下载用）。
        """
        started = time.monotonic()
        parts = urlsplit(url)
        domain = parts.netloc
        try:
            client = self._client_factory()
        except Exception as exc:  # pragma: no cover
            return FetchResult(
                url=url, final_url=url, status=0, html="", content_type="",
                elapsed=time.monotonic() - started, error=f"client_error: {exc}",
                retryable=True,
            )
        try:
            with _domain_lock(domain):
                self._wait_turn(domain)
                try:
                    resp = client.get(url)
                except Exception as exc:
                    self._mark_visit(domain)
                    return self._error_result(url, started, exc)
                self._mark_visit(domain)

            status = int(getattr(resp, "status_code", 0) or 0)
            content_type = _header(resp, "content-type")
            final_url = str(getattr(resp, "url", url) or url)
            raw = _response_bytes(resp)
            elapsed = time.monotonic() - started

            if status == 429:
                return FetchResult(url=url, final_url=final_url, status=status, html="",
                                   content_type=content_type, elapsed=elapsed,
                                   error="http_429", retryable=True)
            if 400 <= status < 500:
                return FetchResult(url=url, final_url=final_url, status=status, html="",
                                   content_type=content_type, elapsed=elapsed,
                                   error=f"http_{status}", retryable=False)
            if status >= 500:
                return FetchResult(url=url, final_url=final_url, status=status, html="",
                                   content_type=content_type, elapsed=elapsed,
                                   error=f"http_{status}", retryable=True)
            if status >= 200:
                too_large = len(raw) > self.max_bytes
                if too_large:
                    raw = raw[: self.max_bytes]
                if binary:
                    return FetchResult(
                        url=url, final_url=final_url, status=status, html="",
                        content_type=content_type, elapsed=elapsed,
                        content=raw, error="too_large" if too_large else "",
                    )
                html = _decode(raw, content_type)
                return FetchResult(
                    url=url, final_url=final_url, status=status, html=html,
                    content_type=content_type, elapsed=elapsed,
                    error="too_large" if too_large else "",
                )
            return FetchResult(url=url, final_url=final_url, status=status, html="",
                               content_type=content_type, elapsed=elapsed,
                               error=f"http_{status}", retryable=False)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # pragma: no cover
                    pass

    def _error_result(self, url: str, started: float, exc: Exception) -> FetchResult:
        name = type(exc).__name__
        msg = str(exc)
        if httpx is not None and isinstance(exc, getattr(httpx, "TimeoutException", ())):
            return FetchResult(url=url, final_url=url, status=0, html="", content_type="",
                               elapsed=time.monotonic() - started, error="timeout",
                               retryable=True)
        if httpx is not None and isinstance(exc, getattr(httpx, "HTTPError", ())):
            return FetchResult(url=url, final_url=url, status=0, html="", content_type="",
                               elapsed=time.monotonic() - started,
                               error=f"request_error: {name}", retryable=True)
        return FetchResult(url=url, final_url=url, status=0, html="", content_type="",
                           elapsed=time.monotonic() - started,
                           error=f"request_error: {name}: {msg}"[:200], retryable=True)

    def fetch(self, url: str, *, respect_robots: bool = True, binary: bool = False) -> FetchResult:
        """抓一个页面。

        :param url: 目标 URL
        :param respect_robots: 是否先查 robots.txt（默认查）
        :param binary: True 时返回原始字节（附件下载），不解码
        """
        started = time.monotonic()
        if not url or not str(url).lower().startswith(("http://", "https://")):
            return FetchResult(url=str(url or ""), final_url=str(url or ""), status=0,
                               html="", content_type="", elapsed=time.monotonic() - started,
                               error="invalid_url")

        if respect_robots and not self._robots_allows(url):
            return FetchResult(url=url, final_url=url, status=0, html="", content_type="",
                               elapsed=time.monotonic() - started,
                               error="robots_disallowed")

        attempts = self.max_retries + 1
        last: Optional[FetchResult] = None
        for attempt in range(attempts):
            result = self._attempt(url, binary=binary)
            last = result
            if not result.error or not result.retryable:
                return result
            if attempt < attempts - 1:
                # 指数退避 1s / 2s / 4s + 抖动
                self._sleep(float(2 ** attempt) + self._rng.uniform(0, 0.5))
        assert last is not None
        return last


def _header(resp, name: str) -> str:
    headers = getattr(resp, "headers", None) or {}
    try:
        value = headers.get(name, "") or headers.get(name.title(), "") or ""
    except Exception:  # pragma: no cover
        value = ""
    return str(value)


def _response_bytes(resp) -> bytes:
    content = getattr(resp, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    text = getattr(resp, "text", None)
    if isinstance(text, str):
        return text.encode("utf-8", "ignore")
    return b""
