"""扫描版兜底解析器：pypdfium2 渲染 300 DPI PNG → 复用 ``services/ocr_router.py``。

定位（doc §4.4）：RapidOCR 适合纯文字扫描页、封面目录、MinerU 失败时的降级；
不适合复杂表格/公式/电路图。所以它是**兜底**，不是主力。

为什么不自己再写一套 OCR 客户端：仓库里已经有 ``OCRRouter``（local-gpu →
paddleocr → rapidocr 三级降级链，带可用性探测和失败原因留痕），这里直接复用，
避免两套 OCR 逻辑各自漂移。

惰性 import：``pypdfium2`` / ``ocr_router`` 都放在函数内部，模块顶层只留纯
Python 逻辑 —— 没装这些依赖的环境也要能 import 本模块。
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.parsers.base import (
    BLOCK_TEXT,
    PDF_KIND_SCANNED,
    ParseResult,
    ParsedBlock,
    ParsedPage,
)

logger = logging.getLogger(__name__)

#: 渲染 DPI（doc §4.5 要求 300 DPI 裁图/渲染）
DEFAULT_DPI = 300
#: OCR 引擎名（写进 ParsedPage.ocr_engine）
ENGINE_NAME = "rapidocr"


def _box_to_bbox(box: Any) -> Optional[Tuple[float, float, float, float]]:
    """把 OCR 的 4 点框转成 (x0,y0,x1,y1)。"""
    if not box:
        return None
    points = []
    if isinstance(box, (list, tuple)):
        for point in box:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                try:
                    points.append((float(point[0]), float(point[1])))
                except (TypeError, ValueError):
                    continue
            elif isinstance(point, dict) and "x" in point and "y" in point:
                try:
                    points.append((float(point["x"]), float(point["y"])))
                except (TypeError, ValueError):
                    continue
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def ocr_result_to_blocks(result: Any, page_no: int) -> List[ParsedBlock]:
    """把 ``OCRResult`` 转成 ``ParsedBlock`` 列表（纯函数，便于单测）。

    OCR 后端有的只回文本不回框（``RapidOCRBackend`` 就是），这时把文本按行拆成
    块、bbox 留空 —— 下游仍能拿到文字，只是拿不到精确位置。

    **数学公式不可信标记（2026-10-20）**
    ---------------------------------
    数学类 PDF 全部是纯扫描件，RapidOCR 在公式上会**读错**（``x``→``α``、
    ``-``→汉字「一」、``f(x)``→``fLg(）``）。所以这里**不把 OCR 文本当权威内容**：
    一律用 ``services.ocr_math_guard`` 判一遍，把结果写进 ``ParsedBlock.extra``：

    * ``math_corrupted=True`` —— 公式结构已坏（强信号），下游必须重解析；
    * ``math_suspect=True`` —— 疑似损坏（弱信号），下游建议复核；
    * ``ocr_confidence_missing=True`` —— 后端没给逐行置信度（如 rapidocr 只回文本），
      文本可信度未知，下游不得当权威。

    置信度本身照常带上（``ParsedBlock.confidence``）；拿不到时保持 ``None``
    并用上面的标记显式说明「缺」，而不是留个空白让人误以为是 1.0。
    """
    from services.ocr_math_guard import detect_math_corruption

    blocks: List[ParsedBlock] = []
    raw_blocks = list(getattr(result, "blocks", None) or [])
    for i, b in enumerate(raw_blocks):
        text = str(getattr(b, "text", "") or "").strip()
        if not text:
            continue
        score = getattr(b, "score", None)
        try:
            confidence = float(score) if score is not None else None
        except (TypeError, ValueError):
            confidence = None
        extra = detect_math_corruption(text).to_extra()
        if confidence is None:
            extra["ocr_confidence_missing"] = True
        blocks.append(
            ParsedBlock(
                page_no=page_no,
                block_type=BLOCK_TEXT,
                text=text,
                bbox=_box_to_bbox(getattr(b, "box", None)),
                block_id=f"p{page_no}-ocr{i}",
                reading_order=i,
                confidence=confidence,
                extra=extra,
            )
        )
    if blocks:
        return blocks

    text = str(getattr(result, "text", "") or "").strip()
    if not text:
        return []
    for i, line in enumerate(t for t in text.splitlines() if t.strip()):
        stripped = line.strip()
        extra = detect_math_corruption(stripped).to_extra()
        # 只回文本的后端（rapidocr）拿不到逐行置信度 → 显式标记「缺」
        extra["ocr_confidence_missing"] = True
        blocks.append(
            ParsedBlock(
                page_no=page_no,
                block_type=BLOCK_TEXT,
                text=stripped,
                block_id=f"p{page_no}-ocr{i}",
                reading_order=i,
                confidence=None,
                extra=extra,
            )
        )
    return blocks


class RapidOCRParser:
    """扫描版兜底解析器。"""

    name = "rapidocr"

    def __init__(self, dpi: int = DEFAULT_DPI, prefer: str = "auto"):
        self.dpi = int(dpi)
        self.prefer = prefer

    # -- 可用性 ----------------------------------------------------------- #
    def available(self) -> bool:
        try:
            import pypdfium2  # noqa: F401  # 只为确认依赖在
        except Exception:  # noqa: BLE001
            return False
        try:
            from services.ocr_router import get_ocr_router

            router = get_ocr_router(prefer=self.prefer)
            return any(router.is_available(name) for name in ("rapidocr", "paddleocr", "local-gpu"))
        except Exception:  # noqa: BLE001
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
        import pypdfium2 as pdfium

        from services.ocr_router import get_ocr_router

        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

        real_out = os.path.abspath(out_dir) if out_dir else tempfile.mkdtemp(prefix="kaoyan_rapidocr_")
        pages_dir = os.path.join(real_out, "pages")
        os.makedirs(pages_dir, exist_ok=True)

        router = get_ocr_router(prefer=self.prefer)
        doc = pdfium.PdfDocument(pdf_path)
        try:
            total = len(doc)
            indices = _resolve_indices(total, max_pages, page_numbers)
            pages: List[ParsedPage] = []
            errors: List[Dict[str, Any]] = []
            for idx in indices:
                page, error = self._parse_page(doc, idx, pages_dir, router)
                pages.append(page)
                if error:
                    errors.append(error)
        finally:
            try:
                doc.close()
            except Exception:  # noqa: BLE001
                pass

        return ParseResult(
            pages=pages,
            engine=self.name,
            pdf_kind=PDF_KIND_SCANNED,
            source_path=os.path.abspath(pdf_path),
            total_pages=total,
            elapsed_seconds=time.perf_counter() - t0,
            meta={
                "out_dir": real_out,
                "pages_dir": os.path.relpath(pages_dir, real_out).replace(os.sep, "/"),
                "dpi": self.dpi,
                "parsed_pages": [p.page_no for p in pages],
                "errors": errors,
            },
        )

    # -- 单页 ------------------------------------------------------------- #
    def _parse_page(self, doc, idx: int, pages_dir: str, router):
        page_no = idx + 1
        pdf_page = doc[idx]
        try:
            scale = self.dpi / 72.0
            bitmap = pdf_page.render(scale=scale)
            image = bitmap.to_pil()
            png_path = os.path.join(pages_dir, f"p{page_no:04d}.png")
            image.save(png_path)
            width = float(pdf_page.get_width()) * scale
            height = float(pdf_page.get_height()) * scale
        except Exception as exc:  # noqa: BLE001
            logger.warning("渲染第 %s 页失败: %s", page_no, exc)
            return (
                ParsedPage(page_no=page_no),
                {"page_no": page_no, "error": f"渲染失败: {exc}"},
            )
        finally:
            try:
                pdf_page.close()
            except Exception:  # noqa: BLE001
                pass

        result = router.recognize_file(png_path)
        blocks = ocr_result_to_blocks(result, page_no)
        confidences = [b.confidence for b in blocks if b.confidence is not None]
        ocr_confidence = sum(confidences) / len(confidences) if confidences else None
        text = str(getattr(result, "text", "") or "").strip()
        if not text:
            text = "\n".join(b.text for b in blocks if b.text)

        page = ParsedPage(
            page_no=page_no,
            width=width,
            height=height,
            text=text,
            image_path=os.path.relpath(png_path, os.path.dirname(pages_dir)).replace(os.sep, "/"),
            ocr_engine=str(getattr(result, "engine", "") or ENGINE_NAME),
            ocr_confidence=ocr_confidence,
            blocks=blocks,
        )
        error = getattr(result, "error", None)
        return page, ({"page_no": page_no, "error": str(error)} if error else None)


def _resolve_indices(
    total_pages: int, max_pages: Optional[int], page_numbers: Optional[Sequence[int]]
) -> List[int]:
    """要处理的 0 基页索引。``page_numbers`` 是 1 基页码，优先于 ``max_pages``。"""
    total = int(total_pages)
    if page_numbers is not None:
        picked = sorted({int(p) for p in page_numbers if 1 <= int(p) <= total})
        return [p - 1 for p in picked]
    if max_pages is not None and int(max_pages) > 0:
        return list(range(min(total, int(max_pages))))
    return list(range(total))
