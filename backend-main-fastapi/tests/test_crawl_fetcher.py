# -*- coding: utf-8 -*-
"""``services/crawl/fetcher.py`` 单测：全部用假客户端，**不发任何网络请求**。"""
from __future__ import annotations

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import httpx  # noqa: E402
import pytest  # noqa: E402

from services.crawl.fetcher import PoliteFetcher, clear_robots_cache  # noqa: E402

PAGE_URL = "https://yz.example.edu.cn/2025/jzsh.html"
ROBOTS_URL = "https://yz.example.edu.cn/robots.txt"


class FakeResponse:
    def __init__(self, status_code=200, content=b"", headers=None, url=""):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.url = url


class FakeClient:
    """按 URL 子串路由的假客户端；记录所有请求。"""

    def __init__(self, script):
        self.script = script
        self.calls = []
        self._counters = {}

    def get(self, url, **kwargs):
        self.calls.append(url)
        for key, seq in self.script.items():
            if key in url:
                idx = self._counters.get(key, 0)
                self._counters[key] = idx + 1
                item = seq[idx] if idx < len(seq) else seq[-1]
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError(f"未预期的请求 URL：{url}")

    def count(self, needle):
        return sum(1 for c in self.calls if needle in c)

    def close(self):
        pass


def make_fetcher(client, **kwargs):
    kwargs.setdefault("delay", (0.0, 0.0))
    kwargs.setdefault("sleep", lambda _s: None)
    kwargs.setdefault("client_factory", lambda: client)
    return PoliteFetcher(**kwargs)


@pytest.fixture(autouse=True)
def _clear_robots():
    clear_robots_cache()
    yield
    clear_robots_cache()


# --------------------------------------------------------------------------- #
def test_200_ok():
    client = FakeClient({
        "robots.txt": [FakeResponse(404, b"")],
        "jzsh.html": [FakeResponse(
            200,
            "<html><body>2025年硕士研究生招生简章</body></html>".encode("utf-8"),
            {"content-type": "text/html; charset=utf-8"},
            url=PAGE_URL,
        )],
    })
    result = make_fetcher(client).fetch(PAGE_URL)
    assert result.status == 200
    assert result.error == ""
    assert "招生简章" in result.html
    assert result.final_url == PAGE_URL
    assert result.elapsed >= 0
    assert result.content_type.startswith("text/html")


def test_404_is_not_retried():
    client = FakeClient({
        "robots.txt": [FakeResponse(404, b"")],
        "jzsh.html": [FakeResponse(404, b"", {"content-type": "text/html"}, url=PAGE_URL)],
    })
    result = make_fetcher(client).fetch(PAGE_URL)
    assert result.status == 404
    assert result.error == "http_404"
    assert client.count("jzsh.html") == 1, "4xx 不该重试"


def test_429_is_retried():
    client = FakeClient({
        "robots.txt": [FakeResponse(404, b"")],
        "jzsh.html": [
            FakeResponse(429, b"", {"content-type": "text/html"}, url=PAGE_URL),
            FakeResponse(200, b"<html>ok</html>", {"content-type": "text/html"}, url=PAGE_URL),
        ],
    })
    result = make_fetcher(client).fetch(PAGE_URL)
    assert result.status == 200
    assert result.error == ""
    assert client.count("jzsh.html") == 2


def test_timeout_is_retried():
    client = FakeClient({
        "robots.txt": [FakeResponse(404, b"")],
        "jzsh.html": [
            httpx.TimeoutException("timeout"),
            FakeResponse(200, b"<html>ok</html>", {"content-type": "text/html"}, url=PAGE_URL),
        ],
    })
    result = make_fetcher(client).fetch(PAGE_URL)
    assert result.status == 200
    assert client.count("jzsh.html") == 2


