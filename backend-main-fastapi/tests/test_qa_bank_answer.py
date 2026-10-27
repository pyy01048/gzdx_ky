# -*- coding: utf-8 -*-
"""题库确定性答案优先（qa_foundation.find_bank_answer）单测。

覆盖：命中 / 无关不误报 / llm_generated 排除 / 低置信排除。
数据用「flush 不 commit、测完 rollback」方式，不污染测试库。
"""
import pytest

from services.qa_foundation import find_bank_answer

STEM = "已知逻辑函数表达式为L=AB+AC，画出实现该式的逻辑电路图，限使用非门和2输入或非门。"


@pytest.fixture()
def db():
    from database import SessionLocal
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _mk_bank(db):
    from models import QuizQuestion
    q = QuizQuestion(
        content=STEM,
        options={"A": "x", "B": "y"}, answer="B", analysis="由摩根定律展开。",
        subject="数字电子技术", question_type="single",
        answer_source="bank", answer_confidence=1.0,
        is_available=True, is_junk=False)
    db.add(q)
    db.flush()
    return q


def test_bank_answer_hit(db):
    _mk_bank(db)
    hit = find_bank_answer(db, f"请帮我解答这道题：{STEM}谢谢")
    assert hit is not None
    assert hit["answer"] == "B"
    assert hit["answer_source"] == "bank"
    assert hit["subject"] == "数字电子技术"
    db.rollback()


def test_irrelevant_query_no_hit(db):
    assert find_bank_answer(db, "今天天气怎么样，我们出去走走吧") is None


def test_llm_generated_source_excluded(db):
    from models import QuizQuestion
    q = QuizQuestion(
        content="完全另一道无关的题目，讨论泰勒公式在证明题里的应用技巧与常见陷阱。",
        answer="A", answer_source="llm_generated",
        is_available=True, is_junk=False)
    db.add(q)
    db.flush()
    assert find_bank_answer(
        db, "完全另一道无关的题目，讨论泰勒公式在证明题里的应用技巧与常见陷阱。") is None
    db.rollback()


def test_low_confidence_excluded(db):
    from models import QuizQuestion
    q = QuizQuestion(
        content=STEM, answer="C", answer_source="source_extract",
        answer_confidence=0.3, is_available=True, is_junk=False)
    db.add(q)
    db.flush()
    # answer_confidence < 0.8 → 不作为确定性答案直接展示
    assert find_bank_answer(db, f"这道题怎么做：{STEM}") is None
    db.rollback()
