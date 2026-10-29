"""三层可审计记忆路由（55 号方案 P0-1）：前缀 /api/memory。

提供：
  GET  /api/memory/overview          记忆图谱总览
  GET  /api/memory/traces            L1 原始轨迹列表
  GET  /api/memory/traces/{id}      单条轨迹详情（含 payload 溯源）
  GET  /api/memory/facts             L2 摘要事实列表
  POST /api/memory/facts/{id}/correct  用户纠错 L2 事实
  GET  /api/memory/synthesis         L3 综合画像列表
  POST /api/memory/synthesis/{id}/correct 用户纠错 L3
  POST /api/memory/distill           手动触发 L2 蒸馏（规则版）
  POST /api/memory/profile           生成/刷新 L3 综合画像
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import User
from services import memory_service
from utils.response import MAX_PAGE_SIZE
from utils.scope import owner_id
from utils.security import current_user

router = APIRouter(prefix="/api/memory", tags=["可审计记忆"])


class CorrectFactRequest(BaseModel):
    corrected_claim: str = Field(..., min_length=1, max_length=2000, description="纠正后的事实陈述")


class CorrectSynthesisRequest(BaseModel):
    corrected_summary: str = Field(..., min_length=1, max_length=4000, description="纠正后的综合结论")


class DistillRequest(BaseModel):
    limit_traces: int = Field(200, ge=1, le=500, description="扫描的 L1 轨迹条数上限")
    min_confidence: float = Field(0.3, ge=0.0, le=1.0, description="最低置信度")


@router.get("/overview")
def overview(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """记忆图谱总览：L1/L2/L3 各层数量与纠错数。"""
    return memory_service.memory_overview(db, user_id=owner_id(user))


@router.get("/traces")
def traces(
    trace_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """L1 原始轨迹列表（按时间倒序）。"""
    return memory_service.list_traces(
        db, user_id=owner_id(user), trace_type=trace_type, limit=limit, offset=offset,
    )


@router.get("/traces/{trace_id}")
def trace_detail(
    trace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """单条 L1 轨迹详情（含 payload 原始上下文，供溯源）。"""
    row = memory_service.get_trace(db, trace_id=trace_id, user_id=owner_id(user))
    if not row:
        raise HTTPException(status_code=404, detail="轨迹不存在")
    return row


@router.get("/facts")
def facts(
    fact_type: Optional[str] = None,
    subject: Optional[str] = None,
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """L2 摘要事实列表（含 evidence 溯源）。"""
    return memory_service.list_facts(
        db, user_id=owner_id(user), fact_type=fact_type, subject=subject,
        limit=limit, offset=offset,
    )


@router.post("/facts/{fact_id}/correct")
def correct_fact(
    fact_id: int,
    req: CorrectFactRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """用户纠错 L2 事实（保留原值快照）。"""
    updated = memory_service.correct_fact(
        db, user_id=owner_id(user), fact_id=fact_id, corrected_claim=req.corrected_claim,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="事实不存在或无权修改")
    return updated


@router.get("/synthesis")
def synthesis(
    synth_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """L3 综合画像列表。"""
    return memory_service.list_synthesis(
        db, user_id=owner_id(user), synth_type=synth_type, limit=limit, offset=offset,
    )


@router.post("/synthesis/{synthesis_id}/correct")
def correct_synthesis(
    synthesis_id: int,
    req: CorrectSynthesisRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """用户纠错 L3 综合画像（保留原值快照）。"""
    updated = memory_service.correct_synthesis(
        db, user_id=owner_id(user), synthesis_id=synthesis_id,
        corrected_summary=req.corrected_summary,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="画像不存在或无权修改")
    return updated


@router.post("/distill")
def distill(
    req: DistillRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """手动触发 L2 蒸馏（规则版，从 L1 轨迹提取摘要事实）。"""
    return memory_service.distill_facts(
        db,
        user_id=owner_id(user),
        limit_traces=req.limit_traces,
        min_confidence=req.min_confidence,
    )


@router.post("/profile")
def profile(
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """生成/刷新 L3 综合画像。"""
    result = memory_service.build_profile(db, user_id=owner_id(user), force=force)
    if not result:
        raise HTTPException(status_code=400, detail="画像生成失败")
    return result