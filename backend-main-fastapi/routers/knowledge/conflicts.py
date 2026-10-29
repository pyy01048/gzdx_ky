# -*- coding: utf-8 -*-
"""冲突复核台路由（V13 · 规格 §1.4）。

GET  /api/conflicts            列表（status/limit/offset/question_id）
GET  /api/conflicts/stats      看板
POST /api/conflicts/{id}/resolve  结案-采纳（409 幂等）
POST /api/conflicts/{id}/reject   结案-驳回（409 幂等）
POST /api/conflicts/seed          历史冲突批量入队（103 条，幂等）
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services import confidence_service

router = APIRouter(prefix="/api/conflicts", tags=["冲突复核台"])


class ResolveReq(BaseModel):
    resolution: str = Field(..., min_length=1, description="结案采纳的答案文本")
    reviewer_note: Optional[str] = None


class RejectReq(BaseModel):
    reviewer_note: Optional[str] = None


class SeedReq(BaseModel):
    rows: List[dict] = Field(..., description="历史冲突列表")


@router.get("")
def list_conflicts(
    status: str = Query("open"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    question_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    try:
        return confidence_service.list_conflicts(db, status=status, limit=limit,
                                                 offset=offset, question_id=question_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return confidence_service.conflict_stats(db)


@router.post("/{queue_id}/resolve")
def resolve(queue_id: int, req: ResolveReq, db: Session = Depends(get_db)):
    try:
        return confidence_service.resolve_conflict(db, queue_id, req.resolution.strip(),
                                                   req.reviewer_note)
    except LookupError:
        raise HTTPException(status_code=404, detail="conflict 不存在")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{queue_id}/reject")
def reject(queue_id: int, req: RejectReq, db: Session = Depends(get_db)):
    try:
        return confidence_service.reject_conflict(db, queue_id, req.reviewer_note)
    except LookupError:
        raise HTTPException(status_code=404, detail="conflict 不存在")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/seed")
def seed(req: SeedReq, db: Session = Depends(get_db)):
    return confidence_service.seed_legacy_conflicts(db, req.rows)
