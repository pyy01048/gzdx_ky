"""页眉/页脚/页码识别 + 水印图剔除的单测。

真实数据上的依据（knowledge_base 里实测）：
- 考研讲义每页页脚有机构 logo（247×46 px）和页码；
- 每页正中盖一个机构水印（同一张图、同一位置）；
- 页眉是「公众号：xxx」「B 站UP:xxx」这类每页重复的短句。

不处理的话，每页都会凭空多出"配图"，题目配图绑定必然错位。
"""
from __future__ import annotations

import pytest

from services.parsers.base import (
    BLOCK_FIGURE,
    BLOCK_FOOTER,
    BLOCK_HEADER,
    BLOCK_PAGE_NO,
    BLOCK_TEXT,
)
from services.parsers.pymupdf_parser import PyMuPDFParser

PAGE_W, PAGE_H = 595.0, 842.0


def _png(tmp_path, name: str = "wm.png", size=(60, 60), color=(200, 30, 30)) -> str:
    """造一张小 PNG（Pillow 在主环境里有）。"""
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / name
    Image.new("RGB", size, color).save(str(path))
    return str(path)


# --------------------------------------------------------------------------- #
# 页眉 / 页脚 / 页码
# --------------------------------------------------------------------------- #
@pytest.fixture()
def running_text_pdf(tmp_path):
    """3 页：每页顶部同一句页眉、底部页码，正文各不相同。"""
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "running.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_text((90, 60), "B station UP: someone", fontsize=9)
        page.insert_text((90, 700), f"body paragraph on page {i + 1} " * 3, fontsize=10)
        page.insert_text((300, 800), str(i + 1), fontsize=10)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_repeated_top_text_becomes_header(running_text_pdf, tmp_path):
    result = PyMuPDFParser().parse(running_text_pdf, out_dir=str(tmp_path / "out"))
    headers = [b for b in result.blocks if b.block_type == BLOCK_HEADER]
    assert headers, "跨页重复的顶部短句应判为页眉"
    assert all("B station" in b.text for b in headers)


def test_page_number_is_marked(running_text_pdf, tmp_path):
    result = PyMuPDFParser().parse(running_text_pdf, out_dir=str(tmp_path / "out"))
    numbers = [b for b in result.blocks if b.block_type == BLOCK_PAGE_NO]
    assert len(numbers) == 3
    assert sorted(b.text for b in numbers) == ["1", "2", "3"]


def test_header_and_page_number_are_not_body(running_text_pdf, tmp_path):
    result = PyMuPDFParser().parse(running_text_pdf, out_dir=str(tmp_path / "out"))
    body = result.pages[0].body_blocks
    texts = [b.text for b in body]
    assert not any("B station" in t for t in texts)
    assert not any(t.strip() in ("1", "2", "3") for t in texts)


def test_page_text_excludes_page_number(running_text_pdf, tmp_path):
    result = PyMuPDFParser().parse(running_text_pdf, out_dir=str(tmp_path / "out"))
    tail = result.pages[0].text.strip().splitlines()[-1].strip()
    assert tail not in ("1", "2", "3")


def test_one_off_top_text_stays_body_text(tmp_path):
    """只出现一次的顶部短句可能是正文首行，不能当页眉删掉。"""
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "oneoff.pdf"
    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_text((90, 60), f"unique line {i}", fontsize=9)
        page.insert_text((90, 400), "real body", fontsize=10)
    doc.save(str(path))
    doc.close()

    result = PyMuPDFParser().parse(str(path), out_dir=str(tmp_path / "out"))
    assert not [b for b in result.blocks if b.block_type == BLOCK_HEADER]
    assert any(b.block_type == BLOCK_TEXT for b in result.blocks)


# --------------------------------------------------------------------------- #
# 页边带 / 水印图
# --------------------------------------------------------------------------- #
@pytest.fixture()
def figure_pdf(tmp_path):
    """3 页：正文里一张真图（每页位置不同）+ 页脚一个 logo + 一个每页同位置的水印图。"""
    pymupdf = pytest.importorskip("pymupdf")
    logo = _png(tmp_path, "logo.png", (60, 30), (20, 20, 20))
    watermark = _png(tmp_path, "wm.png", (120, 120), (200, 30, 30))
    path = tmp_path / "figs.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        # 真图：每页位置都不一样（教材里同一幅图被多题引用也是不同位置）
        page.insert_image(pymupdf.Rect(90, 300 + i * 30, 290, 480 + i * 30), filename=logo)
        # 页脚 logo（落在页脚带里）
        page.insert_image(pymupdf.Rect(60, 790, 200, 815), filename=logo)
        # 水印：同一张图、同一位置，每页都有
        page.insert_image(pymupdf.Rect(400, 100, 520, 220), filename=watermark)
        page.insert_text((90, 600), f"question {i + 1}", fontsize=10)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_margin_decoration_is_not_a_figure(figure_pdf, tmp_path):
    result = PyMuPDFParser().parse(figure_pdf, out_dir=str(tmp_path / "out"))
    for fig in result.figure_blocks():
        y0, y1 = fig.bbox[1], fig.bbox[3]
        assert not (y0 >= PAGE_H * 0.92), f"页脚带的装饰图不该当配图: {fig.bbox}"


def test_watermark_repeated_at_same_place_is_dropped(figure_pdf, tmp_path):
    result = PyMuPDFParser().parse(figure_pdf, out_dir=str(tmp_path / "out"))
    assert result.meta["watermark_figures_dropped"] == 3
    # 水印位置（400,100)-(520,220) 的图块不该留下
    for fig in result.figure_blocks():
        assert not (fig.bbox[0] >= 390 and fig.bbox[2] <= 530 and fig.bbox[1] <= 110)


def test_real_figures_are_kept(figure_pdf, tmp_path):
    result = PyMuPDFParser().parse(figure_pdf, out_dir=str(tmp_path / "out"))
    figures = result.figure_blocks()
    assert len(figures) == 3, f"3 张正文图应保留，实际 {len(figures)}"
    assert all(f.block_type == BLOCK_FIGURE for f in figures)


def test_orphan_images_are_cleaned(figure_pdf, tmp_path):
    import os

    out = str(tmp_path / "out")
    result = PyMuPDFParser().parse(figure_pdf, out_dir=out)
    files = set(os.listdir(os.path.join(out, "images")))
    referenced = {os.path.basename(b.image_path) for b in result.blocks if b.image_path}
    assert files == referenced, "产物目录里不该留下没人引用的图片"
