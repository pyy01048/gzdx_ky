# -*- coding: utf-8 -*-
"""P1-E 多 Agent 答疑协作端点：POST /api/ai/tutoring/orchestrated。

调用 ``services.tutor_orchestrator.orchestrate_tutoring`` 输出
retrieve→solve→verify→remedy 四阶段轨迹，供前端展示
「AI 是如何一步步得出答案的」。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import QuizQuestion, User
from utils.scope import owner_id
from utils.security import current_user
from services import tutor_orchestrator

router = APIRouter(prefix="/api/ai/tutoring", tags=["AI 讲题"])


class OrchestratedReq(BaseModel):
    question_id: int = Field(..., description="题目 ID")
    my_answer: Optional[str] = Field(None, description="学生答案（可选）")
    subject: Optional[str] = Field(None, description="科目（可选）")


@router.post("/orchestrated")
async def orchestrated(
    req: OrchestratedReq,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """多 Agent 协作答疑：返回四阶段完整轨迹。"""
    q = db.query(QuizQuestion).filter(QuizQuestion.id == req.question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")

    result = await tutor_orchestrator.orchestrate_tutoring(
        db=db,
        user_id=owner_id(user),
        question_id=req.question_id,
        my_answer=req.my_answer,
        subject=req.subject,
        question=q,
    )
    return result