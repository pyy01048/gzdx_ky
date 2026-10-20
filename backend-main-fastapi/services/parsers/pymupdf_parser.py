"""数字版 PDF 解析器（PyMuPDF）：文字层块化 + 图片抽取。

对应 ``docx/34-OCR与数据采集开源方案`` §4.5「题目与图片」的第 7 条：

    数字版：``page.get_images()``、``page.get_drawings()``，按 bbox 裁图；
    产物：``figure_crop`` + ``page_thumb`` + ``bbox`` + ``caption``，不要只存整页 PNG。

所以本模块**不产出整页 PNG 当配图**，而是产出两种配图：

1. **内嵌位图**：``page.get_images(full=True)`` 拿到 xref → ``doc.extract_image(xref)``
   存原图（无损、无重采样），bbox 用 ``page.get_image_rects(xref)``。
2. **矢量图区域**：``page.get_drawings()`` 拿到一堆 path → 合并相邻 path 的 bbox →
   ``page.get_pixmap(clip=bbox, dpi=300)`` 裁图。

装饰性小块（分隔线、边框、图标）会被过滤：宽或高小于 ``MIN_FIGURE_SIDE``(40px)
的矢量区域直接丢掉 —— 否则每页都能切出十几条「图」，题目配图会全是噪声。

块级切分：``page.get_text("dict")`` 的每个 block 落一个 ``ParsedBlock``；
字号显著大于正文（≥ 正文中位字号 × 1.25）的判为 ``title``，其余为 ``text``。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.parsers.base import (
    BLOCK_FIGURE,
    BLOCK_FOOTER,
    BLOCK_HEADER,
    BLOCK_PAGE_NO,
    BLOCK_TEXT,
    BLOCK_TITLE,
    PDF_KIND_DIGITAL,
    ParseResult,
    ParsedBlock,
    ParsedPage,
)
from services.parsers.pdf_classifier import load_pymupdf

logger = logging.getLogger(__name__)

#: 图元最小边长（PDF 点，≈px @72dpi）。小于它的是分隔线/边框/小图标。
MIN_FIGURE_SIDE = 40.0
#: 相邻 path 的合并容差（点）。太小合不成图，太大会把整页串成一个区域。
MERGE_GAP = 2.0
#: 合并区域面积占页面面积超过该比例 → 判定为页边框/底纹，不作为配图。
MAX_PAGE_AREA_RATIO = 0.8
#: 矢量裁图 DPI（doc §4.5 要求 300 DPI 裁图）
CROP_DPI = 300
#: 页眉带（占页高比例）：完全落在这条带里的块是页眉候选
HEADER_BAND = 0.08
#: 页脚带（占页高比例）
FOOTER_BAND = 0.92
#: 页眉/页脚文字的最大长度（章标题可以很长，页眉通常是一行短句）
RUNNING_TEXT_MAX = 60
#: 同一段文字至少在多少页重复出现才认定为页眉/页脚（避免误删正文首行）
RUNNING_TEXT_MIN_PAGES = 2
#: 罗马数字页码
_ROMAN = {
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
}
#: 同一张图在同一位置出现在这么多页 → 判为水印/模板图
WATERMARK_MIN_PAGES = 3

Rect = Tuple[float, float, float, float]


# --------------------------------------------------------------------------- #
# 纯函数工具（单测直接打这些，不依赖 PyMuPDF）
# --------------------------------------------------------------------------- #
def _norm(rect: Sequence[float]) -> Rect:
    x0, y0, x1, y1 = (float(v) for v in rect[:4])
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _union(a: Rect, b: Rect) -> Rect:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _near(a: Rect, b: Rect, gap: float) -> bool:
    """两个矩形是否重叠或间距在 ``gap`` 内。"""
    return not (
        a[2] + gap < b[0]
        or b[2] + gap < a[0]
        or a[3] + gap < b[1]
        or b[3] + gap < a[1]
    )


def merge_rects(rects: Iterable[Sequence[float]], gap: float = MERGE_GAP) -> List[Rect]:
    """把相邻/重叠的矩形合并成连通区域。

    ``page.get_drawings()`` 会把一张图拆成几十上百条 path，不合并的话每条线
    都会被当成一个「块」。这里用迭代合并到稳定为止（path 数量级不大，够用）。
    """
    regions: List[Rect] = []
    for raw in rects or []:
        try:
            rect = _norm(raw)
        except (TypeError, ValueError):
            continue
        if rect[2] - rect[0] <= 0 and rect[3] - rect[1] <= 0:
            continue
        merged = True
        while merged:
            merged = False
            for idx, other in enumerate(regions):
                if _near(rect, other, gap):
                    rect = _union(rect, other)
                    regions.pop(idx)
                    merged = True
                    break
        regions.append(rect)
    regions.sort(key=lambda r: (r[1], r[0]))
    return regions


def filter_figure_regions(
    rects: Iterable[Sequence[float]],
    *,
    min_side: float = MIN_FIGURE_SIDE,
    page_area: Optional[float] = None,
    max_area_ratio: float = MAX_PAGE_AREA_RATIO,
) -> List[Rect]:
    """过滤掉装饰性小块，只留下可能是「配图」的区域。

    规则：宽和高都 ≥ ``min_side``；若给了 ``page_area``，还要排除占页面面积
    过大（默认 >80%）的区域 —— 那是页边框/底纹，不是插图。
    """
    out: List[Rect] = []
    for rect in rects or []:
        try:
            r = _norm(rect)
        except (TypeError, ValueError):
            continue
        w, h = r[2] - r[0], r[3] - r[1]
        if w < min_side or h < min_side:
            continue
        if page_area and page_area > 0 and (w * h) > page_area * max_area_ratio:
            continue
        out.append(r)
    return out


def _body_font_size(text_blocks: Sequence[Dict[str, Any]]) -> float:
    """正文基准字号。

    取法：**出现次数最多的字号**（按 span 数计），并列时取较小的那个。

    为什么不用字符数加权的中位数：一页上如果标题比正文还长（分两行的
    章标题），字符中位数会被标题拉高，整页就再也认不出标题了。按 span
    频次取「最常见的字号」更贴近「正文长什么样」，并列取小字号（正文通常
    比标题小）。
    """
    counter: Dict[float, int] = {}
    for block in text_blocks:
        for line in block.get("lines") or []:
            for span in line.get("spans") or []:
                if not str(span.get("text") or "").strip():
                    continue
                size = round(float(span.get("size") or 0.0), 1)
                counter[size] = counter.get(size, 0) + 1
    if not counter:
        return 0.0
    top = max(counter.values())
    return min(size for size, count in counter.items() if count == top)


def resolve_page_indices(
    total_pages: int, max_pages: Optional[int] = None, page_numbers: Optional[Sequence[int]] = None
) -> List[int]:
    """算出要解析的 0 基页索引。

    ``page_numbers`` 优先（1 基页码）；``max_pages`` 限制解析页数（从首页起）。
    """
    total = int(total_pages)
    if page_numbers is not None:
        picked = sorted({int(p) for p in page_numbers if 1 <= int(p) <= total})
        return [p - 1 for p in picked]
    if max_pages is not None and int(max_pages) > 0:
        return list(range(min(total, int(max_pages))))
    return list(range(total))


def _rel_to(base: str, path: str) -> str:
    """相对路径，统一用正斜杠（写库时不会再出现 Windows 反斜杠）。"""
    return os.path.relpath(path, base).replace(os.sep, "/")


# --------------------------------------------------------------------------- #
# 页眉 / 页脚 / 页码
# --------------------------------------------------------------------------- #
def _norm_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _band_of(bbox: Optional[Sequence[float]], page_height: float) -> Optional[str]:
    """块落在页眉带 / 页脚带 → 返回 ``"header"`` / ``"footer"``，否则 None。"""
    if not bbox or not page_height:
        return None
    y0, y1 = float(bbox[1]), float(bbox[3])
    if y1 <= page_height * HEADER_BAND:
        return "header"
    if y0 >= page_height * FOOTER_BAND:
        return "footer"
    return None


def _is_page_number(text: str) -> bool:
    """页码：阿拉伯数字或罗马数字（且长度合理）。"""
    t = _norm_text(text)
    if not t or len(t) > 5:
        return False
    return t.isdigit() or t.upper() in _ROMAN


def mark_running_text(pages: List[ParsedPage]) -> int:
    """标记页眉/页脚/页码，并丢掉落在页边带里的装饰图块。

    为什么必须做：真实考研资料每页页脚都有机构 logo（实测 247×46 px）和页码，
    不处理的话**每一页都会凭空多出一张"配图"**——这正是"386 道题里 131 道没配图"
    的另一面：配图数量对不上、图块里全是页脚水印。

    判定刻意保守，避免误删正文：

    1. 只有**完全落在**页眉带/页脚带里的块才参与判定；
    2. 纯数字/罗马数字 → ``page_no``（页码天然在页边）；
    3. 其余要**在 ≥2 页重复出现**才认定为页眉/页脚 —— 只出现一次的顶部短句
       可能是正文首行，保留为正文。

    :return: 被标记成页眉/页脚/页码的块数
    """
    # 第一遍：统计各段边缘文字在多少页出现
    counts: Dict[str, int] = {}
    for page in pages:
        for b in page.blocks:
            if b.block_type not in (BLOCK_TEXT, BLOCK_TITLE):
                continue
            if not _band_of(b.bbox, page.height):
                continue
            key = _norm_text(b.text)
            if not key or len(key) > RUNNING_TEXT_MAX:
                continue
            counts[key] = counts.get(key, 0) + 1

    marked = 0
    for page in pages:
        keep = []
        for b in page.blocks:
            band = _band_of(b.bbox, page.height)
            if b.block_type == BLOCK_FIGURE:
                # 页边带里的图块是 logo / 水印 / 边框，不是题目配图
                if band:
                    continue
                keep.append(b)
                continue
            if b.block_type in (BLOCK_TEXT, BLOCK_TITLE) and band:
                key = _norm_text(b.text)
                if key and len(key) <= RUNNING_TEXT_MAX:
                    if _is_page_number(b.text):
                        b.block_type = BLOCK_PAGE_NO
                        marked += 1
                    elif counts.get(key, 0) >= RUNNING_TEXT_MIN_PAGES:
                        b.block_type = BLOCK_HEADER if band == "header" else BLOCK_FOOTER
                        marked += 1
            keep.append(b)
        page.blocks = keep

    # 页级文字去掉页眉/页脚/页码（否则 join_text 优先用 text，噪声会漏回去）
    for page in pages:
        if any(b.is_dropped for b in page.blocks):
            page.text = "\n".join(b.text for b in page.body_blocks if b.text.strip())
    return marked


def _watermark_key(block: ParsedBlock) -> Optional[Tuple[str, Tuple[int, int, int, int]]]:
    """水印指纹：图片内容哈希 + 位置（四舍五入到整数）。

    只有「同一张图 + 同一位置」在多页重复出现才是水印；同一张图出现在不同位置
    仍然是**真配图**（教材里同一幅图被多道题引用很常见）。
    """
    md5 = (block.extra or {}).get("content_md5")
    if not md5 or not block.bbox:
        return None
    x0, y0, x1, y1 = (int(round(v)) for v in block.bbox)
    return str(md5), (x0, y0, x1, y1)


def drop_watermark_figures(pages: List[ParsedPage], min_pages: int = WATERMARK_MIN_PAGES) -> int:
    """丢掉「同一张图 + 同一位置」在多页重复出现的水印/模板图。

    实测：考研资料每页正中盖一个机构 logo（研途），不剔掉的话每页都会产出
    一张一模一样的"配图"，题目配图绑定必然错位。

    :return: 被丢掉的水印图块数
    """
    hits: Dict[Tuple[str, Tuple[int, int, int, int]], set] = {}
    for page in pages:
        for b in page.blocks:
            if b.block_type != BLOCK_FIGURE:
                continue
            key = _watermark_key(b)
            if key:
                hits.setdefault(key, set()).add(page.page_no)
    watermarks = {k for k, p in hits.items() if len(p) >= min_pages}
    if not watermarks:
        return 0
    dropped = 0
    for page in pages:
        keep = []
        for b in page.blocks:
            key = _watermark_key(b)
            if b.block_type == BLOCK_FIGURE and key in watermarks:
                dropped += 1
                continue
            keep.append(b)
        page.blocks = keep
    return dropped


def cleanup_unreferenced_images(images_dir: str, pages: List[ParsedPage]) -> int:
    """删掉产物目录里没被任何块引用的图片（水印/装饰图被剔除后留下的孤儿文件）。"""
    if not images_dir or not os.path.isdir(images_dir):
        return 0
    referenced = set()
    for page in pages:
        for b in page.blocks:
            if b.image_path:
                referenced.add(os.path.basename(b.image_path))
    removed = 0
    for name in os.listdir(images_dir):
        if name in referenced:
            continue
        try:
            os.remove(os.path.join(images_dir, name))
            removed += 1
        except OSError:
            continue
    return removed


# --------------------------------------------------------------------------- #
# 解析器
# --------------------------------------------------------------------------- #
class PyMuPDFParser:
    """数字版 PDF 解析器。"""

    name = "pymupdf"

    def available(self) -> bool:
        try:
            load_pymupdf()
            return True
        except Exception:  # noqa: BLE001 - 探测失败等价于不可用
            return False

    # -- 主流程 ----------------------------------------------------------- #
    def parse(
        self,
        pdf_path: str,
        *,
        max_pages: Optional[int] = None,
        out_dir: Optional[str] = None,
        page_numbers: Optional[List[int]] = None,
    ) -> ParseResult:
        t0 = time.perf_counter()
        fitz = load_pymupdf()
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

        real_out = os.path.abspath(out_dir) if out_dir else tempfile.mkdtemp(prefix="kaoyan_pymupdf_")
        images_dir = os.path.join(real_out, "images")
        os.makedirs(images_dir, exist_ok=True)

        doc = fitz.open(pdf_path)
        try:
            if getattr(doc, "needs_pass", False):
                raise RuntimeError(f"PDF 已加密，无法解析: {os.path.basename(pdf_path)}")
            total = int(doc.page_count)
            indices = resolve_page_indices(total, max_pages, page_numbers)
            pages = [
                self._parse_page(doc, idx, real_out, images_dir)
                for idx in indices
            ]
        finally:
            doc.close()

        mark_running_text(pages)
        watermarks = drop_watermark_figures(pages)
        orphans = cleanup_unreferenced_images(images_dir, pages)

        figure_count = sum(1 for p in pages for b in p.blocks if b.block_type == BLOCK_FIGURE)
        return ParseResult(
            pages=pages,
            engine=self.name,
            pdf_kind=PDF_KIND_DIGITAL,
            source_path=os.path.abspath(pdf_path),
            total_pages=total,
            elapsed_seconds=time.perf_counter() - t0,
            meta={
                "out_dir": real_out,
                "images_dir": _rel_to(real_out, images_dir),
                "parsed_pages": [p.page_no for p in pages],
                "figure_count": figure_count,
                "watermark_figures_dropped": watermarks,
                "orphan_images_removed": orphans,
            },
        )

    # -- 单页 ------------------------------------------------------------- #
    def _parse_page(self, doc, idx: int, out_dir: str, images_dir: str) -> ParsedPage:
        page = doc.load_page(idx)
        page_no = idx + 1
        width = float(page.rect.width)
        height = float(page.rect.height)

        raw = page.get_text("dict") or {}
        text_blocks = [b for b in (raw.get("blocks") or []) if int(b.get("type", 0)) == 0]
        body_size = _body_font_size(text_blocks)

        blocks: List[ParsedBlock] = []
        order = 0
        for b in text_blocks:
            lines: List[str] = []
            max_size = 0.0
            for line in b.get("lines") or []:
                spans = line.get("spans") or []
                piece = "".join(str(s.get("text") or "") for s in spans)
                if piece.strip():
                    lines.append(piece)
                for s in spans:
                    if str(s.get("text") or "").strip():
                        max_size = max(max_size, float(s.get("size") or 0.0))
            text = "\n".join(lines).strip()
            if not text:
                continue
            bbox = b.get("bbox")
            btype = BLOCK_TEXT
            if body_size > 0 and max_size >= body_size * 1.25:
                btype = BLOCK_TITLE
            blocks.append(
                ParsedBlock(
                    page_no=page_no,
                    block_type=btype,
                    text=text,
                    bbox=tuple(float(v) for v in bbox) if bbox else None,
                    block_id=f"p{page_no}-t{order}",
                    reading_order=order,
                    extra={"font_size": round(max_size, 2)},
                )
            )
            order += 1

        blocks.extend(self._extract_images(doc, page, page_no, out_dir, images_dir, order))
        order += sum(1 for b in blocks if b.block_type == BLOCK_FIGURE)
        image_bboxes = [b.bbox for b in blocks if b.block_type == BLOCK_FIGURE and b.bbox]
        figure_blocks = self._extract_vector_figures(
            page, page_no, out_dir, images_dir, image_bboxes
        )
        for fig in figure_blocks:
            fig.reading_order = order
            order += 1
        blocks.extend(figure_blocks)

        text = (page.get_text("text") or "").strip()
        return ParsedPage(
            page_no=page_no,
            width=width,
            height=height,
            text=text,
            layout_json={
                "text_blocks": len([b for b in blocks if b.block_type in (BLOCK_TEXT, BLOCK_TITLE)]),
                "figure_blocks": len(figure_blocks),
                "body_font_size": round(body_size, 2),
            },
            blocks=blocks,
        )

    # -- 内嵌位图 --------------------------------------------------------- #
    def _extract_images(
        self, doc, page, page_no: int, out_dir: str, images_dir: str, order: int
    ) -> List[ParsedBlock]:
        out: List[ParsedBlock] = []
        seen_xrefs = set()
        page_height = float(page.rect.height)
        try:
            images = page.get_images(full=True)
        except Exception:  # noqa: BLE001
            images = []
        for info in images or []:
            try:
                xref = int(info[0])
            except (TypeError, ValueError, IndexError):
                continue
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            bbox = None
            try:
                rects = page.get_image_rects(xref)
            except Exception:  # noqa: BLE001
                rects = []
            if not rects:
                # 图片在资源字典里但没被放到页面上（未使用资源 / 藏在表单里）：
                # 没有位置就没法跟题目绑定，留着只会变成噪声图块。
                logger.debug("跳过未定位图片 xref=%s p%s", xref, page_no)
                continue
            bbox = tuple(float(v) for v in rects[0])
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w < MIN_FIGURE_SIDE or h < MIN_FIGURE_SIDE:
                continue  # 小图标 / 装饰点
            if _band_of(bbox, page_height):
                continue  # 页眉页脚的机构 logo / 水印，不是题目配图
            try:
                raw = doc.extract_image(xref)
            except Exception as exc:  # noqa: BLE001
                logger.debug("提取内嵌图片失败 xref=%s: %s", xref, exc)
                continue
            data = raw.get("image") or b""
            if not data:
                continue
            ext = str(raw.get("ext") or "png").lstrip(".")
            name = f"p{page_no:04d}_img{xref}.{ext}"
            path = os.path.join(images_dir, name)
            try:
                with open(path, "wb") as fh:
                    fh.write(data)
            except OSError as exc:
                logger.warning("图片落盘失败 %s: %s", path, exc)
                continue
            out.append(
                ParsedBlock(
                    page_no=page_no,
                    block_type=BLOCK_FIGURE,
                    bbox=bbox,
                    block_id=f"p{page_no}-img{xref}",
                    image_path=_rel_to(out_dir, path),
                    reading_order=order + len(out),
                    extra={
                        "source": "embedded",
                        "xref": xref,
                        "content_md5": hashlib.md5(data).hexdigest(),
                    },
                )
            )
        return out

    # -- 矢量图区域 ------------------------------------------------------- #
    def _extract_vector_figures(
        self,
        page,
        page_no: int,
        out_dir: str,
        images_dir: str,
        image_bboxes: Optional[List[Rect]] = None,
    ) -> List[ParsedBlock]:
        try:
            drawings = page.get_drawings()
        except Exception:  # noqa: BLE001
            drawings = []
        rects = []
        for d in drawings or []:
            r = d.get("rect")
            if r is None:
                continue
            try:
                rects.append(tuple(float(v) for v in r))
            except (TypeError, ValueError):
                continue
        if not rects:
            return []
        page_area = float(page.rect.width) * float(page.rect.height)
        page_height = float(page.rect.height)
        regions = filter_figure_regions(
            merge_rects(rects), page_area=page_area
        )
        out: List[ParsedBlock] = []
        for i, bbox in enumerate(regions, start=1):
            if _band_of(bbox, page_height):
                continue  # 页边带里的矢量图是页边框/装饰
            if _overlaps_any(bbox, image_bboxes or []):
                # 与内嵌位图重叠：要么是位图本身（矢量只是描边/批注），要么是
                # 合并出来的垃圾区域（实测讲义里红笔批注会把半页矢量粘成一块）。
                continue
            try:
                pix = page.get_pixmap(clip=_rect_obj(page, bbox), dpi=CROP_DPI)
            except Exception as exc:  # noqa: BLE001
                logger.debug("矢量区域裁图失败 p%s #%s: %s", page_no, i, exc)
                continue
            if pix.width <= 0 or pix.height <= 0:
                continue
            name = f"p{page_no:04d}_vec{i}.png"
            path = os.path.join(images_dir, name)
            try:
                pix.save(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("矢量裁图落盘失败 %s: %s", path, exc)
                continue
            out.append(
                ParsedBlock(
                    page_no=page_no,
                    block_type=BLOCK_FIGURE,
                    bbox=bbox,
                    block_id=f"p{page_no}-vec{i}",
                    image_path=_rel_to(out_dir, path),
                    reading_order=0,
                    extra={"source": "vector", "dpi": CROP_DPI},
                )
            )
        return out


def _overlaps_any(rect: Rect, others: List[Rect], min_iou: float = 0.2) -> bool:
    """两个矩形是否重叠（IoU ≥ ``min_iou``，或一方基本被另一方包含）。"""
    for other in others:
        ix0 = max(rect[0], other[0])
        iy0 = max(rect[1], other[1])
        ix1 = min(rect[2], other[2])
        iy1 = min(rect[3], other[3])
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        inter = (ix1 - ix0) * (iy1 - iy0)
        area_a = max(1e-6, (rect[2] - rect[0]) * (rect[3] - rect[1]))
        area_b = max(1e-6, (other[2] - other[0]) * (other[3] - other[1]))
        if inter / min(area_a, area_b) >= min_iou:
            return True
    return False


def _rect_obj(page, bbox: Rect):
    """把 (x0,y0,x1,y1) 转成 PyMuPDF 的 Rect（惰性 import，避免顶层依赖）。"""
    fitz = load_pymupdf()
    return fitz.Rect(*bbox)
