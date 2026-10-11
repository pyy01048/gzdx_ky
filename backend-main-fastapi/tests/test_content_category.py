# -*- coding: utf-8 -*-
"""V11 模块5：内容语义分层（content_category）单元测试。

覆盖：
- classify_content_category 四类分支与优先级（exam > example > method > textbook）
- "模拟部分"（模拟电子技术）不得误判为 exam 的回归
- chunk_size_for_category 差异化切分映射与默认回退
- DB 侧：ingest_text 按 content_category 实际使用差异化 chunk_size（临时库）
"""
from __future__ import annotations

from services.kb_service import (
    classify_content_category,
    chunk_size_for_category,
    CONTENT_CATEGORY_CHUNK,
)


# ---------- 纯函数：分类各分支 ----------
def test_exam_keywords():
    assert classify_content_category("2004年真题逐题细解.txt") == "exam"
    assert classify_content_category("2021年全国硕士研究生招生考试西医综合试题.pdf") == "exam"
    assert classify_content_category("数电复习试卷A.pdf") == "exam"
    assert classify_content_category("26考研408回忆版.pdf") == "exam"
    assert classify_content_category("8月数电第二次月考-重庆邮电大学808.pdf") == "exam"
    # 年份+卷
    assert classify_content_category("2018年冲刺卷第一套.pdf") == "exam"


def test_example_keywords():
    assert classify_content_category("数字电子技术基础章节题库.pdf") == "example"
    assert classify_content_category("数电-阎石-第六版-答案.pdf") == "example"
    assert classify_content_category("555定时器专题-答案部分.txt") == "example"
    assert classify_content_category("触发器专题-习题解答.pdf") == "example"
    assert classify_content_category("典型例题精讲300题.pdf") == "example"


def test_method_keywords():
    assert classify_content_category("【模电】全章节总结.pdf") == "method"
    assert classify_content_category("解题技巧大全.pdf") == "method"
    assert classify_content_category("2004年逐词逐句精讲册.txt") == "method"
    assert classify_content_category("复习攻略.pdf") == "method"


def test_textbook_keywords_and_default():
    assert classify_content_category("数电复习讲义.txt") == "textbook"
    assert classify_content_category("数电学习课件.pdf") == "textbook"
    assert classify_content_category("第1章.pptx") == "textbook"
    # 拿不准兜底 textbook
    assert classify_content_category("安徽大学833.pdf") == "textbook"
    assert classify_content_category("") == "textbook"


def test_priority_exam_beats_example():
    # 同时含"真题"与"题解/答案"：真题优先
    assert classify_content_category("2010年真题及答案速查.txt") == "exam"


def test_analog_dianzi_not_misclassified_as_exam():
    """回归：模拟电子技术的"模拟"不得命中 exam（模拟考试/模拟试题才命中）。"""
    assert classify_content_category("【电子技术基础-模拟部分】康华光 全章节总结.pdf") == "method"
    assert classify_content_category("11第一节 数字-模拟转换器.txt") == "textbook"
    assert classify_content_category("模拟电子技术基础 第6版.pdf") == "textbook"
    # 但真正的模拟考试/试题仍为 exam
    assert classify_content_category("2023年5月模拟电子技术模拟考试.pdf") == "exam"
    assert classify_content_category("数字电子技术基础模拟试题A及答案.pdf") == "exam"


# ---------- 差异化切分 ----------
def test_chunk_size_map():
    assert CONTENT_CATEGORY_CHUNK["textbook"] == (512, 64)
    assert CONTENT_CATEGORY_CHUNK["example"] == (1024, 128)
    assert CONTENT_CATEGORY_CHUNK["exam"] == (2048, 256)
    assert CONTENT_CATEGORY_CHUNK["method"] == (768, 96)


def test_chunk_size_fallback():
    # None / 未知类别 → 旧默认 (600, 80)，保证存量兼容
    assert chunk_size_for_category(None) == (600, 80)
    assert chunk_size_for_category("unknown") == (600, 80)


# ---------- DB 侧：ingest 按类别差异化（临时库） ----------
def test_ingest_uses_category_chunk_size(db_schema):
    from database import SessionLocal
    from models import Document, KnowledgeChunk
    from services.kb_service import ingest_text

    # 构造一段约 5000 字、多段落的重复文本
    para = "组合逻辑电路由门电路构成，其输出仅取决于当前输入。"
    long_text = "\n".join([para * 4] * 30)

    db = SessionLocal()
    try:
        # textbook: chunk_size 512 → 块数多；exam: 2048 → 块数少
        d_tb = Document(file_name="教材讲义.txt", file_type="txt",
                        content=long_text, content_category="textbook")
        d_ex = Document(file_name="2004年真题卷.txt", file_type="txt",
                        content=long_text, content_category="exam")
        db.add_all([d_tb, d_ex])
        db.flush()
        n_tb = ingest_text(db, d_tb.id, d_tb.file_name, long_text,
                           content_category="textbook")
        n_ex = ingest_text(db, d_ex.id, d_ex.file_name, long_text,
                           content_category="exam")
        db.commit()
        # 同样文本，exam 大块 → 明显少于 textbook 小块
        assert n_ex < n_tb
        # 且 exam 单块平均长度更大（块更少且总文本相当）
        assert n_ex >= 1
    finally:
        db.close()
