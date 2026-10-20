"""解析层公共契约的单测：页码基线、块类型归一、阅读顺序、注册表。"""
from __future__ import annotations

import pytest

from services.parsers.base import (
    BLOCK_FIGURE,
    BLOCK_HEADER,
    BLOCK_PAGE_NO,
    BLOCK_TEXT,
    BLOCK_TITLE,
    BLOCK_UNKNOWN,
    ParseResult,
    ParsedBlock,
    ParsedPage,
    available_parsers,
    clear_registry,
    get_parser,
    normalize_block_type,
    register_parser,
    registered_parsers,
)


def test_page_no_must_start_from_one():
    with pytest.raises(ValueError):
        ParsedBlock(page_no=0)
    with pytest.raises(ValueError):
        ParsedPage(page_no=0)


def test_block_type_normalization():
    assert normalize_block_type("image") == BLOCK_FIGURE
    assert normalize_block_type("Interline-Equation") == "formula"
    assert normalize_block_type("page_header") == BLOCK_HEADER
    assert normalize_block_type("page_number") == BLOCK_PAGE_NO
    assert normalize_block_type(None) == BLOCK_UNKNOWN
    assert normalize_block_type("某种没见过的标签") == BLOCK_UNKNOWN


def test_dropped_types_are_excluded_from_body():
    page = ParsedPage(
        page_no=3,
        blocks=[
            ParsedBlock(page_no=3, block_type="page_header", text="第三章 电路", reading_order=0),
            ParsedBlock(page_no=3, block_type="title", text="3.1 节点电压法", reading_order=1),
            ParsedBlock(page_no=3, block_type="text", text="正文第一段", reading_order=2),
            ParsedBlock(page_no=3, block_type="page_number", text="57", reading_order=9),
        ],
    )
    body = page.body_blocks
    assert [b.text for b in body] == ["3.1 节点电压法", "正文第一段"]
    assert all(b.block_type not in {BLOCK_HEADER, BLOCK_PAGE_NO} for b in body)


def test_body_blocks_sorted_by_reading_order_then_y():
    page = ParsedPage(
        page_no=1,
        blocks=[
            ParsedBlock(page_no=1, text="下", reading_order=5, bbox=(0, 400, 100, 420)),
            ParsedBlock(page_no=1, text="上", reading_order=5, bbox=(0, 10, 100, 30)),
            ParsedBlock(page_no=1, text="先", reading_order=1, bbox=(0, 900, 100, 920)),
        ],
    )
    assert [b.text for b in page.body_blocks] == ["先", "上", "下"]


def test_join_text_prefers_page_text_and_falls_back_to_blocks():
    with_text = ParsedPage(page_no=1, text="整页文字", blocks=[ParsedBlock(page_no=1, text="块")])
    assert with_text.join_text() == "整页文字"

    no_text = ParsedPage(
        page_no=1,
        blocks=[
            ParsedBlock(page_no=1, text="甲", reading_order=1),
            ParsedBlock(page_no=1, block_type="formula", latex="E=mc^2", reading_order=2),
        ],
    )
    assert no_text.join_text() == "甲\nE=mc^2"


def test_parse_result_aggregates_pages():
    result = ParseResult(
        pages=[
            ParsedPage(page_no=1, text="第一页", blocks=[ParsedBlock(page_no=1, block_type="figure")]),
            ParsedPage(page_no=2, text="第二页"),
        ],
        engine="fake",
        pdf_kind="scanned",
    )
    assert result.total_pages == 2
    assert result.text == "第一页\n第二页"
    assert len(result.figure_blocks()) == 1
    assert result.pdf_kind == "scanned"


def test_parse_result_rejects_unknown_pdf_kind():
    result = ParseResult(pdf_kind="不认识")
    assert result.pdf_kind == "digital"


def test_registry_roundtrip():
    clear_registry()

    class _Fake:
        name = "fake"

        def available(self):
            return True

        def parse(self, pdf_path, **kw):
            return ParseResult(engine="fake")

    class _Broken:
        name = "broken"

        def available(self):
            raise RuntimeError("依赖没装")

        def parse(self, pdf_path, **kw):  # pragma: no cover
            raise NotImplementedError

    register_parser("fake", _Fake)
    register_parser("broken", _Broken)

    assert registered_parsers() == ["broken", "fake"]
    assert get_parser("fake").name == "fake"
    # 探测抛异常等价于不可用，不能把整个 available_parsers 拖崩
    assert available_parsers() == ["fake"]

    with pytest.raises(KeyError):
        get_parser("不存在")

    clear_registry()
