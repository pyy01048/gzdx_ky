# -*- coding: utf-8 -*-
"""PDF 导出接口测试（对标「不背单词」纸质导出）。

覆盖：
1. GET /api/errors/export-pdf 返回 200 + application/pdf + %PDF 文件头；
2. GET /api/words/export-pdf  返回 200 + application/pdf + %PDF 文件头；
3. 筛选参数（subject / status）可叠加，不 5xx；
4. 响应头带 RFC 5987 中文文件名（filename*=UTF-8''...）。
"""
from __future__ import annotations

import pytest


PDF_MAGIC = b"%PDF"


def _assert_pdf(resp):
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-type", "").startswith("application/pdf"), resp.headers
    body = resp.content
    assert body.startswith(PDF_MAGIC), "响应体不是 PDF 文件头"
    assert len(body) > 1000, "PDF 内容过短，疑似空文档"
    cd = resp.headers.get("content-disposition", "")
    assert "filename*=UTF-8''" in cd, f"缺少 RFC 5987 中文文件名：{cd}"


class TestErrorsPdfExport:
    def test_export_pdf_ok(self, client):
        resp = client.get("/api/errors/export-pdf")
        _assert_pdf(resp)

    def test_export_pdf_with_filters(self, client):
        resp = client.get("/api/errors/export-pdf", params={"subject": "数学"})
        _assert_pdf(resp)

    def test_export_pdf_with_status(self, client):
        resp = client.get("/api/errors/export-pdf", params={"status": "active"})
        _assert_pdf(resp)


class TestWordsPdfExport:
    def test_export_pdf_ok(self, client):
        resp = client.get("/api/words/export-pdf")
        _assert_pdf(resp)

    def test_export_pdf_with_status(self, client):
        resp = client.get("/api/words/export-pdf", params={"status": "not_mastered"})
        _assert_pdf(resp)

    def test_export_pdf_with_search(self, client):
        resp = client.get("/api/words/export-pdf", params={"search": "u"})
        _assert_pdf(resp)


@pytest.mark.parametrize("path", [
    "/api/errors/export-pdf",
    "/api/words/export-pdf",
])
def test_pdf_export_is_registered_in_contract(path):
    """新接口必须登记在 test_api_contract.NON_JSON_GET_PATHS，否则契约测试会误报。"""
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_api_contract import NON_JSON_GET_PATHS

    assert path in NON_JSON_GET_PATHS, f"{path} 未登记到 NON_JSON_GET_PATHS"