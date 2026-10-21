"""``services/parsers/pdf_page_compose.py`` 的测试。

三层：

1. **纯函数层**（必跑）：阅读顺序、OCR 行骨架组装、公式内联、双栏判定、渲染。
2. **失败路径**：文件不存在、页面越界、版面模型缺失。
3. **真实模型层**（有模型+真实扫描件才跑）：断言混排结果里
   「文字与公式交替」而不是「公式全堆在前面」。

第 3 层的关键断言来自实测教训：第一版用 Layout 大框做骨架时，
输出是「两个公式在前，一整段文字挤在最后」——语序完全错乱。
改用 OCR 行骨架后才正确，所以这里必须有断言守住。
"""
from __future__ import annotations

import os

import pytest

from services.parsers.pdf_page_compose import (
    COLUMN_GAP_RATIO,
    ROW_TOLERANCE,
    PageComposeResult,
    PageElement,
    _looks_multi_column,
    _overlaps_x,
    assign_reading_order,
    _compose_by_ocr_lines,
    compose_page_text,
)
from services.parsers.pdf_formula_extract import _default_layout_model


# --------------------------------------------------------------------------- #
# 1. 纯函数层
# --------------------------------------------------------------------------- #
def _el(kind: str, bbox, text: str = "", latex: str = "", ok: bool = True) -> PageElement:
    return PageElement(kind=kind, bbox=tuple(bbox), text=text, latex=latex, ok=ok)


class TestPageElementRender:
    def test_inline_formula_uses_single_dollar(self):
        e = _el("formula", (0, 0, 10, 10), latex="x^2")
        assert e.render() == "$x^2$"

    def test_display_formula_uses_double_dollar(self):
        e = _el("display_formula", (0, 0, 10, 30), latex="\\int_0^1 x dx")
        assert e.render() == "$$\\int_0^1 x dx$$"

    def test_failed_formula_shows_reason_not_empty(self):
        """识别失败必须显式标出来——留空等于又一次把公式弄丢。"""
        e = _el("formula", (0, 0, 10, 10), ok=False, latex="")
        e.reason = "unbalanced_brace"
        out = e.render()
        assert "公式" in out
        assert "unbalanced_brace" in out

    def test_text_element_returns_text(self):
        assert _el("text", (0, 0, 10, 10), text="设函数").render() == "设函数"

    def test_table_marker(self):
        assert "表格" in _el("table", (0, 0, 10, 10)).render()

    def test_geometry_helpers(self):
        e = _el("text", (10, 20, 110, 60))
        assert e.y_center == 40
        assert e.height == 40


class TestOverlapsX:
    def test_clearly_overlapping(self):
        # 重叠 60px，超过较窄者(100px)的一半 → 视为同一层
        assert _overlaps_x((0, 0, 100, 10), (20, 20, 120, 30)) is True

    def test_exactly_half_overlap_counts_as_not_overlapping(self):
        """正好一半不算「实质重叠」——这种并排排布应该能进同一行。"""
        assert _overlaps_x((0, 0, 100, 10), (50, 0, 150, 10)) is False

    def test_adjacent_not_overlapping(self):
        assert _overlaps_x((0, 0, 100, 10), (100, 0, 200, 10)) is False

    def test_contained(self):
        assert _overlaps_x((0, 0, 200, 10), (50, 0, 60, 10)) is True


