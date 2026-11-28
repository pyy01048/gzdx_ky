# -*- coding: utf-8 -*-
"""个人题库：用户自建题、公共题收藏、筛选与练习。"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Literal, Optional

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from schemas import (
    PersonalQuizMasteryUpdate,
    PersonalQuizQuestionCreate,
    PersonalQuizQuestionUpdate,
    PersonalQuizSetCreate,
    PersonalQuizSetItemCreate,
    PersonalQuizSetUpdate,
)
from services import quiz_session_service
from services.personal_quiz import (
    add_membership,
    asset_query,
    get_or_create_state,
    mastery_expr,
    mastery_summary,
    normalize_personal_answer,
    normalize_personal_options,
    personal_asset_expr,
)
from services.quiz_query import practiceable_expr
from sqlalchemy import and_, or_, select
from sqlalchemy import text as _text
from sqlalchemy.orm import Session
from utils.response import MAX_PAGE_SIZE
from utils.security import current_user

from models import QuizQuestion, QuizQuestionSet, QuizQuestionSetItem, QuizQuestionState, User

router = APIRouter(prefix="/api/quiz/personal", tags=["personal-quiz"])


# 客观题题型：options 为空时不进入练习
_OBJECTIVE_TYPES = ("single", "multiple", "judge")


def _content_gate_filter():
    """内容可用性门禁（T2）：出题只出 validation_status='pass' AND is_available=true 的题。

    客观题额外校验 options 非空（NOT NULL 且文本形态非 '[]'/'null'/'{}'）；
    主观题不校验 options。叠加在既有 practiceable/asset 过滤之上。
    """
    objective_has_options = or_(
        QuizQuestion.question_type.notin_(_OBJECTIVE_TYPES),
        and_(
            QuizQuestion.options.isnot(None),
            _text("quiz_questions.options::text NOT IN ('[]','null','{}')"),
        ),
    )
    return and_(
        QuizQuestion.validation_status == "pass",
        QuizQuestion.is_available.is_(True),
        objective_has_options,
    )


class PersonalPracticeSessionCreate(BaseModel):
    """个人练习持久会话：服务端筛选并分页，不接收前端全量 question_ids。"""

    bank_id: Optional[int] = Field(None, gt=0)
    subject: Optional[str] = Field(None, max_length=100)
    chapter: Optional[str] = Field(None, max_length=200)
    question_type: Optional[Literal["single", "multiple", "judge", "fill", "essay", "calc", "draw"]] = None
    mastery_state: Optional[Literal["unmastered", "mastered"]] = None
    title: Optional[str] = Field(None, max_length=300)
    no_answer: bool = False
    start_index: int = Field(0, ge=0)


def _owned_set(db: Session, user_id: int, set_id: int) -> QuizQuestionSet:
    bank = (
        db.query(QuizQuestionSet)
        .filter(
            QuizQuestionSet.id == set_id,
            QuizQuestionSet.user_id == user_id,
        )
        .first()
    )
    if bank is None:
        raise HTTPException(status_code=404, detail="题库不存在")
    return bank


def _owned_question(db: Session, user_id: int, question_id: int) -> QuizQuestion:
    question = (
        db.query(QuizQuestion)
        .filter(
            QuizQuestion.id == question_id,
            QuizQuestion.owner_user_id == user_id,
            QuizQuestion.is_available.is_(True),
            QuizQuestion.is_junk.is_(False),
        )
        .first()
    )
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return question


def _asset_question(db: Session, user_id: int, question_id: int) -> QuizQuestion:
    question = (
        db.query(QuizQuestion)
        .filter(
            QuizQuestion.id == question_id,
            personal_asset_expr(user_id),
        )
        .first()
    )
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    return question


def _bank_membership_ids(db: Session, user_id: int, bank_id: int):
    return (
        select(QuizQuestionSetItem.question_id)
        .join(QuizQuestionSet, QuizQuestionSet.id == QuizQuestionSetItem.set_id)
        .where(
            QuizQuestionSet.id == bank_id,
            QuizQuestionSet.user_id == user_id,
        )
    )


def _bank_ids_map(db: Session, user_id: int, question_ids: list[int]) -> dict[int, list[int]]:
    if not question_ids:
        return {}
    rows = (
        db.query(QuizQuestionSetItem.question_id, QuizQuestionSetItem.set_id)
        .join(QuizQuestionSet, QuizQuestionSet.id == QuizQuestionSetItem.set_id)
        .filter(
            QuizQuestionSet.user_id == user_id,
            QuizQuestionSetItem.question_id.in_(question_ids),
        )
        .order_by(QuizQuestionSetItem.set_id)
        .all()
    )
    result: dict[int, list[int]] = {}
    for question_id, set_id in rows:
        result.setdefault(question_id, []).append(set_id)
    return result


def _state_values(state: Optional[QuizQuestionState]) -> dict:
    """提取题目作答状态；state 为 None 时返回未作答默认值。"""
    return {
        "mastery_state": state.mastery_state if state else "unmastered",
        "last_result": state.last_result if state else None,
        "attempts": int(state.attempts or 0) if state else 0,
        "last_answered_at": state.last_answered_at if state else None,
    }


def _serialize_personal_question(
    question: QuizQuestion, state: Optional[QuizQuestionState], bank_ids: list[int]
) -> dict:
    is_personal = question.owner_user_id is not None
    return {
        "id": question.id,
        "content": question.content,
        "options": question.options,
        "images": question.images or [],
        "answer": question.answer,
        "analysis": question.analysis,
        "subject": question.subject,
        "chapter": question.chapter,
        "knowledge_point": question.knowledge_point,
        "difficulty": question.difficulty,
        "question_type": question.question_type,
        "answer_type": question.answer_type,
        "source_kind": question.source_kind,
        "source_label": question.source_label or ("个人自建" if is_personal else None),
        "is_personal": is_personal,
        "bank_id": bank_ids[0] if bank_ids else None,
        "bank_ids": bank_ids,
        **_state_values(state),
    }


def _serialize_practice_question(
    question: QuizQuestion, state: Optional[QuizQuestionState], bank_ids: list[int]
) -> dict:
    # 白名单字段，严禁答案/解析/参考答案进入练习响应。
    return {
        "id": question.id,
        "content": question.content,
        "options": question.options,
        "images": question.images or [],
        "subject": question.subject,
        "chapter": question.chapter,
        "knowledge_point": question.knowledge_point,
        "difficulty": question.difficulty,
        "question_type": question.question_type,
        "answer_type": question.answer_type,
        "source_kind": question.source_kind,
        "source_label": question.source_label or ("个人自建" if question.owner_user_id else None),
        "is_personal": question.owner_user_id is not None,
        "bank_id": bank_ids[0] if bank_ids else None,
        "bank_ids": bank_ids,
        **_state_values(state),
    }


@router.get("/sets")
def list_sets(db: Session = Depends(get_db), user: User = Depends(current_user)):
    banks = (
        db.query(QuizQuestionSet)
        .filter(
            QuizQuestionSet.user_id == user.id,
        )
        .order_by(QuizQuestionSet.updated_at.desc(), QuizQuestionSet.id.desc())
        .all()
    )
    items = []
    for bank in banks:
        query = asset_query(db, user.id).filter(QuizQuestion.id.in_(_bank_membership_ids(db, user.id, bank.id)))
        summary = mastery_summary(query, user.id)
        items.append(
            {
                "id": bank.id,
                "name": bank.name,
                "description": bank.description,
                "created_at": bank.created_at,
                "updated_at": bank.updated_at,
                "question_count": summary["total"],
                "mastered_count": summary["mastered"],
            }
        )
    return {"items": items, "total": len(items)}


@router.post("/sets", status_code=201)
def create_set(payload: PersonalQuizSetCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="题库名称不能为空")
    bank = QuizQuestionSet(
        user_id=user.id,
        name=name,
        description=payload.description,
    )
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return {
        "id": bank.id,
        "name": bank.name,
        "description": bank.description,
        "created_at": bank.created_at,
        "updated_at": bank.updated_at,
        "question_count": 0,
        "mastered_count": 0,
    }


@router.put("/sets/{set_id}")
def update_set(
    set_id: int,
    payload: PersonalQuizSetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    bank = _owned_set(db, user.id, set_id)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        name = (updates["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="题库名称不能为空")
        bank.name = name
    if "description" in updates:
        bank.description = updates["description"]
    bank.updated_at = datetime.datetime.now(datetime.UTC)
    db.commit()
    return {"id": bank.id, "name": bank.name, "description": bank.description, "updated_at": bank.updated_at}


@router.delete("/sets/{set_id}")
def delete_set(set_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    bank = _owned_set(db, user.id, set_id)
    db.delete(bank)
    db.commit()
    return {"success": True, "id": set_id}


@router.post("/sets/{set_id}/items", status_code=201)
def add_set_item(
    set_id: int,
    payload: PersonalQuizSetItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _owned_set(db, user.id, set_id)
    question = (
        db.query(QuizQuestion)
        .filter(
            QuizQuestion.id == payload.question_id,
            QuizQuestion.is_available.is_(True),
            or_(QuizQuestion.owner_user_id.is_(None), QuizQuestion.owner_user_id == user.id),
            or_(QuizQuestion.is_junk.is_(False), QuizQuestion.is_junk.is_(None)),
        )
        .first()
    )
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    add_membership(db, set_id, question.id)
    db.commit()
    return {"success": True, "set_id": set_id, "question_id": question.id}


@router.delete("/sets/{set_id}/items/{question_id}")
def delete_set_item(
    set_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _owned_set(db, user.id, set_id)
    db.query(QuizQuestionSetItem).filter(
        QuizQuestionSetItem.set_id == set_id,
        QuizQuestionSetItem.question_id == question_id,
    ).delete(synchronize_session=False)
    db.commit()
    return {"success": True, "set_id": set_id, "question_id": question_id}


@router.get("/questions")
def list_personal_questions(
    bank_id: Optional[int] = Query(None, gt=0),
    subject: Optional[str] = None,
    chapter: Optional[str] = None,
    question_type: Optional[Literal["single", "multiple", "judge", "fill", "essay", "calc", "draw"]] = None,
    q: Optional[str] = None,
    mastery_state: Optional[Literal["unmastered", "mastered"]] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    query = asset_query(db, user.id).filter(_content_gate_filter())
    if bank_id is not None:
        query = query.filter(QuizQuestion.id.in_(_bank_membership_ids(db, user.id, bank_id)))
    if subject and subject.strip():
        query = query.filter(QuizQuestion.subject == subject.strip())
    if chapter and chapter.strip():
        query = query.filter(QuizQuestion.chapter == chapter.strip())
    if question_type:
        query = query.filter(QuizQuestion.question_type == question_type)
    keyword = q.strip() if q else ""
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(
                QuizQuestion.content.like(like),
                QuizQuestion.analysis.like(like),
                QuizQuestion.knowledge_point.like(like),
            )
        )

    # summary 不受 mastery_state 影响，仍沿用其余资产筛选。
    summary = mastery_summary(query, user.id)
    if mastery_state:
        query = query.filter(mastery_expr(user.id) == mastery_state)
    total = query.count()
    rows = query.order_by(QuizQuestion.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    bank_ids = _bank_ids_map(db, user.id, [row[0].id for row in rows])
    return {
        "items": [
            _serialize_personal_question(question, state, bank_ids.get(question.id, [])) for question, state in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": summary,
    }


def _validated_question_fields(payload, current: Optional[QuizQuestion] = None) -> dict:
    updates = payload.model_dump(exclude_unset=True, exclude={"bank_id"})
    question_type = updates.get("question_type") or (current.question_type if current else "single")
    options = updates.get("options") if "options" in updates else (current.options if current else None)
    updates["options"] = normalize_personal_options(options, question_type)
    if "content" in updates and not (updates["content"] or "").strip():
        raise ValueError("题干不能为空")
    if "content" in updates:
        updates["content"] = updates["content"].strip()
    answer = updates.get("answer") if "answer" in updates else (current.answer if current else None)
    if answer is None or not str(answer).strip():
        raise ValueError("答案不能为空")
    updates["answer"] = normalize_personal_answer(answer, question_type, updates["options"])
    for field in ("subject", "chapter", "knowledge_point", "analysis"):
        if field in updates and isinstance(updates[field], str):
            updates[field] = updates[field].strip() or None
    return updates


@router.post("/questions", status_code=201)
def create_personal_question(
    payload: PersonalQuizQuestionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if payload.bank_id is not None:
        _owned_set(db, user.id, payload.bank_id)
    try:
        fields = _validated_question_fields(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    question = QuizQuestion(
        **fields,
        owner_user_id=user.id,
        source_kind="user_created",
        source_label="个人自建",
        answer_type="subjective" if fields["question_type"] in ("essay", "fill", "calc", "draw") else "objective",
        answer_confidence=1.0,
        is_available=True,
        is_junk=False,
    )
    db.add(question)
    db.flush()
    if payload.bank_id is not None:
        add_membership(db, payload.bank_id, question.id)
    db.commit()
    db.refresh(question)
    bank_ids = _bank_ids_map(db, user.id, [question.id]).get(question.id, [])
    return _serialize_personal_question(question, None, bank_ids)


@router.put("/questions/{question_id}")
def update_personal_question(
    question_id: int,
    payload: PersonalQuizQuestionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    question = _owned_question(db, user.id, question_id)
    if payload.bank_id is not None:
        _owned_set(db, user.id, payload.bank_id)
    try:
        fields = _validated_question_fields(payload, question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for field, value in fields.items():
        setattr(question, field, value)
    if "question_type" in fields:
        question.answer_type = (
            "subjective" if fields["question_type"] in ("essay", "fill", "calc", "draw") else "objective"
        )
    if payload.bank_id is not None:
        add_membership(db, payload.bank_id, question.id)
    db.commit()
    db.refresh(question)
    bank_ids = _bank_ids_map(db, user.id, [question.id]).get(question.id, [])
    state = db.get(QuizQuestionState, (user.id, question.id))
    return _serialize_personal_question(question, state, bank_ids)


@router.delete("/questions/{question_id}")
def delete_personal_question(
    question_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    question = _owned_question(db, user.id, question_id)
    question.is_available = False
    question.is_junk = True
    db.commit()
    return {"success": True, "id": question.id}


@router.put("/questions/{question_id}/mastery")
def set_personal_mastery(
    question_id: int,
    payload: PersonalQuizMasteryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    _asset_question(db, user.id, question_id)
    state = get_or_create_state(db, user.id, question_id)
    state.mastery_state = payload.mastery_state
    state.updated_at = datetime.datetime.now(datetime.UTC)
    db.commit()
    return {"question_id": question_id, **_state_values(state)}


@router.get("/practice")
def personal_practice(
    bank_id: Optional[int] = Query(None, gt=0),
    mastery_state: Optional[Literal["unmastered", "mastered"]] = None,
    subject: Optional[str] = None,
    chapter: Optional[str] = None,
    question_type: Optional[Literal["single", "multiple", "judge", "fill", "essay", "calc", "draw"]] = None,
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    query = asset_query(db, user.id).filter(practiceable_expr(), _content_gate_filter())
    if bank_id is not None:
        # 他人题库自然为空，不暴露其存在性，也不返回 404。
        query = query.filter(QuizQuestion.id.in_(_bank_membership_ids(db, user.id, bank_id)))
    if mastery_state:
        query = query.filter(mastery_expr(user.id) == mastery_state)
    if subject and subject.strip():
        query = query.filter(QuizQuestion.subject == subject.strip())
    if chapter and chapter.strip():
        query = query.filter(QuizQuestion.chapter == chapter.strip())
    if question_type:
        query = query.filter(QuizQuestion.question_type == question_type)
    total = query.count()
    rows = query.order_by(QuizQuestion.id.asc()).limit(limit).all()
    bank_ids = _bank_ids_map(db, user.id, [row[0].id for row in rows])
    return {
        "items": [
            _serialize_practice_question(question, state, bank_ids.get(question.id, [])) for question, state in rows
        ],
        "total": total,
    }


@router.post("/practice/sessions")
def create_personal_practice_session(
    payload: PersonalPracticeSessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """按本人资产口径在服务端 keyset 分批创建可超过 200 题的持久会话。"""
    bank_id = payload.bank_id
    subject = payload.subject.strip() if payload.subject else None
    chapter = payload.chapter.strip() if payload.chapter else None
    query = asset_query(db, user.id).filter(practiceable_expr(), _content_gate_filter())
    if bank_id is not None:
        # 与他人旧 practice 一致：他人题库自然为空，不暴露资源存在性。
        query = query.filter(QuizQuestion.id.in_(_bank_membership_ids(db, user.id, bank_id)))
    if payload.mastery_state:
        query = query.filter(mastery_expr(user.id) == payload.mastery_state)
    if subject:
        query = query.filter(QuizQuestion.subject == subject)
    if chapter:
        query = query.filter(QuizQuestion.chapter == chapter)
    if payload.question_type:
        query = query.filter(QuizQuestion.question_type == payload.question_type)

    filters = {
        key: value
        for key, value in {
            "bank_id": bank_id,
            "subject": subject,
            "chapter": chapter,
            "question_type": payload.question_type,
            "mastery_state": payload.mastery_state,
        }.items()
        if value not in (None, "")
    }
    session_payload = SimpleNamespace(
        question_ids=[],  # 仅兼容会话服务内部模型；实际题目由受控查询分页写入。
        title=payload.title or (active_title(bank_id, db, user.id) if bank_id else "个人题库练习"),
        mode="practice",
        no_answer=payload.no_answer,
        basis={"kind": "personal_question_bank", "bank_id": bank_id},
        filters=filters,
        knowledge_point_ids=[],
        start_index=payload.start_index,
    )
    session = quiz_session_service.create_session_from_query(
        db, user, session_payload, query, personal_asset_expr(user.id)
    )
    return quiz_session_service.serialize_session(db, session)


def active_title(bank_id: int, db: Session, user_id: int) -> str:
    bank = (
        db.query(QuizQuestionSet.name)
        .filter(
            QuizQuestionSet.id == bank_id,
            QuizQuestionSet.user_id == user_id,
        )
        .first()
    )
    return f"{bank[0]}练习" if bank else "个人题库练习"
