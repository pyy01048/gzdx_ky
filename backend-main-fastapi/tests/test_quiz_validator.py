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


# —— 历史数据实证的四类缺陷：必须在导入质量门就被拦住 —— #


def test_duplicate_option_text_fails():
    """OCR 丢字导致两个选项正文相同 → 学生看到两个一样的选项，无法作答。"""
    q = {
        "content": "下列关于反馈的说法正确的是？",
        "options": [
            {"key": "A", "text": "负反馈提高增益稳定性"},
            {"key": "B", "text": "负反馈提高增益稳定性"},
            {"key": "C", "text": "正反馈用于振荡"},
        ],
        "answer": "A",
        "question_type": "single",
        "analysis": "x",
    }
    codes = _codes(validate_question(q))
    assert "OPTION_TEXT_DUP" in codes
    assert classify(validate_question(q)) == "fail"


def test_stem_option_leak_fails():
    """上一题选项被拼进本题题干（跨题串行），题干与答案不属同题。"""
    q = {
        "content": "奉献社会是职业道德规范之一。此外还有 A. 爱岗敬业 B. 诚实守信 C. 办事公道 D. 热情服务。第七章 法律基础 67. 法律的国家强制性表现为",
        "options": [
            {"key": "A", "text": "国家对违法行为的否定和制裁"},
            {"key": "B", "text": "国家对合法行为的肯定和保护"},
        ],
        "answer": "A",
        "question_type": "single",
        "analysis": "x",
    }
    assert "STEM_OPTION_LEAK" in _codes(validate_question(q))


def test_station_enumeration_not_flagged_as_leak():
    """「站 A、B、C、D 通过 CDMA 共享链路」是普通枚举，不是选项泄漏。"""
    q = {
        "content": "站A、B、C、D通过CDMA共享链路，A、B、C要向D发送数据，码片序列如下，则发送的数据分别是（）",
        "options": [{"key": "A", "text": "1,0,1"}, {"key": "B", "text": "0,0,1"}],
        "answer": "A",
        "question_type": "single",
        "analysis": "x",
    }
    assert "STEM_OPTION_LEAK" not in _codes(validate_question(q))


def test_figure_missing_is_warn():
    q = {
        "content": "电路如图 3-1 所示，输出电压 Uo 等于？",
        "options": ["A. 6V", "B. 12V"],
        "answer": "A",
        "question_type": "single",
        "analysis": "x",
        "figure_missing": 1,
        "images": [],
    }
    issues = validate_question(q)
    assert "FIGURE_MISSING" in _codes(issues)
    assert classify(issues) == "warn"


def test_truncated_formula_stem_is_warn():
    q = {
        "content": "设，则（　　）．",
        "options": ["A. 1", "B. 2"],
        "answer": "A",
        "question_type": "single",
        "analysis": "x",
    }
    issues = validate_question(q)
    assert "STEM_FORMULA_LOST" in _codes(issues)
    assert classify(issues) == "warn"


def test_legit_short_stem_not_flagged():
    """「下列描述不正确的是（）」是完整的短题干，不应被误判为公式丢失。"""
    q = {
        "content": "下列描述不正确的是（　　）。",
        "options": ["A. 甲", "B. 乙"],
        "answer": "A",
        "question_type": "single",
        "analysis": "x",
    }
    assert "STEM_FORMULA_LOST" not in _codes(validate_question(q))
