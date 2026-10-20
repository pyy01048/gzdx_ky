# -*- coding: utf-8 -*-
"""入库质量门禁单测（docx/34 §4.7）。

覆盖 A / B / C / JUNK 四档 + 「答案字母不在选项里 → 降级 C」。
纯函数测试：不碰数据库、不需要 mineru、不需要真实 PDF。
"""
from __future__ import annotations

import pytest

from services.ingest_pipeline import (
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_JUNK,
    check_question,
    grade_question,
    normalize_options,
)


def _choice(stem="下列关于放大电路的说法正确的是（　）", options=None, answer="B", analysis="由静态工作点分析可得。"):
    return {
        "stem": stem,
        "options": options if options is not None else [
            "A. 静态工作点越低越好",
            "B. 静态工作点应保证输出不失真",
            "C. 静态工作点与信号无关",
        ],
        "answer": answer,
        "analysis": analysis,
    }


# --------------------------------------------------------------------------- #
# A 档
# --------------------------------------------------------------------------- #
def test_grade_a_full_choice():
    assert grade_question(_choice()) == GRADE_A


def test_grade_a_with_canonical_option_dicts():
    q = _choice(options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}, {"key": "C", "text": "丙"}])
    assert grade_question(q) == GRADE_A


# --------------------------------------------------------------------------- #
# B 档
# --------------------------------------------------------------------------- #
def test_grade_b_subjective_has_answer_no_options():
    q = {"stem": "请简述负反馈放大电路的判别方法。", "options": [], "answer": "看输出是否回到输入", "analysis": ""}
    assert grade_question(q) == GRADE_B


def test_grade_b_judge_question():
    q = {"stem": "理想运算放大器的输入电阻无穷大。", "options": [], "answer": "对", "analysis": ""}
    assert grade_question(q) == GRADE_B


def test_grade_b_choice_missing_analysis():
    grade, issues = check_question(_choice(analysis=""))
    assert grade == GRADE_B
    assert "missing_analysis" in issues


# --------------------------------------------------------------------------- #
# C 档
# --------------------------------------------------------------------------- #
def test_grade_c_missing_answer():
    grade, issues = check_question(_choice(answer=""))
    assert grade == GRADE_C
    assert "missing_answer" in issues


def test_grade_c_answer_letter_not_in_options():
    """答案字母不在选项 key 里 → 强制降级 C，并记 answer_not_in_options。"""
    grade, issues = check_question(_choice(answer="D"))
    assert grade == GRADE_C
    assert "answer_not_in_options" in issues


def test_grade_c_answer_letters_subset_is_ok():
    """答案字母是选项的子集 → 不降级。"""
    q = _choice(options=["A. 甲", "B. 乙", "C. 丙"], answer="AC")
    grade, issues = check_question(q)
    assert grade == GRADE_A
    assert "answer_not_in_options" not in issues


# --------------------------------------------------------------------------- #
# JUNK 档
# --------------------------------------------------------------------------- #
def test_grade_junk_stem_too_short():
    grade, issues = check_question({"stem": "选择", "options": [], "answer": "A", "analysis": ""})
    assert grade == GRADE_JUNK
    assert "stem_too_short" in issues


def test_grade_junk_answer_section():
    """答案解析段不是题目。"""
    q = {"stem": "答案解析：因为输入信号为三角波，输出必然是三角波。", "options": [], "answer": "A", "analysis": ""}
    assert grade_question(q) == GRADE_JUNK


def test_grade_junk_empty_stem():
    grade, issues = check_question({"stem": "", "options": [], "answer": "A", "analysis": ""})
    assert grade == GRADE_JUNK
    assert "empty_stem" in issues


def test_grade_junk_toc_line():
    q = {"stem": "目录 第一章 电路基础 第一节 概述", "options": [], "answer": "", "analysis": ""}
    assert grade_question(q) == GRADE_JUNK


def test_grade_junk_page_number_line():
    q = {"stem": "第 3 页 共 12 页", "options": [], "answer": "", "analysis": ""}
    assert grade_question(q) == GRADE_JUNK


# --------------------------------------------------------------------------- #
# 选项归一
# --------------------------------------------------------------------------- #
def test_normalize_options_variants():
    assert normalize_options(["A. 甲", "B. 乙"]) == {"A": "甲", "B": "乙"}
    assert normalize_options([{"key": "c", "text": "丙"}]) == {"C": "丙"}
    assert normalize_options({"A": "甲", "B": "乙"}) == {"A": "甲", "B": "乙"}
    assert normalize_options(None) == {}


@pytest.mark.parametrize("grade", [GRADE_A, GRADE_B, GRADE_C, GRADE_JUNK])
def test_grade_is_one_of_four_levels(grade):
    assert grade in {GRADE_A, GRADE_B, GRADE_C, GRADE_JUNK}
