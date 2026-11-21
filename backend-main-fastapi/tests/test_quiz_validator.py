# -*- coding: utf-8 -*-
"""题目质量门测试（完善方案 11 §3.3 / 验收清单：构造坏数据实测被整批拒绝）。"""

from __future__ import annotations

import pytest
from services.quiz_validator import (
    ACCURACY_THRESHOLD,
    BatchRejected,
    assert_batch_ok,
    classify,
    dedup_key,
    validate_batch,
    validate_question,
)


def _codes(issues):
    return sorted(i.code for i in issues)


def test_valid_single_choice_passes():
    q = {
        "content": "当输入电压为正弦波时，输出波形为？",
        "options": [{"key": "A", "text": "方波"}, {"key": "B", "text": "正弦波"}],
        "answer": "B",
        "question_type": "single",
        "analysis": "射极跟随器不改变波形。",
    }
    assert validate_question(q) == []
    assert classify([]) == "pass"


def test_missing_options_fails():
    q = {"content": "什么是密勒效应？", "options": [], "answer": "A", "question_type": "single", "analysis": "x"}
    assert "OPTIONS_TOO_FEW" in _codes(validate_question(q))
    assert classify(validate_question(q)) == "fail"


def test_answer_not_in_options_fails():
    q = {
        "content": "逻辑函数化简结果为？",
        "options": ["A. AB", "B. A+B"],
        "answer": "D",
        "question_type": "single",
        "analysis": "卡诺图化简。",
    }
    assert "ANSWER_NOT_IN_OPTIONS" in _codes(validate_question(q))


def test_single_with_multiple_answers_fails():
    q = {
        "content": "以下哪些属于时序逻辑电路？",
        "options": ["A. 触发器", "B. 计数器", "C. 编码器"],
        "answer": "AB",
        "question_type": "single",
        "analysis": "触发器与计数器有时钟。",
    }
    codes = _codes(validate_question(q))
    assert "ANSWER_MULTI_FOR_SINGLE" in codes


def test_placeholder_option_is_warn_not_fail():
    q = {
        "content": "运算放大器理想特性之一是？",
        "options": ["A. 虚短", "B. 略"],
        "answer": "A",
        "question_type": "single",
        "analysis": "虚短虚断。",
    }
    issues = validate_question(q)
    assert classify(issues) == "warn"


def test_missing_analysis_is_warn():
    q = {
        "content": "三极管处于放大区的条件是？",
        "options": ["A. 发射结正偏集电结反偏", "B. 都正偏"],
        "answer": "A",
        "question_type": "single",
    }
    assert classify(validate_question(q)) == "warn"


def test_judge_answer_validation():
    ok = {"content": "理想运放开环增益无穷大。", "question_type": "judge", "answer": "对", "analysis": "理想化假设。"}
    bad = {"content": "理想运放开环增益无穷大。", "question_type": "judge", "answer": "不知道", "analysis": "x"}
    assert validate_question(ok) == []
    assert "JUDGE_ANSWER_INVALID" in _codes(validate_question(bad))


def test_past_exam_requires_year():
    q = {
        "content": "用卡诺图化简 F(A,B,C,D)=Σm(0,2,5,7,8,10,13,15)",
        "question_type": "calc",
        "answer": "BD+B'D'",
        "analysis": "分组化简。",
        "is_past_exam": True,
    }
    assert "PAST_EXAM_YEAR_MISSING" in _codes(validate_question(q))
    q["year"] = 2019
    assert "PAST_EXAM_YEAR_MISSING" not in _codes(validate_question(q))
    q["year"] = 1800
    assert "PAST_EXAM_YEAR_INVALID" in _codes(validate_question(q))


def test_batch_rejects_bad_structural_rate():
    bad_rows = [{"content": "", "options": [], "answer": None, "question_type": "single"} for _ in range(10)]
    good = {
        "content": "某放大电路静态工作点如何计算？",
        "options": ["A. 估算法", "B. 图解法"],
        "answer": "A",
        "question_type": "single",
        "analysis": "略述计算步骤即可通过。",
    }
    rows = bad_rows + [good] * 5
    report = validate_batch(rows, sample_review={"reviewed": 30, "correct": 30})
    assert report.failed == 10
    assert not report.ok
    with pytest.raises(BatchRejected):
        assert_batch_ok(report)


def test_batch_requires_sample_review():
    rows = [
        {
            "content": "触发器的空翻现象如何避免？",
            "options": ["A. 采用主从结构", "B. 提高时钟频率"],
            "answer": "A",
            "question_type": "single",
            "analysis": "主从/边沿触发。",
        }
    ]
    report = validate_batch(rows)
    assert report.sample_pass_rate is None
    assert not report.ok
    assert "抽样验收" in report.reason


def test_batch_sample_below_threshold_rejected():
    rows = [
        {
            "content": "组合逻辑电路的竞争冒险如何消除？",
            "options": ["A. 加滤波电容", "B. 增加冗余项"],
            "answer": "B",
            "question_type": "single",
            "analysis": "增加乘积项。",
        }
    ] * 40
    report = validate_batch(rows, sample_review={"reviewed": 30, "correct": 29})
    assert report.sample_pass_rate is not None
    assert report.sample_pass_rate < ACCURACY_THRESHOLD
    assert not report.ok
    assert "抽样准确率" in report.reason


def test_batch_passes_with_full_sample():
    rows = [
        {
            "content": "放大电路的输入电阻如何测量？",
            "options": ["A. 伏安法", "B. 电桥法"],
            "answer": "A",
            "question_type": "single",
            "analysis": "外加电压测电流。",
        }
    ] * 3
    report = validate_batch(rows, sample_review={"reviewed": 30, "correct": 30})
    assert report.ok
    assert report.fail_rate == 0
    assert len(report.accepted_rows) == 3


def test_dedup_key_normalizes_whitespace():
    a = {"content": "求 极限  lim x→0 sinx/x", "subject": "高等数学", "chapter": "极限"}
    b = {"content": "求极限lim x→0 sinx/x", "subject": "高等数学", "chapter": "极限"}
    assert dedup_key(a) == dedup_key(b)
