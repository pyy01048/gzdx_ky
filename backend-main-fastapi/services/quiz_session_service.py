from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from utils.scope import owner_id

from models import QuizAttempt, QuizQuestion, QuizSession, QuizSessionQuestion
from services.question_evidence import evidence_for_questions
from services.quiz_query import question_owner_expr


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _owned_session(db: Session, user, session_id: int, *, lock: bool = False) -> QuizSession:
    query = db.query(QuizSession).filter(QuizSession.id == session_id, QuizSession.user_id == owner_id(user))
    if lock:
        query = query.with_for_update()
    session = query.first()
    if session is None:
        raise HTTPException(status_code=404, detail="刷题会话不存在")
    return session


def _snapshot(question: QuizQuestion, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": question.id,
        "content": question.content,
        "options": question.options,
        "images": question.images,
        "answer": question.answer,
        "analysis": question.analysis,
        "subject": question.subject,
        "chapter": question.chapter,
        "knowledge_point": question.knowledge_point,
        "difficulty": question.difficulty,
        "source_label": question.source_label,
        "source_kind": question.source_kind,
        "year": question.year,
        "paper": question.paper,
        "paper_id": question.paper_id,
        "origin_document_id": question.origin_document_id,
        "origin_chunk_id": question.origin_chunk_id,
        "source_page": question.source_page,
        "question_no": question.question_no,
        "question_type": question.question_type,
        "answer_type": question.answer_type,
        "answer_confidence": question.answer_confidence,
        # 创建时冻结；后续关联/教材/原卷变化不改变历史会话证据。
        "evidence": evidence,
    }


def _new_session(user, payload, total: int) -> QuizSession:
    return QuizSession(
        user_id=owner_id(user),
        mode=payload.mode or "free_practice",
        title=payload.title or "普通刷题",
        no_answer=bool(payload.no_answer),
        basis=payload.basis,
        filters=payload.filters or {},
        knowledge_point_ids=payload.knowledge_point_ids or [],
        current_index=min(payload.start_index, max(0, total - 1)),
        version=1,
        drafts={},
        text_drafts={},
        self_scores={},
        marked={},
        total_questions=total,
        status="in_progress",
    )


def create_session(db: Session, user, payload) -> QuizSession:
    question_ids = list(dict.fromkeys(payload.question_ids))
    questions = db.query(QuizQuestion).filter(QuizQuestion.id.in_(question_ids), question_owner_expr(user)).all()
    by_id = {question.id: question for question in questions}
    if len(by_id) != len(question_ids):
        raise HTTPException(status_code=404, detail="部分题目不存在或无权访问")

    session = _new_session(user, payload, len(question_ids))
    db.add(session)
    db.flush()
    position = 0
    evidence = evidence_for_questions(db, [by_id[question_id] for question_id in question_ids])
    for question_id in question_ids:
        db.add(
            QuizSessionQuestion(
                session_id=session.id,
                user_id=owner_id(user),
                question_id=question_id,
                position=position,
                snapshot=_snapshot(by_id[question_id], evidence.get(question_id)),
            )
        )
        position += 1
    db.commit()
    db.refresh(session)
    return session


def create_session_from_query(db: Session, user, payload, query, allowed_expr) -> QuizSession:
    """从受控的服务端查询分页创建会话，单事务且不向前端回传全量题。

    查询必须只产生一个 QuizQuestion（或以其为唯一首列），并由调用方附加同一
    用户资产口径；这里再次应用 allowed_expr，避免以后新增入口绕过隔离。
    每批 200 题，既不触发通用 POST 的 question_ids 上限，也不构造超大 IN。
    """
    query = query.filter(allowed_expr)
    total = query.count()
    session = _new_session(user, payload, total)
    db.add(session)
    db.flush()
    last_id: int | None = None
    position = 0
    while True:
        batch_query = query
        if last_id is not None:
            batch_query = batch_query.filter(QuizQuestion.id > last_id)
        rows = batch_query.order_by(QuizQuestion.id.asc()).limit(200).all()
        if not rows:
            break
        questions = [row if isinstance(row, QuizQuestion) else row[0] for row in rows]
        evidence = evidence_for_questions(db, questions)
        for question in questions:
            db.add(
                QuizSessionQuestion(
                    session_id=session.id,
                    user_id=owner_id(user),
                    question_id=question.id,
                    position=position,
                    snapshot=_snapshot(question, evidence.get(question.id)),
                )
            )
            position += 1
        last_id = questions[-1].id
    # 并发删除可能让实际快照数少于 count；以真实写入数为准。
    session.total_questions = position
    session.current_index = min(session.current_index, max(0, position - 1))
    db.commit()
    db.refresh(session)
    return session


def attempt_result(attempt: QuizAttempt) -> dict[str, Any]:
    try:
        result = json.loads(attempt.feedback) if attempt.feedback else {}
    except (TypeError, ValueError):
        result = {}
    result.setdefault("question_id", attempt.question_id)
    result.setdefault("my_answer", attempt.user_answer)
    result.setdefault("correct", attempt.is_correct)
    result.setdefault("needs_review", attempt.is_correct is None)
    result.setdefault("record_id", attempt.answer_record_id)
    result.setdefault("self_score", attempt.score)
    result.setdefault("client_attempt_id", attempt.client_attempt_id)
    return result


