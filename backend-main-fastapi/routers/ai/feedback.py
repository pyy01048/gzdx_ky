# -*- coding: utf-8 -*-
"""AI 答疑回答反馈路由（R4：有用 / 无用 / 纠错三键）。

端点：
  - POST /api/ai/answers/{answer_id}/feedback  用户提交反馈（要求登录）
  - GET  /api/ai/answers/{answer_id}/feedback  管理员查看某回答的反馈列表
"""

from __future__ import annotations

from typing import Optional

from database import get_db
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from services.ai_feedback_service import (
    FEEDBACK_TYPES,
    list_feedback,
    submit_feedback,
)
from sqlalchemy.orm import Session
from utils.security import current_user, require_admin

router = APIRouter(prefix="/api/ai", tags=["AI 反馈"])


class FeedbackPayload(BaseModel):
    """反馈提交载荷。"""

    feedback_type: str
    correction_text: Optional[str] = None

    @field_validator("feedback_type")
    @classmethod
    def _check_feedback_type(cls, v: str) -> str:
        if v not in FEEDBACK_TYPES:
            raise ValueError(f"feedback_type 必须为 {FEEDBACK_TYPES} 之一")
        return v


@router.post("/answers/{answer_id}/feedback")
async def post_feedback(
    answer_id: str,
    payload: FeedbackPayload,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    """用户对 AI 答疑回答提交反馈。

    重复反馈（同 answer_id + user_id）返回 409；未登录返回 401（由 current_user 抛）；
    feedback_type 不合法返回 422（由 Pydantic 校验抛）。
    """
    try:
        feedback_id = await submit_feedback(
            db,
            answer_id=answer_id,
            user_id=user.id,
            feedback_type=payload.feedback_type,
            correction_text=payload.correction_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "feedback_id": feedback_id}


@router.get("/answers/{answer_id}/feedback")
async def get_feedback(
    answer_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_admin),
):
    """管理员查看某回答的反馈列表。"""
    items = await list_feedback(db, answer_id=answer_id)
    return {"total": len(items), "items": items}
