# -*- coding: utf-8 -*-
"""A5 模考考后报告（P0-3）单元测试。

覆盖：
1. ``GET /api/exam/sessions/{session_id}/report`` 在会话不存在时返回 404；
2. 有作答时返回完整报告结构（overview / section_scores / knowledge_weakness /
   time_analysis / wrong_questions），字段口径与 session_detail 一致；
3. 无作答（exam_answers 空）时返回 200 + 空报告结构（不 500）；
4. ``GET /api/exam/sessions`` 列表补充 report_available / max_score / earned_score。

数据隔离：直接向测试库插入 exam_sessions / exam_answers（原生 SQL），
测试结束按 session_id 清理，不影响其它用例。
"""
from __future__ import annotations

import json

import pytest

from services.dbapi_compat import wrap_conn

MARK = "exam_report_test"


@pytest.fixture()
def db(db_schema):  # noqa: ARG001 — db_schema 负责建表
    from database import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _insert_session(db, *, subject="数学", paper="math2", status="submitted"):
    """插入一条模考会话，返回 session_id。

    注意 question_source 在 PG 是 source_kind 枚举，合法值见 core/pg_types.py，
    这里用 external_import（与 core/sql 041 默认值一致），不能用 'all'。
    """
    from services.dbapi_compat import insert_returning_id

    conn = wrap_conn(db.connection().connection)
    config = json.dumps({"blueprint_key": "math2:general"}, ensure_ascii=False)
    return insert_returning_id(
        conn,
        "INSERT INTO exam_sessions"
        " (blueprint_key, subject, paper, mode, question_source, config,"
        "  total_count, total_score, correct_count, score, time_limit_minutes, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("math2:general", subject, paper, "normal", "external_import", config,
         2, 10.0, 1, 5.0, 180, status),
    )


def _insert_answer(db, session_id, *, order_no, qid=None, snap, user_answer="",
                   is_correct=None, time_spent=0, final_score=None, scored_by="auto"):
    """插入一条作答记录，返回 exam_answers.id。

    is_correct 在 PG 是 BOOLEAN 列：None 表示未判分，否则转 bool。
    question_id 引用 quiz_questions(id)（外键）：测试库该表可能为空，
    传 None（允许 NULL），报告完全基于 question_snapshot 快照。
    """
    conn = wrap_conn(db.connection().connection)
    cur = conn.execute(
        "INSERT INTO exam_answers"
        " (session_id, question_id, question_snapshot, section, order_no, user_answer,"
        "  is_correct, time_spent, final_score, scored_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, qid, json.dumps(snap, ensure_ascii=False), "一、单项选择题",
         order_no, user_answer,
         None if is_correct is None else bool(is_correct),
         time_spent, final_score, scored_by),
    )
    return cur.lastrowid


def _cleanup(db, session_ids):
    conn = wrap_conn(db.connection().connection)
    if session_ids:
        ph = ",".join("?" * len(session_ids))
        conn.execute(f"DELETE FROM exam_answers WHERE session_id IN ({ph})", session_ids)
        conn.execute(f"DELETE FROM exam_sessions WHERE id IN ({ph})", session_ids)
    db.commit()


# --------------------------------------------------------------------------- #
# 1. 404：会话不存在
# --------------------------------------------------------------------------- #
def test_report_404_when_session_missing(client, db):
    r = client.get("/api/exam/sessions/999999/report")
    assert r.status_code == 404, r.text
    # 全局异常处理器包装：message 字段携带人话原因
    assert r.json().get("message") == "会话不存在"


