# -*- coding: utf-8 -*-
"""错题重练提交、FSRS 排程与毕业/删除清理契约。"""

from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

import pytest
from database import SessionLocal
from services import review_service
from sqlalchemy import bindparam, event, text
from sqlalchemy.orm import Session
from utils.security import current_user, optional_user
from utils.timeutil import to_naive_utc, utcnow

from models import (
    AnswerRecord,
    ErrorRecord,
    QuizAttempt,
    QuizQuestion,
    QuizSession,
    ReviewRecord,
    ReviewSchedule,
    User,
)

_UID_BASE = 1_200_000_000 + int(uuid.uuid4().hex[:8], 16) % 100_000_000
UID_A = _UID_BASE
UID_B = _UID_BASE + 1
MARKER = f"wrong-review-{uuid.uuid4().hex}"


def _principal(uid: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid,
        username=f"wr_{uid}",
        display_name=f"wr_{uid}",
        role="user",
        is_active=True,
        must_change_password=False,
        token_version=0,
        last_login_at=None,
        created_at=None,
    )


def _cleanup(db) -> None:
    db.rollback()
    params = {"uids": (UID_A, UID_B), "marker": f"{MARKER}%"}
    qids = "SELECT id FROM quiz_questions WHERE content LIKE :marker"
    eids = "SELECT id FROM error_records WHERE user_id IN :uids"
    sids = "SELECT id FROM quiz_sessions WHERE user_id IN :uids"
    statements = [
        f"DELETE FROM quiz_attempts WHERE user_id IN :uids OR question_id IN ({qids}) OR session_id IN ({sids})",
        f"DELETE FROM quiz_session_questions WHERE user_id IN :uids OR question_id IN ({qids}) OR session_id IN ({sids})",
        "DELETE FROM quiz_sessions WHERE user_id IN :uids",
        "DELETE FROM review_schedules WHERE user_id IN :uids",
        "DELETE FROM review_records WHERE user_id IN :uids",
        f"DELETE FROM study_events WHERE user_id IN :uids OR question_id IN ({qids})",
        f"DELETE FROM quiz_question_set_items WHERE question_id IN ({qids})",
        f"DELETE FROM quiz_question_states WHERE user_id IN :uids OR question_id IN ({qids})",
        f"DELETE FROM error_knowledge_links WHERE user_id IN :uids OR error_id IN ({eids})",
        f"DELETE FROM answer_records WHERE user_id IN :uids OR question_id IN ({qids})",
        f"DELETE FROM error_records WHERE user_id IN :uids OR question_id IN ({qids})",
        "DELETE FROM quiz_questions WHERE content LIKE :marker",
        "DELETE FROM users WHERE id IN :uids",
    ]
    try:
        for sql in statements:
            statement = text(sql)
            if ":uids" in sql:
                statement = statement.bindparams(bindparam("uids", expanding=True))
            db.execute(statement, params)
        db.commit()
    except Exception:
        db.rollback()
        raise


