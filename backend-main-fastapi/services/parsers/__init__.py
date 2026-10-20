"""解析器包：把各类 PDF/文档解析引擎归一化成 ``ParsedPage`` / ``ParsedBlock``。

对外只暴露 :mod:`services.parsers.router` 里的 ``route_parse``，
调用方不需要关心底层到底是 PyMuPDF、MinerU 还是 RapidOCR。
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
    "registered_parsers",
]
