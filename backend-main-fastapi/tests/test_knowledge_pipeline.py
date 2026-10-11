"""知识库三级结构 / 真题抽取 / 复习进度 的回归测试。

覆盖 V4 新增的四个核心能力：
- 科目与题型口径（taxonomy）
- 真题 → 结构化题库（qbank_builder）
- 知识点清洗与章节归位（kp_cleaner）
- 复习进度调度（review_service）

这些测试**不依赖数据库**，因此可在任意环境运行：
    pytest tests/test_knowledge_pipeline.py -v
"""
import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services import taxonomy, kp_cleaner, qbank_builder, structure_parser, review_service


# --------------------------------------------------------------------------- #
# 一、科目 / 章节 / 题型口径
# --------------------------------------------------------------------------- #

class TestTaxonomy:

    def test_core_subjects_are_834_scoped(self):
        """主线科目 = 考试口径，只含要考的几门。"""
        assert set(taxonomy.CORE_SUBJECTS) == {
            "数字电子技术", "模拟电子技术", "数学", "英语", "政治", "真题综合"
        }

    def test_major_subjects_present(self):
        """专业课支撑范围必须覆盖电子信息/电气大类 + 408。"""
        for s in ("电路", "信号与系统", "通信原理", "光学与工程光学",
                  "普通物理", "计算机学科专业基础408"):
            assert s in taxonomy.MAJOR_SUBJECTS

    def test_extension_subjects_excluded_from_core(self):
        """拓展资料不进考试口径。"""
        for s in ("电路分析", "光学", "网络补充"):
            assert s in taxonomy.EXT_SUBJECTS
            assert not taxonomy.is_core(s)

    def test_major_subjects_supported_but_not_core(self):
        """专业课支撑科目（电路/信号/通信/光学/普物/408）:
        要能录入资料、出题、路由，但**不算进复习进度口径** ——
        否则会把没考的科目算进进度统计。
        """
        for s in ("电路", "信号与系统", "通信原理",
                  "光学与工程光学", "普通物理", "计算机学科专业基础408"):
            assert s in taxonomy.MAJOR_SUBJECTS
            assert taxonomy.is_major(s), f"{s} 应为专业课支撑科目"
            assert not taxonomy.is_core(s), f"{s} 不应计入考试口径"
            assert taxonomy.is_exam_scoped(s), f"{s} 应可参与出题与路由"

    def test_every_subject_has_chapters_and_types(self):
        """新增科目必须有大纲章节和题型，否则结构化落不了地。"""
        for s in taxonomy.ALL_SUBJECTS:
            assert taxonomy.chapters_of(s), f"{s} 缺章节大纲"
            assert taxonomy.question_types_of(s), f"{s} 缺题型定义"

    def test_major_subject_aliases(self):
        """专业课常见别名要能归一化。"""
        assert taxonomy.normalize_subject("电路分析基础") == "电路"
        assert taxonomy.normalize_subject("信号与线性系统") == "信号与系统"
        assert taxonomy.normalize_subject("工程光学") == "光学与工程光学"
        assert taxonomy.normalize_subject("大学物理") == "普通物理"
        assert taxonomy.normalize_subject("408") == "计算机学科专业基础408"
        assert taxonomy.normalize_subject("数电") == "数字电子技术"
        assert taxonomy.normalize_subject("模电") == "模拟电子技术"

    def test_subject_aliases_normalized(self):
        """834 合并科目等旧名要归一化。"""
        assert taxonomy.normalize_subject("电子技术基础") == "数字电子技术"
        assert taxonomy.normalize_subject("数字电路") == "数字电子技术"
        assert taxonomy.normalize_subject("模拟电路") == "模拟电子技术"
        assert taxonomy.normalize_subject("高等数学") == "数学"
        assert taxonomy.normalize_subject("英语二") == "英语"
        assert taxonomy.normalize_subject(None) == "其他"

    def test_digital_chapters_follow_yan_shi_6th(self):
        """数电 8 章要对齐阎石第 6 版。"""
        chapters = taxonomy.chapters_of("数字电子技术")
        assert len(chapters) == 8
        assert chapters[0] == "第1章 数制和码制"
        assert "第4章 组合逻辑电路" in chapters
        assert "第6章 时序逻辑电路" in chapters

    def test_analog_chapters_count(self):
        assert len(taxonomy.chapters_of("模拟电子技术")) == 10

    def test_question_types_per_subject(self):
        assert "画波形" in taxonomy.question_types_of("数字电子技术")
        assert "化简" in taxonomy.question_types_of("数字电子技术")
        assert taxonomy.question_types_of("英语") == [
            "完形", "阅读", "新题型", "翻译", "小作文", "大作文"
        ]

    def test_guess_question_type(self):
        assert taxonomy.guess_question_type("三、计算题", "模拟电子技术") == "计算"
        assert taxonomy.guess_question_type("一、填空题", "数字电子技术") == "填空"
        assert taxonomy.guess_question_type("毫无线索的句子", "数学") == ""

    def test_extension_subject_has_no_issue(self):
        """拓展科目也要有章节与题型，不能是空壳。"""
        for s in taxonomy.EXT_SUBJECTS:
            assert taxonomy.chapters_of(s), f"{s} 缺章节定义"
            assert taxonomy.question_types_of(s), f"{s} 缺题型定义"


