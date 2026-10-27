# -*- coding: utf-8 -*-
"""三层可审计记忆（55 号方案 P0-1）后端回归测试。

覆盖：
1. L1 轨迹写入（record_trace / record_qa_trace / record_grading_trace）
   - 旁路容错：异常不抛
2. L2 蒸馏（distill_facts）：
   - grading 低分 -> weakness 事实
   - qa 命中疑问词 -> weakness 事实
   - evidence 携带 trace_id（可溯源）
3. L3 综合画像（build_profile）：
   - 聚合 weakness 生成画像，fact_ids 引用 L2
4. 用户纠错（correct_fact / correct_synthesis）：
   - 保留 original_claim / original_summary 快照
   - corrected 字段置真
5. API 层：
   - GET /api/memory/overview
   - GET /api/memory/traces
   - GET /api/memory/facts
   - GET /api/memory/synthesis
   - POST /api/memory/facts/{id}/correct
   - POST /api/memory/synthesis/{id}/correct
   - POST /api/memory/distill
   - POST /api/memory/profile
"""
from __future__ import annotations

import pytest

from database import SessionLocal
from models import MemoryFact, MemorySynthesis, MemoryTrace, QuizQuestion
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)

#: 测试用户（conftest 会在测试库创建 id=0 的 pytest 用户）
TEST_USER_ID = 0


