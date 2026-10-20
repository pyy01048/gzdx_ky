# -*- coding: utf-8 -*-
"""数学公式 OCR 损坏检测单测（数学扫描件主路径的防线）。

背景：数学类 PDF 全部是纯扫描件，RapidOCR 在公式上会**读错**
（``x``→``α``、``-``→汉字「一」、``f(x)``→``fLg(）``），所以解析层要标出
「疑似公式损坏」，下游质检据此把题降级、留痕、挑出来重解析。

纯函数 + 解析器转换层测试：不碰数据库、不需要 mineru、不需要真实 PDF。
"""
from __future__ import annotations

import pytest

from services.ocr_math_guard import (
    detect_math_corruption,
    is_math_corrupted,
    summarize_blocks,
)

#: team-lead 提供的真实损坏样本（RapidOCR 读出来的）
REAL_CORRUPTED = "设函数y=f(r)…恒有f（一）=f()，则称f(α)为…偶函数"

#: 正常数学文本（不该被误判）
CLEAN_TEXT = "设函数 f(x) 在区间 (0,1) 上连续，则 f(x) 的最大值存在且唯一。"


# --------------------------------------------------------------------------- #
# 强信号：结构已坏
# --------------------------------------------------------------------------- #
def test_real_corrupted_sample_is_flagged():
    result = detect_math_corruption(REAL_CORRUPTED)
    assert result.corrupted is True
    assert "empty_call" in result.reasons
    assert "cjk_num_in_paren" in result.reasons


def test_clean_math_text_is_not_flagged():
    result = detect_math_corruption(CLEAN_TEXT)
    assert result.corrupted is False
    assert result.suspect is False
    assert result.reasons == []


def test_empty_call_is_corruption():
    assert is_math_corrupted("由 f() 可知该点为间断点") is True


def test_cjk_numeral_in_call_is_corruption():
    """减号被读成汉字「一」：f(-x) → f（一）"""
    assert is_math_corrupted("恒有 f（一）=f(x) 成立") is True


def test_mixed_width_parenthesis_is_corruption():
    """半角开括号 + 全角闭括号：fLg(）"""
    assert is_math_corrupted("根据 fLg(） 定理可得") is True


def test_chinese_section_marker_is_not_corruption():
    """「（一）单项选择题」是正常小节号，不能误判。"""
    assert is_math_corrupted("（一）单项选择题（每题 2 分）") is False


def test_full_width_parenthesis_pair_is_fine():
    assert is_math_corrupted("当 x∈（0,1）时，函数单调递增") is False


# --------------------------------------------------------------------------- #
# 弱信号：只提示复核
# --------------------------------------------------------------------------- #
def test_greek_argument_alone_is_only_suspect():
    """f(α) 可能是正常数学记号 → 只标可疑，不标损坏。"""
    result = detect_math_corruption("则称 f(α) 为偶函数")
    assert result.corrupted is False
    assert result.suspect is True
    assert "greek_argument" in result.reasons


def test_unbalanced_parenthesis_is_only_suspect():
    """行级 OCR 把跨行公式拆开 → 半边括号常见，只标可疑。"""
    result = detect_math_corruption("由 f(x = x + 1 可知")
    assert result.corrupted is False
    assert result.suspect is True
    assert "unbalanced_paren" in result.reasons


def test_empty_text_is_neither():
    result = detect_math_corruption("")
    assert result.corrupted is False
    assert result.suspect is False
    assert result.hit is False


# --------------------------------------------------------------------------- #
# extra 转换
# --------------------------------------------------------------------------- #
def test_to_extra_for_corrupted():
    extra = detect_math_corruption(REAL_CORRUPTED).to_extra()
    assert extra["math_corrupted"] is True
    assert "math_corrupt_reasons" in extra


def test_to_extra_for_clean_is_empty():
    assert detect_math_corruption(CLEAN_TEXT).to_extra() == {}


def test_to_extra_for_suspect():
    extra = detect_math_corruption("则称 f(α) 为偶函数").to_extra()
    assert "math_corrupted" not in extra
    assert extra["math_suspect"] is True


# --------------------------------------------------------------------------- #
# 解析层转换：rapidocr_parser 落标记
# --------------------------------------------------------------------------- #
def test_rapidocr_blocks_carry_math_flag():
    from services.parsers.rapidocr_parser import ocr_result_to_blocks
    from services.ocr_router import OCRBlock, OCRResult

    result = OCRResult(
        text="",
        blocks=[OCRBlock(text=REAL_CORRUPTED, box=None, score=0.61)],
    )
    blocks = ocr_result_to_blocks(result, page_no=3)
    assert len(blocks) == 1
    extra = blocks[0].extra
    assert extra.get("math_corrupted") is True
    assert blocks[0].confidence == 0.61  # 置信度照常带上
    assert blocks[0].page_no == 3


def test_rapidocr_text_only_fallback_marks_missing_confidence():
    """只回文本的后端拿不到置信度 → 显式标记「缺」，不能留白让人误以为是 1.0。"""
    from services.parsers.rapidocr_parser import ocr_result_to_blocks
    from services.ocr_router import OCRResult

    result = OCRResult(text=CLEAN_TEXT, blocks=[])
    blocks = ocr_result_to_blocks(result, page_no=1)
    assert blocks
    assert blocks[0].confidence is None
    assert blocks[0].extra.get("ocr_confidence_missing") is True


def test_summarize_blocks():
    from services.parsers.base import ParsedBlock

    blocks = [
        ParsedBlock(page_no=1, text="坏块", extra={"math_corrupted": True}, block_id="b1"),
        ParsedBlock(page_no=1, text="可疑块", extra={"math_suspect": True}, block_id="b2"),
        ParsedBlock(page_no=1, text="好块", block_id="b3"),
    ]
    summary = summarize_blocks(blocks)
    assert summary["corrupted"] == 1
    assert summary["suspect"] == 1
    assert summary["block_ids"] == ["b1"]


# --------------------------------------------------------------------------- #
# 真实回归样本：RapidOCR 真跑「27张宇数学公式手册.pdf」前 12 页的输出
# （2026-10-20 实测录，锁住行为防止回退）
# --------------------------------------------------------------------------- #
REAL_CORRUPTED_SAMPLES = [
    "为y=f().",                                        # 原文 y=f(x)
    "果对于I内任意一点r，恒有f（一r）=f（x)，则称",          # 原文 f(-x)=f(x)
    "f()为区间I内的偶函数；如果恒有f(一α)=一f(），",            # 原文 f(-x)=f(x)
    "意的rEI,必有r士TEI,并且f(r十T)=f(),则称",               # 原文 x∈I, x+T∈I, f(x+T)=f(x)
    "则称f(x）为区间I内的奇函数",                          # 半角开括号 + 全角闭括号
    "y=C（常数);",                                    # 全角开 + 半角闭
]

REAL_PROSE_SAMPLES = [
    "数学概念、公式、定理是数学的基础，也是考研数",
    "本手册内容全面，不仅包括高等数学、线性代数、",
    "如果本书有不足之处，希望大家给予批评指正",
]


@pytest.mark.parametrize("text", REAL_CORRUPTED_SAMPLES)
def test_real_corrupted_samples_are_detected(text):
    result = detect_math_corruption(text)
    assert result.corrupted is True, f"漏检：{text}"


@pytest.mark.parametrize("text", REAL_PROSE_SAMPLES)
def test_real_prose_is_not_flagged(text):
    """中文正文误报会把可用内容白白判坏，代价比漏报更大。"""
    result = detect_math_corruption(text)
    assert result.corrupted is False
    assert result.suspect is False