# --------------------------------------------------------------------------- #
# 二、知识点清洗（垃圾识别）
# --------------------------------------------------------------------------- #

class TestKpCleaner:

    def test_accepts_real_concept_names(self):
        for name in ("触发器", "JK触发器", "卡诺图", "静态工作点", "TTL与非门"):
            r = kp_cleaner.assess_knowledge_point(name, "数字电子技术")
            assert r["is_valid"], f"{name} 被误判为垃圾: {r['reason']}"

    def test_rejects_slide_navigation_noise(self):
        """真实的抽取噪声："下页总目录推出下页返回一、概述获取矩形"。"""
        r = kp_cleaner.assess_knowledge_point(
            "第一节 几种常用的脉冲波形的产生和整形电路施密特触发器单稳态触发器概述多谐振荡器下页总目录推出下页返回一、概述获取矩形",
            "数字电子技术",
        )
        assert not r["is_valid"]
        assert r["reason"]

    def test_rejects_ocr_fragment(self):
        r = kp_cleaner.assess_knowledge_point("11010010 11010011返回上页[例1", "数字电子技术")
        assert not r["is_valid"]

    def test_rejects_sentence_fragment(self):
        """断句残片以虚词结尾，不是概念名。"""
        r = kp_cleaner.assess_knowledge_point("换器低，但比计数型A/D转换器的转换速度要高得多", "数字电子技术")
        assert not r["is_valid"]

    def test_rejects_empty_and_tiny(self):
        assert not kp_cleaner.assess_knowledge_point("", "数学")["is_valid"]
        assert not kp_cleaner.assess_knowledge_point("的", "数学")["is_valid"]

    def test_chapter_mapping_by_number(self):
        """'第4章' 这种残缺章名要对齐到大纲的标准章名。"""
        assert kp_cleaner.map_chapter("译码器", "第4章", "数字电子技术") == "第4章 组合逻辑电路"

    def test_chapter_mapping_by_keyword(self):
        """章名存的是文件名时，靠关键词归位。"""
        got = kp_cleaner.map_chapter("卡诺图化简", "数电讲义", "数字电子技术")
        assert got == "第2章 逻辑代数基础"

    def test_chapter_mapping_refuses_when_unsure(self):
        """不确定时宁可返回 None，也不塞错误章节。"""
        assert kp_cleaner.map_chapter("完全无关的内容", None, "政治") is None

    def test_chapter_mapping_clear_winner_wins(self):
        """证据明确时要归位（亚军远低于冠军）。"""
        assert kp_cleaner.map_chapter("卡诺图化简方法", None, "数字电子技术") == "第2章 逻辑代数基础"

    def test_chapter_mapping_respects_subject(self):
        """同名知识点在不同科目要归到各自的章。"""
        analog = kp_cleaner.map_chapter("共射放大电路", None, "模拟电子技术")
        assert analog == "第2章 基本放大电路"