def _make_subjective_question(db, subject="数学"):
    q = QuizQuestion(
        content="请论述微积分在工程中的应用。",
        options=None,
        answer="微积分是研究变化的数学工具。",
        analysis="从极限、导数、积分展开。",
        subject=subject,
        chapter="QA-高数", knowledge_point="QA-微积分",
        difficulty=3, source="自建", question_type="essay",
        answer_type="subjective",
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q.id


@pytest.fixture(autouse=True)
def _clean_memory():
    """每个用例前后清空记忆表，保证隔离。"""
    db = SessionLocal()
    try:
        db.query(MemorySynthesis).filter(MemorySynthesis.user_id == TEST_USER_ID).delete()
        db.query(MemoryFact).filter(MemoryFact.user_id == TEST_USER_ID).delete()
        db.query(MemoryTrace).filter(MemoryTrace.user_id == TEST_USER_ID).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(MemorySynthesis).filter(MemorySynthesis.user_id == TEST_USER_ID).delete()
        db.query(MemoryFact).filter(MemoryFact.user_id == TEST_USER_ID).delete()
        db.query(MemoryTrace).filter(MemoryTrace.user_id == TEST_USER_ID).delete()
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# L1 轨迹写入
# --------------------------------------------------------------------------- #
def test_record_trace_basic():
    from services import memory_service

    db = SessionLocal()
    try:
        tid = memory_service.record_trace(
            user_id=TEST_USER_ID,
            trace_type="study",
            title="学习轨迹",
            payload={"kind": "study", "note": "test"},
            subject="数学",
            db=db,
        )
        assert tid is not None
        row = db.query(MemoryTrace).filter(MemoryTrace.id == tid).first()
        assert row is not None
        assert row.trace_type == "study"
        assert row.payload["kind"] == "study"
    finally:
        db.close()


def test_record_trace_invalid_type_falls_back():
    from services import memory_service

    db = SessionLocal()
    try:
        tid = memory_service.record_trace(
            user_id=TEST_USER_ID,
            trace_type="not-a-type",
            title="x",
            db=db,
        )
        assert tid is not None
        row = db.query(MemoryTrace).filter(MemoryTrace.id == tid).first()
        assert row.trace_type == "qa"  # 非法类型回退 qa
    finally:
        db.close()


def test_record_trace_failure_is_bypassed():
    """旁路容错：user_id 不存在时仍不抛异常（FK 只影响业务表，这里应跳过）。"""
    from services import memory_service

    # 使用超大 user_id 触发 FK 失败（如果 FK 生效），应返回 None 而非抛异常
    result = memory_service.record_trace(
        user_id=999999999,
        trace_type="study",
        title="x",
        payload={},
        db=None,
    )
    # 无论成功或旁路失败，都不抛异常
    assert result is None or isinstance(result, int)


# --------------------------------------------------------------------------- #
# L2 蒸馏
# --------------------------------------------------------------------------- #
def test_distill_grading_weakness():
    from services import memory_service

    db = SessionLocal()
    try:
        qid = _make_subjective_question(db)
        memory_service.record_grading_trace(
            user_id=TEST_USER_ID, question_id=qid, subject="数学",
            question_content="题", my_answer="不会",
            score=3.0, max_score=10.0, evaluation="概念不清", db=db,
        )
        result = memory_service.distill_facts(db, user_id=TEST_USER_ID)
        assert result["created"] >= 1
        facts = memory_service.list_facts(db, user_id=TEST_USER_ID)
        weakness = [f for f in facts if f["fact_type"] == "weakness" and f["subject"] == "数学"]
        assert weakness, "应蒸馏出数学 weakness 事实"
        assert weakness[0]["evidence"][0]["trace_id"] is not None
        assert weakness[0]["evidence"][0]["kind"] == "grading"
    finally:
        db.close()


def test_distill_qa_weakness():
    from services import memory_service

    db = SessionLocal()
    try:
        memory_service.record_qa_trace(
            user_id=TEST_USER_ID,
            question="为什么这个极限不存在？",
            answer="左右极限不相等",
            subject="数学",
            db=db,
        )
        result = memory_service.distill_facts(db, user_id=TEST_USER_ID)
        assert result["created"] >= 1
        facts = memory_service.list_facts(db, user_id=TEST_USER_ID)
        assert any(f["fact_type"] == "weakness" for f in facts)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# L3 综合画像
# --------------------------------------------------------------------------- #
def test_build_profile():
    from services import memory_service

    db = SessionLocal()
    try:
        qid = _make_subjective_question(db)
        memory_service.record_grading_trace(
            user_id=TEST_USER_ID, question_id=qid, subject="数学",
            question_content="题", my_answer="不会",
            score=2.0, max_score=10.0, evaluation="差", db=db,
        )
        memory_service.distill_facts(db, user_id=TEST_USER_ID)
        prof = memory_service.build_profile(db, user_id=TEST_USER_ID)
        assert prof is not None
        assert prof["synth_type"] == "profile"
        assert "数学" in prof["summary"]
        assert isinstance(prof["fact_ids"], list)
        assert len(prof["fact_ids"]) >= 1
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 用户纠错
# --------------------------------------------------------------------------- #
def test_correct_fact_keeps_original():
    from services import memory_service

    db = SessionLocal()
    try:
        qid = _make_subjective_question(db)
        memory_service.record_grading_trace(
            user_id=TEST_USER_ID, question_id=qid, subject="数学",
            question_content="题", my_answer="不会",
            score=3.0, max_score=10.0, evaluation="差", db=db,
        )
        memory_service.distill_facts(db, user_id=TEST_USER_ID)
        facts = memory_service.list_facts(db, user_id=TEST_USER_ID)
        fid = facts[0]["id"]

        updated = memory_service.correct_fact(
            db, user_id=TEST_USER_ID, fact_id=fid,
            corrected_claim="我其实会做，只是粗心",
        )
        assert updated is not None
        assert updated["user_corrected"] is True
        assert updated["corrected_claim"] == "我其实会做，只是粗心"
        assert updated["original_claim"] is not None
        assert updated["original_claim"] == facts[0]["claim"]
    finally:
        db.close()


def test_correct_synthesis_keeps_original():
    from services import memory_service

    db = SessionLocal()
    try:
        qid = _make_subjective_question(db)
        memory_service.record_grading_trace(
            user_id=TEST_USER_ID, question_id=qid, subject="数学",
            question_content="题", my_answer="不会",
            score=3.0, max_score=10.0, evaluation="差", db=db,
        )
        memory_service.distill_facts(db, user_id=TEST_USER_ID)
        prof = memory_service.build_profile(db, user_id=TEST_USER_ID)
        sid = prof["id"]

        updated = memory_service.correct_synthesis(
            db, user_id=TEST_USER_ID, synthesis_id=sid,
            corrected_summary="用户纠正后的画像",
        )
        assert updated is not None
        assert updated["user_corrected"] is True
        assert updated["corrected_summary"] == "用户纠正后的画像"
        assert updated["original_summary"] is not None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# API 层
# --------------------------------------------------------------------------- #
def _seed_memory():
    from services import memory_service

    db = SessionLocal()
    try:
        qid = _make_subjective_question(db)
        memory_service.record_grading_trace(
            user_id=TEST_USER_ID, question_id=qid, subject="数学",
            question_content="题", my_answer="不会",
            score=3.0, max_score=10.0, evaluation="差", db=db,
        )
        memory_service.distill_facts(db, user_id=TEST_USER_ID)
        memory_service.build_profile(db, user_id=TEST_USER_ID)
    finally:
        db.close()


def test_api_overview():
    _seed_memory()
    resp = client.get("/api/memory/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trace_count"] >= 1
    assert data["fact_count"] >= 1
    assert data["synthesis_count"] >= 1
    assert data["layers"]["l1_traces"] >= 1


def test_api_traces_list():
    _seed_memory()
    resp = client.get("/api/memory/traces")
    assert resp.status_code == 200
    traces = resp.json()
    assert len(traces) >= 1
    assert traces[0]["trace_type"] == "grading"
    assert traces[0]["payload"]["kind"] == "grading"


def test_api_facts_list_and_correct():
    _seed_memory()
    resp = client.get("/api/memory/facts")
    assert resp.status_code == 200
    facts = resp.json()
    assert len(facts) >= 1
    fid = facts[0]["id"]

    resp = client.post(
        f"/api/memory/facts/{fid}/correct",
        json={"corrected_claim": "我其实会做，只是粗心"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_corrected"] is True
    assert data["original_claim"] is not None


def test_api_synthesis_list_and_correct():
    _seed_memory()
    resp = client.get("/api/memory/synthesis")
    assert resp.status_code == 200
    syns = resp.json()
    assert len(syns) >= 1
    sid = syns[0]["id"]

    resp = client.post(
        f"/api/memory/synthesis/{sid}/correct",
        json={"corrected_summary": "用户纠正后的画像"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_corrected"] is True
    assert data["original_summary"] is not None


def test_api_distill_and_profile():
    from services import memory_service

    db = SessionLocal()
    try:
        qid = _make_subjective_question(db)
        memory_service.record_grading_trace(
            user_id=TEST_USER_ID, question_id=qid, subject="数学",
            question_content="题", my_answer="不会",
            score=3.0, max_score=10.0, evaluation="差", db=db,
        )
    finally:
        db.close()

    resp = client.post("/api/memory/distill", json={"limit_traces": 100})
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] >= 1

    resp = client.post("/api/memory/profile")
    assert resp.status_code == 200
    prof = resp.json()
    assert prof["synth_type"] == "profile"


def test_api_trace_detail_404():
    resp = client.get("/api/memory/traces/999999999")
    assert resp.status_code == 404