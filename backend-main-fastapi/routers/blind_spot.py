"""知识盲区池路由（A4）：前缀 /api/blind-spot。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services import blind_spot_pool
from services.module_a_schema import ensure_module_a_schema

router = APIRouter(prefix="/api/blind-spot", tags=["知识盲区"])


class ResolveRequest(BaseModel):
    action: str = "resolved"  # resolved | ignored | duplicate


@router.get("/gaps")
def list_gaps(
    subject: Optional[str] = None,
    status: str = "open",
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """盲区看板：待补充问题清单（默认按出现次数降序）。"""
    ensure_module_a_schema(db)
    return blind_spot_pool.get_gaps(db, subject=subject, status=status, limit=limit)


@router.get("/top")
def top_gaps(
    subject: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """高频缺口聚合。"""
    ensure_module_a_schema(db)
    return blind_spot_pool.top_gaps(db, subject=subject, limit=limit)


@router.get("/weakest-subjects")
def weakest_subjects(limit: int = 10, db: Session = Depends(get_db)):
    """薄弱科目排行（未解决缺口加权）。"""
    ensure_module_a_schema(db)
    return blind_spot_pool.get_weakest_subjects(db, limit=limit)


@router.get("/weakest-kps")
def weakest_kps(limit: int = 20, db: Session = Depends(get_db)):
    """薄弱知识点建议（反哺刷题）。"""
    ensure_module_a_schema(db)
    return blind_spot_pool.get_weakest_kps(db, limit=limit)


@router.post("/{gap_id}/resolve")
def resolve_gap(gap_id: int, req: ResolveRequest, db: Session = Depends(get_db)):
    """标记缺口已处理（resolved | ignored | duplicate）。"""
    ensure_module_a_schema(db)
    if not blind_spot_pool.resolve_gap(db, gap_id, action=req.action):
        raise HTTPException(status_code=404, detail="缺口不存在")
    return {"id": gap_id, "status": req.action, "message": "缺口状态已更新"}
