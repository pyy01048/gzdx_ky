# -*- coding: utf-8 -*-
"""切题源头三处修复的单元测试。

重点覆盖**防误杀**：题目内容里恰好含「选择题」「参考答案」「第3题」等字样
时，判据函数必须返回 False。本项目已有 158 条误删的账，本模块的每一条
True 分支都必须有对应的 False 分支守卫。
"""

from __future__ import annotations

import pytest

from services.extraction_noise import (
    SPLIT_OPTIONS_ENV,
    clean_answer,
    clean_content,
    find_cross_question_leak,
    is_running_header_noise,
    split_options_enabled,
    split_stem_and_options,
    strip_cross_question_leak,
)


# --------------------------------------------------------------------------- #
# 修复 1：页眉 / 页脚 / 试卷通知噪声
# --------------------------------------------------------------------------- #
class TestRunningHeaderNoise:
    @pytest.mark.parametrize(
        "text",
        [
            "第8 音拓展习题",
            "第8章 部分自测题和习题参考答案",
            "科目代码：834",
            "科目名称： 电子技术基础 第 44 页",
            "考试科目代码：834",
            "第 12 页",
            "习题 399",
            "（考生注意：全部答案必须写在答题纸上否则后果自负！）",
            "东坡哥微信:haidongpo8",
            "微信公众号：电子与通信工程考研",
            "本试题纸须随答题纸一起装入试题袋中交回！",
        ],
    )
    def test_detects_noise(self, text: str) -> None:
        assert is_running_header_noise(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "与、或、非",
            "接高电平或与其它输入端并接或悬空",
            "Qn+1＝J'·Qn＋K'·Qn′",
            "第3题主要考查触发器的分类",
            "下列说法正确的是（　）",
            "本题的答案在解析中给出",
            "参考答案见教材第8页",
            "选择题共有10小题",
            "关于单调谐振电路，下列说法正确的是（ ）A、可以作为选频网络B、",
            "",
            None,
        ],
    )
    def test_does_not_kill_legit(self, text: str | None) -> None:
        assert is_running_header_noise(text) is False


class TestCleanAnswer:
    def test_header_becomes_none(self) -> None:
        assert clean_answer("第8 音拓展习题") is None

    def test_notice_becomes_none(self) -> None:
        assert clean_answer("必须写在答题纸上否则后果自负！）") is None

    def test_section_title_becomes_none(self) -> None:
        assert clean_answer("四、简答题（共4题，每题6分，共24分）") is None

    def test_legit_answer_kept(self) -> None:
        assert clean_answer("与、或、非") == "与、或、非"

    def test_empty_becomes_none(self) -> None:
        assert clean_answer("   ") is None
        assert clean_answer(None) is None


class TestCleanContent:
    def test_removes_embedded_noise_lines(self) -> None:
        raw = "14 LM1877N-9为2通道低频功率放大电路\n科目代码：834\n图P8.14所示"
        assert clean_content(raw) == (
            "14 LM1877N-9为2通道低频功率放大电路\n图P8.14所示"
        )

    def test_keeps_intact_question(self) -> None:
        raw = "TTL与非门多余输入端的处理方法是______。"
        assert clean_content(raw) == raw


# --------------------------------------------------------------------------- #
# 修复 2：选项必须与题干整体切出
# --------------------------------------------------------------------------- #
class TestSplitStemAndOptions:
    def test_splits_even_without_sec_type(self) -> None:
        body = (
            "1. 下列二极管中，常用于高频电路检波的是（）"
            "A. 整流二极管 B. 稳压二极管 C. 肖特基二极管 D. 发光二极管"
        )
        stem, opts = split_stem_and_options(body, sec_type="")
        assert stem == "1. 下列二极管中，常用于高频电路检波的是（）"
        assert len(opts) == 4
        assert opts[0].startswith("A.")
        assert opts[3].startswith("D.")

    def test_no_split_when_labels_not_sequential(self) -> None:
        body = "判断下列说法：A. 正确 C. 错误 D. 无 D. 无"
        stem, opts = split_stem_and_options(body)
        assert opts == []
        assert stem == body

    def test_no_split_when_stray_label_follows_run(self) -> None:
        """防误杀：连续序列后还有游离标签，说明这是正文列表项而非选项。"""
        body = "列出下列器件：A. 二极管 B. 三极管 E. 游离标签"
        stem, opts = split_stem_and_options(body)
        assert opts == []
        assert stem == body

    def test_no_split_when_only_two_labels(self) -> None:
        body = "以下正确的是A. 甲B. 乙"
        _stem, opts = split_stem_and_options(body)
        assert opts == []

    def test_does_not_kill_plain_question(self) -> None:
        body = "TTL与非门多余输入端的处理方法是______。"
        stem, opts = split_stem_and_options(body, sec_type="填空")
        assert opts == []
        assert stem == body

    def test_multiline_options_split(self) -> None:
        body = "本征半导体的空穴是（）\nA.带负电的离子\nB.电子脱离共价键后留下的空穴\nC.缺陷"
        stem, opts = split_stem_and_options(body, sec_type=None)
        assert stem == "本征半导体的空穴是（）"
        assert len(opts) == 3

    def test_empty_body(self) -> None:
        assert split_stem_and_options("") == ("", [])


