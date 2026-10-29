# -*- coding: utf-8 -*-
"""M0-103②：AI 答疑的「真题 / 教材」模式区分 + 选项解析 + 动态科目身份。

纯函数级回归（不发起 LLM 调用），锁定三个既存缺陷的修复：
  ① 讲师身份不得写死"数电/模电"，须按题目实际科目（缺失时中性表述）；
  ② `options` 反序列化后是 list（ORM JSON 列），旧代码走 dict 分支失败 →
     把 Python repr 喂给模型；现按 list 顺序拼成 A．… B．…；
  ③ exam / textbook 两种模式的提示词必须有**实质差异**（评分视角 vs 概念理解）。
"""
from __future__ import annotations

from types import SimpleNamespace

from routers.ai import ai_tutoring as t


def _q(source=None, subject=None, options=None):
    return SimpleNamespace(id=1, source=source, subject=subject, options=options,
                           content="c", answer="A", analysis=None, knowledge_point=None,
                           year=None, paper=None)


# --------------------------- ① 动态科目身份 --------------------------- #
def test_tutor_role_uses_real_subject_not_hardcoded():
    role = t._tutor_role(_q(subject="模拟电子技术"))
    assert "模拟电子技术" in role
    # 不得再出现旧硬编码
    assert "数电/模电" not in role


def test_tutor_role_neutral_when_subject_missing():
    role = t._tutor_role(_q(subject=None))
    assert "数电" not in role and "模电" not in role
    assert "未标注科目" in role


# --------------------------- ② 选项解析 --------------------------- #
def test_format_options_list_with_letters_kept():
    opts = ["A．奇偶校验码", "B．5421BCD 码", "C．余三码", "D．格雷码"]
    out = t._format_options(opts)
    assert out == "A．奇偶校验码 B．5421BCD 码 C．余三码 D．格雷码"
    assert "[" not in out and "'" not in out  # 绝不能是 list 的 repr


def test_format_options_list_without_letters_gets_numbered():
    out = t._format_options(["接地", "接高电平"])
    assert out == "A.接地 B.接高电平"


def test_format_options_dict_and_json_str_and_blank():
    assert t._format_options({"A": "接地", "B": "接高电平"}) == "A.接地；B.接高电平"
    assert t._format_options('["甲","乙"]') == "A.甲 B.乙"
    assert t._format_options(None) == ""
    # 全空白数组（库内大量存在）→ 空串，不产生 【选项】 行
    assert t._format_options(["", "  ", None]) == ""


def test_context_text_never_leaks_list_repr():
    txt = t._context_text(_q(source="真题:X", options=["A．甲", "B．乙"]), "A")
    assert "【选项】A．甲 B．乙" in txt
    assert "[" not in txt.split("【正确答案】")[0]


# --------------------------- ③ 模式区分 --------------------------- #
def test_resolve_mode_derives_from_source():
    assert t._resolve_mode(_q(source="真题:2023数学一"), None) == "exam"
    assert t._resolve_mode(_q(source="知识库:教材第三章"), None) == "textbook"
    assert t._resolve_mode(_q(source="ai:variant"), None) == "general"
    assert t._resolve_mode(_q(source=None), None) == "general"


def test_resolve_mode_override_wins():
    # 题目本身是真题，但用户手动切到教材模式
    assert t._resolve_mode(_q(source="真题:X"), "textbook") == "textbook"
    assert t._resolve_mode(_q(source="知识库:X"), "exam") == "exam"


def test_two_modes_have_substantively_different_prompts():
    q = _q(source="真题:X", subject="数字电子技术")
    exam = t._build_system_prompt(q, t._resolve_mode(q, "exam"))
    tb = t._build_system_prompt(q, t._resolve_mode(q, "textbook"))
    assert exam != tb
    # 真题模式：评分视角关键词
    assert "踩分点" in exam and "失分" in exam and "答题书写" in exam
    # 教材模式：理解视角关键词
    assert "原理" in tb and "推导链" in tb and "辨析" in tb
    # 两者的立场关键词不互相串
    assert "推导链" not in exam and "踩分点" not in tb
    # 科目仍按题目实际科目
    assert "数字电子技术" in exam and "数字电子技术" in tb