class TestReadingOrder:
    def test_same_row_sorted_by_x(self):
        els = [
            _el("text", (200, 0, 300, 20), text="右"),
            _el("text", (0, 0, 100, 20), text="左"),
        ]
        out = assign_reading_order(els)
        assert [e.text for e in out] == ["左", "右"]
        assert [e.order for e in out] == [0, 1]

    def test_different_rows_sorted_by_y(self):
        els = [
            _el("text", (0, 100, 100, 120), text="下"),
            _el("text", (0, 0, 100, 20), text="上"),
        ]
        out = assign_reading_order(els)
        assert [e.text for e in out] == ["上", "下"]

    def test_overlapping_x_forces_new_row(self):
        """x 重叠说明是上下层（如正文与页眉），不能并进同一行。"""
        els = [
            _el("text", (0, 0, 300, 20), text="A"),
            _el("text", (0, 5, 300, 25), text="B"),
        ]
        out = assign_reading_order(els)
        # 两个都占了整行宽，必须分成两行
        assert out[0].order == 0 and out[1].order == 1

    def test_empty_input(self):
        assert assign_reading_order([]) == []

    def test_order_is_contiguous(self):
        els = [_el("text", (i * 10, 0, i * 10 + 5, 20), text=str(i)) for i in range(5)]
        out = assign_reading_order(els)
        assert [e.order for e in out] == [0, 1, 2, 3, 4]


class TestMultiColumnHint:
    def test_single_column_not_flagged(self):
        els = [_el("text", (50, i * 50, 800, i * 50 + 40)) for i in range(8)]
        assert _looks_multi_column(els, 1000) is False

    def test_two_columns_flagged(self):
        els = [_el("text", (50, i * 50, 400, i * 50 + 40)) for i in range(4)]
        els += [_el("text", (600, i * 50, 950, i * 50 + 40)) for i in range(4)]
        assert _looks_multi_column(els, 1000) is True

    def test_too_few_elements_not_flagged(self):
        els = [_el("text", (0, 0, 10, 10)), _el("text", (900, 0, 1000, 10))]
        assert _looks_multi_column(els, 1000) is False


class TestComposeByOcrLines:
    def test_formula_inserted_between_text_on_same_line(self):
        """核心行为：行内公式要嵌在文字中间，不能甩到行首/行尾。"""
        blocks = [
            ("与两直线", (0, 100, 100, 130), 0.9),
            ("都平行", (300, 100, 380, 130), 0.9),
        ]
        formulas = [_el("formula", (150, 105, 280, 125), latex="\\frac{x+1}{1}")]
        lines = _compose_by_ocr_lines(blocks, formulas)
        assert len(lines) == 1
        line = lines[0]
        assert line.startswith("与两直线")
        assert "$\\frac{x+1}{1}$" in line
        assert line.index("与两直线") < line.index("\\frac") < line.index("都平行")

    def test_ocr_text_inside_formula_box_is_dropped(self):
        """OCR 会把公式区域也当文字识别，必须丢掉，否则同一处出两遍。"""
        blocks = [
            ("题干文字", (0, 100, 120, 130), 0.9),
            ("x=1x+1y+2z-l", (150, 100, 400, 130), 0.9),  # 落在公式框内
        ]
        formulas = [_el("formula", (150, 100, 400, 130), latex="x=1")]
        lines = _compose_by_ocr_lines(blocks, formulas)
        joined = "\n".join(lines)
        assert "题干文字" in joined
        assert "x=1x+1y+2z-l" not in joined, "公式框内的 OCR 乱码没被丢掉"
        assert "$x=1$" in joined

    def test_orphan_formula_still_appears(self):
        """没归属到任何行的公式不能静默消失。"""
        blocks = [("文字", (0, 0, 100, 20), 0.9)]
        formulas = [_el("formula", (0, 800, 100, 820), latex="y=0")]
        lines = _compose_by_ocr_lines(blocks, formulas)
        assert any("y=0" in ln for ln in lines)

    def test_display_formula_kept_as_block(self):
        blocks = [("解法如下", (0, 0, 100, 20), 0.9)]
        formulas = [_el("display_formula", (0, 30, 300, 90), latex="\\int_0^1 x dx")]
        lines = _compose_by_ocr_lines(blocks, formulas)
        joined = "\n".join(lines)
        assert "$$\\int_0^1 x dx$$" in joined

    def test_empty_inputs(self):
        assert _compose_by_ocr_lines([], []) == []

    def test_only_formulas(self):
        formulas = [_el("formula", (0, 0, 50, 20), latex="a")]
        assert _compose_by_ocr_lines([], formulas) == ["$a$"]

    def test_rows_sorted_top_to_bottom(self):
        blocks = [("下", (0, 200, 50, 220), 0.9), ("上", (0, 0, 50, 20), 0.9)]
        lines = _compose_by_ocr_lines(blocks, [])
        assert lines[0] == "上"
        assert lines[1] == "下"


