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
    # 幂等前置清理：本文件验收的是"导入 6 题 → 去重后 5 题 + 3 张卷"，
    # 但题库去重与试卷 ON CONFLICT 都是幂等的 —— 第二次跑就变成
    # imported=0 / papers_created=0，断言必然失败（实测）。
    # 清掉上次运行留下的 QBANK 题目与试卷，让验收口径可复现。
    from sqlalchemy import text as _text

    db = SessionLocal()
    try:
        stems = [
            "%多余输入端应如何处理%", "%组合逻辑电路的特点%", "%卡诺图化简的依据%",
            "%8421BCD 码是%", "%竞争冒险的消除方法%",
        ]
        like = " OR ".join(f"content LIKE '{x}'" for x in stems)
        # 顺序要紧：先删所有**引用**题目的表，再删题目本身。
        # 漏掉 answer_review_queue 会留下孤儿行 —— 队列里 item 的
        # question_id 指向已删题目，测试取到它再查库就是 None
        # （实测：AttributeError 'NoneType' object has no attribute 'answer'）。
        for ref_tbl in ("paper_questions", "answer_review_queue"):
            db.execute(_text(
                f"DELETE FROM {ref_tbl} WHERE question_id IN "
                f"(SELECT id FROM quiz_questions WHERE {like})"))
        db.execute(_text(f"DELETE FROM quiz_questions WHERE {like}"))
        db.execute(_text("DELETE FROM papers WHERE title LIKE '%（题库包导入）'"))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        import warnings

        warnings.warn(f"QBANK 前置清理失败（断言可能不可复现）: {exc}")
    finally:
        db.close()


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
        if q is None:
            # 库里所有题都有答案时自造一条缺答案题（正典数组 options，避开触发器拦截）
            q = QuizQuestion(
                content="QA 队列自造缺答案题：门电路输出电平？",
                options=[{"key": "A", "text": "高电平"}, {"key": "B", "text": "低电平"}],
                answer=None, subject="数电", question_type="single",
                answer_source="llm_generated",
            )
            db.add(q)
            db.commit()
            db.refresh(q)
        qa_foundation.resolve_review  # 确认函数存在
        # 直接向队列表插一条 pending（导入缺答案场景）
        # 跨方言：INSERT OR IGNORE 是 SQLite 方言，PG 走 ON CONFLICT DO NOTHING
        from database import engine as _eng
        from sqlalchemy import text as _t

        with _eng.begin() as conn:
            conn.execute(_t(
                "INSERT INTO answer_review_queue "
                "(question_id, conflict_type, detail, status, created_at) "
                f"VALUES ({q.id}, 'missing', '\"导入缺答案\"', 'pending', 'now') "
                "ON CONFLICT DO NOTHING"))
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
