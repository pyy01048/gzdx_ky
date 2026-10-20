"""PyMuPDF 解析器的图元过滤单测：装饰性小块要丢，真正的图要留。

核心痛点：``page.get_drawings()`` 会把一张图拆成上百条 path，还会把分隔线、
页边框、表格线也一并返回。不做尺寸过滤的话，题目配图会全是线条噪声。

前两个用例是纯函数（不依赖 PyMuPDF）；后两个用 PyMuPDF 现场生成 PDF，
不依赖 knowledge_base 里的用户数据。
"""
from __future__ import annotations

import pytest

from services.parsers.pymupdf_parser import (
    MIN_FIGURE_SIDE,
    filter_figure_regions,
    merge_rects,
)


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #
def test_small_vector_blocks_are_dropped():
    rects = [
        (0, 0, 10, 10),      # 小图标
        (0, 0, 300, 12),     # 分隔线（高度不足）
        (0, 0, 12, 300),     # 分隔线（宽度不足）
        (100, 100, 400, 320),  # 真图
    ]
    kept = filter_figure_regions(rects)
    assert kept == [(100, 100, 400, 320)]


def test_exactly_min_side_is_kept():
    rects = [(0, 0, MIN_FIGURE_SIDE, MIN_FIGURE_SIDE)]
    assert filter_figure_regions(rects) == rects


def test_merged_neighbour_paths_become_one_figure():
    """一条图被拆成 4 段相邻 path → 合并后仍是一张够大的图。"""
    rects = [
        (100, 100, 200, 200),
        (200, 100, 300, 200),
        (100, 200, 200, 300),
        (200, 200, 300, 300),
    ]
    merged = merge_rects(rects)
    assert len(merged) == 1
    assert merged[0] == (100, 100, 300, 300)
    assert filter_figure_regions(merged) == [(100, 100, 300, 300)]


def test_distant_paths_are_not_merged():
    merged = merge_rects([(0, 0, 50, 50), (400, 400, 500, 500)])
    assert len(merged) == 2


def test_full_page_region_is_dropped():
    """占满整页的区域是页边框/底纹，不是配图。"""
    rects = [(0, 0, 595, 842)]
    assert filter_figure_regions(rects, page_area=595 * 842) == []


# --------------------------------------------------------------------------- #
# 真 PDF（现场生成，不碰用户数据）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def sample_pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Chapter One Circuit Analysis", fontsize=24)
    page.insert_text((72, 140), "body text for the paragraph", fontsize=10)
    # 一块够大的矢量图
    page.draw_rect(pymupdf.Rect(100, 200, 400, 500), color=(0, 0, 0), width=2)
    # 一条装饰性分隔线（高度远小于 40）
    page.draw_line((50, 600), (545, 600), color=(0, 0, 0), width=1)
    doc.new_page(width=595, height=842)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_parse_extracts_figure_and_skips_decoration(sample_pdf, tmp_path):
    from services.parsers.pymupdf_parser import PyMuPDFParser

    result = PyMuPDFParser().parse(sample_pdf, out_dir=str(tmp_path / "out"))
    assert result.engine == "pymupdf"
    assert result.total_pages == 2
    assert len(result.pages) == 2

    figures = result.figure_blocks()
    assert len(figures) == 1, "只应保留那一块大矢量图，分隔线必须被丢掉"
    assert figures[0].bbox is not None
    width = figures[0].bbox[2] - figures[0].bbox[0]
    height = figures[0].bbox[3] - figures[0].bbox[1]
    assert width >= MIN_FIGURE_SIDE and height >= MIN_FIGURE_SIDE

    # 图片落盘，且存的是相对 out_dir 的相对路径
    assert figures[0].image_path.startswith("images/")
    assert not figures[0].image_path.startswith("/")
    import os

    assert os.path.isfile(os.path.join(result.meta["out_dir"], figures[0].image_path))


def test_parse_marks_big_font_as_title(sample_pdf, tmp_path):
    from services.parsers.base import BLOCK_TITLE
    from services.parsers.pymupdf_parser import PyMuPDFParser

    result = PyMuPDFParser().parse(sample_pdf, out_dir=str(tmp_path / "out"))
    types = [b.block_type for b in result.pages[0].blocks]
    assert BLOCK_TITLE in types, "24 号字的标题应被判为 title"


def test_parse_can_limit_pages(sample_pdf, tmp_path):
    from services.parsers.pymupdf_parser import PyMuPDFParser

    result = PyMuPDFParser().parse(sample_pdf, max_pages=1, out_dir=str(tmp_path / "out"))
    assert [p.page_no for p in result.pages] == [1]
