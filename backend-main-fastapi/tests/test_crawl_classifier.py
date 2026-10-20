# -*- coding: utf-8 -*-
"""``services/crawl/classifier.py`` 单测：规则分类（doc §5.4 规则表全覆盖）。"""
from __future__ import annotations

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import pytest  # noqa: E402

from services.crawl.classifier import (  # noqa: E402
    NOTICE_TYPES,
    OTHER,
    classify_notice,
    to_db_notice_type,
)

#: doc §5.4 每一类给两个真实感标题
CASES = [
    ("招生简章", "北京大学2025年硕士研究生招生简章"),
    ("招生简章", "复旦大学2025年硕士研究生招生章程"),
    ("专业目录", "中山大学2025年硕士招生专业目录"),
    ("专业目录", "山东大学2025年硕士研究生招生考试科目一览"),
    ("复试线", "清华大学公布2025年硕士研究生复试分数线"),
    ("复试线", "上海交通大学2025年复试基本分数线公告"),
    ("报录比", "浙江大学2025年硕士研究生报考人数与录取人数统计"),
    ("报录比", "南京大学2025年招生报录比及推免占比公示"),
    ("复试细则", "华中科技大学2025年硕士研究生复试录取实施细则"),
    ("复试细则", "同济大学2025年研究生复试办法"),
    ("调剂", "北京航空航天大学2025年硕士研究生招生调剂公告"),
    ("调剂", "华中师范大学2025年硕士研究生调剂系统开放通知"),
    ("推免", "中国人民大学2025年推荐优秀应届本科毕业生免试攻读研究生（推免）"),
    ("推免", "厦门大学2026年优秀大学生夏令营通知"),
    ("录取", "复旦大学2025年硕士研究生拟录取名单公示"),
    ("录取", "武汉大学2025年硕士研究生拟录取结果"),
    ("初试", "北京大学2025年硕士研究生初试成绩查询开通"),
    ("初试", "浙江大学2025年硕士研究生初试成绩复核申请"),
    ("报名", "中国传媒大学2025年硕士研究生招生预报名公告"),
    ("报名", "东南大学2025年硕士研究生网上确认公告"),
    ("大纲", "山东大学2025年硕士研究生招生考试大纲"),
    ("大纲", "北京邮电大学2025年硕士研究生招生参考书目"),
]


@pytest.mark.parametrize("expected,title", CASES)
def test_classify_by_title(expected, title):
    kind, confidence = classify_notice(title)
    assert kind == expected, f"{title!r} 应判为 {expected}，实际 {kind}"
    assert 0.0 < confidence <= 1.0


def test_every_doc_type_is_covered():
    """doc §5.4 的 11 个类型全部有单测覆盖。"""
    covered = {expected for expected, _ in CASES}
    assert covered == set(NOTICE_TYPES)


def test_doc_keywords_are_all_present():
    """doc §5.4 原表关键词必须全部出现在规则表里。"""
    doc_keywords = {
        "招生简章": ["招生简章", "招生章程", "报考条件"],
        "专业目录": ["专业目录", "招生专业目录", "考试科目"],
        "复试线": ["复试分数线", "复试基本分数线", "校线", "院线"],
        "报录比": ["报录比", "报考人数", "录取人数", "推免占比"],
        "复试细则": ["复试录取实施细则", "复试办法", "复试科目"],
        "调剂": ["调剂公告", "调剂缺额", "调剂系统"],
        "推免": ["推免", "推荐免试", "夏令营"],
        "录取": ["拟录取名单", "录取公示"],
        "初试": ["初试成绩", "成绩查询", "复核"],
        "报名": ["预报名", "正式报名", "网上确认"],
        "大纲": ["考试大纲", "参考书目"],
    }
    for name, keywords in doc_keywords.items():
        for kw in keywords:
            assert kw in NOTICE_TYPES[name], f"{name} 缺少关键词 {kw}"


def test_unknown_notice_is_other():
    kind, confidence = classify_notice("关于开展学生公寓空调维修的通知")
    assert kind == OTHER
    assert confidence == 0.0


def test_title_weight_beats_body():
    title_hit = classify_notice("关于2025年硕士研究生招生复试录取实施细则的说明", "无关正文")
    body_only = classify_notice("一则通知", "正文中提到了复试分数线和调剂安排")
    assert title_hit[0] == "复试细则"
    assert body_only[0] == OTHER or body_only[1] < title_hit[1]


def test_more_specific_keyword_wins():
    """「推免占比」比「推免」更具体，应判为报录比。"""
    kind, _ = classify_notice("南京大学2025年招生报录比及推免占比公示")
    assert kind == "报录比"


def test_db_type_mapping_is_within_enum():
    enum_labels = {"公告", "简章", "复试", "调剂", "录取", "初试", "报名", "大纲", "目录"}
    for name in list(NOTICE_TYPES) + [OTHER]:
        assert to_db_notice_type(name) in enum_labels


def test_llm_fallback_only_used_when_rules_miss():
    called = []

    def fake_llm(title, text):
        called.append(title)
        return ("调剂", 0.88)

    kind, conf = classify_notice("无关标题", "", llm_fallback=fake_llm)
    assert called == ["无关标题"]
    assert kind == "调剂" and conf == 0.88

    called.clear()
    kind, conf = classify_notice("2025年硕士研究生招生简章", "", llm_fallback=fake_llm)
    assert called == [], "规则命中时不该调 LLM"
    assert kind == "招生简章"
