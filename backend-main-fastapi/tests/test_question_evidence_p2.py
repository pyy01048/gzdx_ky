# -*- coding: utf-8 -*-
"""P2 题目证据链与个人持久会话契约测试（不在此任务中执行 pytest）。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from database import SessionLocal
from sqlalchemy import text
from sqlalchemy.orm import Session
from utils.security import current_user, optional_user

from models import (
    Document,
    KaoyanMajor,
    KaoyanSchool,
    KnowledgeChunk,
    KnowledgePoint,
    Paper,
    PaperQuestion,
    QuestionEvidenceLink,
    QuestionKnowledgeLink,
    QuizQuestion,
    QuizQuestionSet,
    QuizQuestionSetItem,
    QuizSession,
    Subject,
    Textbook,
    TextbookDocument,
    User,
)

_UID = 1_300_000_000 + int(uuid.uuid4().hex[:8], 16) % 100_000_000
MARKER = f"p2-evidence-{uuid.uuid4().hex}"


def _principal(uid: int):
    return SimpleNamespace(
        id=uid,
        username=f"p2_{uid}",
        display_name="p2",
        role="user",
        is_active=True,
        must_change_password=False,
        token_version=0,
        last_login_at=None,
        created_at=None,
    )


def _question(db: Session, *, owner_user_id: int | None, suffix: str, **fields):
    row = QuizQuestion(
        content=f"{MARKER}-{suffix}",
        options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
        answer="A",
        analysis="解析",
        subject="数学",
        question_type="single",
        owner_user_id=owner_user_id,
        **fields,
    )
    db.add(row)
    db.flush()
    # T2 内容可用性门禁：trg_quiz_questions_gate 在 INSERT 时因 subject_id IS NULL
    # 等条件设 validation_status='warn'。出题接口只返回 'pass' 的题，这里用 SQL
    # 直接置 pass（UPDATE validation_status 不触发该触发器）。
    db.execute(
        text("UPDATE quiz_questions SET validation_status = 'pass' WHERE id = :qid"),
        {"qid": row.id},
    )
    db.flush()
    return row


@pytest.fixture
def evidence_seed(db_schema):  # noqa: ARG001
    db = SessionLocal()
    ids: dict[str, list[int]] = {
        name: []
        for name in (
            "questions",
            "documents",
            "chunks",
            "points",
            "textbooks",
            "papers",
            "schools",
            "majors",
            "subjects",
        )
    }
    try:
        user = User(id=_UID, username=f"p2_{_UID}", password_hash="x", role="user")
        db.add(user)
        db.commit()

        subject = Subject(code=f"P2-{uuid.uuid4().hex[:8]}", name="P2数学")
        school = KaoyanSchool(name=f"{MARKER}-school")
        db.add_all([subject, school])
        db.flush()
        ids["subjects"].append(subject.id)
        ids["schools"].append(school.id)
        major = KaoyanMajor(school_id=school.id, name=f"{MARKER}-major")
        db.add(major)
        db.flush()
        ids["majors"].append(major.id)

        document = Document(file_name=f"{MARKER}.pdf", subject="数学")
        db.add(document)
        db.flush()
        ids["documents"].append(document.id)
        chunk = KnowledgeChunk(document_id=document.id, chunk_index=3, page_start=17, page_end=18, subject="数学")
        db.add(chunk)
        db.flush()
        ids["chunks"].append(chunk.id)
        point = KnowledgePoint(name="极限", document_id=document.id, source_chunk_id=chunk.id, subject="数学")
        db.add(point)
        db.flush()
        ids["points"].append(point.id)
        textbook = Textbook(
            title=f"{MARKER}-教材", authors="测试作者", subject_id=subject.id, source="official", confidence="high"
        )
        db.add(textbook)
        db.flush()
        ids["textbooks"].append(textbook.id)
        db.add(TextbookDocument(textbook_id=textbook.id, document_id=document.id, doc_role="body"))
        paper = Paper(title="精确原卷", subject="数学", year=2024, total_score=100)
        db.add(paper)
        db.flush()
        ids["papers"].append(paper.id)

        linked = _question(
            db,
            owner_user_id=_UID,
            suffix="linked",
            origin_document_id=document.id,
            origin_chunk_id=chunk.id,
            source_page=17,
            paper="原始字符串不能覆盖明确ID",
            paper_id=paper.id,
        )
        raw = _question(db, owner_user_id=_UID, suffix="raw", paper="未关联原卷")
        missing = _question(db, owner_user_id=_UID, suffix="missing")
        ids["questions"].extend([linked.id, raw.id, missing.id])
        db.add(
            QuestionKnowledgeLink(
                question_id=linked.id, knowledge_point_id=point.id, role="primary", weight=1.0, is_verified=True
            )
        )
        db.add(
            QuestionEvidenceLink(
                question_id=linked.id,
                knowledge_chunk_id=chunk.id,
                document_id=document.id,
                textbook_id=textbook.id,
                school_id=school.id,
                major_id=major.id,
                subject_id=subject.id,
                page_start=17,
                page_end=18,
                source="official_catalog",
                confidence=0.95,
                verification_status="verified",
            )
        )
        db.commit()
        yield {
            "db": db,
            "linked": linked.id,
            "raw": raw.id,
            "missing": missing.id,
            "paper": paper.id,
            "document": document.id,
            "chunk": chunk.id,
            "point": point.id,
            "textbook": textbook.id,
            "major": major.id,
            "school": school.id,
            "subject": subject.id,
            "ids": ids,
        }
    finally:
        db.rollback()
        db.query(QuizSession).filter(QuizSession.user_id.in_([_UID, _UID + 1])).delete(synchronize_session=False)
        db.query(QuizQuestion).filter(QuizQuestion.owner_user_id.in_([_UID, _UID + 1])).delete(
            synchronize_session=False
        )
        if ids["papers"]:
            db.query(PaperQuestion).filter(PaperQuestion.paper_id.in_(ids["papers"])).delete(synchronize_session=False)
        if ids["textbooks"]:
            db.query(TextbookDocument).filter(TextbookDocument.textbook_id.in_(ids["textbooks"])).delete(
                synchronize_session=False
            )
        for table, key in (
            (KnowledgePoint, "points"),
            (KnowledgeChunk, "chunks"),
            (Document, "documents"),
            (Textbook, "textbooks"),
            (Paper, "papers"),
            (KaoyanMajor, "majors"),
            (KaoyanSchool, "schools"),
            (Subject, "subjects"),
        ):
            if ids[key]:
                db.query(table).filter(table.id.in_(ids[key])).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_([_UID, _UID + 1])).delete(synchronize_session=False)
        db.commit()
        db.close()


def _login(app_module):
    previous = app_module.dependency_overrides.get(current_user)
    app_module.dependency_overrides[current_user] = lambda: _principal(_UID)
    app_module.dependency_overrides[optional_user] = lambda: _principal(_UID)
    return previous


def _restore(app_module, previous):
    for dependency, value in ((current_user, previous), (optional_user, previous)):
        if value is None:
            app_module.dependency_overrides.pop(dependency, None)
        else:
            app_module.dependency_overrides[dependency] = value


def test_evidence_chain_uses_real_ids_pages_and_freezes_into_session(client, app_module, evidence_seed):
    previous = _login(app_module)
    try:
        response = client.get(f"/api/quiz/questions/{evidence_seed['linked']}/evidence")
        assert response.status_code == 200, response.text
        evidence = response.json()
        assert evidence["origin_document_id"] == evidence_seed["document"]
        assert evidence["origin_chunk_id"] == evidence_seed["chunk"]
        assert evidence["source_page"] == 17
        assert evidence["knowledge_points"][0]["id"] == evidence_seed["point"]
        assert evidence["knowledge_points"][0]["verification_status"] == "verified"
        assert evidence["knowledge_chunks"][0]["page_start"] == 17
        assert evidence["knowledge_chunks"][0]["page_end"] == 18
        page = evidence["textbook_pages"][0]
        assert page["textbook_id"] == evidence_seed["textbook"]
        assert page["document_id"] == evidence_seed["document"]
        assert page["page_start"] == 17
        assert page["major_id"] == evidence_seed["major"]
        assert page["school_id"] == evidence_seed["school"]
        assert page["subject_id"] == evidence_seed["subject"]
        assert page["confidence"] == 0.95
        assert evidence["paper"]["id"] == evidence_seed["paper"]
        assert evidence["paper"]["match_method"] == "quiz_questions.paper_id"
        assert evidence["paper"]["raw_paper"] == "原始字符串不能覆盖明确ID"
        assert evidence["chain_summary"]["knowledge_point"]["id"] == evidence_seed["point"]
        assert evidence["chain_summary"]["knowledge_chunk"]["id"] == evidence_seed["chunk"]
        assert evidence["chain_summary"]["textbook_page"]["textbook_id"] == evidence_seed["textbook"]
        assert evidence["chain_summary"]["paper"]["id"] == evidence_seed["paper"]
        assert evidence["chain_summary"]["complete"] is True
        assert evidence["missing"] == []

        created = client.post(
            "/api/quiz/sessions", json={"question_ids": [evidence_seed["linked"]], "mode": "practice"}
        )
        assert created.status_code == 200, created.text
        snapshot = created.json()["questions"][0]
        assert snapshot["evidence"] == evidence
        assert snapshot["answer"] is None

        # 会话创建后修改原题来源，历史快照仍保持创建时证据。
        evidence_seed["db"].query(QuizQuestion).filter(QuizQuestion.id == evidence_seed["linked"]).update(
            {"paper": "已变更"}
        )
        evidence_seed["db"].commit()
        restored = client.get(f"/api/quiz/sessions/{created.json()['session_id']}")
        assert restored.status_code == 200, restored.text
        assert restored.json()["questions"][0]["evidence"] == evidence
    finally:
        _restore(app_module, previous)


def test_missing_and_unlinked_evidence_is_explicit(client, app_module, evidence_seed):
    previous = _login(app_module)
    try:
        raw = client.get(f"/api/quiz/questions/{evidence_seed['raw']}/evidence").json()
        assert raw["paper"]["linked"] is False
        assert raw["paper"]["id"] is None
        assert raw["paper"]["label"] == "未关联原卷"
        assert raw["paper"]["unlinked_reason"] == "no_explicit_relation"
        assert raw["knowledge_points"] == []
        assert raw["knowledge_chunks"] == []
        assert raw["textbook_pages"] == []
        assert raw["origin_document"] is None
        assert raw["source_page"] is None

        missing = client.get(f"/api/quiz/questions/{evidence_seed['missing']}/evidence").json()
        assert missing["paper"]["unlinked_reason"] == "missing_paper"
        assert missing["chain_summary"] == {
            "knowledge_point": None,
            "knowledge_chunk": None,
            "textbook_page": None,
            "paper": None,
            "complete": False,
        }
        assert set(missing["missing"]) == {"knowledge_points", "knowledge_chunks", "textbooks", "paper"}

        db = evidence_seed["db"]
        no_page_chunk = KnowledgeChunk(
            document_id=evidence_seed["document"], chunk_index=99, page_start=None, page_end=None, subject="数学"
        )
        db.add(no_page_chunk)
        db.flush()
        evidence_seed["ids"]["chunks"].append(no_page_chunk.id)
        no_page_question = _question(
            db,
            owner_user_id=_UID,
            suffix="no-page",
            origin_document_id=evidence_seed["document"],
            origin_chunk_id=no_page_chunk.id,
        )
        evidence_seed["ids"]["questions"].append(no_page_question.id)
        db.commit()
        no_page = client.get(f"/api/quiz/questions/{no_page_question.id}/evidence").json()
        assert no_page["knowledge_chunks"][0]["page_start"] is None
        assert no_page["knowledge_chunks"][0]["page_end"] is None
        assert no_page["knowledge_chunks"][0]["page_source"] is None
        assert no_page["textbook_pages"][0]["page_start"] is None
        assert no_page["textbook_pages"][0]["page_end"] is None
        assert no_page["textbook_pages"][0]["page_source"] is None
        assert "textbook_page_numbers" in no_page["missing"]

        second = Paper(title="另一份原卷", subject="数学", year=2024, total_score=100)
        db.add(second)
        db.flush()
        evidence_seed["ids"]["papers"].append(second.id)
        db.add_all(
            [
                PaperQuestion(paper_id=evidence_seed["paper"], question_id=evidence_seed["raw"], seq=1, content="快照"),
            ]
        )
        db.commit()
        exact = client.get(f"/api/quiz/questions/{evidence_seed['raw']}/evidence").json()
        assert exact["paper"]["linked"] is True, exact["paper"]
        assert exact["paper"]["id"] == evidence_seed["paper"]
        assert exact["paper"]["match_method"] == "paper_questions.question_id"
        db.add(PaperQuestion(paper_id=second.id, question_id=evidence_seed["raw"], seq=1, content="快照"))
        db.commit()
        ambiguous = client.get(f"/api/quiz/questions/{evidence_seed['raw']}/evidence").json()
        assert ambiguous["paper"]["linked"] is False
        assert ambiguous["paper"]["unlinked_reason"] == "ambiguous_explicit_relations"
    finally:
        _restore(app_module, previous)


def test_personal_session_uses_server_pagination_over_200_and_keeps_user_isolation(client, app_module, evidence_seed):
    previous = _login(app_module)
    try:
        db = evidence_seed["db"]
        bank = QuizQuestionSet(user_id=_UID, name=f"{MARKER}-bank")
        db.add(bank)
        db.flush()
        rows = [_question(db, owner_user_id=_UID, suffix=f"bulk-{index}") for index in range(201)]
        evidence_seed["ids"]["questions"].extend(row.id for row in rows)
        db.add_all([QuizQuestionSetItem(set_id=bank.id, question_id=row.id) for row in rows])
        outsider = User(id=_UID + 1, username=f"p2_{_UID + 1}", password_hash="x", role="user")
        db.add(outsider)
        db.flush()
        foreign = _question(db, owner_user_id=_UID + 1, suffix="foreign")
        evidence_seed["ids"]["questions"].append(foreign.id)
        db.commit()

        response = client.post("/api/quiz/personal/practice/sessions", json={"bank_id": bank.id})
        assert response.status_code == 200, response.text
        created = response.json()
        assert created["total_questions"] == 201
        assert len(created["questions"]) == 201
        assert foreign.id not in created["question_ids"]
        assert all(question["evidence"] is not None for question in created["questions"])

        session_id = created["session_id"]
        patched = client.request(
            "PATCH",
            f"/api/quiz/sessions/{session_id}",
            json={
                "version": created["version"],
                "current_index": 200,
                "drafts": {str(rows[0].id): 0},
                "marked": {str(rows[0].id): True},
                "self_scores": {str(rows[0].id): 2},
                "duration_seconds": 90,
            },
        )
        assert patched.status_code == 200, patched.text
        restored = client.get(f"/api/quiz/sessions/{session_id}")
        assert restored.json()["current_index"] == 200
        assert restored.json()["drafts"][str(rows[0].id)] == 0
        assert restored.json()["marked"][str(rows[0].id)] is True
        assert restored.json()["self_scores"][str(rows[0].id)] == 2
        assert restored.json()["duration_seconds"] == 90

        app_module.dependency_overrides[current_user] = lambda: _principal(_UID + 1)
        denied = client.get(f"/api/quiz/sessions/{session_id}")
        assert denied.status_code == 404
        denied_evidence = client.get(f"/api/quiz/questions/{evidence_seed['linked']}/evidence")
        assert denied_evidence.status_code == 404
        db.query(User).filter(User.id == _UID + 1).delete(synchronize_session=False)
        db.commit()
    finally:
        _restore(app_module, previous)
