# -*- coding: utf-8 -*-
"""入库管线幂等性单测。

用**注入的假 parse_fn** 返回人造 ParseResult（不依赖 mineru、不需要真实 PDF），
连跑两次 ``ingest_pdf(write=True)``，断言：

* ``document_pages`` 行数不变（按 (document_id, page_no) upsert，不产生重复行）；
* ``document_blocks`` 行数不变（先删后插，幂等）；
* ``page_no`` 是 **1 基**（与 services/parsers/base.py 同基线）。

只用 conftest 的测试沙箱库（kaoyan_test），绝不碰生产库。
"""
from __future__ import annotations

import pytest

from services.ingest_pipeline import ingest_pdf
from services.parsers.base import (
    BLOCK_FIGURE,
    BLOCK_TEXT,
    ParseResult,
    ParsedBlock,
    ParsedPage,
)


def _fake_result() -> ParseResult:
    """人造解析结果：2 页、若干块、1 个 figure。"""
    page1 = ParsedPage(
        page_no=1,
        width=595.0,
        height=842.0,
        text="1. 放大电路的输入电阻应当足够大。",
        ocr_engine="fake",
        ocr_confidence=0.99,
        blocks=[
            ParsedBlock(page_no=1, block_type=BLOCK_TEXT, text="1. 放大电路的输入电阻应当足够大。",
                        bbox=(50, 100, 500, 130), block_id="b1", reading_order=0, confidence=0.98),
            ParsedBlock(page_no=1, block_type=BLOCK_FIGURE, text="图1-1 放大电路示意图",
                        bbox=(50, 200, 500, 400), block_id="f1", reading_order=1, confidence=0.9),
        ],
    )
    page2 = ParsedPage(
        page_no=2,
        width=595.0,
        height=842.0,
        text="2. 判断放大电路是否工作在线性区。",
        ocr_engine="fake",
        ocr_confidence=0.97,
        blocks=[
            ParsedBlock(page_no=2, block_type=BLOCK_TEXT, text="2. 判断放大电路是否工作在线性区。",
                        bbox=(50, 100, 520, 130), block_id="b2", reading_order=0, confidence=0.95),
        ],
    )
    return ParseResult(
        pages=[page1, page2],
        engine="fake-engine",
        pdf_kind="digital",
        source_path="fake.pdf",
        total_pages=2,
    )


@pytest.fixture()
def fake_parse_fn():
    def _parse(pdf_path, **kwargs):  # noqa: ARG001 - 形参对齐 route_parse
        return _fake_result()

    return _parse


@pytest.fixture()
def document_id(db_schema):  # noqa: ARG001 - 依赖建表夹具
    from database import SessionLocal
    from models import Document

    db = SessionLocal()
    try:
        doc = Document(file_name="幂等测试.pdf", file_path="fake://idempotent.pdf",
                       source_format="pdf", subject="数字电子技术")
        db.add(doc)
        db.commit()
        return int(doc.id)
    finally:
        db.close()


def test_ingest_is_idempotent(fake_parse_fn, document_id):
    from database import SessionLocal
    from models import DocumentBlock, DocumentPage

    db = SessionLocal()
    try:
        first = ingest_pdf(db, "fake://idempotent.pdf", document_id=document_id,
                           subject="数字电子技术", parse_fn=fake_parse_fn, write=True)
        assert first["written"] is True
        assert first["pages"] == 2
        assert first["blocks"] == 3
        assert first["document_id"] == document_id

        pages_after_first = db.query(DocumentPage).filter(
            DocumentPage.document_id == document_id).count()
        blocks_after_first = db.query(DocumentBlock).filter(
            DocumentBlock.document_id == document_id).count()
        assert pages_after_first == 2
        assert blocks_after_first == 3

        # —— 第二遍：同参数再跑一次 ——
        second = ingest_pdf(db, "fake://idempotent.pdf", document_id=document_id,
                            subject="数字电子技术", parse_fn=fake_parse_fn, write=True)
        assert second["pages"] == 2
        assert second["blocks"] == 3

        pages_after_second = db.query(DocumentPage).filter(
            DocumentPage.document_id == document_id).count()
        blocks_after_second = db.query(DocumentBlock).filter(
            DocumentBlock.document_id == document_id).count()

        assert pages_after_second == pages_after_first, "重复 ingest 产生了重复的页行"
        assert blocks_after_second == blocks_after_first, "重复 ingest 产生了重复的块行"
    finally:
        db.close()


def test_page_no_is_one_based(fake_parse_fn, document_id):
    from database import SessionLocal
    from models import DocumentBlock, DocumentPage

    db = SessionLocal()
    try:
        ingest_pdf(db, "fake://idempotent.pdf", document_id=document_id,
                   parse_fn=fake_parse_fn, write=True)

        page_nos = [row.page_no for row in db.query(DocumentPage).filter(
            DocumentPage.document_id == document_id).all()]
        block_page_nos = [row.page_no for row in db.query(DocumentBlock).filter(
            DocumentBlock.document_id == document_id).all()]

        assert sorted(page_nos) == [1, 2]
        assert min(page_nos) >= 1, "页码必须 1 基"
        assert min(block_page_nos) >= 1, "块页码必须 1 基"
        assert set(block_page_nos) <= {1, 2}
    finally:
        db.close()


def test_dry_run_writes_nothing(fake_parse_fn, document_id):
    """write=False 只统计不写库。"""
    from database import SessionLocal
    from models import DocumentBlock, DocumentPage

    db = SessionLocal()
    try:
        stats = ingest_pdf(db, "fake://idempotent.pdf", document_id=document_id,
                           parse_fn=fake_parse_fn, write=False)
        assert stats["written"] is False
        assert stats["pages"] == 2
        assert db.query(DocumentPage).filter(
            DocumentPage.document_id == document_id).count() == 0
        assert db.query(DocumentBlock).filter(
            DocumentBlock.document_id == document_id).count() == 0
    finally:
        db.close()


def test_grades_and_stats(fake_parse_fn, document_id):
    """切题 + 门禁统计：题干够长但缺答案 → C。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        stats = ingest_pdf(db, "fake://idempotent.pdf", document_id=document_id,
                           parse_fn=fake_parse_fn, write=True)
        assert stats["questions"] >= 1
        assert set(stats["grades"]) == {"A", "B", "C", "JUNK"}
        assert stats["grades"]["C"] >= 1
        assert stats["engine"] == "fake-engine"
        assert stats["pdf_kind"] == "digital"
        assert stats["elapsed_seconds"] >= 0
    finally:
        db.close()
