# -*- coding: utf-8 -*-
"""数据地基路由（V12）：题库包导入 / 薄弱点聚合 / 人工确认队列 / 学习快照。"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services import qa_foundation
from services import agent_router as agent_router_svc

from utils.response import MAX_PAGE_SIZE
from utils.security import require_admin

router = APIRouter(prefix="/api/qa", tags=["数据地基"], dependencies=[Depends(require_admin)])


@router.post("/agent/route")
def agent_route(payload: dict):
    """轻量 Agent 编排：意图识别 → 能力路由（Tutor/Planner/Consultant/Radar/Reviewer）。"""
    question = str(payload.get("question", ""))
    return agent_router_svc.route(question)


class QbankImportReq(BaseModel):
    """题库包导入请求：payload 为题目列表或 {科目: [...]} 字典。"""
    payload: dict = Field(..., description="题目 JSON（list / {questions:[…]} / {科目:[…]})")
    subject: Optional[str] = Field(None, description="强制指定科目（payload 未带科目时）")
    dry_run: bool = Field(True, description="默认只跑 QC 不入库")


class ReviewResolveReq(BaseModel):
    action: str = Field(..., description="confirm / reject")
    resolution: Optional[str] = None


@router.post("/import-qbank")
def import_qbank(req: QbankImportReq, db: Session = Depends(get_db)):
    """公共课真题归位：JSON 题库包 → 题库 + 试卷 + QC 报告（dry_run 先审后灌）。"""
    try:
        return qa_foundation.import_qbank(
            db, req.payload, subject=req.subject, dry_run=req.dry_run
        )
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"JSON 解析失败: {e}")


@router.post("/refresh-weak")
def refresh_weak(db: Session = Depends(get_db)):
    """刷新薄弱知识点聚合表（错题+作答流水 → weak_knowledge）。"""
    return qa_foundation.refresh_weak_knowledge(db)


@router.get("/weak-knowledge")
def weak_knowledge(subject: Optional[str] = None, limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
                   db: Session = Depends(get_db)):
    """薄弱知识点列表（按掌握度升序 = 最薄弱在前）。"""
    return qa_foundation.list_weak_knowledge(db, subject=subject, limit=limit)


@router.get("/review-queue")
def review_queue(status: str = "pending", limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
                 db: Session = Depends(get_db)):
    """低置信答案人工确认队列（103 冲突根治：确认而非自动消解）。"""
    return qa_foundation.review_queue(db, status=status, limit=limit)


@router.post("/review-queue/{queue_id}/resolve")
def resolve_review(queue_id: int, req: ReviewResolveReq, db: Session = Depends(get_db)):
    """confirm=采纳答案（user_confirmed/1.0）；reject=清空答案（题干保留）。"""
    ok = qa_foundation.resolve_review(db, queue_id, req.action, req.resolution)
    if not ok:
        raise HTTPException(status_code=404, detail="队列项不存在或 action 非法")
    return {"resolved": True, "action": req.action}


@router.get("/export-snapshot")
def export_snapshot(db: Session = Depends(get_db)):
    """学习快照 JSON（错题/薄弱点），供桌面 Agent 直读生成周复盘。"""
    return qa_foundation.export_snapshot(db)
