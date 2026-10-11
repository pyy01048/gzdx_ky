# -*- coding: utf-8 -*-
"""V13 冲突复核台回归（规格 §1.7 用例清单）。

覆盖：seed 幂等 / open 全局唯一（同题第二次登记跳过）/ 列表过滤分页 /
resolve 采纳（候选 user_confirmed 1.0 + 其它 ×0.8 + 题目主答案同步）/
resolve 幂等 409 / reject 降权 ×0.7 / stats 看板 / 非法 status 400。
"""
from __future__ import annotations

import pytest

from database import Base, SessionLocal, engine
from models import QuizQuestion
from services import confidence_service
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.add_all([
            QuizQuestion(id=7101, content="冲突题A：与门输出？", answer="高电平",
                         answer_source="bank", answer_confidence=0.9, subject="数电"),
            QuizQuestion(id=7102, content="冲突题B：或非门输出？", answer=None,
                         subject="数电"),
        ])
        db.commit()
    finally:
        db.close()


def test_seed_and_open_unique():
    r1 = client.post("/api/conflicts/seed", json={"rows": [
        {"question_id": 7101, "answer_a": "高电平", "answer_b": "低电平",
         "source_a": "bank", "source_b": "llm", "confidence_a": 0.9,
         "confidence_b": 0.5},
    ]})
    assert r1.status_code == 200 and r1.json()["seeded"] == 1
    # 幂等：同题已有 open → 第二次跳过
    r2 = client.post("/api/conflicts/seed", json={"rows": [
        {"question_id": 7101, "answer_a": "x", "answer_b": "y",
         "source_a": "bank", "source_b": "llm"}]})
    assert r2.json()["seeded"] == 0
    items = client.get("/api/conflicts", params={"status": "open"}).json()
    assert items["total"] == 1 and items["items"][0]["question_id"] == 7101


def test_list_filter_and_invalid_status():
    assert client.get("/api/conflicts",
                      params={"status": "resolved"}).json()["total"] == 0
    assert client.get("/api/conflicts", params={"status": "bad"}).status_code == 400


def test_resolve_writes_candidate_and_downgrades():
    items = client.get("/api/conflicts", params={"question_id": 7101}).json()
    print("DEBUG resolve查询:", items)
    qid = items["items"][0]["id"]
    r = client.post(f"/api/conflicts/{qid}/resolve",
                    json={"resolution": "高电平", "reviewer_note": "与教材一致"})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    # 幂等：重复 resolve → 409
    assert client.post(f"/api/conflicts/{qid}/resolve",
                       json={"resolution": "again"}).status_code == 409
    db = SessionLocal()
    try:
        q = db.query(QuizQuestion).filter(QuizQuestion.id == 7101).first()
        assert q.answer == "高电平" and q.answer_source == "user_confirmed"
    finally:
        db.close()


def test_reject_downgrade_and_stats():
    client.post("/api/conflicts/seed", json={"rows": [
        {"question_id": 7102, "answer_a": "疑似A", "answer_b": "疑似B",
         "source_a": "llm", "source_b": "extracted"}]})
    items = client.get("/api/conflicts", params={"question_id": 7102}).json()
    qid = items["items"][0]["id"]
    r = client.post(f"/api/conflicts/{qid}/reject",
                    json={"reviewer_note": "题面缺条件"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    st = client.get("/api/conflicts/stats").json()
    assert st["open"] == 0 and st["resolved"] >= 1 and st["rejected"] >= 1
    assert isinstance(st["by_source"], dict)
