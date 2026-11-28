# -*- coding: utf-8 -*-
"""经验卡路由（已上岸校友分享 · R6）。

alumni 角色提交结构化经验卡，管理员审核通过 / 驳回，公开列表默认只返回已审核。
端点：
  - POST   /api/experiences            alumni 提交（要求 role=alumni）
  - GET    /api/experiences            公开列表（默认 status=approved）
  - POST   /api/experiences/{id}/approve  管理员审核通过
  - POST   /api/experiences/{id}/reject   管理员驳回
"""

from __future__ import annotations

from typing import Optional

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from services.experience_service import (
    ExperienceCreate,
    approve_experience,
    create_experience,
    list_experiences,
    reject_experience,
)
from sqlalchemy.orm import Session
from utils.security import current_user, require_admin

from models import Role

router = APIRouter(prefix="/api/experiences", tags=["经验卡"])


def require_alumni(user=Depends(current_user)):
    """要求 alumni 角色（已上岸校友方可提交经验卡）。"""
    if user.role != Role.alumni:
        raise HTTPException(status_code=403, detail="仅已上岸校友可提交经验卡")
    return user


@router.post("")
async def submit_experience(
    payload: ExperienceCreate,
    db: Session = Depends(get_db),
    user=Depends(require_alumni),
):
    """alumni 提交经验卡。"""
    try:
        card = await create_experience(db, author_id=user.id, data=payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize(card)


@router.get("")
async def get_experiences(
    school_id: Optional[int] = Query(None, description="按院校过滤"),
    status: Optional[str] = Query("approved", description="状态过滤，公开列表默认 approved"),
    db: Session = Depends(get_db),
):
    """公开列表（默认只返回已审核通过）。"""
    items = await list_experiences(db, school_id=school_id, status=status)
    return {"total": len(items), "items": [_serialize(c) for c in items]}


@router.post("/{card_id}/approve")
async def approve_card(
    card_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """管理员审核通过。"""
    try:
        card = await approve_experience(db, card_id=card_id, approver_id=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize(card)


@router.post("/{card_id}/reject")
async def reject_card(
    card_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """管理员驳回。"""
    try:
        card = await reject_experience(db, card_id=card_id, approver_id=user.id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize(card)


def _serialize(card) -> dict:
    """经验卡序列化（含 evidence 与审核状态）。"""
    return {
        "id": card.id,
        "author_id": card.author_id,
        "school_id": card.school_id,
        "major_id": card.major_id,
        "year": card.year,
        "score": card.score,
        "content": card.content,
        "methodology": card.methodology,
        "evidence": card.evidence_json,
        "status": card.status,
        "created_at": card.created_at.isoformat() if card.created_at else None,
        "approved_at": card.approved_at.isoformat() if card.approved_at else None,
        "approved_by": card.approved_by,
    }