def serialize_session(db: Session, session: QuizSession) -> dict[str, Any]:
    attempts = db.query(QuizAttempt).filter(QuizAttempt.session_id == session.id).all()
    answered_ids = {attempt.question_id for attempt in attempts}
    records = {str(attempt.question_id): attempt_result(attempt) for attempt in attempts}
    questions = []
    for item in session.questions:
        question = dict(item.snapshot or {})
        # 206 之前的旧快照没有证据字段；显式 NULL，不伪装成完整证据链。
        question.setdefault("evidence", None)
        if not session.no_answer and item.question_id not in answered_ids:
            question["answer"] = None
            question["analysis"] = None
        questions.append(question)
    return {
        "session_id": session.id,
        "title": session.title,
        "mode": session.mode,
        "no_answer": session.no_answer,
        "basis": session.basis,
        "filters": session.filters or {},
        "knowledge_point_ids": session.knowledge_point_ids or [],
        "question_ids": [item.question_id for item in session.questions],
        "questions": questions,
        "current_index": session.current_index,
        "version": session.version,
        "drafts": session.drafts or {},
        "text_drafts": session.text_drafts or {},
        "self_scores": session.self_scores or {},
        "marked": session.marked or {},
        "elapsed_seconds": session.duration_seconds,
        "duration_seconds": session.duration_seconds,
        "total_questions": session.total_questions,
        "answered_count": session.answered_count,
        "correct_count": session.correct_count,
        "status": session.status,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "records": records,
    }


def patch_session(db: Session, user, session_id: int, payload) -> QuizSession:
    session = _owned_session(db, user, session_id, lock=True)
    if session.status != "in_progress":
        raise HTTPException(status_code=409, detail="会话已结束，不能再保存进度")
    if payload.version is not None and payload.version != session.version:
        raise HTTPException(status_code=409, detail="进度版本已变化，请刷新后重试")

    updates = payload.model_dump(exclude_unset=True, exclude={"version"})
    for field in ("drafts", "text_drafts", "self_scores", "marked"):
        if field in updates:
            value = updates[field]
            if not isinstance(value, dict):
                raise HTTPException(status_code=400, detail=f"{field} 必须是对象")
            updates[field] = {str(key): item for key, item in value.items()}
    if "current_index" in updates:
        updates["current_index"] = max(0, min(int(updates["current_index"]), max(0, session.total_questions - 1)))
    if "duration_seconds" in updates:
        updates["duration_seconds"] = max(0, int(updates["duration_seconds"]))
    for field, value in updates.items():
        setattr(session, field, value)
    session.version += 1
    session.updated_at = _now()
    db.commit()
    db.refresh(session)
    return session


def complete_session(db: Session, user, session_id: int) -> QuizSession:
    session = _owned_session(db, user, session_id, lock=True)
    if session.status == "abandoned":
        raise HTTPException(status_code=409, detail="会话已放弃")
    if session.status != "completed":
        session.status = "completed"
        session.completed_at = _now()
        session.updated_at = _now()
        session.version += 1
        db.commit()
        db.refresh(session)
    return session


def latest_session(db: Session, user) -> QuizSession | None:
    return (
        db.query(QuizSession)
        .filter(QuizSession.user_id == owner_id(user), QuizSession.status == "in_progress")
        .order_by(QuizSession.updated_at.desc(), QuizSession.id.desc())
        .first()
    )


def lock_submission(db: Session, user, session_id: int, question_id: int):
    session = _owned_session(db, user, session_id, lock=True)
    if session.status != "in_progress":
        raise HTTPException(status_code=409, detail="会话已结束，不能再提交答案")
    item = next((row for row in session.questions if row.question_id == question_id), None)
    if item is None:
        raise HTTPException(status_code=400, detail="题目不属于当前会话")
    attempt = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.session_id == session.id, QuizAttempt.question_id == question_id)
        .first()
    )
    return session, attempt


def attach_attempt(
    db: Session, user, session: QuizSession, *, question_id: int, record, result: dict[str, Any], cost_seconds: int
):
    db.flush()
    attempt = QuizAttempt(
        session_id=session.id,
        question_id=question_id,
        user_id=owner_id(user),
        client_attempt_id=result.get("client_attempt_id"),
        answer_record_id=record.id,
        user_answer=record.my_answer,
        is_correct=record.is_correct,
        score=result.get("self_score"),
        quality=5 if record.is_correct is True else 1 if record.is_correct is False else 3,
        time_spent_seconds=max(0, int(cost_seconds or 0)),
        feedback=json.dumps(result, ensure_ascii=False, default=str),
        self_rating="correct" if record.is_correct is True else "wrong" if record.is_correct is False else "pending",
    )
    db.add(attempt)
    db.flush()
    session.answered_count = db.query(func.count(QuizAttempt.id)).filter(QuizAttempt.session_id == session.id).scalar()
    session.correct_count = (
        db.query(func.count(QuizAttempt.id))
        .filter(QuizAttempt.session_id == session.id, QuizAttempt.is_correct.is_(True))
        .scalar()
    )
    session.duration_seconds = max(session.duration_seconds, int(cost_seconds or 0))
    session.updated_at = _now()
    return attempt
