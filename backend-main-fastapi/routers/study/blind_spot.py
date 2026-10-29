"""知识盲区池路由（A4）：前缀 /api/blind-spot。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import User
from services import blind_spot_pool
from services.module_a_schema import ensure_module_a_schema

from utils.response import MAX_PAGE_SIZE
from utils.scope import owner_id  # B4 行级隔离：写入归属
from utils.security import current_user

router = APIRouter(prefix="/api/blind-spot", tags=["知识盲区"])


class ResolveRequest(BaseModel):
    action: str = "resolved"  # resolved | ignored | duplicate


@router.get("/gaps")
def list_gaps(
    subject: Optional[str] = None,
    status: str = "open",
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """盲区看板：待补充问题清单（默认按出现次数降序）。"""
    ensure_module_a_schema(db)
    return blind_spot_pool.get_gaps(db, subject=subject, status=status, limit=limit, user_id=owner_id(user))


@router.get("/top")
def top_gaps(
    subject: Optional[str] = None,
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """高频缺口聚合。"""
    ensure_module_a_schema(db)
    return blind_spot_pool.top_gaps(db, subject=subject, limit=limit, user_id=owner_id(user))


@router.get("/weakest-subjects")
def weakest_subjects(limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """薄弱科目排行（未解决缺口加权）。"""
    ensure_module_a_schema(db)
    return blind_spot_pool.get_weakest_subjects(db, limit=limit, user_id=owner_id(user))


@router.get("/weakest-kps")
def weakest_kps(limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """薄弱知识点建议（反哺刷题）。"""
    ensure_module_a_schema(db)
    return blind_spot_pool.get_weakest_kps(db, limit=limit, user_id=owner_id(user))


@router.get("/weekly-topics")
def weekly_topics(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """周会议题聚合（多人计数视图）：跨小组按 subject+gap_type 统计近 N 天活跃缺口。

    只返回聚合计数（open 数 / 参与人数 / 出现总次数）与最近建议，
    **不返回他人原始问题文本**，在聚合层守住 B4 的行级隔离精神。
    """
    ensure_module_a_schema(db)
    return blind_spot_pool.weekly_topics(db, days=days, limit=limit)


@router.post("/{gap_id}/resolve")
def resolve_gap(gap_id: int, req: ResolveRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """标记缺口已处理（resolved | ignored | duplicate）。"""
    ensure_module_a_schema(db)
    if not blind_spot_pool.resolve_gap(db, gap_id, action=req.action, user_id=owner_id(user)):
        raise HTTPException(status_code=404, detail="缺口不存在")
    return {"id": gap_id, "status": req.action, "message": "缺口状态已更新"}
