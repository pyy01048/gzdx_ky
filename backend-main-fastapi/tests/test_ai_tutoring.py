# -*- coding: utf-8 -*-
"""V14 场景化讲题回归：explain 三视角 + 追问（无 LLM 走降级包，云端即可测）。"""
from __future__ import annotations

import pytest

from database import Base, SessionLocal, engine
from models import QuizQuestion
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # 幂等：8801 是固定种子 id，上一次跑留下的行会让本次 INSERT 撞
        # ``quiz_questions_pkey`` (UniqueViolation)，4 个用例连带 ERROR。
        # 种子行只被本文件消费，先删后建是安全的。
        from sqlalchemy import text as _text

        db.execute(_text("DELETE FROM quiz_questions WHERE id = 8801"))
        db.commit()
        db.add(QuizQuestion(id=8801, content="TTL 与非门多余输入端？",
                            options='{"A":"接地","B":"接高电平"}', answer="B",
                            analysis="多余端接高电平不影响逻辑功能",
                            knowledge_point="TTL 门电路", subject="数电"))
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize("angle", ["why_wrong", "solution", "method"])
def test_explain_three_angles(angle):
    r = client.post("/api/ai/tutoring/explain",
                    json={"question_id": 8801, "angle": angle, "my_answer": "A"})
    assert r.status_code == 200
    d = r.json()
    assert d["question_id"] == 8801
    assert d["content"]  # 降级本地包或 LLM 内容，非空
    assert d["route"]


def test_explain_404_and_followup(monkeypatch):
    r = client.post("/api/ai/tutoring/explain", json={"question_id": 99, "angle": "why_wrong"})
    assert r.status_code == 404

    # 追问用例做确定性桩：真实 LLM 链受本机 Ollama 负载/冷加载影响，慢时会被
    # 60s 外层守卫掐成 504（环境相关抖动）。这里只桩掉 AIService.chat，
    # 仍真实走完 路由参数校验 → 题目加载 → messages 组装 → 响应壳 的链路。
    async def _stub_chat(self, messages, **kwargs):  # noqa: ARG001
        return {"content": "（测试桩）追问：第2步为什么这样？", "provider": "test-stub", "route": "stub"}

    monkeypatch.setattr("services.ai_service.AIService.chat", _stub_chat)
    r = client.post("/api/ai/tutoring/followup", json={
        "question_id": 8801, "message": "第2步为什么这样？",
        "history": [{"role": "user", "content": "讲一下"},
                    {"role": "assistant", "content": "好"}]})
    assert r.status_code == 200 and r.json()["content"]


def test_stuck_records_to_blind_spot():
    """AI 讲题「仍未理解」→ 盲点池闭环：gap_type=not_understood，按用户隔离可查。"""
    r = client.post("/api/ai/tutoring/stuck", json={
        "question_id": 8801, "note": "第2步没懂", "angle": "solution"})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "recorded"
    assert d["stuck_id"] > 0

    gaps = client.get("/api/blind-spot/gaps", params={"status": "all"}).json()
    matched = [
        g for g in gaps
        if g.get("gap_type") == "not_understood" and "第2步没懂" in (g.get("question") or "")
    ]
    assert matched, f"盲点池中应存在 not_understood 记录：{gaps[:3]}"

    # 不存在的题目 → 404
    r404 = client.post("/api/ai/tutoring/stuck", json={"question_id": 99})
    assert r404.status_code == 404


def test_weekly_topics_aggregation():
    """周会议题聚合（多人计数视图）：按 subject+gap_type 统计，只返回计数不泄露他人文本。"""
    r = client.post("/api/ai/tutoring/stuck", json={
        "question_id": 8801, "note": "周会聚合验证", "angle": "solution"})
    assert r.status_code == 200

    topics = client.get("/api/blind-spot/weekly-topics", params={"days": 7}).json()
    matched = [
        t for t in topics
        if t.get("subject") == "数电" and t.get("gap_type") == "not_understood"
    ]
    assert matched, f"周会议题应包含 not_understood 聚合：{topics[:3]}"
    topic = matched[0]
    assert topic["open_count"] >= 1
    assert topic["user_count"] >= 1
    assert topic["total_occurrences"] >= 1
    # 聚合层不泄露原始问题文本（B4 精神）
    assert "周会聚合验证" not in str(topics)