@pytest.fixture
def wrong_review_env(app_module, db_schema, client):  # noqa: ARG001
    db = SessionLocal()
    dependencies = (current_user, optional_user)
    saved = {dep: app_module.dependency_overrides.get(dep) for dep in dependencies}

    def login(uid: int) -> None:
        principal = _principal(uid)
        app_module.dependency_overrides[current_user] = lambda principal=principal: principal
        app_module.dependency_overrides[optional_user] = lambda principal=principal: principal

    try:
        _cleanup(db)
        db.add_all(
            [
                User(id=UID_A, username=f"wr_{UID_A}", password_hash="x", role="user"),
                User(id=UID_B, username=f"wr_{UID_B}", password_hash="x", role="user"),
            ]
        )
        common = {
            "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            "answer": "A",
            "analysis": f"{MARKER} 解析",
            "subject": "数学",
            "owner_user_id": None,
            "answer_type": "objective",
            "answer_confidence": 1.0,
            "is_available": True,
            "is_junk": False,
            "question_type": "single",
        }
        rows = [
            QuizQuestion(**common, content=f"{MARKER}-q0"),
            QuizQuestion(**common, content=f"{MARKER}-q1"),
            QuizQuestion(**{**common, "answer_confidence": 0.5}, content=f"{MARKER}-low"),
            QuizQuestion(
                **{
                    **common,
                    "options": None,
                    "answer": "参考答案",
                    "question_type": "essay",
                    "answer_type": "subjective",
                },
                content=f"{MARKER}-subjective",
            ),
            QuizQuestion(**{**common, "answer": None}, content=f"{MARKER}-pending"),
        ]
        db.add_all(rows)
        db.commit()
        yield SimpleNamespace(
            db=db,
            client=client,
            login=login,
            q0_id=rows[0].id,
            q1_id=rows[1].id,
            q_low_id=rows[2].id,
            q_subjective_id=rows[3].id,
            q_pending_id=rows[4].id,
        )
    finally:
        for dep, previous in saved.items():
            if previous is None:
                app_module.dependency_overrides.pop(dep, None)
            else:
                app_module.dependency_overrides[dep] = previous
        _cleanup(db)
        db.close()


def _add_error(env, question_id: int, *, uid: int = UID_A, status: str = "active") -> ErrorRecord:
    error = ErrorRecord(
        user_id=uid,
        question_id=question_id,
        content=f"{MARKER}-error-{question_id}-{uid}",
        my_answer="旧答案",
        correct_answer="A",
        error_reason="契约测试错题",
        subject="数学",
        status=status,
        accuracy=0.2,
        review_count=1,
        next_review=utcnow() - datetime.timedelta(days=1),
    )
    env.db.add(error)
    env.db.commit()
    env.db.refresh(error)
    return error


def _add_schedule(env, error_id: int, *, uid: int = UID_A) -> ReviewSchedule:
    now = utcnow()
    schedule = ReviewSchedule(
        user_id=uid,
        item_type="error_record",
        item_id=error_id,
        algorithm="fsrs",
        stability=3.0,
        difficulty=5.0,
        retrievability=0.9,
        state=2,
        interval_days=3,
        repetitions=1,
        lapses=0,
        last_reviewed_at=now - datetime.timedelta(days=3),
        next_review_at=now - datetime.timedelta(days=1),
    )
    env.db.add(schedule)
    env.db.commit()
    env.db.refresh(schedule)
    return schedule


def _schedule_snapshot(schedule: ReviewSchedule) -> tuple:
    return (
        schedule.algorithm,
        schedule.stability,
        schedule.difficulty,
        schedule.retrievability,
        schedule.state,
        schedule.interval_days,
        schedule.repetitions,
        schedule.lapses,
        to_naive_utc(schedule.last_reviewed_at),
        to_naive_utc(schedule.next_review_at),
    )


