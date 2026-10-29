"""P2-M5 代码上机 OJ 路由。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import User
from utils.security import current_user
from services import code_oj_service

router = APIRouter(prefix="/api/code", tags=["代码上机OJ"])


class CodeSubmitRequest(BaseModel):
    problem_id: int
    language: str
    code: str


@router.get("/problems")
async def list_problems(
    subject: Optional[str] = None,
    difficulty: Optional[int] = None,
    tag: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """编程题目列表。"""
    items = code_oj_service.list_problems(
        db, subject=subject, difficulty=difficulty, tag=tag, limit=limit, offset=offset,
    )
    return {"total": len(items), "items": items}


@router.get("/problems/{problem_id}")
async def problem_detail(problem_id: int, db: Session = Depends(get_db)):
    """题目详情（含样例）。"""
    detail = code_oj_service.get_problem_detail(db, problem_id)
    if not detail:
        raise HTTPException(status_code=404, detail="题目不存在")
    return detail


@router.post("/submit")
async def submit_code(req: CodeSubmitRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """提交代码并判题（需登录）。"""
    try:
        result = code_oj_service.submit_code(
            db,
            problem_id=req.problem_id,
            language=req.language,
            code=req.code,
            user_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/submissions/{submission_id}")
async def submission_detail(submission_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取提交详情（需登录）。"""
    detail = code_oj_service.get_submission_detail(db, submission_id)
    if not detail:
        raise HTTPException(status_code=404, detail="提交记录不存在")
    return detail


@router.get("/submissions")
async def user_submissions(
    problem_id: Optional[int] = None,
    user_id: Optional[int] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """获取提交记录列表（需登录）。"""
    items = code_oj_service.get_user_submissions(db, problem_id=problem_id, user_id=user_id, limit=limit)
    return {"items": items}
