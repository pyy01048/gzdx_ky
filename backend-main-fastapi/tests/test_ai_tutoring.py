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


def test_explain_404_and_followup():
    r = client.post("/api/ai/tutoring/explain", json={"question_id": 99, "angle": "why_wrong"})
    assert r.status_code == 404
    r = client.post("/api/ai/tutoring/followup", json={
        "question_id": 8801, "message": "第2步为什么这样？",
        "history": [{"role": "user", "content": "讲一下"},
                    {"role": "assistant", "content": "好"}]})
    assert r.status_code == 200 and r.json()["content"]