def _create_session(env, question_id: int) -> int:
    env.login(UID_A)
    response = env.client.post(
        "/api/quiz/sessions",
        json={
            "question_ids": [question_id],
            "title": f"{MARKER}-session",
            "mode": "free_practice",
            "no_answer": False,
            "basis": {"source": "test"},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def _submit(env, question_id: int, my_answer: str, *, error_id: int, session_id: int | None = None, **extra):
    env.login(UID_A)
    payload = {
        "question_id": question_id,
        "my_answer": my_answer,
        "error_id": error_id,
        "cost_seconds": 5,
        **extra,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    return env.client.post("/api/quiz/submit", json=payload)


def test_error_review_rejects_unowned_missing_or_mismatched_without_writes(wrong_review_env):
    env = wrong_review_env
    other_error = _add_error(env, env.q0_id, uid=UID_B)
    mismatched_error = _add_error(env, env.q1_id)
    session_id = _create_session(env, env.q0_id)
    missing_id = max(other_error.id, mismatched_error.id) + 1_000_000_000

    for error_id in (other_error.id, missing_id, mismatched_error.id):
        response = _submit(env, env.q0_id, "B", error_id=error_id, session_id=session_id)
        assert response.status_code == 404, response.text
        assert response.json()["message"] == "错题不存在"

    env.db.expire_all()
    assert env.db.query(AnswerRecord).filter(AnswerRecord.user_id == UID_A).count() == 0
    assert env.db.query(QuizAttempt).filter(QuizAttempt.user_id == UID_A).count() == 0
    assert env.db.query(ReviewRecord).filter(ReviewRecord.user_id == UID_A).count() == 0
    assert env.db.query(ReviewSchedule).filter(ReviewSchedule.user_id == UID_A).count() == 0
    assert env.db.query(ErrorRecord).filter(ErrorRecord.user_id == UID_A).count() == 1
    session = env.db.query(QuizSession).filter(QuizSession.id == session_id).one()
    assert session.answered_count == 0
    assert session.correct_count == 0


def test_wrong_review_updates_original_and_commits_all_rows_together(wrong_review_env):
    env = wrong_review_env
    error = _add_error(env, env.q0_id)
    session_id = _create_session(env, env.q0_id)
    required = {AnswerRecord, ReviewRecord, ReviewSchedule, QuizAttempt}
    seen: dict[Session, set] = {}
    commits: list[set] = []

    def before_flush(session, _context, _instances):
        seen.setdefault(session, set()).update(set(session.new) | set(session.dirty) | set(session.deleted))

    def before_commit(session):
        types = {type(obj) for obj in seen.get(session, set())}
        if required.issubset(types):
            commits.append(types)

    def after_commit(session):
        seen.pop(session, None)

    listeners = []

    def listen(identifier, callback):
        event.listen(Session, identifier, callback)
        listeners.append((identifier, callback))

    listen("before_flush", before_flush)
    listen("before_commit", before_commit)
    listen("after_commit", after_commit)
    try:
        response = _submit(env, env.q0_id, "B", error_id=error.id, session_id=session_id)
    finally:
        for identifier, callback in listeners:
            event.remove(Session, identifier, callback)

    assert response.status_code == 200, response.text
    assert response.json()["correct"] is False
    assert len(commits) == 1

    env.db.expire_all()
    answers = (
        env.db.query(AnswerRecord).filter(AnswerRecord.user_id == UID_A, AnswerRecord.question_id == env.q0_id).all()
    )
    assert len(answers) == 1
    assert answers[0].my_answer == "B"
    assert answers[0].is_correct is False

    errors = env.db.query(ErrorRecord).filter(ErrorRecord.user_id == UID_A, ErrorRecord.question_id == env.q0_id).all()
    assert len(errors) == 1
    updated = errors[0]
    assert updated.id == error.id
    assert updated.my_answer == "B"
    assert updated.correct_answer == "A"
    assert updated.review_count == 2
    assert updated.accuracy == 0.2
    assert updated.last_review is not None

    reviews = env.db.query(ReviewRecord).filter(ReviewRecord.user_id == UID_A, ReviewRecord.item_id == error.id).all()
    assert len(reviews) == 1
    assert reviews[0].item_type == "error"
    assert reviews[0].result == "again"
    assert reviews[0].grade == 1

    schedule = (
        env.db.query(ReviewSchedule)
        .filter(
            ReviewSchedule.user_id == UID_A,
            ReviewSchedule.item_type == "error_record",
            ReviewSchedule.item_id == error.id,
        )
        .one()
    )
    assert schedule.algorithm == "fsrs"
    assert schedule.interval_days == 1
    assert schedule.repetitions == 0
    assert schedule.lapses == 1
    assert updated.interval_days == schedule.interval_days
    assert to_naive_utc(updated.next_review) == to_naive_utc(schedule.next_review_at)

    attempt = env.db.query(QuizAttempt).filter(QuizAttempt.user_id == UID_A, QuizAttempt.session_id == session_id).one()
    assert attempt.answer_record_id == answers[0].id
    assert attempt.is_correct is False
    session = env.db.query(QuizSession).filter(QuizSession.id == session_id).one()
    assert session.answered_count == 1
    assert session.correct_count == 0


def test_correct_review_uses_mastered_fsrs_without_duplicating_error(wrong_review_env):
    env = wrong_review_env
    error = _add_error(env, env.q0_id)
    session_id = _create_session(env, env.q0_id)

    response = _submit(env, env.q0_id, "A", error_id=error.id, session_id=session_id)
    assert response.status_code == 200, response.text
    assert response.json()["correct"] is True

    env.db.expire_all()
    assert (
        env.db.query(ErrorRecord).filter(ErrorRecord.user_id == UID_A, ErrorRecord.question_id == env.q0_id).count()
        == 1
    )
    updated = env.db.query(ErrorRecord).filter(ErrorRecord.id == error.id).one()
    assert updated.status == "active"
    assert updated.review_count == 2
    assert updated.accuracy == 1.0

    review = env.db.query(ReviewRecord).filter(ReviewRecord.user_id == UID_A, ReviewRecord.item_id == error.id).one()
    assert review.result == "good"
    assert review.grade == 5
    assert review.mastery_after == 100

    schedule = (
        env.db.query(ReviewSchedule)
        .filter(
            ReviewSchedule.user_id == UID_A,
            ReviewSchedule.item_type == "error_record",
            ReviewSchedule.item_id == error.id,
        )
        .one()
    )
    assert schedule.algorithm == "fsrs"
    assert schedule.state == 2
    assert schedule.repetitions == 1
    assert schedule.lapses == 0
    assert schedule.stability > 1
    assert schedule.interval_days > 1
    assert updated.interval_days == schedule.interval_days
    assert to_naive_utc(updated.next_review) == to_naive_utc(schedule.next_review_at)

    session = env.db.query(QuizSession).filter(QuizSession.id == session_id).one()
    assert session.answered_count == 1
    assert session.correct_count == 1


@pytest.mark.parametrize("question_key", ["q_low_id", "q_pending_id", "q_subjective_id"])
def test_pending_low_confidence_and_unscored_do_not_advance_fsrs(wrong_review_env, question_key):
    env = wrong_review_env
    error = _add_error(env, getattr(env, question_key))
    schedule = _add_schedule(env, error.id)
    schedule_before = _schedule_snapshot(schedule)
    error_next_review = to_naive_utc(error.next_review)

    response = _submit(env, getattr(env, question_key), "待确认答案", error_id=error.id)
    assert response.status_code == 200, response.text
    assert response.json()["correct"] is None
    assert response.json()["needs_review"] is True

    env.db.expire_all()
    answer = env.db.query(AnswerRecord).filter(AnswerRecord.user_id == UID_A).one()
    assert answer.is_correct is None
    updated = env.db.query(ErrorRecord).filter(ErrorRecord.id == error.id).one()
    assert updated.review_count == 1
    assert updated.accuracy == 0.2
    assert to_naive_utc(updated.next_review) == error_next_review
    unchanged = (
        env.db.query(ReviewSchedule)
        .filter(
            ReviewSchedule.user_id == UID_A,
            ReviewSchedule.item_type == "error_record",
            ReviewSchedule.item_id == error.id,
        )
        .one()
    )
    assert _schedule_snapshot(unchanged) == schedule_before
    assert (
        env.db.query(ReviewRecord).filter(ReviewRecord.user_id == UID_A, ReviewRecord.item_id == error.id).count() == 0
    )
    assert env.db.query(ErrorRecord).filter(ErrorRecord.user_id == UID_A).count() == 1


def test_graduated_error_rejects_review_submission_and_apply_review(wrong_review_env):
    env = wrong_review_env
    error = _add_error(env, env.q0_id, status="graduated")
    schedule = _add_schedule(env, error.id)
    schedule_before = _schedule_snapshot(schedule)
    session_id = _create_session(env, env.q0_id)

    response = _submit(env, env.q0_id, "A", error_id=error.id, session_id=session_id)
    assert response.status_code == 409, response.text
    assert response.json()["message"] == "错题已毕业，不能再重练"

    with pytest.raises(ValueError, match="毕业"):
        review_service.apply_review(
            env.db,
            item_type="error",
            item_id=error.id,
            result="mastered",
            commit=False,
            user_id=UID_A,
        )
    env.db.rollback()
    env.db.expire_all()
    assert env.db.query(AnswerRecord).filter(AnswerRecord.user_id == UID_A).count() == 0
    assert env.db.query(QuizAttempt).filter(QuizAttempt.user_id == UID_A).count() == 0
    assert env.db.query(ReviewRecord).filter(ReviewRecord.user_id == UID_A).count() == 0
    unchanged = env.db.query(ErrorRecord).filter(ErrorRecord.id == error.id).one()
    assert unchanged.status == "graduated"
    assert unchanged.review_count == 1
    assert (
        _schedule_snapshot(env.db.query(ReviewSchedule).filter(ReviewSchedule.id == schedule.id).one())
        == schedule_before
    )
    session = env.db.query(QuizSession).filter(QuizSession.id == session_id).one()
    assert session.answered_count == 0


def test_graduate_cleans_owned_schedule_and_due_queue_excludes_graduated(wrong_review_env):
    env = wrong_review_env
    error = _add_error(env, env.q0_id)
    own_schedule = _add_schedule(env, error.id)
    other_schedule = _add_schedule(env, error.id, uid=UID_B)
    own_schedule_id = own_schedule.id
    other_schedule_id = other_schedule.id
    error_id = error.id
    active_error = _add_error(env, env.q1_id)
    _add_schedule(env, active_error.id)

    env.login(UID_A)
    before = env.client.get("/api/review/due", params={"include_new": False}).json()
    assert error_id in {item["id"] for item in before["items"] if item["item_type"] == "error"}

    response = env.client.post(f"/api/errors/{error_id}/graduate")
    assert response.status_code == 200, response.text
    env.db.expire_all()
    assert env.db.query(ErrorRecord).filter(ErrorRecord.id == error_id).one().status == "graduated"
    assert env.db.query(ReviewSchedule).filter(ReviewSchedule.id == own_schedule_id).first() is None
    assert env.db.query(ReviewSchedule).filter(ReviewSchedule.id == other_schedule_id).first() is not None

    after = env.client.get("/api/review/due", params={"include_new": False}).json()
    due_error_ids = {item["id"] for item in after["items"] if item["item_type"] == "error"}
    assert error_id not in due_error_ids
    assert active_error.id in due_error_ids

    env.db.add(
        ReviewSchedule(
            user_id=UID_A,
            item_type="error_record",
            item_id=error_id,
            algorithm="fsrs",
            interval_days=1,
            next_review_at=utcnow() - datetime.timedelta(days=1),
        )
    )
    env.db.commit()
    defended = env.client.get("/api/review/due", params={"include_new": False}).json()
    assert error_id not in {item["id"] for item in defended["items"] if item["item_type"] == "error"}


def test_delete_cleans_only_owned_error_schedule(wrong_review_env):
    env = wrong_review_env
    error = _add_error(env, env.q0_id)
    own_schedule = _add_schedule(env, error.id)
    other_schedule = _add_schedule(env, error.id, uid=UID_B)
    error_id = error.id
    own_schedule_id = own_schedule.id
    other_schedule_id = other_schedule.id

    env.login(UID_A)
    response = env.client.delete(f"/api/errors/{error_id}")
    assert response.status_code == 200, response.text
    env.db.expire_all()
    assert env.db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first() is None
    assert env.db.query(ReviewSchedule).filter(ReviewSchedule.id == own_schedule_id).first() is None
    assert env.db.query(ReviewSchedule).filter(ReviewSchedule.id == other_schedule_id).first() is not None
