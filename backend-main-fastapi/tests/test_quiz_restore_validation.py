# -*- coding: utf-8 -*-
"""题库复核 restore：修复后必须重新逐题校验，失败题不得上架。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from database import SessionLocal

from models import QuizQuestion

VALID_OPTIONS = [
    {"key": "A", "text": "选项甲"},
    {"key": "B", "text": "选项乙"},
    {"key": "C", "text": "选项丙"},
    {"key": "D", "text": "选项丁"},
]


@pytest.fixture()
def review_question(db_schema):  # noqa: ARG001
    db = SessionLocal()
    question = QuizQuestion(
        content="恢复校验测试题：以下说法正确的是",
        options=VALID_OPTIONS,
        answer="A",
        analysis="选项甲符合题意。",
        question_type="single",
        source_kind="chapter_exercise",
        is_available=False,
        is_junk=False,
        needs_review=True,
        validation_status="fail",
        validation_errors=[{"code": "LEGACY", "message": "待修复"}],
    )
    db.add(question)
    db.commit()
    question_id = question.id
    db.close()
    try:
        yield SimpleNamespace(id=question_id)
    finally:
        db = SessionLocal()
        db.query(QuizQuestion).filter(QuizQuestion.id == question_id).delete(synchronize_session=False)
        db.commit()
        db.close()


def _reload(question_id: int) -> QuizQuestion:
    db = SessionLocal()
    try:
        return db.query(QuizQuestion).filter(QuizQuestion.id == question_id).one()
    finally:
        db.close()


def test_restore_rejects_empty_answer_and_keeps_repair(client, review_question):
    response = client.post(
        f"/api/quiz/review/{review_question.id}",
        json={"action": "restore", "answer": ""},
    )
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]["validation_errors"]
    assert "ANSWER_EMPTY" in {error["code"] for error in errors}
    assert all(error.get("detail") for error in errors)

    question = _reload(review_question.id)
    assert question.answer == ""
    assert question.is_available is False
    assert question.needs_review is True
    assert question.validation_status == "fail"
    assert "ANSWER_EMPTY" in {error["code"] for error in question.validation_errors}


def test_restore_rejects_corrupted_options(client, review_question):
    response = client.post(
        f"/api/quiz/review/{review_question.id}",
        json={
            "action": "restore",
            "options": [
                {"key": "A", "text": "重复选项甲"},
                {"key": "A", "text": "重复选项乙"},
                {"key": "C", "text": "选项丙"},
                {"key": "D", "text": "选项丁"},
            ],
        },
    )
    assert response.status_code == 422, response.text
    question = _reload(review_question.id)
    assert question.is_available is False
    assert question.needs_review is True
    assert question.validation_status == "fail"
    assert "OPTION_KEY_DUP" in {error["code"] for error in question.validation_errors}


def test_restore_allows_valid_question(client, review_question):
    response = client.post(
        f"/api/quiz/review/{review_question.id}",
        json={"action": "restore", "content": "恢复校验测试题：修复后的正确题干"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "restore"

    question = _reload(review_question.id)
    assert question.content == "恢复校验测试题：修复后的正确题干"
    assert question.is_available is True
    assert question.is_junk is False
    assert question.needs_review is False
    assert question.validation_status == "pass"
    assert question.validation_errors == []


def test_restore_preserves_warning_instead_of_forcing_pass(client, review_question):
    response = client.post(
        f"/api/quiz/review/{review_question.id}",
        json={"action": "restore", "analysis": ""},
    )
    assert response.status_code == 200, response.text
    question = _reload(review_question.id)
    assert question.is_available is True
    assert question.needs_review is False
    assert question.validation_status == "warn"
    assert "ANALYSIS_MISSING" in {error["code"] for error in question.validation_errors}
