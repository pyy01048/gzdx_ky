# -*- coding: utf-8 -*-
"""M1-1d：科目分类器对"裸电子技术专名"的回归测试。

背景：`_SUBJECT_STRONG` 原先缺"电子技术基础/电子技术"裸专名，
导致《【电子技术基础】国家职业资格培训》被判成 `其他`（历史上甚至被错标为"政治"），
进而使 781 道模电题挂到政治栏。本测试锁定修复后的行为。
"""
from __future__ import annotations

from services.kb_service import classify_subject_confidence


def test_bare_electronics_basics_to_analog():
    """无"数字/模拟"限定的"电子技术(基础)"应归模电。"""
    assert classify_subject_confidence(
        "【电子技术基础】国家职业资格培训.txt")[0] == "模拟电子技术"
    assert classify_subject_confidence(
        "【电子技术基础】国家职业资格培训.pdf")[0] == "模拟电子技术"
    assert classify_subject_confidence("电子技术基础")[0] == "模拟电子技术"


def test_digital_part_still_digital():
    """含"数字部分"时，互斥线索应压过"电子技术基础"→ 归数电（防止回归）。"""
    assert classify_subject_confidence(
        "【电子技术基础-数字部分】康华光 考研真题解析")[0] == "数字电子技术"


def test_analog_part_still_analog():
    assert classify_subject_confidence(
        "电子技术基础 模拟部分 习题")[0] == "模拟电子技术"


def test_politics_exam_unaffected():
    """真正的政治真题不受影响。"""
    assert classify_subject_confidence("2024年考研政治真题及答案")[0] == "政治"
    assert classify_subject_confidence("政治答题卡")[0] == "政治"


def test_other_subjects_unaffected():
    assert classify_subject_confidence("数据结构 二叉树")[0] == "计算机学科专业基础408"
    assert classify_subject_confidence("数电 卡诺图")[0] == "数字电子技术"
