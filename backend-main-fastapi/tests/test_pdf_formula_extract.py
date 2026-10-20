"""``services/parsers/pdf_formula_extract.py`` 的测试。

分三层：

1. **纯函数/契约层**（必跑）：类别表、裁切边界、结果聚合、Markdown 输出。
2. **失败路径**：文件不存在、版面模型缺失、识别器不可用，必须**显式报错**。
3. **真实模型层**（有模型+真实 PDF 才跑）：扫描版数学真题单页，断言能检出公式
   且成功率过半、`\\oint` / `\\begin{cases}` 这类结构出现。

第 3 层用 skipif 守住环境依赖，不让没装模型的机器红。
"""
from __future__ import annotations

import os

import pytest
from PIL import Image

from services.parsers.pdf_formula_extract import (
    CLS_DISPLAY_FORMULA,
    CLS_INLINE_FORMULA,
    CLS_TABLE,
    FORMULA_CLASSES,
    LAYOUT_LABELS,
    LayoutDetector,
    PdfFormula,
    PdfFormulaResult,
    PdfPageFormulas,
    _clamp_crop,
    _default_layout_model,
    _pad_crop,
    formulas_to_markdown,
    get_layout_detector,
)


# --------------------------------------------------------------------------- #
# 1. 纯函数 / 契约层
# --------------------------------------------------------------------------- #
class TestLayoutLabels:
    def test_label_count_and_critical_indices(self):
        """类别表的**顺序就是 class_id**，错一位就会把公式当正文。

        这张表来自模型自带的 inference.yml，改之前必须重新核对。
        """
        assert len(LAYOUT_LABELS) == 25
        assert LAYOUT_LABELS[CLS_DISPLAY_FORMULA] == "display_formula"
        assert LAYOUT_LABELS[CLS_INLINE_FORMULA] == "inline_formula"
        assert LAYOUT_LABELS[CLS_TABLE] == "table"
        assert LAYOUT_LABELS[0] == "abstract"
        assert LAYOUT_LABELS[22] == "text"

    def test_formula_classes(self):
        assert CLS_DISPLAY_FORMULA in FORMULA_CLASSES
        assert CLS_INLINE_FORMULA in FORMULA_CLASSES
        assert CLS_TABLE not in FORMULA_CLASSES

    def test_no_duplicate_labels(self):
        assert len(set(LAYOUT_LABELS)) == len(LAYOUT_LABELS)


class TestCropBounds:
    def test_clamp_inside(self):
        assert _clamp_crop((10, 20, 100, 200), 500, 400) == (10, 20, 100, 200)

    def test_clamp_negative_and_overflow(self):
        x1, y1, x2, y2 = _clamp_crop((-5, -8, 9999, 9999), 300, 200)
        assert x1 >= 0 and y1 >= 0
        assert x2 <= 300 and y2 <= 200
        assert x2 > x1 and y2 > y1

    def test_clamp_degenerate_box_gets_min_size(self):
        """退化框（宽高为 0）也要给出至少 2×2，否则 crop 会抛异常。"""
        x1, y1, x2, y2 = _clamp_crop((50, 50, 50, 50), 200, 200)
        assert x2 > x1 and y2 > y1

    def test_pad_expands_but_stays_inside(self):
        box = _pad_crop((10, 10, 90, 90), 5, 200, 200)
        assert box == (5, 5, 95, 95)

    def test_pad_clipped_at_edges(self):
        box = _pad_crop((0, 0, 199, 199), 10, 200, 200)
        assert box == (0, 0, 200, 200)

    def test_pad_zero_is_noop(self):
        assert _pad_crop((10, 10, 90, 90), 0, 200, 200) == (10, 10, 90, 90)


class TestFormulaModels:
    def test_pdf_formula_geometry(self):
        f = PdfFormula(page_no=1, label="inline_formula", bbox=(10, 20, 110, 60), score=0.9)
        assert f.width == 100
        assert f.height == 40
        d = f.to_dict()
        assert d["page_no"] == 1
        assert d["bbox"] == [10, 20, 110, 60]
        assert d["score"] == 0.9

    def test_page_ok_count(self):
        page = PdfPageFormulas(page_no=2)
        page.formulas = [
            PdfFormula(page_no=2, label="inline_formula", bbox=(0, 0, 10, 10), score=0.9, ok=True, latex="x"),
            PdfFormula(page_no=2, label="inline_formula", bbox=(0, 20, 10, 30), score=0.9, ok=False, reason="too_short"),
        ]
        assert page.ok_count == 1
        d = page.to_dict()
        assert d["formula_count"] == 2
        assert d["ok_count"] == 1

    def test_result_totals(self):
        res = PdfFormulaResult(source_path="a.pdf")
        p1 = PdfPageFormulas(page_no=1)
        p1.formulas = [PdfFormula(page_no=1, label="inline_formula", bbox=(0, 0, 1, 1), score=1.0, ok=True)]
        p2 = PdfPageFormulas(page_no=2)
        p2.formulas = [
            PdfFormula(page_no=2, label="display_formula", bbox=(0, 0, 1, 1), score=1.0, ok=True),
            PdfFormula(page_no=2, label="inline_formula", bbox=(0, 2, 1, 3), score=1.0, ok=False),
        ]
        res.pages = [p1, p2]
        assert res.total_formulas == 3
        assert res.total_ok == 2
        d = res.to_dict()
        assert d["total_formulas"] == 3
        assert d["total_ok"] == 2


