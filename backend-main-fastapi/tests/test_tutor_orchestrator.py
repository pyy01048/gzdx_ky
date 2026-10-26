# -*- coding: utf-8 -*-
"""P1-E 多 Agent 答疑编排器（55 号 DeepTutor 升级方案）测试。

覆盖：
1. retrieve 阶段：返回知识库 hits（monkeypatch AIService.search_knowledge_base）
2. solve 阶段：调用 chat 并返回 content / provider / route
3. verify 阶段：
   - calc 题执行沙箱验算（math_verified=True）
   - 主观题跳过沙箱、执行一致性校验（math_verified=None, consistency 判定）
4. remedy 阶段：输出 suggestions 与 knowledge_point
5. 任一阶段抛异常时整体仍返回 200 结构且 degraded=True
6. API 端到端：POST /api/ai/tutoring/orchestrated 返回含四阶段的 trace；
   题目不存在返回 404

注意：所有 AIService 调用一律 monkeypatch，不依赖真实外部模型。
"""
from __future__ import annotations

import asyncio

import pytest

from database import SessionLocal
from models import QuizQuestion
from services import tutor_orchestrator
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)

TEST_USER_ID = 0


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #
def _make_question(db, *, question_type="calc", answer="9", content="计算 (1+2)*3 的值。"):
    q = QuizQuestion(
        content=content,
        options=None,
        answer=answer,
        analysis="先算括号内加法，再乘 3。",
        subject="数学",
        chapter="QA-高数",
        knowledge_point="QA-四则运算",
        difficulty=2,
        source="自建",
        question_type=question_type,
        answer_type="subjective" if question_type in ("calc", "fill", "essay") else "objective",
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def _stub_ai(monkeypatch, *, hits=None, chat_result=None, chat_side_effect=None):
    """统一 monkeypatch AIService 的检索与对话方法。"""

    async def _fake_chat(self, messages, **kwargs):  # noqa: ARG001
        if chat_side_effect is not None:
            return chat_side_effect(messages, **kwargs)
        return chat_result or {
            "content": "分步解答：先算括号 1+2=3，再乘 3 得 9。",
            "provider": "test-stub",
            "route": "online",
            "route_reason": "测试桩",
        }

    def _fake_search(self, query, limit=6, min_score=1.0, subject=None):  # noqa: ARG001
        if hits is not None:
            return hits
        return [
            {"score": 0.9, "source": "知识分块", "title": "四则运算",
             "content": "先括号后乘除，再加减。", "doc_id": 1, "chunk_id": 1,
             "subject": "数学", "doc_name": "高数讲义"},
        ]

    monkeypatch.setattr("services.ai_service.AIService.chat", _fake_chat)
    monkeypatch.setattr("services.ai_service.AIService.search_knowledge_base", _fake_search)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# retrieve 阶段
# --------------------------------------------------------------------------- #
def test_retrieve_returns_hits(monkeypatch):
    """retrieve 阶段返回知识库 hits，trace 首阶段 status=ok。"""
    _stub_ai(monkeypatch)

    db = SessionLocal()
    try:
        q = _make_question(db)
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id, my_answer="9",
            subject="数学", question=q, knowledge_point="四则运算",
        ))
        retrieve = result["trace"][0]
        assert retrieve["stage"] == "retrieve"
        assert retrieve["status"] == "ok"
        assert len(retrieve["data"]["hits"]) >= 1
        assert retrieve["data"]["hits"][0]["title"] == "四则运算"
    finally:
        db.close()


def test_retrieve_no_hits_still_ok(monkeypatch):
    """知识库无命中时 data.hits=[] 且 status 仍为 ok（不报错）。"""
    _stub_ai(monkeypatch, hits=[])

    db = SessionLocal()
    try:
        q = _make_question(db)
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id, question=q,
        ))
        retrieve = result["trace"][0]
        assert retrieve["stage"] == "retrieve"
        assert retrieve["status"] == "ok"
        assert retrieve["data"]["hits"] == []
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# solve 阶段
# --------------------------------------------------------------------------- #
def test_solve_calls_chat_and_returns_content(monkeypatch):
    """solve 阶段调用 chat 并返回 content；answer 非空且 route=online。"""
    called = {}

    async def _fake_chat(self, messages, **kwargs):  # noqa: ARG001
        called["messages"] = messages
        return {
            "content": "先算括号：1+2=3，再乘 3，得 9。",
            "provider": "test-stub",
            "route": "online",
            "route_reason": "测试桩",
        }

    _stub_ai(monkeypatch, chat_result=None)
    monkeypatch.setattr("services.ai_service.AIService.chat", _fake_chat)

    db = SessionLocal()
    try:
        q = _make_question(db)
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id, my_answer="9",
            question=q, knowledge_point="四则运算",
        ))
        assert result["answer"] == "先算括号：1+2=3，再乘 3，得 9。"
        assert result["route"] == "online"
        assert result["confidence"] in ("high", "medium", "low")
        solve = result["trace"][1]
        assert solve["stage"] == "solve"
        assert solve["status"] == "ok"
        assert solve["data"]["provider"] == "test-stub"
        # messages 包含【题目】【正确答案】【学生答案】【检索到的讲义片段】【考点】
        user_content = called["messages"][-1]["content"]
        assert "【题目】" in user_content
        assert "【正确答案】" in user_content
        assert "【学生答案】" in user_content
        assert "【检索到的讲义片段】" in user_content
        assert "【考点】" in user_content
        assert "【参考解析】" in user_content
    finally:
        db.close()


