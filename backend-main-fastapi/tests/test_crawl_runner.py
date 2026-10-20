# -*- coding: utf-8 -*-
"""``services/crawl/runner.py`` 单测：假抓取器 + 内存队列，不联网、不落生产库。"""
from __future__ import annotations

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.crawl.classifier import classify_notice  # noqa: E402
from services.crawl.extractor import extract  # noqa: E402
from services.crawl.fetcher import FetchResult  # noqa: E402
from services.crawl.queue import CrawlQueue, MemoryJobStore  # noqa: E402
from services.crawl.runner import (  # noqa: E402
    MemoryNoticeWriter,
    MemoryPageIndex,
    NullPageWriter,
    run_once,
)

HTML = """
<html><head><meta property="article:published_time" content="2025-03-12">
<title>某大学2025年硕士研究生招生复试分数线</title></head>
<body><article><h1>某大学2025年硕士研究生招生复试分数线</h1>
<p>根据教育部有关要求，现公布我校2025年硕士研究生招生复试分数线，详见附件。</p>
<p>考生可登录研究生招生网查询成绩，请按要求完成网上确认。</p>
</article></body></html>
"""


class FakeFetcher:
    """假抓取器：按 URL 返回预置结果。"""

    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    def fetch(self, url, respect_robots=True):
        self.calls.append((url, respect_robots))
        if url in self.results:
            return self.results[url]
        return FetchResult(
            url=url, final_url=url, status=200, html=HTML,
            content_type="text/html; charset=utf-8", elapsed=0.01,
        )


def _queue_with(urls):
    queue = CrawlQueue(store=MemoryJobStore())
    for url in urls:
        queue.enqueue(source_key="test", url=url, school_id=1)
    return queue


def test_run_once_writes_page_and_notice():
    url = "https://yz.example.edu.cn/2025/fenshuxian.html"
    queue = _queue_with([url])
    index = MemoryPageIndex()
    notices = MemoryNoticeWriter()

    stats = run_once(
        None,
        limit=5,
        queue=queue,
        page_index=index,
        page_writer=NullPageWriter(),
        notice_writer=notices,
        fetcher=FakeFetcher(),
        extract_fn=extract,
        classify_fn=classify_notice,
    )

    assert stats["claimed"] == 1
    assert stats["fetched"] == 1
    assert stats["failed"] == 0
    assert stats["deduped"] == 0
    assert stats["notices_written"] == 1
    assert stats["notices_skipped"] == 0
    assert stats["errors"] == []
    assert queue.stats()["done"] == 1
    assert len(index.records) == 1
    assert index.records[0].canonical_url == url
    assert index.records[0].notice_type == "复试线"
    assert notices.written[0]["title"].startswith("某大学2025年硕士研究生招生复试分数线")


def test_run_once_dedupes_same_page():
    url = "https://yz.example.edu.cn/2025/fenshuxian.html"
    index = MemoryPageIndex()
    queue = _queue_with([url])
    stats = run_once(None, queue=queue, page_index=index, fetcher=FakeFetcher(),
                     extract_fn=extract, classify_fn=classify_notice)
    assert stats["fetched"] == 1

    # 同一 URL 再来一次（不同 source_key）→ 应判重
    queue2 = _queue_with([url])
    stats2 = run_once(None, queue=queue2, page_index=index, fetcher=FakeFetcher(),
                      extract_fn=extract, classify_fn=classify_notice)
    assert stats2["deduped"] == 1
    assert stats2["notices_written"] == 0
    assert len(index.records) == 1


def test_run_once_counts_failures():
    url = "https://yz.example.edu.cn/2025/boom.html"
    failed = FetchResult(url=url, final_url=url, status=0, html="", content_type="",
                         elapsed=0.01, error="robots_disallowed")
    queue = _queue_with([url])
    stats = run_once(None, queue=queue, page_index=MemoryPageIndex(),
                     fetcher=FakeFetcher({url: failed}))
    assert stats["failed"] == 1
    assert stats["fetched"] == 0
    assert any("robots_disallowed" in e for e in stats["errors"])
    assert queue.stats()["failed"] == 1


def test_run_once_dry_run_writes_nothing():
    url = "https://yz.example.edu.cn/2025/fenshuxian.html"
    index = MemoryPageIndex()
    stats = run_once(None, queue=_queue_with([url]), page_index=index,
                     page_writer=NullPageWriter(), notice_writer=None,
                     fetcher=FakeFetcher(), extract_fn=extract, classify_fn=classify_notice)
    assert stats["notices_written"] == 0
    assert stats["pages_written"] == 0
    assert stats["fetched"] == 1


def test_run_once_skips_other_type_notices():
    html = "<html><body><p>关于开展学生公寓空调维修的通知</p></body></html>"
    url = "https://yz.example.edu.cn/2025/other.html"
    notices = MemoryNoticeWriter()
    result = FetchResult(url=url, final_url=url, status=200, html=html,
                         content_type="text/html", elapsed=0.01)
    stats = run_once(None, queue=_queue_with([url]), page_index=MemoryPageIndex(),
                     notice_writer=notices, fetcher=FakeFetcher({url: result}),
                     extract_fn=extract, classify_fn=classify_notice)
    assert stats["fetched"] == 1
    assert stats["notices_written"] == 0
    assert notices.written == []