# --------------------------------------------------------------------------- #
# 2. 有作答时报告结构完整且字段正确
# --------------------------------------------------------------------------- #
def test_report_full_structure(client, db):
    sid = _insert_session(db)
    db.commit()

    try:
        # 客观题：正确，用时 30s，满分 5
        _insert_answer(
            db, sid, order_no=1,
            snap={"content": "1+1=?", "answer": "B", "knowledge_point": "算术",
                  "question_type": "single", "answer_type": "objective", "max_score": 5.0},
            user_answer="B", is_correct=1, time_spent=30, final_score=5.0, scored_by="auto",
        )
        # 客观题：错误，用时 60s，满分 5
        _insert_answer(
            db, sid, order_no=2,
            snap={"content": "2+2=?", "answer": "D", "knowledge_point": "算术",
                  "question_type": "single", "answer_type": "objective", "max_score": 5.0},
            user_answer="A", is_correct=0, time_spent=60, final_score=0.0, scored_by="auto",
        )
        db.commit()

        r = client.get(f"/api/exam/sessions/{sid}/report")
        assert r.status_code == 200, r.text
        body = r.json()

        # overview
        ov = body["overview"]
        assert ov["session_id"] == sid
        assert ov["total_score"] == 5.0
        assert ov["max_score"] == 10.0
        assert ov["accuracy"] == 0.5
        assert ov["total_time_spent"] == 90
        assert ov["question_count"] == 2
        assert ov["question_type_distribution"] == {"single": 2}

        # section_scores
        sec = body["section_scores"]
        assert len(sec) == 1
        assert sec[0]["question_type"] == "single"
        assert sec[0]["count"] == 2
        assert sec[0]["score"] == 5.0
        assert sec[0]["max_score"] == 10.0
        assert sec[0]["accuracy"] == 0.5

        # knowledge_weakness
        kw = body["knowledge_weakness"]
        assert len(kw) == 1
        assert kw[0]["knowledge_point"] == "算术"
        assert kw[0]["correct_rate"] == 0.5
        assert kw[0]["question_count"] == 2

        # time_analysis
        ta = body["time_analysis"]
        assert ta["total_time_spent"] == 90
        assert ta["average_time_per_question"] == 45.0
        assert len(ta["top_slowest_questions"]) == 2
        assert ta["top_slowest_questions"][0]["order_no"] == 2
        assert ta["top_slowest_questions"][0]["time_spent"] == 60

        # wrong_questions
        wq = body["wrong_questions"]
        assert len(wq) == 1
        assert wq[0]["order_no"] == 2
        assert wq[0]["user_answer"] == "A"
        assert wq[0]["correct_answer"] == "D"
        assert wq[0]["final_score"] == 0.0
        assert wq[0]["max_score"] == 5.0
        assert "2+2=?" in wq[0]["content"]
    finally:
        _cleanup(db, [sid])


# --------------------------------------------------------------------------- #
# 3. 无作答：200 + 空报告结构
# --------------------------------------------------------------------------- #
def test_report_empty_structure(client, db):
    sid = _insert_session(db)
    db.commit()

    try:
        r = client.get(f"/api/exam/sessions/{sid}/report")
        assert r.status_code == 200, r.text
        body = r.json()

        ov = body["overview"]
        assert ov["total_score"] == 0.0
        assert ov["max_score"] == 0.0
        assert ov["accuracy"] == 0.0
        assert ov["total_time_spent"] == 0
        assert ov["question_count"] == 0
        assert ov["question_type_distribution"] == {}

        assert body["section_scores"] == []
        assert body["knowledge_weakness"] == []
        assert body["time_analysis"]["top_slowest_questions"] == []
        assert body["wrong_questions"] == []
    finally:
        _cleanup(db, [sid])


# --------------------------------------------------------------------------- #
# 4. 列表增强：report_available / max_score / earned_score
# --------------------------------------------------------------------------- #
def test_list_sessions_aggregated_fields(client, db):
    # 已交卷且有作答的会话
    sid_submitted = _insert_session(db, status="submitted")
    # 未交卷（ongoing）但已有快照（无作答内容）的会话
    sid_ongoing = _insert_session(db, status="ongoing")
    db.commit()

    try:
        _insert_answer(
            db, sid_submitted, order_no=1,
            snap={"content": "Q", "answer": "B", "knowledge_point": "算术",
                  "question_type": "single", "answer_type": "objective", "max_score": 5.0},
            user_answer="B", is_correct=1, time_spent=10, final_score=5.0, scored_by="auto",
        )
        _insert_answer(
            db, sid_ongoing, order_no=1,
            snap={"content": "Q2", "answer": "C", "knowledge_point": "算术",
                  "question_type": "single", "answer_type": "objective", "max_score": 5.0},
            user_answer="", is_correct=None, time_spent=0, final_score=None, scored_by="auto",
        )
        db.commit()

        r = client.get("/api/exam/sessions?status=submitted")
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, list)
        target = next((s for s in body if s["id"] == sid_submitted), None)
        assert target is not None, f"列表中找不到 session {sid_submitted}: {body}"
        assert target["report_available"] is True
        assert target["max_score"] == 5.0
        assert target["earned_score"] == 5.0
        # 旧字段保留（向后兼容）
        assert "total_score" in target
        assert "score" in target
        assert "status" in target

        r2 = client.get("/api/exam/sessions?status=ongoing")
        body2 = r2.json()
        target2 = next((s for s in body2 if s["id"] == sid_ongoing), None)
        assert target2 is not None
        assert target2["report_available"] is False
        # 有冻结快照但未作答 → max_score 仍聚合（5.0），earned_score 为 0
        assert target2["max_score"] == 5.0
        assert target2["earned_score"] == 0.0
    finally:
        _cleanup(db, [sid_submitted, sid_ongoing])