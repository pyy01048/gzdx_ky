"""答案交叉校验路由（A6）：前缀 /api/answers。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services import answer_cross_check
from services.module_a_schema import ensure_module_a_schema

router = APIRouter(prefix="/api/answers", tags=["答案交叉校验"])


class CrossCheckRequest(BaseModel):
    question_id: int
    prefer: Optional[str] = None


class CrossCheckBatchRequest(BaseModel):
    question_ids: Optional[List[int]] = None
    limit: int = 50
    prefer: Optional[str] = None


@router.post("/check")
def cross_check(req: CrossCheckRequest, db: Session = Depends(get_db)):
    """单题交叉校验：题库答案 vs 真题2-gram检索 vs LLM 生成，写 answer_candidates。"""
    ensure_module_a_schema(db)
    try:
        result = answer_cross_check.cross_check_question(
            db, req.question_id, prefer=req.prefer
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result


@router.post("/check-batch")
def cross_check_batch(req: CrossCheckBatchRequest, db: Session = Depends(get_db)):
    """批量交叉校验（不指定 question_ids 时取未校验/置信度非 high 的题）。"""
    ensure_module_a_schema(db)
    try:
        result = answer_cross_check.check_batch(
            db, question_ids=req.question_ids, limit=req.limit, prefer=req.prefer
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/stats")
def cross_check_stats(db: Session = Depends(get_db)):
    """校验统计：来源分布 / 置信度分布 / 冲突数。"""
    ensure_module_a_schema(db)
    return answer_cross_check.stats(db)