def test_solve_offline_marks_degraded(monkeypatch):
    """route==offline 时 solve 阶段 status=degraded，但整体仍返回 200 结构。"""
    _stub_ai(monkeypatch, chat_result={
        "content": "（本地知识库离线回答）",
        "provider": "offline-kb",
        "route": "offline",
    })

    db = SessionLocal()
    try:
        q = _make_question(db)
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id, question=q,
        ))
        assert result["degraded"] is True
        solve = result["trace"][1]
        assert solve["status"] == "degraded"
        assert result["answer"]  # 离线兜底文本非空
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# verify 阶段
# --------------------------------------------------------------------------- #
def test_verify_calc_runs_sandbox(monkeypatch):
    """calc 题执行沙箱验算：math_verified=True。"""
    _stub_ai(monkeypatch)

    db = SessionLocal()
    try:
        q = _make_question(db, question_type="calc", answer="(1+2)*3")
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id, my_answer="9",
            question=q,
        ))
        verify = result["trace"][2]
        assert verify["stage"] == "verify"
        assert verify["status"] == "ok"
        ver = verify["data"]["verification"]
        assert ver["math_verified"] is True
        assert ver["consistency"] is True
        assert ver["score_estimate"] is not None
        assert ver["sandbox"]["usable"] is True
    finally:
        db.close()


def test_verify_essay_uses_consistency_only(monkeypatch):
    """主观题（essay）跳过沙箱，math_verified=None，做规则一致性校验。"""
    _stub_ai(monkeypatch)

    db = SessionLocal()
    try:
        q = _make_question(
            db,
            question_type="essay",
            answer="微积分是研究变化的数学工具",
            content="请简述微积分是什么。",
        )
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id,
            my_answer="微积分是研究变化的数学工具",
            question=q,
        ))
        verify = result["trace"][2]
        assert verify["stage"] == "verify"
        assert verify["status"] == "ok"
        ver = verify["data"]["verification"]
        assert ver["math_verified"] is None  # 主观题不执行沙箱
        assert ver["consistency"] is True   # 关键词命中
        assert "sandbox" not in ver         # 主观题不产出沙箱验算卡
    finally:
        db.close()


def test_verify_inconsistent_answer(monkeypatch):
    """学生答案与参考答案不一致时 consistency=False。"""
    _stub_ai(monkeypatch)

    db = SessionLocal()
    try:
        q = _make_question(db, question_type="calc", answer="(1+2)*3")
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id,
            my_answer="我不确定，答案是 100", question=q,
        ))
        ver = result["trace"][2]["data"]["verification"]
        assert ver["consistency"] is False
        assert result["confidence"] == "low"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# remedy 阶段
# --------------------------------------------------------------------------- #
def test_remedy_outputs_suggestions(monkeypatch):
    """remedy 阶段输出 suggestions 与 knowledge_point。"""
    _stub_ai(monkeypatch)

    db = SessionLocal()
    try:
        q = _make_question(db)
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id,
            my_answer="100", question=q, knowledge_point="QA-四则运算",
        ))
        remedy = result["trace"][3]
        assert remedy["stage"] == "remedy"
        assert remedy["status"] == "ok"
        assert remedy["data"]["knowledge_point"] == "QA-四则运算"
        assert len(remedy["data"]["suggestions"]) >= 1
        assert "同类题" in remedy["data"]["suggestions"][0]
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 容错：任一阶段抛异常 → 整体仍返回结构且 degraded
# --------------------------------------------------------------------------- #
def test_retrieve_exception_degrades_but_continues(monkeypatch):
    """retrieve 抛异常 → 该阶段 degraded，后续阶段继续执行。"""

    def _boom_search(self, query, limit=6, min_score=1.0, subject=None):  # noqa: ARG001
        raise RuntimeError("检索服务不可用")

    async def _fake_chat(self, messages, **kwargs):  # noqa: ARG001
        return {"content": "解答", "provider": "stub", "route": "online"}

    monkeypatch.setattr("services.ai_service.AIService.search_knowledge_base", _boom_search)
    monkeypatch.setattr("services.ai_service.AIService.chat", _fake_chat)

    db = SessionLocal()
    try:
        q = _make_question(db)
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id, question=q,
        ))
        assert result["trace"][0]["status"] == "degraded"
        assert result["trace"][1]["status"] == "ok"  # solve 继续执行
        assert len(result["trace"]) == 4
    finally:
        db.close()


