"""解析路由：按 PDF 类型选引擎，产出统一的 ``ParseResult``。

决策表（doc §4.1）：

===========  ==========================================================
pdf_kind    走哪条路
===========  ==========================================================
digital     PyMuPDF 全量取文字层（不 OCR）
scanned     OCR 引擎链：MinerU 优先，RapidOCR 兜底
hybrid      PyMuPDF 取有字的页；文字层不足 30 字的页交给 OCR 引擎
===========  ==========================================================

合并要点（hybrid）：**页码不重排**。数字版页和扫描页混在同一本 PDF 里时，
两边都用物理页码，合并后「第 7 页」仍然是原 PDF 的第 7 页 —— 下游按页码
回填题目配图时不能被重排打乱。

所有引擎都返回 ``ParseResult``，``elapsed_seconds`` 用 ``time.perf_counter()``
实测（不是估算）。
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Any, List, Optional

from services.parsers.base import (
    PDF_KIND_DIGITAL,
    PDF_KIND_HYBRID,
    PDF_KIND_SCANNED,
    ParseResult,
)
from services.parsers.pdf_classifier import classify_pdf, needs_ocr_pages

logger = logging.getLogger(__name__)

#: OCR 引擎优先顺序（MinerU 做版面，RapidOCR 兜底）
DEFAULT_OCR_CHAIN = ("mineru", "rapidocr")


def _build_parser(name: str):
    """按名造解析器（延迟 import：避免顶层拉重依赖）。"""
    if name == "pymupdf":
        from services.parsers.pymupdf_parser import PyMuPDFParser

        return PyMuPDFParser()
    if name == "mineru":
        from services.parsers.mineru_parser import MinerUParser

        return MinerUParser()
    if name == "rapidocr":
        from services.parsers.rapidocr_parser import RapidOCRParser

        return RapidOCRParser()
    raise KeyError(f"未知解析器: {name}")


def _ocr_chain(prefer: Optional[Any]) -> List[str]:
    """确定 OCR 引擎顺序。

    ``prefer`` 可以是引擎名（``"mineru"`` / ``"rapidocr"``）或引擎名列表；
    ``None`` / ``"auto"`` 用默认顺序。
    """
    if prefer is None or (isinstance(prefer, str) and prefer.lower() in ("", "auto")):
        return list(DEFAULT_OCR_CHAIN)
    if isinstance(prefer, str):
        wanted = prefer.strip()
        chain = [wanted] + [n for n in DEFAULT_OCR_CHAIN if n != wanted]
        return chain
    chain = [str(n) for n in prefer if str(n)]
    for name in DEFAULT_OCR_CHAIN:
        if name not in chain:
            chain.append(name)
    return chain


def route_parse(
    pdf_path: str,
    *,
    prefer: Optional[Any] = None,
    max_pages: Optional[int] = None,
    out_dir: Optional[str] = None,
) -> ParseResult:
    """解析一份 PDF，返回归一化结果。

    :param pdf_path: PDF 路径
    :param prefer: OCR 引擎偏好（``"mineru"`` / ``"rapidocr"`` 或列表）
    :param max_pages: 最多解析多少页（从首页起）
    :param out_dir: 产物目录（图片落在这里）；不给则用临时目录
    :raises RuntimeError: 扫描版且没有任何可用 OCR 引擎
    """
    t0 = time.perf_counter()
    profile = classify_pdf(pdf_path)
    route: List[str] = [f"classify:{profile.kind}"]
    logger.info("PDF 分类 %s → %s（平均 %s 字/页）", os.path.basename(pdf_path), profile.kind,
                round(profile.avg_chars_per_page, 1))

    real_out = os.path.abspath(out_dir) if out_dir else tempfile.mkdtemp(prefix="kaoyan_parse_")
    os.makedirs(real_out, exist_ok=True)

    if profile.kind == PDF_KIND_SCANNED:
        result = _parse_scanned(pdf_path, prefer, max_pages, real_out, route)
    elif profile.kind == PDF_KIND_HYBRID:
        result = _parse_hybrid(pdf_path, prefer, max_pages, real_out, route, profile)
    else:
        parser = _build_parser("pymupdf")
        result = parser.parse(pdf_path, max_pages=max_pages, out_dir=real_out)
        result.pdf_kind = PDF_KIND_DIGITAL
        route.append("pymupdf:all")

    result.elapsed_seconds = time.perf_counter() - t0
    result.meta.setdefault("out_dir", real_out)
    result.meta["route"] = route
    result.meta["profile"] = profile.to_dict()
    result.meta["engine"] = result.engine
    return result


def _parse_scanned(
    pdf_path: str,
    prefer: Optional[Any],
    max_pages: Optional[int],
    out_dir: str,
    route: List[str],
) -> ParseResult:
    """扫描版：按优先链试 OCR 引擎。"""
    chain = _ocr_chain(prefer)
    for name in chain:
        try:
            parser = _build_parser(name)
        except KeyError:
            route.append(f"{name}:unknown")
            continue
        if not parser.available():
            route.append(f"{name}:unavailable")
            continue
        route.append(f"{name}:parse")
        result = parser.parse(pdf_path, max_pages=max_pages, out_dir=out_dir)
        result.pdf_kind = PDF_KIND_SCANNED
        return result
    raise RuntimeError("没有可用的 OCR 引擎（mineru / rapidocr 均不可用）")


def _parse_hybrid(
    pdf_path: str,
    prefer: Optional[Any],
    max_pages: Optional[int],
    out_dir: str,
    route: List[str],
    profile,
) -> ParseResult:
    """混合版：文字层够的页走 PyMuPDF，不够的页走 OCR，两边按物理页码合并。"""
    ocr_pages = needs_ocr_pages(profile)
    all_pages = sorted(profile.page_char_counts.keys()) or list(range(1, profile.total_pages + 1))
    text_pages = [p for p in all_pages if p not in set(ocr_pages)]

    pymupdf = _build_parser("pymupdf")
    text_result = pymupdf.parse(
        pdf_path, page_numbers=text_pages or [], out_dir=out_dir
    )
    route.append(f"pymupdf:text_pages={len(text_pages)}")

    ocr_result: Optional[ParseResult] = None
    if ocr_pages:
        chain = _ocr_chain(prefer)
        for name in chain:
            try:
                parser = _build_parser(name)
            except KeyError:
                route.append(f"{name}:unknown")
                continue
            if not parser.available():
                route.append(f"{name}:unavailable")
                continue
            route.append(f"{name}:ocr_pages={len(ocr_pages)}")
            ocr_result = parser.parse(
                pdf_path, page_numbers=ocr_pages, out_dir=out_dir
            )
            break
        if ocr_result is None:
            raise RuntimeError("没有可用的 OCR 引擎（mineru / rapidocr 均不可用）")

    pages = list(text_result.pages)
    if ocr_result is not None:
        pages.extend(ocr_result.pages)
    pages.sort(key=lambda p: p.page_no)  # 物理页码，不重排

    engine = "pymupdf"
    if ocr_result is not None:
        engine = f"pymupdf+{ocr_result.engine}"

    return ParseResult(
        pages=pages,
        engine=engine,
        pdf_kind=PDF_KIND_HYBRID,
        source_path=os.path.abspath(pdf_path),
        total_pages=profile.total_pages,
        meta={
            "out_dir": out_dir,
            "text_pages": text_pages,
            "ocr_pages": ocr_pages,
        },
    )
