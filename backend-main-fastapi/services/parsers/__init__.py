"""解析器包：把各类 PDF/文档解析引擎归一化成 ``ParsedPage`` / ``ParsedBlock``。

对外只暴露 :mod:`services.parsers.router` 里的 ``route_parse``，
调用方不需要关心底层到底是 PyMuPDF、MinerU 还是 RapidOCR。

三个解析器（``pymupdf`` / ``mineru`` / ``rapidocr``）在这里注册进
``services.parsers.base`` 的注册表。工厂函数里才 import 具体模块 —— 模块顶层
只留纯 Python 逻辑，没有 PyMuPDF / MinerU / OCR 依赖的环境也能 import 本包。
"""

from __future__ import annotations

from services.parsers.base import (  # noqa: F401
    BLOCK_FIGURE,
    BLOCK_FORMULA,
    BLOCK_HEADER,
    BLOCK_PAGE_NO,
    BLOCK_TABLE,
    BLOCK_TEXT,
    BLOCK_TITLE,
    BLOCK_TYPES,
    BLOCK_UNKNOWN,
    DROP_BLOCK_TYPES,
    PDF_KIND_DIGITAL,
    PDF_KIND_HYBRID,
    PDF_KIND_SCANNED,
    PDF_KINDS,
    ParsedBlock,
    ParsedPage,
    ParseResult,
    available_parsers,
    clear_registry,
    get_parser,
    normalize_block_type,
    register_parser,
    registered_parsers,
)

__all__ = [
    "BLOCK_FIGURE",
    "BLOCK_FORMULA",
    "BLOCK_HEADER",
    "BLOCK_PAGE_NO",
    "BLOCK_TABLE",
    "BLOCK_TEXT",
    "BLOCK_TITLE",
    "BLOCK_TYPES",
    "BLOCK_UNKNOWN",
    "DROP_BLOCK_TYPES",
    "PDF_KIND_DIGITAL",
    "PDF_KIND_HYBRID",
    "PDF_KIND_SCANNED",
    "PDF_KINDS",
    "ParseResult",
    "ParsedBlock",
    "ParsedPage",
    "available_parsers",
    "clear_registry",
    "get_parser",
    "normalize_block_type",
    "register_parser",
    "register_builtin_parsers",
    "registered_parsers",
    "route_parse",
]


# --------------------------------------------------------------------------- #
# 内置解析器注册（工厂内才 import，避免顶层拉重依赖）
# --------------------------------------------------------------------------- #
def _make_pymupdf():
    from services.parsers.pymupdf_parser import PyMuPDFParser

    return PyMuPDFParser()


def _make_mineru():
    from services.parsers.mineru_parser import MinerUParser

    return MinerUParser()


def _make_rapidocr():
    from services.parsers.rapidocr_parser import RapidOCRParser

    return RapidOCRParser()


def register_builtin_parsers() -> None:
    """把三个内置解析器注册进注册表（幂等，可重复调用）。"""
    register_parser("pymupdf", _make_pymupdf)
    register_parser("mineru", _make_mineru)
    register_parser("rapidocr", _make_rapidocr)


register_builtin_parsers()


def route_parse(pdf_path, *, prefer=None, max_pages=None, out_dir=None) -> ParseResult:
    """解析一份 PDF（薄封装，真正实现见 :mod:`services.parsers.router`）。"""
    from services.parsers.router import route_parse as _route_parse

    return _route_parse(pdf_path, prefer=prefer, max_pages=max_pages, out_dir=out_dir)