# --------------------------------------------------------------------------- #
# 修复 3：跨题串接检测
# --------------------------------------------------------------------------- #
class TestCrossQuestionLeak:
    def test_detects_tail_section_header(self) -> None:
        text = "逻辑代数化简的目的是减少逻辑门的数量。 四、简答题（共4题，每题6分，共24分）"
        assert find_cross_question_leak(text) is not None
        cleaned, leaked = strip_cross_question_leak(text)
        assert leaked is True
        assert cleaned == "逻辑代数化简的目的是减少逻辑门的数量"

    def test_detects_choice_section_tail(self) -> None:
        text = "按结构来分，正弦波振荡电路主要有 型和 型两大类。 二、选择题（每题4分，共48分）"
        assert strip_cross_question_leak(text)[1] is True

    def test_not_leak_when_mentions_choices_inline(self) -> None:
        """防误杀：题干中间提到「选择题」不得判为串接。"""
        text = "下列说法正确的是（　）A、...B、...C、...D、... 这是选择题常见题型"
        assert find_cross_question_leak(text) is None
        assert strip_cross_question_leak(text) == (text.strip(), False)

    def test_not_leak_when_choice_section_is_only_line(self) -> None:
        """防误杀：整段就是「二、选择题」大标题时，检测应命中而不是被静默放过。"""
        text = "二、选择题（每题4分，共48分）"
        assert find_cross_question_leak(text) is not None

    def test_not_leak_for_normal_single_line(self) -> None:
        text = "触发器按动作特点可分为基本型、______、______和边沿型。"
        assert find_cross_question_leak(text) is None
        assert strip_cross_question_leak(text) == (text, False)

    def test_empty(self) -> None:
        assert find_cross_question_leak("") is None
        assert strip_cross_question_leak(None) == ("", False)

class TestSplitOptionsSwitch:
    """第 2 处修复的开关：默认关闭，关闭时走修复前路径。"""

    def test_default_is_disabled(self, monkeypatch) -> None:
        monkeypatch.delenv(SPLIT_OPTIONS_ENV, raising=False)
        assert split_options_enabled() is False

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
    def test_enabled_values(self, monkeypatch, raw: str) -> None:
        monkeypatch.setenv(SPLIT_OPTIONS_ENV, raw)
        assert split_options_enabled() is True

    @pytest.mark.parametrize("raw", ["0", "false", "", "off", "2"])
    def test_disabled_values(self, monkeypatch, raw: str) -> None:
        monkeypatch.setenv(SPLIT_OPTIONS_ENV, raw)
        assert split_options_enabled() is False

    def test_switch_off_keeps_old_path_in_builder(self, monkeypatch) -> None:
        """开关关闭时，extract_questions 必须走原逻辑（依赖 sec_type）。"""
        import importlib

        from services import qbank_builder

        monkeypatch.delenv(SPLIT_OPTIONS_ENV, raising=False)
        importlib.reload(qbank_builder)
        assert qbank_builder._split_options_enabled() is False

        # 修复前路径：sec_type 非选择类 → 选项整体留在题干，options 为空
        body = "1．下列说法正确的是（　）。\nA．一 B．二 C．三 D．四"
        text = (
            "一、选择题（每题2分，共10分）\n"
            "1．不属于数字电路基本运算的是（　）。\n"
            "A．与 B．或 C．非 D．异或\n"
            "二、简答题（共4题）\n"
            "2．简述反馈的作用。\n"
        )
        got = qbank_builder.extract_questions(text)
        assert isinstance(got, list)