def test_5xx_retries_then_gives_up():
    client = FakeClient({
        "robots.txt": [FakeResponse(404, b"")],
        "jzsh.html": [FakeResponse(500, b"", {"content-type": "text/html"}, url=PAGE_URL)],
    })
    result = make_fetcher(client).fetch(PAGE_URL)
    assert result.status == 500
    assert result.error == "http_500"
    assert client.count("jzsh.html") == 4, "3 次重试 + 1 次首尝 = 4 次"


def test_robots_disallowed_never_fetches_page():
    client = FakeClient({
        "robots.txt": [FakeResponse(
            200, b"User-agent: *\nDisallow: /\n", {"content-type": "text/plain"}, url=ROBOTS_URL
        )],
        "jzsh.html": [FakeResponse(200, b"<html>should not be fetched</html>",
                                   {"content-type": "text/html"}, url=PAGE_URL)],
    })
    result = make_fetcher(client).fetch(PAGE_URL)
    assert result.error == "robots_disallowed"
    assert result.status == 0
    assert client.count("jzsh.html") == 0, "被 robots 禁止时不该发页面请求"


def test_robots_can_be_skipped():
    client = FakeClient({
        "robots.txt": [FakeResponse(200, b"User-agent: *\nDisallow: /\n",
                                    {"content-type": "text/plain"}, url=ROBOTS_URL)],
        "jzsh.html": [FakeResponse(200, b"<html>ok</html>", {"content-type": "text/html"},
                                   url=PAGE_URL)],
    })
    result = make_fetcher(client).fetch(PAGE_URL, respect_robots=False)
    assert result.status == 200
    assert client.count("robots.txt") == 0


def test_oversized_page_is_truncated():
    body = ("中" * 5000).encode("utf-8")
    client = FakeClient({
        "robots.txt": [FakeResponse(404, b"")],
        "jzsh.html": [FakeResponse(200, body, {"content-type": "text/html"}, url=PAGE_URL)],
    })
    result = make_fetcher(client, max_bytes=100).fetch(PAGE_URL)
    assert result.error == "too_large"
    assert len(result.html) < 200


def test_gbk_page_is_decoded_by_meta_charset():
    html = '<html><head><meta charset="gb2312"></head><body>中文内容测试</body></html>'
    client = FakeClient({
        "robots.txt": [FakeResponse(404, b"")],
        "jzsh.html": [FakeResponse(200, html.encode("gb18030"),
                                   {"content-type": "text/html"}, url=PAGE_URL)],
    })
    result = make_fetcher(client).fetch(PAGE_URL)
    assert "中文内容测试" in result.html


def test_same_domain_requests_are_spaced():
    """同域连续两次请求，间隔不小于 delay。"""
    client = FakeClient({
        "robots.txt": [FakeResponse(404, b"")],
        "jzsh.html": [FakeResponse(200, b"<html>ok</html>", {"content-type": "text/html"},
                                   url=PAGE_URL)],
    })
    slept = []
    fetcher = PoliteFetcher(delay=(1.0, 1.0), client_factory=lambda: client,
                             sleep=slept.append)
    fetcher.fetch(PAGE_URL)
    fetcher.fetch(PAGE_URL)
    assert any(s >= 0.5 for s in slept), f"同域请求应有节流等待，实际 sleep={slept}"


def test_invalid_url_is_rejected():
    client = FakeClient({})
    result = make_fetcher(client).fetch("ftp://example.edu.cn/a.txt")
    assert result.error == "invalid_url"
    assert client.calls == []


def test_robots_cache_is_reused():
    client = FakeClient({
        "robots.txt": [FakeResponse(404, b"")],
        "jzsh.html": [FakeResponse(200, b"<html>ok</html>", {"content-type": "text/html"},
                                   url=PAGE_URL)],
    })
    fetcher = make_fetcher(client)
    fetcher.fetch(PAGE_URL)
    fetcher.fetch(PAGE_URL)
    assert client.count("robots.txt") == 1, "robots.txt 应被缓存，不重复请求"
    assert client.count("jzsh.html") == 2
