"""PDF 页面 → 「文字 + LaTeX」混排文本（阅读顺序还原）。

为什么需要这个
--------------
``pdf_formula_extract.py`` 只能给出「这页有哪些公式、识别成了什么」的清单。
但要真正修数据，必须把它**插回正文的正确位置**：一段话里
「设 ___ 是数列」的公式在中间，不能扔到页末。

本模块做的是完整还原：

    页面渲染 → 版面检测 → 分两类元素
                            ├─ 文字框 → 文字层优先，退 OCR
                            └─ 公式框 → PP-FormulaNet 识别 → LaTeX
                          → 按阅读顺序排序（y 分行、行内按 x）
                          → 拼成 Markdown

阅读顺序怎么判
--------------
版面检测只给框，不给阅读顺序。这里用最朴素但有效的办法：

1. 先按 bbox 的 **y 中心**排序；
2. 相邻元素若 y 中心差小于「中位行高 × 0.6」且水平不重叠，视为同一行；
3. 行内按 x1 排序。

双栏排版的坑：这里**不做栏检测**。教材/题库绝大多数是单栏；真遇到双栏，
y 分行会把左右栏混排。要正确处理需要栏分割，超出本轮范围——
所以 ``compose_page_text`` 的返回值里带 ``meta["possible_multi_column"]``
提示，让人知道这页结果可能不可靠，而不是静默给一份错乱的文本。

文字来源
--------
* **数字版**：优先 PyMuPDF 的文字层（``page.get_text("text", clip=bbox)``），
  准确、零成本。
* **扫描件**（文字层为空）：整页 OCR 一次拿到带 box 的 blocks，
  再按 bbox 归属到版面文字框。**只 OCR 一次**，不逐框 OCR（那会慢十几倍）。

公式来源
--------
``services/formula_latex.py``（PP-FormulaNet ONNX）。失败时保留
``[公式: 原因]`` 占位，**绝不静默留空**——留空等于又一次把公式弄丢。

用法
----
```python
from services.parsers.pdf_page_compose import compose_page_text

r = compose_page_text("某真题.pdf", 0)
print(r.text)          # 混排 Markdown
for el in r.elements:  # 结构化元素
    print(el.order, el.kind, el.text or el.latex)
```
"""
from __future__ import annotations

import os
import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from .pdf_formula_extract import (
    CLS_DISPLAY_FORMULA,
    CLS_INLINE_FORMULA,
    CLS_TABLE,
    FORMULA_CLASSES,
    LAYOUT_LABELS,
    LayoutDetector,
    get_layout_detector,
)

# 文字类版面框：正文、内容、标题、编号、段落标题、竖排文字
TEXT_CLASSES = frozenset({4, 6, 7, 16, 17, 22, 23})
# 同一行的 y 中心容差（占中位行高的比例）
ROW_TOLERANCE = 0.6
# 栏检测阈值：如果某侧元素的 x 起点明显分成两簇，提示可能双栏
COLUMN_GAP_RATIO = 0.18


@dataclass
class PageElement:
    """页面上的一个元素（文字或公式）。"""

    kind: str  # "text" | "formula" | "display_formula" | "table" | "unknown"
    bbox: Tuple[float, float, float, float]
    text: str = ""
    latex: str = ""
    label: str = ""
    score: float = 0.0
    order: int = 0
    source: str = ""  # "text_layer" | "ocr" | "formula_onnx"
    ok: bool = True
    reason: str = ""

    @property
    def y_center(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0

    @property
    def height(self) -> float:
        return max(0.0, self.bbox[3] - self.bbox[1])

    def render(self) -> str:
        if self.kind == "formula":
            return f"${self.latex}$" if self.ok and self.latex else f"[公式: {self.reason or '未识别'}]"
        if self.kind == "display_formula":
            return f"$${self.latex}$$" if self.ok and self.latex else f"[公式: {self.reason or '未识别'}]"
        if self.kind == "table":
            return f"[表格 {self.text}]" if self.text else "[表格]"
        return self.text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "bbox": [round(v, 1) for v in self.bbox],
            "text": self.text,
            "latex": self.latex,
            "label": self.label,
            "score": round(self.score, 3),
            "order": self.order,
            "source": self.source,
            "ok": self.ok,
            "reason": self.reason,
        }


