# -*- coding: utf-8 -*-
"""``services/crawl/attachments.py`` 单测：附件下载/存盘/解析（不联网、不写生产库）。"""
from __future__ import annotations

import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.crawl.attachments import (  # noqa: E402
    STATUS_FAILED,
    STATUS_PARSED,
    STATUS_PARSE_SKIPPED,
    STATUS_STORED,
    AttachmentPipeline,
    storage_root,
)
from services.crawl.fetcher import FetchResult  # noqa: E402
from services.crawl.queue import CrawlQueue, MemoryJobStore  # noqa: E402
from services.crawl.runner import MemoryPageIndex, run_once  # noqa: E402

PAGE_URL = "https://yz.example.edu.cn/2025/jzsh.html"


class FakeBinaryFetcher:
    """假抓取器：附件 URL 返回字节，其它 URL 返回一段 HTML。"""

    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    def fetch(self, url, respect_robots=True, binary=False):
        self.calls.append((url, binary))
        item = self.results.get(url)
        if isinstance(item, FetchResult):
            return item
        if isinstance(item, str):
            return FetchResult(url=url, final_url=url, status=0, html="", content_type="",
                               elapsed=0.01, error=item)
        if item is None:
            return FetchResult(url=url, final_url=url, status=200,
                               html="<html><body>公告正文</body></html>",
                               content_type="text/html", elapsed=0.01)
        return FetchResult(url=url, final_url=url, status=200, html="",
                           content_type="application/pdf", elapsed=0.01, content=item)


def _make_job():
    """造一个真实任务对象（死信要挂 job_id）。"""
    queue = CrawlQueue(store=MemoryJobStore())
    queue.enqueue(source_key="test", url=PAGE_URL, school_id=None)
    return queue.claim(1)[0]


def _pipeline(tmp_path, **kwargs):
    kwargs.setdefault("fetcher", FakeBinaryFetcher())
    kwargs.setdefault("db", object())  # 假 db：解析走注入的假实现
    return AttachmentPipeline(root=str(tmp_path), **kwargs)


def test_storage_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("KAOYAN_CRAWL_ROOT", str(tmp_path / "custom"))
    assert storage_root() == os.path.abspath(str(tmp_path / "custom"))
    assert storage_root(str(tmp_path / "explicit")) == os.path.abspath(str(tmp_path / "explicit"))


