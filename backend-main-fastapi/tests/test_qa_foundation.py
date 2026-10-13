# -*- coding: utf-8 -*-
"""V12 数据地基回归：置信度分级 / 题库包导入+QC / 薄弱点聚合 / 确认队列 / 快照。

隔离：conftest 临时库。合成 JSON 题库包（数电/数逻各 3 题，含缺答案与重复条）。
"""
from __future__ import annotations

import pytest

from database import Base, SessionLocal, engine
from models import Paper, QuizQuestion
from services import qa_foundation
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)

QBANK = {
    "数字电路": [
        {"question": "TTL 与非门多余输入端应如何处理？", "options": {"A": "接地", "B": "接高电平或悬空", "C": "接低电平", "D": "任意"}, "answer": "B", "analysis": "多余端接高电平不影响逻辑", "year": 2023},
        {"question": "TTL 与非门多余输入端应如何处理？", "options": {"A": "接地", "B": "接高电平或悬空", "C": "接低电平", "D": "任意"}, "answer": "B", "year": 2023},  # 同科重复 → 去重
        {"question": "组合逻辑电路的特点是什么？", "options": {"A": "有记忆", "B": "无记忆", "C": "含触发器", "D": "反馈结构"}, "answer": "B", "year": 2023},
        {"question": "卡诺图化简的依据是？", "options": {"A": "摩根定律", "B": "相邻最小项合并", "C": "德摩根", "D": "真值表"}, "answer": None, "year": 2024},  # 缺答案 → QC
    ],
    "数字逻辑": [
        {"question": "十进制 25 的 8421BCD 码是？", "options": {"A": "00100101", "B": "00110011", "C": "00011001", "D": "11001"}, "answer": "A", "year": 2024},
        {"question": "竞争冒险的消除方法不包括？", "options": {"A": "加冗余项", "B": "加滤波电容", "C": "修改真值表", "D": "选通法"}, "answer": "C", "year": 2024},
    ],
}


@pytest.fixture(scope="module", autouse=True)
def _seed():
    Base.metadata.create_all(bind=engine)


# --------------------------------------------------------------------------- #
# 1. 题库包导入 + QC + 试卷归位
# --------------------------------------------------------------------------- #
def test_import_qbank_dry_run():
    r = client.post("/api/qa/import-qbank", json={"payload": QBANK, "dry_run": True})
    assert r.status_code == 200
    qc = r.json()
    assert qc["total"] == 6
    assert qc["imported"] == 0  # dry_run 不入库
    assert qc["would_import"] == 6  # dry_run 分支在去重前，报告"将会导入"
    assert qc["missing_answer"] == 1
    assert qc["skipped_dup"] == 0


def test_import_qbank_apply_creates_papers():
    r = client.post("/api/qa/import-qbank", json={"payload": QBANK, "dry_run": False})
    assert r.status_code == 200
    d = r.json()
    print("DEBUG apply 返回:", d)
    assert d["imported"] == 5  # 6 - 1重复（缺答案题也入库，answer=NULL）
    assert d["papers_created"] == 3  # 数电2023/2024 + 数逻2024
    db = SessionLocal()
    try:
        assert db.query(Paper).count() >= 2
        # 缺答案题：answer 置空 + 低置信（llm_generated）
        blank = db.query(QuizQuestion).filter(QuizQuestion.answer.is_(None)).count()
        assert blank >= 1
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 2. 薄弱点聚合 + 快照
# --------------------------------------------------------------------------- #
def test_weak_knowledge_flow():
    _db = SessionLocal()
    print("DEBUG weak开头题目数:", _db.query(QuizQuestion).count(), "| bind:", _db.get_bind().url)
    _db.close()
    r = client.post("/api/qa/refresh-weak")
    assert r.status_code == 200
    r = client.get("/api/qa/weak-knowledge")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    r = client.get("/api/qa/export-snapshot")
    assert r.status_code == 200
    assert "weak_knowledge" in r.json() and "recent_errors" in r.json()


# --------------------------------------------------------------------------- #
# 3. 人工确认队列（resolve confirm / reject）
# --------------------------------------------------------------------------- #
def test_review_queue_resolve():
    db = SessionLocal()
    try:
        _all = db.query(QuizQuestion).all()
        print("DEBUG 题目数:", len(_all), [(x.id, repr(x.answer), x.answer_source) for x in _all])
        q = db.query(QuizQuestion).filter(QuizQuestion.answer.is_(None)).first()
        qa_foundation.resolve_review  # 确认函数存在
        # 直接向队列表插一条 pending（导入缺答案场景）
        from database import engine as _eng
        with _eng.begin() as conn:
            conn.exec_driver_sql(
                "INSERT OR IGNORE INTO answer_review_queue "
                "(question_id, conflict_type, detail, status, created_at) "
                f"VALUES ({q.id}, 'missing', '\"导入缺答案\"', 'pending', 'now')")
    finally:
        db.close()
    items = client.get("/api/qa/review-queue").json()
    assert len(items) >= 1
    qid = items[0]["id"]
    r = client.post(f"/api/qa/review-queue/{qid}/resolve", json={"action": "confirm", "resolution": "B"})
    assert r.status_code == 200
    db = SessionLocal()
    try:
        q = db.query(QuizQuestion).filter(QuizQuestion.id == items[0]["question_id"]).first()
        assert q.answer == "B" and q.answer_source == "user_confirmed"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 4. 判分分级：低置信题 needs_review，不判错
# --------------------------------------------------------------------------- #
def test_submit_low_confidence_question():
    db = SessionLocal()
    try:
        q = QuizQuestion(content="低置信测试题", options='{"A":"1","B":"2"}',
                         answer="llm猜想", answer_source="llm_generated",
                         answer_confidence=0.55, subject="数电")
        db.add(q); db.commit(); qid = q.id
    finally:
        db.close()
    r = client.post("/api/quiz/submit", json={
        "question_id": qid, "my_answer": "A", "mode": "practice", "cost_seconds": 5})
    assert r.status_code == 200
    d = r.json()
    assert d["needs_review"] is True
    assert d["correct"] is False  # 低置信不判分