# --------------------------------------------------------------------------- #
# 三、真题 → 结构化题库
# --------------------------------------------------------------------------- #

SAMPLE_EXAM = """电子技术基础练习题
一、选择题（共2题，每题2分）
1. 集成运放构成反相比例放大器时，反馈类型为（）
        A. 正反馈  B. 电压串联负反馈  C. 电压并联负反馈  D. 电流并联负反馈
2. 下列寄存器中，能实现数据移位功能的是（）
        A. 并行输入并行输出寄存器  B. 移位寄存器
二、填空题（共2题，每题2分）
1. 三极管的电流分配关系满足______。
2. 组合逻辑电路设计的核心步骤是写出______。
三、判断题（共1题）
1. 负反馈会减小放大电路的放大倍数。
"""


class TestQbankBuilder:

    def test_extract_questions_from_exam(self):
        qs = qbank_builder.extract_questions(SAMPLE_EXAM)
        assert len(qs) >= 4
        types = {q["section_type"] for q in qs}
        assert "选择" in types
        assert "填空" in types

    def test_extract_options_for_choice(self):
        qs = qbank_builder.extract_questions(SAMPLE_EXAM)
        choice = [q for q in qs if q["section_type"] == "选择"]
        assert choice, "未抽出选择题"
        assert len(choice[0]["options"]) >= 3
        assert choice[0]["options"][0].startswith("A")

    def test_empty_or_short_text_returns_nothing(self):
        assert qbank_builder.extract_questions("") == []
        assert qbank_builder.extract_questions("太短") == []

    def test_guess_subject_digital_vs_analog(self):
        assert qbank_builder._guess_subject("逻辑函数的卡诺图化简与触发器") == "数字电子技术"
        assert qbank_builder._guess_subject("共射放大电路的静态工作点与反馈") == "模拟电子技术"
        assert qbank_builder._guess_subject("完全无关的一句话") is None

    def test_classify_question_assigns_chapter(self):
        """题干点明了所属章的关键概念时，应归到该章。"""
        cls = qbank_builder.classify_question(
            "共射极放大电路的静态工作点如何计算",
            subject_hint="模拟电子技术", section_type="选择",
        )
        assert cls["subject"] == "模拟电子技术"
        assert cls["chapter"] == "第2章 基本放大电路"
        assert cls["question_type"] == "single"

    def test_question_chapter_prefers_dominant_evidence(self):
        """一条题干牵涉多章时，取证据最强的一章（集成运放 → 第4章）。"""
        cls = qbank_builder.classify_question(
            "集成运放构成反相比例放大器时，反馈类型为（）",
            subject_hint="模拟电子技术", section_type="选择",
        )
        assert cls["chapter"] == "第4章 集成运算放大电路"

    def test_no_chapter_when_evidence_is_balanced(self):
        """两章证据接近时判为不确定，返回 None —— 宁可不归章也不归错章。

        构造"与或非"（第2章）与"集成运放"（第4章）等权并列的输入：
        两章得分相同，任何选择都是猜测，所以必须返回 None。
        """
        assert kp_cleaner.map_chapter("与或非与集成运放", None, "数字电子技术") is None

    def test_question_type_mapping(self):
        assert qbank_builder._norm_qtype("填空") == "fill"
        assert qbank_builder._norm_qtype("判断") == "judge"
        assert qbank_builder._norm_qtype("计算") == "calc"
        assert qbank_builder._norm_qtype("选择") == "single"

    def test_content_hash_dedup_ignores_punctuation(self):
        a = qbank_builder.content_hash("触发器是什么？")
        b = qbank_builder.content_hash("触发器是什么")
        assert a == b


# --------------------------------------------------------------------------- #
# 四、复习进度调度
# --------------------------------------------------------------------------- #

