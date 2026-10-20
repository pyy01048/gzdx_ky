"""MinerU ``content_list.json`` → ``ParsedPage`` 的转换单测。

不需要装 MinerU：转换逻辑是纯函数（``content_list_to_pages``），
喂一份假的 content_list 即可。
"""
from __future__ import annotations

import json

import pytest

from services.parsers.base import (
    BLOCK_FIGURE,
    BLOCK_FORMULA,
    BLOCK_TABLE,
    BLOCK_TEXT,
    BLOCK_TITLE,
)
from services.parsers.mineru_parser import content_list_to_pages


@pytest.fixture()
def fake_content_list():
    """一份覆盖各种字段形态的 content_list。

    - ``page_idx`` 是 0 基 → 页码必须 +1
    - bbox 有像素形态和 0-1 归一化形态两种
    - 图片块带 ``img_path``（相对输出目录）
    - 公式块带 ``text``
    - 表格块带 ``table_body``
    - 标题块带 ``text_level``
    """
    return [
        {
            "type": "text",
            "page_idx": 0,
            "bbox": [72, 100, 520, 160],
            "text": "第一章 电路分析",
            "page_size": [595, 842],
        },
        {
            "type": "text",
            "page_idx": 0,
            "bbox": [72, 180, 520, 260],
            "text": "设则（ ），求等效电阻。",
            "page_size": [595, 842],
        },
        {
            "type": "image",
            "page_idx": 0,
            "bbox": [0.1, 0.2, 0.5, 0.6],
            "img_path": "images/fig1.png",
            "page_size": [595, 842],
        },
        {
            "type": "equation",
            "page_idx": 0,
            "bbox": [72, 300, 300, 340],
            "text": "E=mc^2",
            "page_size": [595, 842],
        },
        {
            "type": "table",
            "page_idx": 0,
            "bbox": [72, 400, 520, 500],
            "table_body": "| R | I |\n|---|---|\n| 1 | 2 |",
            "page_size": [595, 842],
        },
        {
            "type": "title",
            "page_no": 2,  # 1 基页码字段
            "bbox": [72, 90, 520, 130],
            "text": "第二章 动态电路",
            "text_level": 1,
            "page_size": [595, 842],
        },
    ]


@pytest.fixture()
def mineru_out(tmp_path):
    """模拟 MinerU 输出目录（含一张被引用的图片）。"""
    images = tmp_path / "images"
    images.mkdir(parents=True, exist_ok=True)
    (images / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return tmp_path


def test_page_numbers_are_one_based(fake_content_list, mineru_out):
    pages = content_list_to_pages(fake_content_list, str(mineru_out))
    assert [p.page_no for p in pages] == [1, 2]
    # 第 1 页的块 page_no 全是 1（page_idx=0 → +1）
    assert all(b.page_no == 1 for b in pages[0].blocks)


def test_block_types_are_normalized(fake_content_list, mineru_out):
    pages = content_list_to_pages(fake_content_list, str(mineru_out))
    types = [b.block_type for p in pages for b in p.blocks]
    assert BLOCK_TITLE in types  # "title" 条目
    assert BLOCK_FIGURE in types  # "image" 条目
    assert BLOCK_FORMULA in types  # "equation" 条目
    assert BLOCK_TABLE in types  # "table" 条目
    assert BLOCK_TEXT in types


def test_formula_keeps_latex(fake_content_list, mineru_out):
    pages = content_list_to_pages(fake_content_list, str(mineru_out))
    formulas = [b for b in pages[0].blocks if b.block_type == BLOCK_FORMULA]
    assert formulas and formulas[0].latex == "E=mc^2"


def test_table_body_becomes_text(fake_content_list, mineru_out):
    pages = content_list_to_pages(fake_content_list, str(mineru_out))
    tables = [b for b in pages[0].blocks if b.block_type == BLOCK_TABLE]
    assert tables and "R" in tables[0].text


def test_normalized_bbox_is_scaled_to_pixels(fake_content_list, mineru_out):
    pages = content_list_to_pages(fake_content_list, str(mineru_out))
    figures = [b for b in pages[0].blocks if b.block_type == BLOCK_FIGURE]
    assert figures
    bbox = figures[0].bbox
    # 0-1 归一化 × 页面尺寸(595×842)
    assert bbox == pytest.approx((0.1 * 595, 0.2 * 842, 0.5 * 595, 0.6 * 842), abs=0.01)


def test_pixel_bbox_is_kept(fake_content_list, mineru_out):
    pages = content_list_to_pages(fake_content_list, str(mineru_out))
    first = pages[0].blocks[0]
    assert first.bbox == pytest.approx((72, 100, 520, 160))


def test_image_is_copied_and_path_is_relative(fake_content_list, mineru_out):
    pages = content_list_to_pages(fake_content_list, str(mineru_out))
    figures = [b for b in pages[0].blocks if b.block_type == BLOCK_FIGURE]
    assert figures
    image_path = figures[0].image_path
    # 相对路径，不许出现机器绝对路径
    assert not image_path.startswith("/") and ":" not in image_path
    assert image_path.startswith("images/")
    copied = mineru_out / image_path
    assert copied.is_file()


def test_missing_image_is_flagged(mineru_out):
    content_list = [
        {"type": "image", "page_idx": 0, "bbox": [1, 2, 30, 40], "img_path": "images/nope.png"}
    ]
    pages = content_list_to_pages(content_list, str(mineru_out))
    assert pages[0].blocks
    assert pages[0].blocks[0].extra.get("image_missing") is True


def test_reading_order_is_sequential(fake_content_list, mineru_out):
    pages = content_list_to_pages(fake_content_list, str(mineru_out))
    orders = [b.reading_order for b in pages[0].blocks]
    assert orders == sorted(orders) == list(range(len(orders)))


def test_page_text_joins_blocks(fake_content_list, mineru_out):
    pages = content_list_to_pages(fake_content_list, str(mineru_out))
    assert "设则" in pages[0].text


def test_content_list_file_roundtrip(tmp_path, fake_content_list, mineru_out):
    """落盘再读回来结果一致（模拟真实 MinerU 产物）。"""
    path = mineru_out / "demo_content_list.json"
    path.write_text(json.dumps(fake_content_list, ensure_ascii=False), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = content_list_to_pages(data, str(mineru_out))
    assert [p.page_no for p in pages] == [1, 2]
    assert len(pages[0].blocks) == 5


def test_unknown_type_without_content_is_dropped(mineru_out):
    pages = content_list_to_pages([{"type": "wat", "page_idx": 0}], str(mineru_out))
    assert not pages or not pages[0].blocks