def test_solve_exception_falls_back(monkeypatch):
    """solve 抛异常 → 本地兜底答案，degraded=True，请求不 500。"""

    async def _boom_chat(self, messages, **kwargs):  # noqa: ARG001
        raise RuntimeError("模型服务不可用")

    def _fake_search(self, query, limit=6, min_score=1.0, subject=None):  # noqa: ARG001
        return [{"source": "知识分块", "title": "t", "content": "c"}]

    monkeypatch.setattr("services.ai_service.AIService.chat", _boom_chat)
    monkeypatch.setattr("services.ai_service.AIService.search_knowledge_base", _fake_search)

    db = SessionLocal()
    try:
        q = _make_question(db)
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id, question=q,
        ))
        assert result["degraded"] is True
        assert result["trace"][1]["status"] == "degraded"
        assert "本地兜底" in result["answer"]
        assert result["confidence"] == "low"
        # 后续 verify/remedy 仍然存在
        assert [t["stage"] for t in result["trace"]] == ["retrieve", "solve", "verify", "remedy"]
    finally:
        db.close()


def test_verify_exception_degrades(monkeypatch):
    """verify 阶段内部异常 → verification 降级为不可用，整体不 500。"""
    _stub_ai(monkeypatch)
    # 让 sandbox_verify 抛异常
    monkeypatch.setattr(
        "services.subjective_grader.sandbox_verify",
        lambda question, reference_answer: (_ for _ in ()).throw(RuntimeError("沙箱崩溃")),
    )

    db = SessionLocal()
    try:
        q = _make_question(db)
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=q.id, question=q,
        ))
        verify = result["trace"][2]
        assert verify["status"] == "degraded"
        ver = verify["data"]["verification"]
        assert ver["math_verified"] is False
        assert ver["consistency"] is None
        assert ver["summary"] == "验证不可用"
    finally:
        db.close()


def test_question_not_found_returns_early(monkeypatch):
    """题目不存在时编排器返回 question_id + degraded=True，不抛异常。"""
    db = SessionLocal()
    try:
        result = _run(tutor_orchestrator.orchestrate_tutoring(
            db=db, user_id=TEST_USER_ID, question_id=999999999,
        ))
        assert result["question_id"] == 999999999
        assert result["degraded"] is True
        assert result["trace"][0]["stage"] == "retrieve"
        assert result["trace"][0]["status"] == "degraded"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# API 端到端
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _clean_orchestrated_questions():
    """每个用例前后清理本测试文件创建的题目，保证隔离。"""
    db = SessionLocal()
    try:
        db.query(QuizQuestion).filter(
            QuizQuestion.content.in_([
                "计算 (1+2)*3 的值。",
                "请简述微积分是什么。",
            ])
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(QuizQuestion).filter(
            QuizQuestion.content.in_([
                "计算 (1+2)*3 的值。",
                "请简述微积分是什么。",
            ])
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_api_orchestrated_returns_trace(monkeypatch):
    """POST /api/ai/tutoring/orchestrated 返回含四阶段的 trace。"""
    _stub_ai(monkeypatch)

    db = SessionLocal()
    try:
        q = _make_question(db)
        qid = q.id
    finally:
        db.close()

    r = client.post("/api/ai/tutoring/orchestrated", json={
        "question_id": qid,
        "my_answer": "9",
        "subject": "数学",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["question_id"] == qid
    stages = [t["stage"] for t in data["trace"]]
    assert stages == ["retrieve", "solve", "verify", "remedy"]
    assert all(t["status"] == "ok" for t in data["trace"])
    assert data["answer"]
    assert data["confidence"] in ("high", "medium", "low")
    assert data["route"] in ("hybrid", "offline", "local", "online")


def test_api_orchestrated_404():
    """题目不存在时返回 404。"""
    r = client.post("/api/ai/tutoring/orchestrated", json={"question_id": 999999999})
    assert r.status_code == 404