@dataclass
class PageComposeResult:
    """单页还原结果。"""

    page_no: int = 1
    width: int = 0
    height: int = 0
    text: str = ""
    elements: List[PageElement] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    elapsed: float = 0.0
    error: str = ""

    @property
    def formula_count(self) -> int:
        return sum(1 for e in self.elements if e.kind in ("formula", "display_formula"))

    @property
    def formula_ok(self) -> int:
        return sum(1 for e in self.elements if e.kind in ("formula", "display_formula") and e.ok)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_no": self.page_no,
            "width": self.width,
            "height": self.height,
            "formula_count": self.formula_count,
            "formula_ok": self.formula_ok,
            "elapsed": round(self.elapsed, 2),
            "meta": self.meta,
            "error": self.error,
            "text": self.text,
            "elements": [e.to_dict() for e in self.elements],
        }


# --------------------------------------------------------------------------- #
# 阅读顺序
# --------------------------------------------------------------------------- #
def _overlaps_x(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    """两个框在 x 方向是否有实质重叠（超过较窄者宽度的一半）。"""
    w_a = max(1e-6, a[2] - a[0])
    w_b = max(1.0, b[2] - b[0])
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    return overlap > 0.5 * min(w_a, w_b)


def assign_reading_order(elements: List[PageElement]) -> List[PageElement]:
    """按「y 分行、行内按 x」分配阅读顺序。

    同一行的判定：y 中心差 < 中位行高 × ``ROW_TOLERANCE``，
    **且** x 方向不重叠（重叠说明是上下层关系，应该分行）。
    """
    if not elements:
        return elements
    heights = [e.height for e in elements if e.height > 1]
    median_h = statistics.median(heights) if heights else 20.0
    tol = max(4.0, median_h * ROW_TOLERANCE)

    ordered = sorted(elements, key=lambda e: (e.y_center, e.bbox[0]))
    rows: List[List[PageElement]] = []
    for el in ordered:
        placed = False
        for row in rows:
            ref = row[0]
            if abs(el.y_center - ref.y_center) <= tol and not _overlaps_x(el.bbox, ref.bbox):
                row.append(el)
                placed = True
                break
        if not placed:
            rows.append([el])

    order = 0
    result: List[PageElement] = []
    for row in rows:
        for el in sorted(row, key=lambda e: e.bbox[0]):
            el.order = order
            order += 1
            result.append(el)
    return result


def _looks_multi_column(elements: List[PageElement], page_width: int) -> bool:
    """粗判是否双栏：看元素的 x 起点是否明显分成两簇。"""
    if page_width <= 0 or len(elements) < 6:
        return False
    xs = sorted(e.bbox[0] for e in elements)
    mid = page_width * 0.5
    left = [x for x in xs if x < mid * 0.7]
    right = [x for x in xs if x > mid * 1.1]
    if len(left) < 3 or len(right) < 3:
        return False
    # 两簇之间有明显空白带
    gap_start = max(left)
    gap_end = min(right)
    return (gap_end - gap_start) > page_width * COLUMN_GAP_RATIO


# --------------------------------------------------------------------------- #
# 文字来源
# --------------------------------------------------------------------------- #
def _text_from_layer(page, bbox: Tuple[float, float, float, float], dpi: int) -> str:
    """从 PDF 文字层按 bbox 取文字。坐标需要 PDF 点（1/72 英寸）而非像素。"""
    scale = 72.0 / dpi
    clip = (
        bbox[0] * scale,
        bbox[1] * scale,
        bbox[2] * scale,
        bbox[3] * scale,
    )
    try:
        raw = page.get_text("text", clip=clip) or ""
    except Exception:  # noqa: BLE001
        return ""
    # 合并多余空白，保留换行语义
    lines = [ln.strip() for ln in raw.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


_RAPID_ENGINE = None
_RAPID_LOCK = None


def _get_rapidocr():
    """懒加载 RapidOCR（onnxruntime 版，纯 CPU）。

    **不能走 ``services/ocr_router.py``**：那条链的 RapidOCR 后端只把文本按行
    拆成 block，**不保留 bbox**（实测整页 738 字符但 ``blocks: 0``）。
    没有坐标就无法把文字归到版面框里，整页文字会全丢——这是实测踩到的坑。
    所以这里直接调 rapidocr 拿原生结果（``[box, text, score]``，box 是四点坐标）。
    """
    global _RAPID_ENGINE, _RAPID_LOCK
    import threading

    if _RAPID_LOCK is None:
        _RAPID_LOCK = threading.Lock()
    if _RAPID_ENGINE is not None:
        return _RAPID_ENGINE
    with _RAPID_LOCK:
        if _RAPID_ENGINE is None:
            from rapidocr_onnxruntime import RapidOCR

            _RAPID_ENGINE = RapidOCR()
    return _RAPID_ENGINE


def _to_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _ocr_blocks_for_image(img: Image.Image) -> List[Tuple[str, Tuple[float, float, float, float], float]]:
    """整页 OCR 一次，返回 ``[(text, (x1,y1,x2,y2), score)]``。"""
    arr = np.asarray(img.convert("RGB"))[:, :, ::-1]  # PIL 是 RGB，rapidocr 要 BGR
    try:
        engine = _get_rapidocr()
        result, _elapse = engine(arr)
    except Exception:  # noqa: BLE001
        return []

    out: List[Tuple[str, Tuple[float, float, float, float], float]] = []
    for item in result or []:
        try:
            box, txt = item[0], item[1]
            score = _to_float(item[2] if len(item) > 2 else 0.0)
        except (IndexError, TypeError):
            continue
        txt = (txt or "").strip()
        if not txt or not box or len(box) < 3:
            continue
        xs = [_to_float(p[0]) for p in box]
        ys = [_to_float(p[1]) for p in box]
        out.append((txt, (min(xs), min(ys), max(xs), max(ys)), score))
    return out


def _text_from_ocr(ocr_blocks, bbox: Tuple[float, float, float, float]) -> str:
    """把落在版面框内的 OCR 文本按 y、x 拼起来。"""
    if not ocr_blocks:
        return ""
    x1, y1, x2, y2 = bbox
    inside = []
    for txt, ob, sc in ocr_blocks:
        ox1, oy1, ox2, oy2 = ob
        if ox2 <= ox1 or oy2 <= oy1:
            continue  # 无坐标，跳过（无法归属）
        cy = (oy1 + oy2) / 2.0
        cx = (ox1 + ox2) / 2.0
        if x1 - 2 <= cx <= x2 + 2 and y1 - 2 <= cy <= y2 + 2:
            inside.append((oy1, ox1, txt))
    if not inside:
        return ""
    inside.sort()
    return "".join(t for _, _, t in inside).strip()


# --------------------------------------------------------------------------- #
# 以 OCR 行为骨架组装（比用 Layout 大框更准）
# --------------------------------------------------------------------------- #
def _compose_by_ocr_lines(
    ocr_blocks: List[Tuple[str, Tuple[float, float, float, float], float]],
    formulas: List[PageElement],
    *,
    line_tolerance: float = 0.6,
) -> List[str]:
    """把公式插进 OCR 行内，返回按阅读顺序排好的文本片段列表。

    **为什么不用 Layout 的文字大框做骨架**：Layout 给的是「段落级」框，
    一个框可能覆盖整道题（题干 + 选项 + 解析）。用它当骨架时，公式框
    与段落框的 y 中心差很大，按 y 分行就会把公式全挤到段落前面——
    实测效果是「两个公式在前，一整段文字挤在最后」。

    OCR 的 block 天然是**一行一个**，粒度刚好。所以：

    1. 按 y 把 OCR 行分组（同一行可能被 OCR 切成几段）；
    2. 每个公式按 **y 中心** 归属到最近的那一行（容差 = 行高 × 0.6）；
    3. 行内按 x 排序拼接：文字段与公式交替出现；
    4. 找不到归属的公式（悬空）单独成行，按 y 插到行间。

    这样「（1）与两直线 $...$ 和 $...$ 都平行」才会真的拼在一起。
    """
    if not ocr_blocks and not formulas:
        return []

    # 0) **丢掉落在公式框里的 OCR 文本**
    # OCR 会把公式区域也当文字识别，得到 `x=1 x+1 y+2 z-l` 这种乱码，
    # 与同一位置的 LaTeX 重复两遍。判定用「OCR 框中心是否落在公式框内」：
    # 中心在内 → 整条丢弃（公式框会补上 LaTeX）；
    # 只是边缘相交 → 保留（说明是「题干文字 + 行内公式」的混合行）。
    formula_boxes = [f.bbox for f in formulas]
    kept_blocks = []
    dropped = 0
    for txt, bb, sc in ocr_blocks:
        cx = (bb[0] + bb[2]) / 2.0
        cy = (bb[1] + bb[3]) / 2.0
        inside = False
        for fb in formula_boxes:
            if fb[0] - 2 <= cx <= fb[2] + 2 and fb[1] - 2 <= cy <= fb[3] + 2:
                inside = True
                break
        if inside:
            dropped += 1
            continue
        kept_blocks.append((txt, bb, sc))
    ocr_blocks = kept_blocks
    if not ocr_blocks and not formulas:
        return []

    # 1) OCR 行分组
    rows: List[Dict[str, Any]] = []
    for txt, bb, sc in ocr_blocks:
        y_c = (bb[1] + bb[3]) / 2.0
        h = max(1.0, bb[3] - bb[1])
        placed = False
        for row in rows:
            if abs(y_c - row["y_center"]) <= max(4.0, min(h, row["height"]) * line_tolerance):
                row["items"].append((bb[0], txt, "text"))
                row["y_center"] = (row["y_center"] * row["n"] + y_c) / (row["n"] + 1)
                row["n"] += 1
                row["height"] = max(row["height"], h)
                placed = True
                break
        if not placed:
            rows.append({"y_center": y_c, "height": h, "n": 1, "items": [(bb[0], txt, "text")]})

    # 2) 公式归属
    orphans: List[PageElement] = []
    for f in formulas:
        best = None
        for row in rows:
            if abs(f.y_center - row["y_center"]) <= max(6.0, row["height"] * 0.8):
                if best is None or abs(f.y_center - row["y_center"]) < abs(f.y_center - best["y_center"]):
                    best = row
        if best is None:
            orphans.append(f)
        else:
            best["items"].append((f.bbox[0], f, "formula"))

    # 3) 行内按 x 拼
    rows.sort(key=lambda r: r["y_center"])
    lines: List[str] = []
    for row in rows:
        row["items"].sort(key=lambda it: it[0])
        buf: List[str] = []
        prev_kind = None
        for _x, val, kind in row["items"]:
            if kind == "text":
                if prev_kind == "text" and buf and not buf[-1].endswith((" ", "，", "。")):
                    buf.append(" ")
                buf.append(val)
            else:
                buf.append(val.render())
            prev_kind = kind
        line = "".join(buf).strip()
        if line:
            lines.append(line)

    # 4) 悬空公式按 y 插到行间（粗略：追加到末尾，但要标出来）
    if orphans:
        orphans.sort(key=lambda f: f.y_center)
        for f in orphans:
            lines.append(f.render())
    return lines


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def compose_page_text(
    pdf_path: str,
    page_no: int = 0,
    *,
    dpi: int = 200,
    min_score: float = 0.3,
    layout: Optional[LayoutDetector] = None,
    recognizer=None,
    prefer_text_layer: bool = True,
    ocr_fallback: bool = True,
    max_formulas: int = 0,
) -> PageComposeResult:
    """还原一页的「文字 + 公式」混排文本。

    参数
    ----
    page_no: 0 基页码。
    prefer_text_layer: 优先用 PDF 文字层（数字版准且快）。
    ocr_fallback: 文字层为空时是否 OCR（扫描件必须开）。
    max_formulas: 最多识别多少个公式（0=不限）。**调试/试跑时限制它**，
        因为一页可能有上百个公式框，每个 0.3–0.5s。
    """
    t0 = time.time()
    res = PageComposeResult(page_no=page_no + 1)
    if not pdf_path or not os.path.exists(pdf_path):
        res.error = "file_not_found"
        res.elapsed = time.time() - t0
        return res

    det = layout or get_layout_detector()
    if not det.available:
        res.error = f"layout_unavailable: {det.load_error}"
        res.elapsed = time.time() - t0
        return res

    rec = recognizer
    if rec is None:
        try:
            from services.formula_latex import get_recognizer

            rec = get_recognizer()
        except Exception as exc:  # noqa: BLE001
            res.error = f"recognizer_unavailable: {type(exc).__name__}: {exc}"
            res.elapsed = time.time() - t0
            return res

    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # type: ignore

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:  # noqa: BLE001
        res.error = f"open_failed: {type(exc).__name__}: {exc}"
        res.elapsed = time.time() - t0
        return res

    try:
        if page_no < 0 or page_no >= doc.page_count:
            res.error = f"page_out_of_range: {page_no} (共 {doc.page_count} 页)"
            return res
        page = doc[page_no]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        pw, ph = img.size
        res.width, res.height = pw, ph

        boxes = det.detect(img, min_score=min_score)
        if not boxes:
            res.error = "no_layout_boxes"
            res.elapsed = time.time() - t0
            return res

        # 先看文字层有没有内容（决定是否要走 OCR）
        layer_probe = (page.get_text("text") or "").strip()
        need_ocr = ocr_fallback and len(layer_probe) < 10
        ocr_blocks = _ocr_blocks_for_image(img) if need_ocr else []
        res.meta["text_source"] = "ocr" if need_ocr else "text_layer"
        res.meta["ocr_blocks"] = len(ocr_blocks)
        res.meta["layer_chars"] = len(layer_probe)

        elements: List[PageElement] = []
        seen_boxes: set = set()
        formula_budget = max_formulas if max_formulas > 0 else 10 ** 9
        formula_used = 0

        for cid, score, bbox in boxes:
            label = LAYOUT_LABELS[cid] if 0 <= cid < len(LAYOUT_LABELS) else f"?{cid}"
            # 去重（DETR 会输出近似重复框）
            key = (round(bbox[0] / 4), round(bbox[1] / 4), round(bbox[2] / 4), round(bbox[3] / 4))
            if key in seen_boxes:
                continue
            seen_boxes.add(key)

            if cid in FORMULA_CLASSES:
                if formula_used >= formula_budget:
                    elements.append(PageElement(
                        kind="formula" if cid == CLS_INLINE_FORMULA else "display_formula",
                        bbox=bbox, label=label, score=score, ok=False,
                        reason="超出本页识别预算", source="skipped",
                    ))
                    continue
                formula_used += 1
                kind = "formula" if cid == CLS_INLINE_FORMULA else "display_formula"
                el = PageElement(kind=kind, bbox=bbox, label=label, score=score, source="formula_onnx")
                try:
                    x1, y1, x2, y2 = (int(round(v)) for v in bbox)
                    x1 = max(0, x1 - 3); y1 = max(0, y1 - 3)
                    x2 = min(pw, x2 + 3); y2 = min(ph, y2 + 3)
                    if x2 > x1 and y2 > y1:
                        r = rec.recognize_image(img.crop((x1, y1, x2, y2))) if hasattr(rec, "recognize_image") else None
                        if r is None:
                            el.ok, el.reason = False, "recognizer_no_image_api"
                        else:
                            el.ok, el.latex, el.reason = bool(r.ok), r.latex or "", r.reason or ""
                    else:
                        el.ok, el.reason = False, "degenerate_bbox"
                except Exception as exc:  # noqa: BLE001
                    el.ok, el.reason = False, f"{type(exc).__name__}: {exc}"
                elements.append(el)
            elif cid in TEXT_CLASSES:
                txt = ""
                src = ""
                if prefer_text_layer:
                    txt = _text_from_layer(page, bbox, dpi)
                    if txt:
                        src = "text_layer"
                if not txt and ocr_blocks:
                    txt = _text_from_ocr(ocr_blocks, bbox)
                    if txt:
                        src = "ocr"
                if txt:
                    elements.append(PageElement(
                        kind="text", bbox=bbox, text=txt, label=label,
                        score=score, source=src,
                    ))
            elif cid == CLS_TABLE:
                elements.append(PageElement(
                    kind="table", bbox=bbox, label=label, score=score,
                    text="", source="layout",
                ))

        elements = assign_reading_order(elements)
        res.elements = elements
        res.meta["possible_multi_column"] = _looks_multi_column(elements, pw)
        res.meta["layout_counts"] = {}
        for cid, _s, _b in boxes:
            nm = LAYOUT_LABELS[cid] if 0 <= cid < len(LAYOUT_LABELS) else f"?{cid}"
            res.meta["layout_counts"][nm] = res.meta["layout_counts"].get(nm, 0) + 1

        # 组装文本：有 OCR 行时以「行」为骨架（精度高得多），
        # 否则退回 Layout 元素的 y-x 排序（数字版文字层够用的场景）。
        formulas_only = [e for e in elements if e.kind in ("formula", "display_formula")]
        if ocr_blocks:
            lines = _compose_by_ocr_lines(ocr_blocks, formulas_only)
            res.text = "\n".join(lines)
            res.meta["compose_skeleton"] = "ocr_lines"
        else:
            parts: List[str] = []
            prev_kind = None
            for el in elements:
                piece = el.render()
                if not piece:
                    continue
                if el.kind in ("text", "table") and prev_kind in ("text", "table") and parts:
                    parts.append("\n")
                parts.append(piece)
                prev_kind = el.kind
            res.text = "\n".join(parts) if parts else ""
            res.meta["compose_skeleton"] = "layout_boxes"
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass

    res.elapsed = time.time() - t0
    return res