def test_attachments_are_downloaded_and_stored(tmp_path):
    url = "https://yz.example.edu.cn/files/fenshuxian.pdf"
    fetcher = FakeBinaryFetcher({url: b"%PDF-1.4 fake"})
    pipeline = AttachmentPipeline(root=str(tmp_path), fetcher=fetcher, db=object(),
                                  parse_pdfs=False)
    artifacts = pipeline.process(
        html="<html></html>",
        url=PAGE_URL,
        attachments=[{"url": url, "filename": "复试分数线.pdf", "ext": "pdf"}],
    )
    assert len(artifacts.attachments) == 1
    record = artifacts.attachments[0]
    assert record.status == STATUS_STORED
    assert record.size == len(b"%PDF-1.4 fake")
    assert os.path.exists(record.path)
    assert record.rel_path.startswith("attachments/")
    assert artifacts.manifest_rel_path.endswith("manifest.json")
    with open(os.path.join(tmp_path, artifacts.manifest_rel_path), encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest["page_url"] == PAGE_URL
    assert manifest["attachments"][0]["url"] == url


def test_html_is_saved_and_relative_path_returned(tmp_path):
    pipeline = _pipeline(tmp_path, parse_pdfs=False)
    artifacts = pipeline.save_html("<html>正文</html>", PAGE_URL)
    assert artifacts.html_rel_path.startswith("pages/")
    assert os.path.exists(artifacts.html_path)
    assert not os.path.isabs(artifacts.html_rel_path)


def test_pdf_attachment_is_parsed_and_ingested(tmp_path):
    url = "https://yz.example.edu.cn/files/zhuanye.pdf"
    fetcher = FakeBinaryFetcher({url: b"%PDF-1.4 fake"})
    calls = {}

    def fake_parse(pdf_path, **kwargs):
        calls["parse"] = pdf_path
        return object()

    def fake_ingest(db, pdf_path, **kwargs):
        calls["ingest"] = (db, pdf_path, kwargs.get("cut_questions"))
        # 真实链路里 ingest_pipeline 会用注入的 parse_fn 去解析
        kwargs.get("parse_fn")(pdf_path)
        return {"document_id": 42, "pages": 7, "blocks": 31}

    pipeline = AttachmentPipeline(root=str(tmp_path), fetcher=fetcher, db=object(),
                                  parse_fn=fake_parse, ingest_fn=fake_ingest)
    artifacts = pipeline.process(
        url=PAGE_URL,
        attachments=[{"url": url, "filename": "zhuanye.pdf", "ext": "pdf"}],
    )
    record = artifacts.attachments[0]
    assert record.status == STATUS_PARSED
    assert record.document_id == 42
    assert record.pages == 7
    assert record.blocks == 31
    assert calls["ingest"][2] is False, "公告附件不切题"
    assert calls["parse"].endswith("zhuanye.pdf")


def test_non_pdf_attachment_is_only_stored(tmp_path):
    url = "https://yz.example.edu.cn/files/list.xlsx"
    fetcher = FakeBinaryFetcher({url: b"PK\x03\x04"})
    pipeline = AttachmentPipeline(root=str(tmp_path), fetcher=fetcher, db=object(),
                                  parse_fn=lambda *a, **k: object(),
                                  ingest_fn=lambda *a, **k: {})
    artifacts = pipeline.process(
        url=PAGE_URL,
        attachments=[{"url": url, "filename": "list.xlsx", "ext": "xlsx"}],
    )
    record = artifacts.attachments[0]
    assert record.status == STATUS_STORED
    assert record.document_id is None


def test_parser_unavailable_does_not_crash_and_reports_dead_letter(tmp_path):
    url = "https://yz.example.edu.cn/files/a.pdf"
    fetcher = FakeBinaryFetcher({url: b"%PDF"})

    def boom(*_args, **_kwargs):
        raise ImportError("No module named 'services.parsers.router'")

    pipeline = AttachmentPipeline(root=str(tmp_path), fetcher=fetcher, db=object(),
                                  parse_fn=boom, ingest_fn=boom)
    errors = []
    artifacts = pipeline.process(
        url=PAGE_URL,
        attachments=[{"url": url, "filename": "a.pdf", "ext": "pdf"}],
        job=_make_job(),
        on_error=lambda job, error, payload: errors.append((error, payload)),
    )
    record = artifacts.attachments[0]
    assert record.status == STATUS_PARSE_SKIPPED
    assert "parser_unavailable" in record.error or "ingest_unavailable" in record.error
    assert errors, "解析不可用应产生死信记录"
    assert errors[0][1]["kind"] == "attachment"


def test_download_failure_is_recorded(tmp_path):
    url = "https://yz.example.edu.cn/files/missing.pdf"
    fetcher = FakeBinaryFetcher({url: "http_404"})
    pipeline = AttachmentPipeline(root=str(tmp_path), fetcher=fetcher, db=object(),
                                  parse_pdfs=False)
    errors = []
    artifacts = pipeline.process(
        url=PAGE_URL,
        attachments=[{"url": url, "filename": "missing.pdf", "ext": "pdf"}],
        job=_make_job(),
        on_error=lambda job, error, payload: errors.append(error),
    )
    assert artifacts.attachments[0].status == STATUS_FAILED
    assert errors == ["http_404"]


def test_max_files_limit(tmp_path):
    pipeline = AttachmentPipeline(root=str(tmp_path), fetcher=FakeBinaryFetcher(),
                                  db=object(), parse_pdfs=False, max_files=2)
    attachments = [
        {"url": f"https://yz.example.edu.cn/f/{i}.pdf", "filename": f"{i}.pdf", "ext": "pdf"}
        for i in range(5)
    ]
    artifacts = pipeline.process(url=PAGE_URL, attachments=attachments)
    assert len(artifacts.attachments) == 2


def test_runner_wires_attachment_pipeline(tmp_path):
    url = "https://yz.example.edu.cn/files/fenshuxian.pdf"
    fetcher = FakeBinaryFetcher({url: b"%PDF-1.4 fake"})
    pipeline = AttachmentPipeline(root=str(tmp_path), fetcher=fetcher, db=object(),
                                  parse_pdfs=False)
    queue = CrawlQueue(store=MemoryJobStore())
    queue.enqueue(source_key="test", url=PAGE_URL, school_id=None)
    index = MemoryPageIndex()
    stats = run_once(
        None,
        limit=1,
        queue=queue,
        page_index=index,
        attachment_pipeline=pipeline,
        fetcher=fetcher,
        extract_fn=lambda html, url_: _FakeExtracted(),
    )
    assert stats["attachments_downloaded"] == 1
    assert index.records[0].html_path.startswith("pages/")


class _FakeExtracted:
    title = "某大学2025年硕士研究生招生简章"
    text = "正文内容"
    publish_date = None
    engine = "fake"
    attachments = [
        {"url": "https://yz.example.edu.cn/files/fenshuxian.pdf",
         "filename": "fenshuxian.pdf", "ext": "pdf"}
    ]
