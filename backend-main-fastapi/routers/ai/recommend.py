"""闭环个性化推题路由（55 号 DeepTutor 升级方案 P0-C）：前缀 /api/recommend。

提供：
  GET  /api/recommend/weak-points   融合信号识别薄弱知识点
  POST /api/recommend/variants      LLM 生成薄弱点变式题并入库
  POST /api/recommend/mastery-gate  掌握门控（连续答对判定）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import User
from services import recommend_loop
from utils.scope import owner_id
from utils.security import current_user

router = APIRouter(prefix="/api/recommend", tags=["个性化推题"])


class VariantsRequest(BaseModel):
    kp_id: int = Field(..., description="薄弱知识点 ID")
    count: int = Field(3, ge=1, le=10, description="生成题目数量")


class MasteryGateRequest(BaseModel):
    kp_id: int = Field(..., description="知识点 ID")
    consecutive_required: int = Field(3, ge=1, le=10, description="连续答对阈值")


@router.get("/weak-points")
def weak_points(
    subject: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50, description="返回条数"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """融合错题密度 / 掌握度 / 记忆事实三个信号识别薄弱知识点。"""
    items = recommend_loop.identify_weak_points(
        db, user_id=owner_id(user), subject=subject, limit=limit
    )
    return {"items": items}


@router.post("/variants")
def variants(
    req: VariantsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """基于薄弱知识点生成变式题并入库。

    生成失败（模型输出非法 JSON 等）时返回 HTTP 200 + ``{"created": 0, "error": ...}``，
    不抛 500（旁路容错）。
    """
    try:
        result = recommend_loop.generate_variant_questions(
            db, user_id=owner_id(user), kp_id=req.kp_id, count=req.count
        )
    except ValueError as exc:
        # 知识点不存在 → 业务性错误，仍以 200 + error 返回，不抛 500
        return {"created": 0, "error": str(exc)}
    if result.get("created", 0) == 0 and result.get("error"):
        return result
    return result


@router.post("/mastery-gate")
def mastery_gate(
    req: MasteryGateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """掌握门控：检查薄弱知识点最近连续答对是否达到阈值。"""
    return recommend_loop.mastery_gate(
        db, user_id=owner_id(user), kp_id=req.kp_id,
        consecutive_required=req.consecutive_required,
    )