class TestReviewScheduling:

    def test_mastered_extends_interval(self):
        interval, ef, nxt = review_service.next_review_at(
            review_count=3, ease_factor=2.5, interval=10, result="mastered"
        )
        assert interval > 10
        # P0-4：next_review_at 返回 naive UTC，比较基准也必须 naive
        assert nxt > datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    def test_forgotten_resets_interval(self):
        interval, ef, nxt = review_service.next_review_at(
            review_count=5, ease_factor=2.5, interval=30, result="forgotten"
        )
        assert interval == 1
        assert ef >= 1.3          # EF 有下限

    def test_interval_capped_at_60_days(self):
        interval, ef, _ = review_service.next_review_at(
            review_count=20, ease_factor=3.0, interval=55, result="mastered"
        )
        assert interval <= 60

    def test_ease_factor_floor(self):
        interval, ef, _ = review_service.next_review_at(
            review_count=1, ease_factor=1.3, interval=1, result="forgotten"
        )
        assert ef >= 1.3

    def test_result_grade_and_delta_tables_are_consistent(self):
        assert set(review_service.RESULT_GRADE) == set(review_service.MASTERY_DELTA)
        assert review_service.RESULT_GRADE["forgotten"] < review_service.RESULT_GRADE["mastered"]
        assert review_service.MASTERY_DELTA["forgotten"] < 0
        assert review_service.MASTERY_DELTA["mastered"] > 0


# --------------------------------------------------------------------------- #
# 五、正文 → 章节树
# --------------------------------------------------------------------------- #

class TestStructureParser:

    SAMPLE = """第1章 数制和码制
1.1 几种常用的数制
二进制是逢二进一。
1.2 二进制算术运算
反码补码运算规则。
第2章 逻辑代数基础
2.1 逻辑代数中的三种基本运算
与或非三种运算。
"""

    def test_parses_chapters(self):
        parsed = structure_parser.parse_structure(self.SAMPLE, "数字电子技术")
        assert parsed["level"] == "structured"
        titles = parsed["chapter_titles"]
        assert "第1章 数制和码制" in titles
        assert "第2章 逻辑代数基础" in titles

    def test_parses_sections(self):
        parsed = structure_parser.parse_structure(self.SAMPLE, "数字电子技术")
        ch1 = parsed["chapters"][0]
        assert len(ch1["sections"]) >= 2

    def test_flat_text_degrades_gracefully(self):
        """没有章节结构的正文不应报错，只标记为 flat。"""
        parsed = structure_parser.parse_structure("这是一段没有章节结构的普通正文。" * 5, "数学")
        assert parsed["level"] == "flat"
        assert parsed["chapters"] == []

    def test_summarize_shape(self):
        parsed = structure_parser.parse_structure(self.SAMPLE, "数字电子技术")
        s = structure_parser.summarize(parsed)
        assert s["chapter_count"] == len(parsed["chapters"])
        assert "chapters" in s

# --------------------------------------------------------------------------- #
# 学科分类回归（2026-10 修复：文档类型词曾被当科目信号）
# --------------------------------------------------------------------------- #