class TestResultAggregates:
    def test_counts(self):
        r = PageComposeResult(page_no=1)
        r.elements = [
            _el("formula", (0, 0, 1, 1), latex="a"),
            _el("formula", (0, 2, 1, 3), ok=False),
            _el("text", (0, 4, 1, 5), text="字"),
        ]
        assert r.formula_count == 2
        assert r.formula_ok == 1
        d = r.to_dict()
        assert d["formula_count"] == 2
        assert d["formula_ok"] == 1


# --------------------------------------------------------------------------- #
# 2. 失败路径
# --------------------------------------------------------------------------- #
class TestFailurePaths:
    def test_missing_pdf(self):
        r = compose_page_text("D:/definitely/not/here.pdf", 0)
        assert r.error == "file_not_found"
        assert r.text == ""

    def test_page_out_of_range(self):
        r = compose_page_text(__file__, 9999)  # 不是 PDF，会先报 open_failed
        assert r.error

    def test_layout_unavailable(self, tmp_path):
        from services.parsers.pdf_formula_extract import LayoutDetector

        det = LayoutDetector(model_path=str(tmp_path / "x.onnx"))
        r = compose_page_text(__file__, 0, layout=det)
        assert r.error.startswith("layout_unavailable")


# --------------------------------------------------------------------------- #
# 3. 真实模型层
# --------------------------------------------------------------------------- #
_HAS_LAYOUT = os.path.exists(_default_layout_model())
_pdf_candidates = [r"D:\平台\knowledge_base\数学\1987年考研数学三真题及解析 .pdf"]
_REAL_PDF = next((p for p in _pdf_candidates if os.path.exists(p)), None)

requires_real = pytest.mark.skipif(
    not (_HAS_LAYOUT and _REAL_PDF),
    reason="需要版面模型与真实扫描版 PDF",
)


@requires_real
class TestRealCompose:
    @pytest.fixture(scope="class")
    def res(self):
        r = compose_page_text(_REAL_PDF, 0, max_formulas=12)
        if r.error:
            pytest.skip(f"混排失败: {r.error}")
        return r

    def test_text_not_empty(self, res):
        assert len(res.text) > 100, "混排文本过短，说明文字部分丢了"

    def test_has_both_text_and_formula(self, res):
        assert res.formula_count >= 5
        # 文本里必须同时有中文和 LaTeX
        assert any("\u4e00" <= ch <= "\u9fff" for ch in res.text)
        assert "$" in res.text

    def test_skeleton_is_ocr_lines(self, res):
        """扫描件必须走 OCR 行骨架；用 Layout 大框会语序错乱。"""
        assert res.meta.get("compose_skeleton") == "ocr_lines"
        assert res.meta.get("ocr_blocks", 0) > 0

    def test_formula_not_all_dumped_at_start(self, res):
        """回归：第一版输出是「公式全在前、文字挤最后」，语序完全错。

        判断方法：文本里**第一个中文字符**的位置不应晚于**第一个 $**。
        """
        first_cjk = next((i for i, ch in enumerate(res.text) if "\u4e00" <= ch <= "\u9fff"), -1)
        first_tex = res.text.find("$")
        assert first_cjk >= 0 and first_tex >= 0
        assert first_cjk < first_tex, "输出仍是「公式全在前面」，语序没修好"

    def test_inline_formula_shares_line_with_text(self, res):
        """至少有一行是「文字 + 公式 + 文字」混排，而不是纯公式行。"""
        mixed = 0
        for line in res.text.splitlines():
            has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in line)
            has_tex = "$" in line
            if has_cjk and has_tex:
                mixed += 1
        assert mixed >= 1, "没有任何一行是文字与公式混排的"
