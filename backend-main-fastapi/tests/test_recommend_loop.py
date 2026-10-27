# -*- coding: utf-8 -*-
"""闭环个性化推题（55 号方案 P0-C）后端测试。

覆盖：
1. identify_weak_points：无数据时返回空列表（不抛异常）
2. generate_variant_questions：
   - 不存在的 kp_id 抛 ValueError
   - 模型输出非法 JSON → 降级返回 {"created": 0, "error": ...}
   - 模型输出合法 JSON → 创建 QuizQuestion（source_label="ai:variant"、variant_group）
3. mastery_gate：不存在的 kp 返回 reason=="kp_not_found"
4. API 冒烟：GET /api/recommend/weak-points、POST /api/recommend/mastery-gate
"""
from __future__ import annotations

import json

import pytest

from database import SessionLocal
from models import KnowledgePoint, QuizQuestion
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)

#: 测试用户（conftest 会在测试库创建 id=0 的 pytest 用户）
TEST_USER_ID = 0


@pytest.fixture(autouse=True)
def _clean_recommend_data():
    """每个用例前后清理变式题 / 融合测试数据，保证隔离。"""
    from models import ErrorKnowledgeLink, ErrorRecord, MemoryFact

    db = SessionLocal()
    try:
        db.query(QuizQuestion).filter(
            QuizQuestion.source_label == "ai:variant"
        ).delete(synchronize_session=False)
        db.query(ErrorKnowledgeLink).delete(synchronize_session=False)
        db.query(ErrorRecord).filter(ErrorRecord.user_id == TEST_USER_ID).delete(
            synchronize_session=False
        )
        db.query(MemoryFact).filter(MemoryFact.user_id == TEST_USER_ID).delete(
            synchronize_session=False
        )
        db.query(KnowledgePoint).filter(
            KnowledgePoint.name.in_(["QA-变式测试点", "QA-融合测试点"])
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(QuizQuestion).filter(
            QuizQuestion.source_label == "ai:variant"
        ).delete(synchronize_session=False)
        db.query(ErrorKnowledgeLink).delete(synchronize_session=False)
        db.query(ErrorRecord).filter(ErrorRecord.user_id == TEST_USER_ID).delete(
            synchronize_session=False
        )
        db.query(MemoryFact).filter(MemoryFact.user_id == TEST_USER_ID).delete(
            synchronize_session=False
        )
        db.query(KnowledgePoint).filter(
            KnowledgePoint.name.in_(["QA-变式测试点", "QA-融合测试点"])
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _make_kp(db, name="QA-变式测试点", subject="数学", chapter="QA-高数", mastery=40):
    kp = KnowledgePoint(
        name=name, subject=subject, chapter=chapter,
        mastery=mastery, exam_frequency=3, difficulty=3,
    )
    db.add(kp)
    db.commit()
    db.refresh(kp)
    return kp


# --------------------------------------------------------------------------- #
# identify_weak_points
# --------------------------------------------------------------------------- #
def test_identify_weak_points_empty():
    """无任何数据时返回空列表，不抛异常。"""
    from services.recommend_loop import identify_weak_points

    db = SessionLocal()
    try:
        result = identify_weak_points(db, user_id=TEST_USER_ID)
        assert result == []
    finally:
        db.close()


def test_identify_weak_points_fusion():
    """错题密度 + 记忆事实两个信号融合：error_count / memory_fact_count / sources 正确。"""
    from models import ErrorKnowledgeLink, ErrorRecord, MemoryFact
    from services.recommend_loop import identify_weak_points

    db = SessionLocal()
    try:
        kp = _make_kp(db, name="QA-融合测试点", mastery=0)
        # 信号 A：错题关联
        err = ErrorRecord(
            user_id=TEST_USER_ID, content="QA 融合错题",
            my_answer="A", correct_answer="B", error_reason="概念不清",
            subject="数学", status="active",
        )
        db.add(err)
        db.commit()
        db.refresh(err)
        db.add(ErrorKnowledgeLink(
            error_id=err.id, knowledge_point_id=kp.id, relevance=1.0, source="manual",
        ))
        # 信号 C：记忆 weakness 事实
        db.add(MemoryFact(
            user_id=TEST_USER_ID, fact_type="weakness", subject="数学",
            knowledge_point_id=kp.id, kp_name=kp.name,
            claim="QA weakness", confidence=0.5, evidence=[],
        ))
        db.commit()

        result = identify_weak_points(db, user_id=TEST_USER_ID, limit=10)
        assert result, "应识别出融合薄弱点"
        item = result[0]
        assert item["knowledge_point_id"] == kp.id
        assert item["error_count"] >= 1
        assert item["memory_fact_count"] >= 1
        assert "error" in item["sources"]
        assert "memory" in item["sources"]
        assert item["weak_score"] > 0
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# generate_variant_questions
# --------------------------------------------------------------------------- #
def test_generate_variants_kp_not_found():
    """不存在的 kp_id 抛 ValueError。"""
    from services.recommend_loop import generate_variant_questions

    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            generate_variant_questions(db, user_id=TEST_USER_ID, kp_id=999999999)
    finally:
        db.close()


def test_generate_variants_invalid_json(monkeypatch):
    """模型输出非法 JSON 时降级返回 {"created": 0, "error": ...}，不抛异常。"""

    def _fake_chat(*args, **kwargs):
        return {"answer": "这不是 JSON，只是一段文字"}

    # 函数内是 from services.model_gateway import get_gateway，
    # 因此需要 patch model_gateway 模块的 get_gateway。
    monkeypatch.setattr(
        "services.model_gateway.get_gateway", lambda: type("G", (), {"chat": _fake_chat})()
    )

    from services.recommend_loop import generate_variant_questions

    db = SessionLocal()
    try:
        kp = _make_kp(db)
        result = generate_variant_questions(db, user_id=TEST_USER_ID, kp_id=kp.id)
        assert result["created"] == 0
        assert "error" in result
    finally:
        db.close()


def test_generate_variants_valid_json(monkeypatch):
    """模型输出合法 JSON 时创建题目，断言 QuizQuestion 新增与来源标记。"""

    def _fake_chat(*args, **kwargs):
        return {
            "answer": json.dumps([{
                "content": "变式题：计算极限 lim(x→0) sin x / x",
                "options": None,
                "answer": "1",
                "analysis": "重要极限",
                "question_type": "calc",
                "answer_type": "subjective",
            }], ensure_ascii=False)
        }

    monkeypatch.setattr(
        "services.model_gateway.get_gateway", lambda: type("G", (), {"chat": _fake_chat})()
    )

    from services.recommend_loop import generate_variant_questions

    db = SessionLocal()
    try:
        kp = _make_kp(db)
        result = generate_variant_questions(db, user_id=TEST_USER_ID, kp_id=kp.id, count=1)
        assert result["created"] == 1
        assert result["variant_group"] == f"variant:{kp.id}"
        assert len(result["question_ids"]) == 1

        q = db.query(QuizQuestion).filter(QuizQuestion.id == result["question_ids"][0]).first()
        assert q is not None
        assert q.source_label == "ai:variant"
        assert q.ai_generated is True
        assert q.verified is False
        assert q.variant_group == f"variant:{kp.id}"
        assert q.knowledge_point == kp.name
        assert q.subject == kp.subject
        assert q.chapter == kp.chapter
        assert q.question_type == "calc"
        assert q.answer_type == "subjective"
        assert q.is_available is True
        assert q.is_junk is False
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# mastery_gate
# --------------------------------------------------------------------------- #
def test_mastery_gate_kp_not_found():
    """不存在的 kp 返回 reason=="kp_not_found"。"""
    from services.recommend_loop import mastery_gate

    db = SessionLocal()
    try:
        result = mastery_gate(db, user_id=TEST_USER_ID, kp_id=999999999)
        assert result["mastered"] is False
        assert result["reason"] == "kp_not_found"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# API 冒烟
# --------------------------------------------------------------------------- #
def test_api_weak_points():
    resp = client.get("/api/recommend/weak-points")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


def test_api_mastery_gate_kp_not_found():
    resp = client.post(
        "/api/recommend/mastery-gate",
        json={"kp_id": 999999999, "consecutive_required": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reason"] == "kp_not_found"