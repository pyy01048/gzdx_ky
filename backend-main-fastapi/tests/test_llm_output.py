# -*- coding: utf-8 -*-
"""thinking 模型输出清洗的回归测试。

锁死这个真实事故：`think:false` 会让 qwen3 把推理过程倒进 content，
而旧代码会把「首先，用户要求我提炼…」当成知识要点写进知识库。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_output import (  # noqa: E402
    build_payload,
    extract_answer,
    looks_like_chain_of_thought,
)

# 实测抓到的真实思维链片段（think:false 时出现在 content 里）
REAL_COT = (
    "首先，用户要求我提炼以下资料的要点，输出3条简短要点。资料是："
    "“时序逻辑电路的状态转换表描述了电路在时钟脉冲作用下状态的变化规律。”\n"
    "我需要理解资料内容：\n"
    "- 时序逻辑电路的状态转换表：描述了在时钟脉冲作用下状态的变化规律。\n"
    "用户指定要输出3条简短要点。所以，我必须提炼出核心要点，保持简短。\n"
    "关键点：\n1. 时序逻辑电路的状态转换表\n2. 触发器\n"
)

# 实测抓到的干净答案（默认不传 think 时）
REAL_ANSWER = (
    "1. 时序电路状态转换表描述时钟脉冲下状态变化规律  \n"
    "2. 触发器是构成时序电路的基本单元  \n"
    "3. 常见触发器类型包括RS、JK、D、T"
)


class TestChainOfThoughtDetection:

    def test_real_cot_detected(self):
        assert looks_like_chain_of_thought(REAL_COT), "真实思维链必须被识别"

    def test_real_answer_not_flagged(self):
        assert not looks_like_chain_of_thought(REAL_ANSWER), "干净答案不能误判"

    def test_first_person_openers(self):
        for opener in ("首先，我需要分析", "用户要求我回答", "让我想想这个问题",
                       "The user is asking", "I need to figure out"):
            assert looks_like_chain_of_thought(opener + "……"), f"{opener} 应判为思维链"

    def test_overlong_text_is_cot(self):
        assert looks_like_chain_of_thought("正常内容。" * 200), "超长文本应判为思维链"

    def test_empty_is_not_cot(self):
        assert not looks_like_chain_of_thought("")

    def test_normal_short_answer_ok(self):
        assert not looks_like_chain_of_thought("卡诺图是化简布尔表达式的图形化工具。")
        assert not looks_like_chain_of_thought("RS触发器有不定状态，JK触发器解决了这个问题。")


class TestExtractAnswer:

    def test_prefers_content(self):
        """content 干净时直接用 content，忽略 thinking。"""
        msg = {"content": REAL_ANSWER, "thinking": "很长的推理" * 50}
        assert extract_answer(msg) == REAL_ANSWER

    def test_rejects_cot_in_content(self):
        """content 是思维链时必须丢弃 —— 这正是事故场景。"""
        msg = {"content": REAL_COT, "thinking": ""}
        assert extract_answer(msg) == "", "思维链绝不能当答案返回"

    def test_falls_back_to_thinking_when_content_empty(self):
        """content 为空、thinking 干净时可回退。"""
        msg = {"content": "", "thinking": "卡诺图用于化简逻辑函数。"}
        assert extract_answer(msg) == "卡诺图用于化简逻辑函数。"

    def test_empty_message(self):
        assert extract_answer({}) == ""
        assert extract_answer(None) == ""

    def test_strips_whitespace(self):
        assert extract_answer({"content": "  答案  "}) == "答案"

    def test_handles_reasoning_alias(self):
        """有些实现用 reasoning 而不是 thinking。"""
        msg = {"content": "", "reasoning": "这是结论。"}
        assert extract_answer(msg) == "这是结论。"

    def test_extracts_conclusion_from_cot_thinking(self):
        """thinking 里推理+结论混杂时，尽量抽出结论段落。"""
        msg = {
            "content": "",
            "thinking": REAL_COT + "\n\n所以，时序电路状态转换表描述状态变化规律。",
        }
        out = extract_answer(msg)
        assert "状态转换表" in out or out == ""


class TestBuildPayload:

    def test_omits_think_by_default(self):
        """默认不能带 think 字段 —— 传 false 会触发事故。"""
        p = build_payload("qwen3:4b", "问题")
        assert "think" not in p, "默认不能传 think（实测传 false 会导致推理泄漏）"

    def test_can_force_think(self):
        p = build_payload("qwen3:4b", "问题", think=True)
        assert p["think"] is True

    def test_has_keep_alive_and_options(self):
        p = build_payload("qwen3:4b", "问题")
        assert p["keep_alive"] == "10m"
        assert p["options"]["num_predict"] >= 512
        assert p["stream"] is False