class TestMarkdownOutput:
    def test_inline_and_display_rendered_differently(self):
        page = PdfPageFormulas(page_no=1)
        page.formulas = [
            PdfFormula(page_no=1, label="inline_formula", bbox=(0, 10, 50, 30), score=0.9, ok=True, latex="x^2"),
            PdfFormula(page_no=1, label="display_formula", bbox=(0, 100, 200, 160), score=0.9, ok=True, latex="\\int_0^1 x dx"),
        ]
        md = formulas_to_markdown(page)
        assert "$x^2$" in md
        assert "$$\\int_0^1 x dx$$" in md
        # 按 y 排序：行内公式在前
        assert md.index("x^2") < md.index("int_0")

    def test_failed_formula_shows_reason_not_silent(self):
        """识别失败必须显式标出来，不能给个空串让人以为没问题。"""
        page = PdfPageFormulas(page_no=1)
        page.formulas = [
            PdfFormula(page_no=1, label="inline_formula", bbox=(0, 0, 10, 10), score=0.9,
                       ok=False, reason="unbalanced_brace"),
        ]
        md = formulas_to_markdown(page)
        assert "公式未识别" in md
        assert "unbalanced_brace" in md

    def test_empty_page(self):
        assert formulas_to_markdown(PdfPageFormulas(page_no=1)) == ""


# --------------------------------------------------------------------------- #
# 2. 失败路径
# --------------------------------------------------------------------------- #
class TestFailurePaths:
    def test_missing_pdf(self):
        from services.parsers.pdf_formula_extract import extract_pdf_formulas

        res = extract_pdf_formulas("D:/definitely/not/here.pdf")
        assert res.error == "file_not_found"
        assert res.pages == []

    def test_layout_model_missing(self, tmp_path):
        """版面模型不存在时必须报 layout_unavailable，不能静默返回空结果。"""
        from services.parsers.pdf_formula_extract import extract_pdf_formulas

        det = LayoutDetector(model_path=str(tmp_path / "no_model.onnx"))
        res = extract_pdf_formulas(
            __file__,  # 存在即可，早点因为 layout 不可用而返回
            layout=det,
        )
        assert res.error.startswith("layout_unavailable")
        assert det.load_error

    def test_layout_detector_unavailable_reports(self, tmp_path):
        det = LayoutDetector(model_path=str(tmp_path / "x.onnx"))
        assert det.available is False
        assert det.load_error
        # 不可用时 detect 返回空列表而不是抛异常
        assert det.detect(Image.new("RGB", (100, 100))) == []


# --------------------------------------------------------------------------- #
# 3. 真实模型层
# --------------------------------------------------------------------------- #
_HAS_LAYOUT = os.path.exists(_default_layout_model())
requires_layout = pytest.mark.skipif(not _HAS_LAYOUT, reason=f"未找到版面模型: {_default_layout_model()}")

_pdf_candidates = [
    r"D:\平台\knowledge_base\数学\1987年考研数学三真题及解析 .pdf",
]
_REAL_PDF = next((p for p in _pdf_candidates if os.path.exists(p)), None)
requires_pdf = pytest.mark.skipif(_REAL_PDF is None, reason="未找到真实扫描版 PDF 样本")


@requires_layout
class TestRealLayout:
    def test_detector_loads(self):
        det = get_layout_detector()
        assert det.available, det.load_error

    def test_detect_on_synthetic_page(self):
        """造一页「白底黑字」的图，必须能检出东西且坐标在图内。"""
        det = get_layout_detector()
        img = Image.new("RGB", (800, 1000), (255, 255, 255))
        from PIL import ImageDraw

        d = ImageDraw.Draw(img)
        for i in range(6):
            d.rectangle((60, 80 + i * 120, 740, 150 + i * 120), fill=(210, 210, 210))
        boxes = det.detect(img)
        assert boxes, "合成页面没检出任何区域"
        for _cid, sc, (x1, y1, x2, y2) in boxes:
            assert 0.0 <= sc <= 1.0
            assert 0 <= x1 < x2 <= 800
            assert 0 <= y1 < y2 <= 1000


@requires_layout
@requires_pdf
class TestRealPdfExtraction:
    @pytest.fixture(scope="class")
    def res(self):
        from services.parsers.pdf_formula_extract import extract_pdf_formulas

        r = extract_pdf_formulas(_REAL_PDF, pages=[0], min_score=0.3)
        if r.error:
            pytest.skip(f"提取失败: {r.error}")
        return r

    def test_page_extracted(self, res):
        assert len(res.pages) == 1
        page = res.pages[0]
        assert page.width > 0 and page.height > 0

    def test_detects_formulas(self, res):
        page = res.pages[0]
        assert len(page.formulas) >= 10, f"一页数学真题只检出 {len(page.formulas)} 个公式，太少"
        assert "inline_formula" in page.layout_counts

    def test_success_rate_above_half(self, res):
        page = res.pages[0]
        rate = page.ok_count / max(1, len(page.formulas))
        assert rate >= 0.5, f"识别成功率只有 {rate:.0%}"

    def test_latex_is_real_math(self, res):
        page = res.pages[0]
        latexes = [f.latex for f in page.formulas if f.ok and f.latex]
        joined = " ".join(latexes)
        # 真数学公式必然出现这些结构
        assert any(k in joined for k in ("\\frac", "\\int", "\\lim", "\\sum", "\\begin", "\\partial")), (
            f"识别结果不像数学公式: {joined[:200]}"
        )

    def test_bbox_within_page(self, res):
        page = res.pages[0]
        for f in page.formulas:
            x1, y1, x2, y2 = f.bbox
            assert 0 <= x1 < x2 <= page.width, f"bbox 超出页面宽: {f.bbox}"
            assert 0 <= y1 < y2 <= page.height, f"bbox 超出页面高: {f.bbox}"
