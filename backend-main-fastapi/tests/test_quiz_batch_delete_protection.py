# -*- coding: utf-8 -*-
"""题库批量删除保护：管理员、物理删除开关、PG 可用备份与审计回归。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from core.models.schools import AuditLog
from database import SessionLocal
from routers.study import stats_export
from utils.security import current_user

from models import AnswerRecord, QuizQuestion


@pytest.fixture()
def deletable_question(app_module, db_schema):  # noqa: ARG001
    db = SessionLocal()
    question = QuizQuestion(
        content="批量删除保护测试题：待删除题目",
        options=[
            {"key": "A", "text": "选项甲"},
            {"key": "B", "text": "选项乙"},
            {"key": "C", "text": "选项丙"},
            {"key": "D", "text": "选项丁"},
        ],
        answer="A",
        analysis="选项甲符合题意。",
        question_type="single",
        source_kind="chapter_exercise",
        is_available=True,
    )
    control = QuizQuestion(
        content="批量删除保护测试题：保留题目",
        options=question.options,
        answer="B",
        analysis="选项乙符合题意。",
        question_type="single",
        source_kind="chapter_exercise",
        is_available=True,
    )
    db.add_all([question, control])
    db.flush()
    answer = AnswerRecord(
        user_id=0,
        question_id=question.id,
        my_answer="A",
        correct_answer="A",
        is_correct=True,
        subject="数学",
    )
    db.add(answer)
    db.commit()
    ids = SimpleNamespace(question=question.id, control=control.id, answer=answer.id)
    previous = app_module.dependency_overrides.get(current_user)
    db.close()
    try:
        yield ids
    finally:
        if previous is None:
            app_module.dependency_overrides.pop(current_user, None)
        else:
            app_module.dependency_overrides[current_user] = previous
        db = SessionLocal()
        db.query(AuditLog).filter(
            AuditLog.table_name == "quiz_questions",
            AuditLog.record_id.in_((ids.question, ids.control)),
        ).delete(synchronize_session=False)
        db.query(AnswerRecord).filter(AnswerRecord.id == ids.answer).delete(synchronize_session=False)
        db.query(QuizQuestion).filter(QuizQuestion.id.in_((ids.question, ids.control))).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()


def _exists(question_id: int) -> bool:
    db = SessionLocal()
    try:
        return db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first() is not None
    finally:
        db.close()


def test_batch_delete_requires_admin(client, app_module, deletable_question):
    app_module.dependency_overrides[current_user] = lambda: SimpleNamespace(id=0, role="user")
    response = client.post("/api/quiz/batch-delete", json=[deletable_question.question])
    assert response.status_code == 403, response.text
    assert _exists(deletable_question.question)


def test_batch_delete_guard_blocks_before_backup_or_mutation(client, monkeypatch, deletable_question):
    monkeypatch.delenv("KAOYAN_ALLOW_PHYSICAL_DELETE", raising=False)
    calls = []
    monkeypatch.setattr(stats_export, "ensure_write_backup", lambda: calls.append("backup"))

    response = client.post("/api/quiz/batch-delete", json=[deletable_question.question])

    assert response.status_code == 403, response.text
    assert calls == []
    assert _exists(deletable_question.question)


def test_batch_delete_backup_failure_blocks_mutation(client, monkeypatch, deletable_question):
    from services import backup_service

    monkeypatch.setenv("KAOYAN_ALLOW_PHYSICAL_DELETE", "1")
    monkeypatch.setattr(backup_service, "is_test_database", lambda: False)

    def fail_backup():
        raise RuntimeError("模拟 pg_dump 不可用")

    monkeypatch.setattr(backup_service, "create_backup", fail_backup)
    response = client.post("/api/quiz/batch-delete", json=[deletable_question.question])

    assert response.status_code == 503, response.text
    assert "写前备份失败" in response.text
    assert _exists(deletable_question.question)
    db = SessionLocal()
    try:
        assert db.query(AnswerRecord).filter(AnswerRecord.id == deletable_question.answer).first()
        assert (
            db.query(AuditLog)
            .filter(
                AuditLog.table_name == "quiz_questions",
                AuditLog.record_id == deletable_question.question,
            )
            .first()
            is None
        )
    finally:
        db.close()


def test_batch_delete_uses_shared_backup_gate():
    from services import kb_service

    assert stats_export.ensure_write_backup is kb_service.ensure_write_backup


def test_batch_delete_backs_up_deletes_answers_and_audits(client, monkeypatch, deletable_question):
    monkeypatch.setenv("KAOYAN_ALLOW_PHYSICAL_DELETE", "1")
    calls = []
    monkeypatch.setattr(stats_export, "ensure_write_backup", lambda: calls.append("backup"))

    response = client.post(
        "/api/quiz/batch-delete",
        json=[deletable_question.question, 999999999],
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": 1}
    assert calls == ["backup"]
    assert not _exists(deletable_question.question)
    assert _exists(deletable_question.control)

    db = SessionLocal()
    try:
        assert db.query(AnswerRecord).filter(AnswerRecord.id == deletable_question.answer).first() is None
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.table_name == "quiz_questions",
                AuditLog.record_id == deletable_question.question,
            )
            .one()
        )
        assert audit.action == "DELETE"
        assert audit.operator_id == 0
        assert audit.before_data["content"] == "批量删除保护测试题：待删除题目"
        assert audit.before_data["answer"] == "A"
        assert audit.change_summary
    finally:
        db.close()
