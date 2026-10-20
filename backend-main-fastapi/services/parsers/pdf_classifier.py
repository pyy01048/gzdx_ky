"""PDF 类型分类：数字版 / 扫描版 / 混合版。

判定规则严格对齐 ``docx/34-OCR与数据采集开源方案`` §4.1：

1. 抽样（首页 / 中间页 / 末页）统计每页文字层字符数；
2. 平均字符/页 ≥ 100 → ``digital``，直接取文字层，不 OCR；
3. 平均 < 30 → ``scanned``，整本走 OCR；
4. 介于两者 → ``hybrid``，再全量扫一遍，文字层不足 30 字的页才 OCR。

为什么要分：数字版讲义/题库往往占一半以上，全量 OCR 既慢又会把本来干净的
文字层糊成「设则（ ）」（真实数据 386 题里 32 题的根因）。

容错：``knowledge_base`` 里有大量扫描件，其中不少是加密或结构损坏的 PDF。
这些文件不允许把整条入库管线拖崩 —— 分类失败一律降级为 ``scanned``（OCR 是
唯一的兜底路径），并把真实异常记进 ``PdfProfile.error``。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from services.parsers.base import (
    PDF_KIND_DIGITAL,
    PDF_KIND_HYBRID,
    PDF_KIND_SCANNED,
)

logger = logging.getLogger(__name__)

#: 抽样页平均字符数 ≥ 该值 → digital
DIGITAL_MIN_CHARS = 100
#: 抽样页平均字符数 < 该值 → scanned；hybrid 时单页 < 该值 → 需要 OCR
SCANNED_MAX_CHARS = 30

#: 默认抽样页数（首页 / 中间页 / 末页）
DEFAULT_SAMPLE_PAGES = 3


def load_pymupdf():
    """返回 PyMuPDF 模块。

    PyMuPDF ≥1.26 把包名收敛成 ``pymupdf``，``fitz`` 只是历史别名（并且
    1.28 起在本机环境里已经 import 不到了）。两个名字都试，优先新名字。
    import 放在函数内部：模块本身在没装 PyMuPDF 的环境里也要能被 import，
    否则 ``services.parsers`` 整个包会在测试机上炸掉。
    """
    try:
        import pymupdf  # type: ignore

        return pymupdf
    except ImportError:
        pass
    try:
        import fitz  # type: ignore

        return fitz
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise RuntimeError("未安装 PyMuPDF，无法解析 PDF 文字层（pip install pymupdf）") from exc


@dataclass
class PdfProfile:
    """一份 PDF 的「有没有文字层」画像。"""

    kind: str
    avg_chars_per_page: float
    sampled_pages: List[int]
    page_char_counts: Dict[int, int]
    total_pages: int
    #: 分类过程中的异常（加密 / 损坏 / 文件不存在），正常为空串
    error: str = ""
    #: 判定时用的抽样页平均字符数（hybrid 时 page_char_counts 会被替换成全量，
    #: 但 kind 仍由抽样结果决定，这里保留原始依据便于复查）
    sampled_avg_chars: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "avg_chars_per_page": round(float(self.avg_chars_per_page), 2),
            "sampled_pages": list(self.sampled_pages),
            "page_char_counts": {int(k): int(v) for k, v in self.page_char_counts.items()},
            "total_pages": int(self.total_pages),
            "error": self.error,
            "sampled_avg_chars": round(float(self.sampled_avg_chars), 2),
        }


def _text_char_count(page) -> int:
    """一页文字层的有效字符数（去掉所有空白，换行不算内容）。"""
    raw = page.get_text("text") or ""
    return len("".join(raw.split()))


def page_char_counts(
    pdf_path: str, *, pages: Optional[Iterable[int]] = None
) -> Dict[int, int]:
    """统计每页文字层字符数。

    :param pdf_path: PDF 路径
    :param pages: 只统计这些页（**1 基**页码）；None 表示全量
    :return: ``{1 基页码: 字符数}``
    :raises RuntimeError: 加密 / 无权限 / 文件损坏 / 未安装 PyMuPDF
    """
    fitz = load_pymupdf()
    doc = fitz.open(pdf_path)
    try:
        if getattr(doc, "needs_pass", False):
            raise RuntimeError(f"PDF 已加密，无法读取文字层: {os.path.basename(pdf_path)}")
        total = int(doc.page_count)
        wanted = (
            list(range(1, total + 1))
            if pages is None
            else [int(p) for p in pages]
        )
        out: Dict[int, int] = {}
        for page_no in wanted:
            if page_no < 1 or page_no > total:
                continue
            out[page_no] = _text_char_count(doc.load_page(page_no - 1))
        return out
    finally:
        doc.close()


def _total_pages(pdf_path: str) -> int:
    fitz = load_pymupdf()
    doc = fitz.open(pdf_path)
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def sample_page_numbers(total_pages: int, sample_pages: int = DEFAULT_SAMPLE_PAGES) -> List[int]:
    """抽样页（1 基）：首页 / 中间页 / 末页；页数不足时取实际存在的页。"""
    total = int(total_pages)
    if total <= 0:
        return []
    want = max(1, int(sample_pages))
    if total <= want:
        return list(range(1, total + 1))
    if want == 1:
        return [1]
    if want == 2:
        return [1, total]
    # want >= 3：按等距取 want 个点，天然包含首页与末页，中间点落在几何中心附近
    step = (total - 1) / float(want - 1)
    picked = {1, total}
    for i in range(want):
        picked.add(min(total, max(1, int(round(1 + i * step)))))
    return sorted(picked)


def _kind_from_avg(avg: float) -> str:
    if avg >= DIGITAL_MIN_CHARS:
        return PDF_KIND_DIGITAL
    if avg < SCANNED_MAX_CHARS:
        return PDF_KIND_SCANNED
    return PDF_KIND_HYBRID


def _error_profile(message: str, total_pages: int = 0) -> PdfProfile:
    return PdfProfile(
        kind=PDF_KIND_SCANNED,
        avg_chars_per_page=0.0,
        sampled_pages=[],
        page_char_counts={},
        total_pages=int(total_pages),
        error=message,
        sampled_avg_chars=0.0,
    )


def classify_pdf(pdf_path: str, sample_pages: int = DEFAULT_SAMPLE_PAGES) -> PdfProfile:
    """判定 PDF 属于 digital / scanned / hybrid。

    任何读取异常都降级成 ``scanned``：OCR 拿不到文字至少还能从图里认字，
    而把异常抛给调用方只会让整本资料入库失败。
    """
    if not pdf_path or not os.path.exists(pdf_path):
        return _error_profile(f"文件不存在: {pdf_path}")

    try:
        total = _total_pages(pdf_path)
    except Exception as exc:  # noqa: BLE001 - 损坏件必须降级
        logger.warning("PDF 页数读取失败，按扫描件处理: %s: %s", pdf_path, exc)
        return _error_profile(f"{type(exc).__name__}: {exc}")

    if total <= 0:
        return _error_profile("PDF 没有可读页面", total_pages=total)

    sampled = sample_page_numbers(total, sample_pages)
    try:
        counts = page_char_counts(pdf_path, pages=sampled)
    except Exception as exc:  # noqa: BLE001 - 加密/损坏必须降级
        logger.warning("PDF 文字层统计失败，按扫描件处理: %s: %s", pdf_path, exc)
        return _error_profile(f"{type(exc).__name__}: {exc}", total_pages=total)

    if not counts:
        return _error_profile("抽样页没有可读文字层", total_pages=total)

    avg = sum(counts.values()) / float(len(counts))
    kind = _kind_from_avg(avg)
    error = ""

    if kind == PDF_KIND_HYBRID:
        # 混合件必须知道「哪几页没字」，抽样不够用 → 全量统计。
        # 全量统计失败时保留抽样结果（退化成只对抽样页判断），不改变 kind。
        try:
            counts = page_char_counts(pdf_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("混合 PDF 全量字符统计失败，沿用抽样结果: %s: %s", pdf_path, exc)
            error = f"全量统计失败: {type(exc).__name__}: {exc}"

    return PdfProfile(
        kind=kind,
        avg_chars_per_page=avg,
        sampled_pages=sampled,
        page_char_counts=counts,
        total_pages=total,
        error=error,
        sampled_avg_chars=avg,
    )


def needs_ocr_pages(profile: PdfProfile, threshold: int = SCANNED_MAX_CHARS) -> List[int]:
    """返回文字层不足 ``threshold`` 字的页（1 基、升序）。"""
    counts = profile.page_char_counts or {}
    return sorted(int(p) for p, c in counts.items() if int(c) < int(threshold))


def looks_like_hybrid(profile: PdfProfile) -> bool:
    return profile.kind == PDF_KIND_HYBRID
