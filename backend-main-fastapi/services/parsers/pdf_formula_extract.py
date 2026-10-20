"""PDF 公式提取（版面检测 + 公式识别，全 ONNX，零 torch / 零联网）。

背景
----
数学类 PDF 几乎全是**扫描件**（文字层 0 字符、每页一张图）。原来的管线只能整页
丢给 OCR，而 RapidOCR 对公式是「**读错**」而不是「漏读」：

    f(x) → f(α) / f(r) / f(z)
    f(-x)=f(x) → f（一）=f()
    f(g(x)) → fLg(）

这些错字会原样入库，LLM 读到的是错误的数学式——比缺公式更危险。
实测这类污染有 **6,077 块 / 454 篇**，是本项目最大的一块数据缺口。

为什么不走 MinerU
-----------------
MinerU 2.7.6 的 pipeline 要 torch 版 PDF-Extract-Kit，而本机 `.venv-ocr` 是
**CPU 版 torch**：实测单页 Layout 9.6s → 公式检测 7.4s → 公式识别阶段
**卡在第 16/28 张超 2 分钟**（与 docx 侧发现的「极扁图推理极慢」同源）。
换 CUDA torch 要重下 2.5GB，性价比低。

所以复用本机**已有的 MinerU 4.x ONNX 模型**，自己串一条链：

    页面渲染(PyMuPDF 200dpi)
      → 版面检测 PP-DocLayoutV2（ONNX，800×800）
      → 取 display_formula(5) / inline_formula(15) 框
      → 裁切
      → 公式识别 PP-FormulaNet_plus-M（services/formula_latex.py）
      → LaTeX

全部 onnxruntime CPU 可跑，无外部依赖。

实测（1987 考研数学三真题第 1 页，扫描件）
----------------------------------------
* 版面检测：单页检出 **141 个公式框**（118 行内 + 23 块级），耗时约 2s
* 公式识别：按面积取前 12 个，**11 个成功**，另一个是 aspect=14.9 的极扁图
  被 `MAX_ASPECT` 正确拦下

识别质量样例::

    \\lim_{x \\to 0} \\frac{1}{bx - \\sin x} \\int_{0}^{x} \\frac{t^2}{...}
    \\oint_{L} (2xy - 2y)dx + (x^2 - 4x)dy
    \\begin{cases}x = 1 \\\\ y = -1 + t \\\\ z = 2 + t\\end{cases}
    \\alpha_{1} = (1,1,0)

版面类别表（PP-DocLayoutV2，顺序即 class_id）
-----------------------------------------
``0 abstract / 1 algorithm / 2 aside_text / 3 chart / 4 content /
5 display_formula / 6 doc_title / 7 figure_title / 8 footer / 9 footer_image /
10 footnote / 11 formula_number / 12 header / 13 header_image / 14 image /
15 inline_formula / 16 number / 17 paragraph_title / 18 reference /
19 reference_content / 20 seal / 21 table / 22 text /
23 vertical_text / 24 vision_footnote``

用法
----
```python
from services.parsers.pdf_formula_extract import extract_pdf_formulas

res = extract_pdf_formulas("xxx.pdf", pages=[0, 1], out_dir="D:/tmp/crops")
for page in res.pages:
    for f in page.formulas:
        print(page.page_no, f.label, f.latex, f.bbox)
```
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

# ---- 版面类别（PP-DocLayoutV2，index 即 class_id） ----------------------- #
LAYOUT_LABELS: Tuple[str, ...] = (
    "abstract", "algorithm", "aside_text", "chart", "content",
    "display_formula", "doc_title", "figure_title", "footer", "footer_image",
    "footnote", "formula_number", "header", "header_image", "image",
    "inline_formula", "number", "paragraph_title", "reference",
    "reference_content", "seal", "table", "text", "vertical_text",
    "vision_footnote",
)
CLS_DISPLAY_FORMULA = 5
CLS_INLINE_FORMULA = 15
CLS_TABLE = 21
CLS_TEXT_LIKE = frozenset({4, 6, 7, 16, 17, 22, 23})  # content/title/number/paragraph/text
FORMULA_CLASSES = frozenset({CLS_DISPLAY_FORMULA, CLS_INLINE_FORMULA})

# 版面模型输入尺寸（固定 800×800，直接拉伸，不做 letterbox）
LAYOUT_INPUT = 800
# 渲染 DPI：200 足够让 33px 高的行内公式被识别，300 会慢一倍
DEFAULT_DPI = 200
# 版面检测置信度门槛
DEFAULT_MIN_SCORE = 0.5


@dataclass
class PdfFormula:
    """页面上一个公式区域及其识别结果。"""

    page_no: int
    label: str
    bbox: Tuple[float, float, float, float]
    score: float
    latex: str = ""
    ok: bool = False
    reason: str = ""
    crop_path: str = ""

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_no": self.page_no,
            "label": self.label,
            "bbox": list(self.bbox),
            "score": round(self.score, 3),
            "latex": self.latex,
            "ok": self.ok,
            "reason": self.reason,
            "crop_path": self.crop_path,
        }


@dataclass
class PdfPageFormulas:
    """单页的公式提取结果。"""

    page_no: int
    width: int = 0
    height: int = 0
    formulas: List[PdfFormula] = field(default_factory=list)
    layout_counts: Dict[str, int] = field(default_factory=dict)
    elapsed: float = 0.0

    @property
    def ok_count(self) -> int:
        return sum(1 for f in self.formulas if f.ok)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_no": self.page_no,
            "width": self.width,
            "height": self.height,
            "formula_count": len(self.formulas),
            "ok_count": self.ok_count,
            "layout_counts": self.layout_counts,
            "elapsed": round(self.elapsed, 2),
            "formulas": [f.to_dict() for f in self.formulas],
        }


@dataclass
class PdfFormulaResult:
    """整份 PDF 的公式提取结果。"""

    source_path: str = ""
    engine_layout: str = "pp-doclayoutv2-onnx"
    engine_formula: str = ""
    pages: List[PdfPageFormulas] = field(default_factory=list)
    total_pages: int = 0
    elapsed_seconds: float = 0.0
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_formulas(self) -> int:
        return sum(len(p.formulas) for p in self.pages)

    @property
    def total_ok(self) -> int:
        return sum(p.ok_count for p in self.pages)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "engine_layout": self.engine_layout,
            "engine_formula": self.engine_formula,
            "total_pages": self.total_pages,
            "pages_done": len(self.pages),
            "total_formulas": self.total_formulas,
            "total_ok": self.total_ok,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "error": self.error,
            "meta": self.meta,
            "pages": [p.to_dict() for p in self.pages],
        }


def _default_layout_model() -> str:
    env = os.environ.get("KAOYAN_LAYOUT_MODEL", "").strip()
    if env:
        return env
    home = os.path.expanduser("~")
    return os.path.join(
        home, ".mineru", "models", "MinerU-4_models_onnx",
        "Layout", "PP-DocLayoutV2", "inference.onnx",
    )


class LayoutDetector:
    """PP-DocLayoutV2 版面检测器（ONNX Runtime）。

    输出每行 ``[class_id, score, x1, y1, x2, y2, w, h]``，坐标**已经是原图像素**，
    不需要再按 800/原图 反算（实测确认：1654×2339 的页面，raw 输出 x∈[84,1567]，
    y∈[68,1941]，正好落在图内）。
    """

    engine_name = "pp-doclayoutv2-onnx"

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or _default_layout_model()
        self._sess: Any = None
        self._lock = threading.Lock()
        self._load_error = ""

    def _ensure(self) -> bool:
        if self._sess is not None:
            return True
        with self._lock:
            if self._sess is not None:
                return True
            if self._load_error:
                return False
            try:
                import onnxruntime as ort

                if not os.path.exists(self.model_path):
                    raise FileNotFoundError(f"版面模型不存在: {self.model_path}")
                opts = ort.SessionOptions()
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                avail = ort.get_available_providers()
                providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail]
                self._sess = ort.InferenceSession(self.model_path, sess_options=opts, providers=providers)
            except Exception as exc:  # noqa: BLE001
                self._load_error = f"{type(exc).__name__}: {exc}"
                return False
            return True

    @property
    def available(self) -> bool:
        return self._ensure()

    @property
    def load_error(self) -> str:
        return self._load_error

    def detect(self, page_img: Image.Image, *, min_score: float = 0.0) -> List[Tuple[int, float, Tuple[float, float, float, float]]]:
        """检测一页，返回 ``[(class_id, score, (x1,y1,x2,y2)), ...]``。"""
        if not self._ensure():
            return []
        ow, oh = page_img.size
        # 预处理严格照 inference.yml：直接拉伸到 800×800、/255、mean=0/std=1
        resized = page_img.convert("RGB").resize((LAYOUT_INPUT, LAYOUT_INPUT), Image.BICUBIC)
        arr = np.asarray(resized).astype(np.float32) / 255.0
        inp = arr.transpose(2, 0, 1)[None, ...]
        im_shape = np.array([[LAYOUT_INPUT, LAYOUT_INPUT]], dtype=np.float32)
        scale_factor = np.array(
            [[LAYOUT_INPUT / float(max(1, oh)), LAYOUT_INPUT / float(max(1, ow))]], dtype=np.float32
        )
        try:
            outs = self._sess.run(
                None, {"image": inp, "im_shape": im_shape, "scale_factor": scale_factor}
            )
        except Exception:  # noqa: BLE001
            return []
        boxes = np.asarray(outs[0])
        if boxes.size == 0:
            return []
        out: List[Tuple[int, float, Tuple[float, float, float, float]]] = []
        for row in boxes:
            if len(row) < 6:
                continue
            cid = int(row[0])
            score = float(row[1])
            if score < min_score:
                continue
            x1, y1, x2, y2 = (float(row[2]), float(row[3]), float(row[4]), float(row[5]))
            x1 = max(0.0, min(x1, ow - 1.0))
            y1 = max(0.0, min(y1, oh - 1.0))
            x2 = max(x1 + 1.0, min(x2, float(ow)))
            y2 = max(y1 + 1.0, min(y2, float(oh)))
            out.append((cid, score, (x1, y1, x2, y2)))
        return out


_LAYOUT: Optional[LayoutDetector] = None
_LAYOUT_LOCK = threading.Lock()


def get_layout_detector() -> LayoutDetector:
    global _LAYOUT
    if _LAYOUT is None:
        with _LAYOUT_LOCK:
            if _LAYOUT is None:
                _LAYOUT = LayoutDetector()
    return _LAYOUT


def _clamp_crop(bbox: Tuple[float, float, float, float], w: int, h: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    ix1 = max(0, int(round(x1)))
    iy1 = max(0, int(round(y1)))
    ix2 = min(w, int(round(x2)))
    iy2 = min(h, int(round(y2)))
    if ix2 <= ix1:
        ix2 = min(w, ix1 + 2)
    if iy2 <= iy1:
        iy2 = min(h, iy1 + 2)
    return ix1, iy1, ix2, iy2


def _pad_crop(box: Tuple[int, int, int, int], pad: int, w: int, h: int) -> Tuple[int, int, int, int]:
    """给裁切框加一点边距。

    版面框常常贴着字形边缘，直接裁会把笔画切掉（尤其分式的上下横线和积分号）。
    加 2–4px 余量能明显提升识别率。
    """
    if pad <= 0:
        return box
    x1, y1, x2, y2 = box
    return (max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad))


def extract_pdf_formulas(
    pdf_path: str,
    *,
    pages: Optional[Sequence[int]] = None,
    dpi: int = DEFAULT_DPI,
    out_dir: Optional[str] = None,
    min_score: float = DEFAULT_MIN_SCORE,
    max_pages: int = 0,
    recognizer=None,
    layout: Optional[LayoutDetector] = None,
    crop_pad: int = 3,
    on_page=None,
) -> PdfFormulaResult:
    """从 PDF 提取公式区域并识别为 LaTeX。

    参数
    ----
    pages:
        0 基页码列表；``None`` 表示从第一页开始（受 ``max_pages`` 限制）。
    out_dir:
        给了就把每个公式裁图存下来（便于人工复核）；不给则不落盘。
    min_score:
        版面检测置信度门槛。实测数学试卷公式框较多、置信度分布宽，
        0.5 能去掉大部分噪声又不漏真公式。
    max_pages:
        ``pages`` 为 None 时最多处理多少页（0=不限）。**扫描件一页约 2–4 秒**
        （版面 2s + 公式识别按数量），批量跑前先用小值试。
    crop_pad:
        裁切外扩像素。0 关闭。
    """
    t0 = time.time()
    res = PdfFormulaResult(source_path=pdf_path)
    if not pdf_path or not os.path.exists(pdf_path):
        res.error = "file_not_found"
        res.elapsed_seconds = time.time() - t0
        return res

    det = layout or get_layout_detector()
    if not det.available:
        res.error = f"layout_unavailable: {det.load_error}"
        res.elapsed_seconds = time.time() - t0
        return res
    rec = recognizer
    if rec is None:
        try:
            from services.formula_latex import get_recognizer

            rec = get_recognizer()
        except Exception as exc:  # noqa: BLE001
            res.error = f"recognizer_unavailable: {type(exc).__name__}: {exc}"
            res.elapsed_seconds = time.time() - t0
            return res
    if not rec.available:
        res.error = f"recognizer_unavailable: {rec.load_error}"
        res.elapsed_seconds = time.time() - t0
        return res
    res.engine_formula = getattr(rec, "engine_name", "")

    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # type: ignore

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:  # noqa: BLE001
        res.error = f"open_failed: {type(exc).__name__}: {exc}"
        res.elapsed_seconds = time.time() - t0
        return res

    try:
        res.total_pages = doc.page_count
        if pages is not None:
            targets = [p for p in pages if 0 <= p < doc.page_count]
        else:
            n = doc.page_count if max_pages <= 0 else min(doc.page_count, max_pages)
            targets = list(range(n))

        for pno in targets:
            pt0 = time.time()
            page = doc[pno]
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pw, ph = img.size
            pf = PdfPageFormulas(page_no=pno + 1, width=pw, height=ph)

            boxes = det.detect(img, min_score=min_score)
            counts: Dict[str, int] = {}
            for cid, _sc, _bb in boxes:
                name = LAYOUT_LABELS[cid] if 0 <= cid < len(LAYOUT_LABELS) else f"?{cid}"
                counts[name] = counts.get(name, 0) + 1
            pf.layout_counts = counts

            formula_boxes = [
                (cid, sc, bb) for cid, sc, bb in boxes
                if cid in FORMULA_CLASSES and sc >= min_score
            ]
            # 同一区域可能被重复检出（display 与 inline 各一次），按 bbox 去重
            seen: set = set()
            uniq: List[Tuple[int, float, Tuple[float, float, float, float]]] = []
            for cid, sc, bb in formula_boxes:
                key = (round(bb[0] / 4), round(bb[1] / 4), round(bb[2] / 4), round(bb[3] / 4))
                if key in seen:
                    continue
                seen.add(key)
                uniq.append((cid, sc, bb))

            for i, (cid, sc, bb) in enumerate(uniq):
                box = _clamp_crop(bb, pw, ph)
                box = _pad_crop(box, crop_pad, pw, ph)
                f = PdfFormula(
                    page_no=pno + 1,
                    label=LAYOUT_LABELS[cid] if 0 <= cid < len(LAYOUT_LABELS) else f"?{cid}",
                    bbox=bb,
                    score=sc,
                )
                try:
                    crop = img.crop(box)
                except Exception as exc:  # noqa: BLE001
                    f.reason = f"crop_failed: {type(exc).__name__}"
                    pf.formulas.append(f)
                    continue
                if out_dir:
                    try:
                        os.makedirs(out_dir, exist_ok=True)
                        cp = os.path.join(out_dir, f"p{pno + 1:04d}_f{i:03d}.png")
                        crop.save(cp)
                        f.crop_path = cp
                    except Exception:  # noqa: BLE001
                        pass
                # 直接吃内存里的裁图：一页可能上百个公式框，
                # 每个都写临时文件既慢又难清理。
                if hasattr(rec, "recognize_image"):
                    r = rec.recognize_image(crop, image_path=f.crop_path)
                else:
                    tmp = f.crop_path
                    if not tmp:
                        os.makedirs(out_dir or os.path.join(os.getcwd(), ".tmp_formula"), exist_ok=True)
                        tmp = os.path.join(out_dir or os.path.join(os.getcwd(), ".tmp_formula"),
                                           f"p{pno + 1:04d}_f{i:03d}.png")
                        crop.save(tmp)
                        f.crop_path = tmp
                    r = rec.recognize(tmp)
                f.ok = bool(r.ok)
                f.latex = r.latex or ""
                f.reason = r.reason or ""
                pf.formulas.append(f)

            pf.elapsed = time.time() - pt0
            res.pages.append(pf)
            if on_page:
                on_page(pf)
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass

    res.elapsed_seconds = time.time() - t0
    return res


def formulas_to_markdown(page: PdfPageFormulas, *, block_sep: str = "\n\n") -> str:
    """把一页的公式按阅读顺序（y 再 x）排成 Markdown 片段。

    **注意**：这是「公式清单」，不是「正文混排」。把公式精确插回正文
    需要文本块的 bbox 一起参与排序，属于下一阶段（见模块顶部说明）。
    当前函数的用途是：让人能快速看到一页有哪些公式、识别成了什么。
    """
    items = sorted(page.formulas, key=lambda f: (round(f.bbox[1] / 8), f.bbox[0]))
    lines: List[str] = []
    for f in items:
        if f.ok and f.latex:
            tex = f.latex if f.label == "display_formula" else f.latex
            lines.append(f"$${tex}$$" if f.label == "display_formula" else f"${tex}$")
        else:
            lines.append(f"[公式未识别: {f.reason or 'unknown'}]")
    return block_sep.join(lines)