class TestSubjectClassification:
    """分类器曾把"精讲册/逐词逐句/阅读"这类**文档形态词**当科目信号，
    导致 187 篇电子技术资料被误标为「英语」。以下用例锁死正确行为。
    """

    def test_electronics_not_misclassified_as_english(self):
        """带"精讲册/真题解析/逐题细解"的电子技术资料不能判成英语。"""
        from services.kb_service import classify_subject
        cases = [
            ("【电子技术基础-数字部分】康华光 考研真题解析 讲义.pdf", "数字电子技术"),
            ("【电子技术基础-模拟部分】康华光 课后答案.pdf", "模拟电子技术"),
            ("数字电子技术基础同步辅导 课后习题全解答案 高教阎石第5版.pdf", "数字电子技术"),
            ("2023年5月模拟电子技术模拟考试答案.pdf", "模拟电子技术"),
            ("《考研专业课真题必练（含关键考点点评）：数字电路》.pdf", "数字电子技术"),
        ]
        for name, expect in cases:
            assert classify_subject(name) == expect, f"{name} 分类错误"

    def test_english_still_detected(self):
        """真英语资料仍要判对（靠文件名或正文拉丁字母密度）。"""
        from services.kb_service import classify_subject
        assert classify_subject("27考研词汇闪过抗遗忘时间规划打卡表.pdf") == "英语"
        assert classify_subject("考研英语长难句解析.pdf") == "英语"
        # 文件名不含科目信息时，靠正文判定
        en = ("Many theories concerning the causes of juvenile delinquency focus either "
              "on the individual or on society as the major contributing influence.")
        assert classify_subject("2004年真题逐题细解.txt", en) == "英语"

    def test_chapter_words_not_confused_with_circuit_theory(self):
        """数电/模电的"XX电路"章节名不能判成电路理论。"""
        from services.kb_service import classify_subject
        for name in ("中规模时序电路分析专题-试题部分.txt",
                     "异步时序电路分析专题-答案部分.txt",
                     "组合电路分析设计-数据选择器专题-答案部分.txt",
                     "10第一节 几种常用的脉冲波形的产生和整形电路.txt"):
            assert classify_subject(name) == "数字电子技术", f"{name} 误判"

    def test_real_circuit_theory_detected(self):
        from services.kb_service import classify_subject
        for name in ("邱关源电路课后习题答案.pdf",
                     "电路分析基础-戴维南定理.pdf",
                     "电路分析-网孔电流法.pdf"):
            assert classify_subject(name) == "电路", f"{name} 误判"

    def test_math_abbreviations(self):
        from services.kb_service import classify_subject
        assert classify_subject("概统框架.pdf") == "数学"
        assert classify_subject("概率统计讲义.pdf") == "数学"

    def test_major_subjects_detected(self):
        from services.kb_service import classify_subject
        assert classify_subject("郑君里信号与系统习题解答.pdf") == "信号与系统"
        assert classify_subject("樊昌信通信原理课后答案.pdf") == "通信原理"
        assert classify_subject("郁道银工程光学课后答案.pdf") == "光学与工程光学"
        assert classify_subject("大学物理课后习题解答.pdf") == "普通物理"

    def test_parse_failure_text_not_used(self):
        """解析失败留下的英文报错不能被当成英语资料。"""
        from services.kb_service import classify_subject, is_parse_failure
        bad = "[解析失败 .ppt: Package not found at 'D:\\x.ppt']"
        assert is_parse_failure(bad)
        assert classify_subject("7第二节 随机存储器.ppt", bad) == "数字电子技术"
        assert not is_parse_failure("正常的中文正文")

    def test_short_fragment_not_english(self):
        """几十个字符的 OCR 碎片不足以定成英语（曾误判微信图片）。"""
        from services.kb_service import classify_subject_confidence
        got, conf = classify_subject_confidence(
            "微信图片_20260611000715_137_695.jpg", "[OCR]ab cd ef gh ij kl"
        )
        assert not conf, "短碎片不应给出高置信判定"

    def test_low_confidence_for_generic_names(self):
        """只有"第1章"这类无信息名称时，应报低置信。"""
        from services.kb_service import classify_subject_confidence
        got, conf = classify_subject_confidence("第1章.pptx", "")
        assert not conf

    def test_confidence_true_for_clear_names(self):
        from services.kb_service import classify_subject_confidence
        got, conf = classify_subject_confidence("异步时序电路分析专题-答案部分.txt", "")
        assert conf and got == "数字电子技术"

    def test_classify_returns_standard_subject(self):
        """分类结果必须落在标准科目表内（否则前端筛选会漏数据）。"""
        from services.kb_service import classify_subject
        from services import taxonomy
        for name in ("邱关源电路.pdf", "未知文件.xyz", "英语真题.pdf", "第1章.pptx"):
            assert classify_subject(name) in taxonomy.ALL_SUBJECTS
