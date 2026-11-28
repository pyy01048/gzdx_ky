# -*- coding: utf-8 -*-
"""普通刷题持久会话 HTTP 契约测试。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from database import SessionLocal
from sqlalchemy import inspect, text
from utils.security import current_user, optional_user

from models import AnswerRecord, ErrorRecord, QuizQuestion, User

_UID_BASE = 1_100_000_000 + int(uuid.uuid4().hex[:8], 16) % 100_000_000
UID_A = _UID_BASE
UID_B = _UID_BASE + 1
MARKER = f"quiz-session-{uuid.uuid4().hex}"


def _principal(uid: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid,
        username=f"qs_{uid}",
        display_name=f"qs_{uid}",
        role="user",
        is_active=True,
        must_change_password=False,
        token_version=0,
        last_login_at=None,
        created_at=None,
    )


def _cleanup(db):
    db.rollback()
    table_names = inspect(db.get_bind()).get_table_names()
    columns = {table: {column["name"] for column in inspect(db.get_bind()).get_columns(table)} for table in table_names}
    owned = [table for table in table_names if table != "users" and "user_id" in columns[table]]
    priority = ["quiz_attempts", "quiz_session_questions", "error_knowledge_links", "answer_records", "error_records"]
    ordered = [table for table in priority if table in owned]
    ordered.extend(sorted(set(owned) - set(ordered)))
    for _ in range(2):
        for table in ordered:
            try:
                db.execute(text(f'DELETE FROM "{table}" WHERE user_id IN (:a, :b)'), {"a": UID_A, "b": UID_B})
                db.commit()
            except Exception:
                db.rollback()
    for table in table_names:
        if "content" in columns[table]:
            try:
                db.execute(text(f'DELETE FROM "{table}" WHERE content LIKE :marker'), {"marker": f"{MARKER}%"})
                db.commit()
            except Exception:
                db.rollback()
    try:
        db.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": UID_A, "b": UID_B})
        db.commit()
    except Exception:
        db.rollback()


@pytest.fixture
def session_users(db_schema):  # noqa: ARG001
    db = SessionLocal()
    try:
        _cleanup(db)
        db.add_all(
            [
                User(id=UID_A, username=f"qs_{UID_A}", password_hash="x", role="user"),
                User(id=UID_B, username=f"qs_{UID_B}", password_hash="x", role="user"),
            ]
        )
        db.commit()
        yield
    finally:
        _cleanup(db)
        db.close()


@pytest.fixture
def questions(session_users):  # noqa: ARG001
    db = SessionLocal()
    try:
        rows = [
            QuizQuestion(
                content=f"{MARKER}-{i}",
                options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
                answer="A",
                analysis=f"解析-{i}",
                subject="数学",
                question_type="single",
                owner_user_id=None,
            )
            for i in range(2)
        ]
        db.add_all(rows)
        db.commit()
        yield [row.id for row in rows]
    finally:
        db.close()


def _login(app_module, uid: int):
    previous = app_module.dependency_overrides.get(current_user)
    app_module.dependency_overrides[current_user] = lambda: _principal(uid)
    app_module.dependency_overrides[optional_user] = lambda: _principal(uid)
    return previous


def _restore(app_module, previous):
    if previous is None:
        app_module.dependency_overrides.pop(current_user, None)
    else:
        app_module.dependency_overrides[current_user] = previous


def _create(client, question_ids, **extra):
    payload = {
        "question_ids": question_ids,
        "title": "普通刷题",
        "mode": "free_practice",
        "no_answer": False,
        "basis": {"source": "test"},
        **extra,
    }
    response = client.post("/api/quiz/sessions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_create_snapshot_restore_sanitize_and_user_isolation(client, app_module, questions):
    previous = _login(app_module, UID_A)
    try:
        created = _create(client, [questions[1], questions[0]])
        assert created["question_ids"] == [questions[1], questions[0]]
        assert [q["id"] for q in created["questions"]] == [questions[1], questions[0]]
        assert all(q["answer"] is None and q["analysis"] is None for q in created["questions"])
        session_id = created["session_id"]

        patched = client.request(
            "PATCH",
            f"/api/quiz/sessions/{session_id}",
            json={
                "current_index": 1,
                "drafts": {str(questions[1]): 0},
                "text_drafts": {},
                "self_scores": {},
                "marked": {str(questions[1]): True},
                "duration_seconds": 42,
            },
        )
        assert patched.status_code == 200, patched.text

        restored = client.get(f"/api/quiz/sessions/{session_id}")
        assert restored.status_code == 200, restored.text
        body = restored.json()
        assert body["current_index"] == 1
        assert body["drafts"] == {str(questions[1]): 0}
        assert body["marked"] == {str(questions[1]): True}
        assert body["duration_seconds"] == 42
        assert body["status"] == "in_progress"
        assert all(q["answer"] is None and q["analysis"] is None for q in body["questions"])

        _login(app_module, UID_B)
        for method in ("get", "patch"):
            response = client.request(
                method.upper(), f"/api/quiz/sessions/{session_id}", json={} if method == "patch" else None
            )
            assert response.status_code == 404
    finally:
        _restore(app_module, previous)


def test_submit_is_idempotent_and_complete_hides_latest(client, app_module, questions):
    previous = _login(app_module, UID_A)
    try:
        created = _create(client, questions)
        session_id = created["session_id"]
        payload = {
            "session_id": session_id,
            "question_id": questions[0],
            "my_answer": "A",
            "client_attempt_id": f"{MARKER}-attempt",
            "cost_seconds": 5,
        }
        first = client.post("/api/quiz/submit", json=payload)
        second = client.post("/api/quiz/submit", json=payload)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["correct"] is True
        assert second.json()["record_id"] == first.json()["record_id"]

        db = SessionLocal()
        try:
            answer_count = (
                db.query(AnswerRecord)
                .filter(AnswerRecord.user_id == UID_A, AnswerRecord.question_id == questions[0])
                .count()
            )
            attempt_count = db.execute(
                text("SELECT count(*) FROM quiz_attempts WHERE user_id=:uid AND session_id=:sid AND question_id=:qid"),
                {"uid": UID_A, "sid": session_id, "qid": questions[0]},
            ).scalar()
            assert answer_count == 1
            assert attempt_count == 1
        finally:
            db.close()

        restored = client.get(f"/api/quiz/sessions/{session_id}").json()
        assert restored["answered_count"] == 1
        assert str(questions[0]) in restored["records"]
        assert restored["records"][str(questions[0])]["correct"] is True
        by_id = {q["id"]: q for q in restored["questions"]}
        assert by_id[questions[0]]["answer"] == "A"
        assert by_id[questions[1]]["answer"] is None

        completed = client.post(f"/api/quiz/sessions/{session_id}/complete")
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "completed"
        latest = client.get("/api/quiz/sessions/latest")
        assert latest.status_code == 200
        assert latest.json() is None
    finally:
        _restore(app_module, previous)


def test_version_conflict_completed_reject_and_legacy_submit(client, app_module, questions):
    previous = _login(app_module, UID_A)
    try:
        created = _create(client, questions)
        session_id = created["session_id"]
        latest = client.get("/api/quiz/sessions/latest").json()
        assert latest["session_id"] == session_id

        saved = client.request("PATCH", f"/api/quiz/sessions/{session_id}", json={"version": 1, "current_index": 1})
        assert saved.status_code == 200
        assert saved.json()["version"] == 2
        stale = client.request("PATCH", f"/api/quiz/sessions/{session_id}", json={"version": 1, "current_index": 0})
        assert stale.status_code == 409

        db = SessionLocal()
        try:
            question = db.query(QuizQuestion).filter(QuizQuestion.id == questions[0]).one()
            question.content = f"{MARKER}-changed"
            db.commit()
        finally:
            db.close()
        restored = client.get(f"/api/quiz/sessions/{session_id}").json()
        assert restored["questions"][0]["content"] == f"{MARKER}-0"

        assert client.post(f"/api/quiz/sessions/{session_id}/complete").status_code == 200
        rejected = client.post(
            "/api/quiz/submit",
            json={"session_id": session_id, "question_id": questions[0], "my_answer": "A"},
        )
        assert rejected.status_code == 409
        assert (
            client.request("PATCH", f"/api/quiz/sessions/{session_id}", json={"duration_seconds": 5}).status_code == 409
        )

        legacy = client.post("/api/quiz/submit", json={"question_id": questions[0], "my_answer": "A"})
        assert legacy.status_code == 200, legacy.text
        db = SessionLocal()
        try:
            assert (
                db.execute(
                    text("SELECT count(*) FROM quiz_attempts WHERE session_id=:sid"), {"sid": session_id}
                ).scalar()
                == 0
            )
        finally:
            db.close()
    finally:
        _restore(app_module, previous)


@pytest.mark.parametrize("mode", ["practice", "memorize"])
def test_create_accepts_frontend_practice_modes(client, app_module, questions, mode):
    previous = _login(app_module, UID_A)
    try:
        created = _create(client, questions, mode=mode)
        assert created["mode"] == mode
    finally:
        _restore(app_module, previous)


def test_submit_grades_locked_snapshot_after_question_changes(client, app_module, questions):
    previous = _login(app_module, UID_A)
    try:
        created = _create(client, [questions[0]])
        db = SessionLocal()
        try:
            question = db.query(QuizQuestion).filter(QuizQuestion.id == questions[0]).one()
            question.answer = "B"
            question.analysis = "修改后的解析"
            question.question_type = "judge"
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/api/quiz/submit",
            json={
                "session_id": created["session_id"],
                "question_id": questions[0],
                "my_answer": "A",
                "cost_seconds": 5,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["correct"] is True
        assert response.json()["correct_answer"] == "A"
        assert response.json()["analysis"] == "解析-0"
        assert response.json()["question_type"] == "single"

        db = SessionLocal()
        try:
            answer = (
                db.query(AnswerRecord)
                .filter(AnswerRecord.user_id == UID_A, AnswerRecord.question_id == questions[0])
                .one()
            )
            assert answer.correct_answer == "A"
            assert answer.is_correct is True
            assert (
                db.query(ErrorRecord)
                .filter(ErrorRecord.user_id == UID_A, ErrorRecord.question_id == questions[0])
                .count()
                == 0
            )
        finally:
            db.close()
    finally:
        _restore(app_module, previous)


def test_submit_rejects_question_outside_session(client, app_module, questions):
    previous = _login(app_module, UID_A)
    try:
        created = _create(client, [questions[0]])
        response = client.post(
            "/api/quiz/submit",
            json={
                "session_id": created["session_id"],
                "question_id": questions[1],
                "my_answer": "A",
                "client_attempt_id": f"{MARKER}-outside",
            },
        )
        assert response.status_code == 400
        db = SessionLocal()
        try:
            count = db.query(ErrorRecord).filter(ErrorRecord.user_id == UID_A).count()
            assert count == 0
        finally:
            db.close()
    finally:
        _restore(app_module, previous)
