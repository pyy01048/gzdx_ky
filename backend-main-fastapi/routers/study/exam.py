"""组卷-模考路由（A5）：前缀 /api/exam。"""

from __future__ import annotations

from typing import List, Optional

from database import get_db
from fastapi import APIRouter, Depends, HTTPException
from models import User
from pydantic import BaseModel
from services import exam_builder
from services.dbapi_compat import wrap_conn
from services.exam_report import session_report
from services.module_a_schema import ensure_module_a_schema
from sqlalchemy import text
from sqlalchemy.orm import Session
from utils.scope import owner_id  # B4 行级隔离：模考场次是个人数据
from utils.security import current_user

router = APIRouter(prefix="/api/exam", tags=["组卷模考"])


class ExamBuildRequest(BaseModel):
    subject: str
    paper: Optional[str] = None
    year: Optional[int] = None
    mode: str = "normal"  # normal | weakest | random
    count_override: Optional[int] = None
    kp_ids: Optional[List[int]] = None
    question_source: str = "all"  # all | error | ai_generated
    exclude_recent_days: int = 14


class ExamAnswerItem(BaseModel):
    question_id: int
    user_answer: str = ""
    self_score: Optional[float] = None
    time_spent: Optional[int] = None


class ExamSubmitRequest(BaseModel):
    answers: List[ExamAnswerItem]


@router.post("/build")
def build_exam(req: ExamBuildRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """按蓝图组卷：normal | weakest | random，试卷冻结写快照。"""
    ensure_module_a_schema(db)
    try:
        session = exam_builder.build_paper(
            db,
            subject=req.subject,
            paper=req.paper,
            year=req.year,
            mode=req.mode,
            count_override=req.count_override,
            kp_ids=req.kp_ids,
            question_source=req.question_source,
            exclude_recent_days=req.exclude_recent_days,
            user_id=owner_id(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return session


@router.post("/{session_id}/submit")
def submit_exam(
    session_id: int, req: ExamSubmitRequest, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """交卷判分：客观题 auto、主观题 ai|self，错题回流 error_records。"""
    ensure_module_a_schema(db)
    uid = owner_id(user)
    # 先校验归属：他人会话 404（submit_session 内部返回 error dict 是 200 语义，
    # 越权必须在这里拦成 404，不泄露存在性）
    if exam_builder.session_detail(db, session_id, user_id=uid) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    answers = [a.model_dump() for a in req.answers]
    try:
        result = exam_builder.submit_session(db, session_id, answers, user_id=uid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return result


@router.get("/sessions")
def list_exam_sessions(
    subject: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """模考会话列表（只列本人场次）。"""
    return exam_builder.list_sessions(db, subject=subject, status=status, user_id=owner_id(user))


@router.get("/sessions/{session_id}")
def exam_session_detail(session_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """会话详情（含逐题快照）。"""
    result = exam_builder.session_detail(db, session_id, user_id=owner_id(user))
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return result


@router.get("/sessions/{session_id}/report")
def exam_session_report(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """模考考后报告：基于 exam_answers 逐题作答现算聚合（不新增表）。

    B4：exam_sessions 已补 user_id（121 分片），只认本人会话；
    存量 NULL 行无归属，对任何用户都按不存在处理（404）。
    """
    result = session_report(db, session_id, user_id=owner_id(user))
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return result


#: exam_blueprints 题型列名缓存（内省一次；PG=blueprint_question_type）
_BP_QT_COL: Optional[str] = None


def _bp_question_type_col(db: Session) -> str:
    """题型列名（内省 + 进程内缓存）。避免每条请求都查 information_schema。"""
    global _BP_QT_COL
    if _BP_QT_COL:
        return _BP_QT_COL
    from services.module_a_schema import blueprint_question_type_col

    try:
        _BP_QT_COL = blueprint_question_type_col(wrap_conn(db.connection().connection))
    except Exception:  # noqa: BLE001 - 内省失败退回 SQLite 兼容列名
        _BP_QT_COL = "question_type"
    return _BP_QT_COL


@router.get("/blueprints")
def list_blueprints(db: Session = Depends(get_db)):
    """蓝图列表（按科目/试卷）。"""
    ensure_module_a_schema(db)
    # SQLAlchemy 2.x 要求文本 SQL 显式声明为 text()，否则抛 ArgumentError。
    # 注意：接收者是 Session（而非 wrap_conn(db.connection().connection) 的 DBAPI 代理）。
    # 题型列名内省：PG 正典是 blueprint_question_type，SQLite 兼容版是 question_type，
    # 统一 AS question_type 输出，列名差异不外溢到 API 契约。
    qt = _bp_question_type_col(db)
    rows = db.execute(
        text(
            f"SELECT id, subject, paper, year, section, {qt} AS question_type, count, "
            "score_per_question, sort_order, is_active FROM exam_blueprints "
            "ORDER BY subject, sort_order"
        )
    ).fetchall()
    return [dict(r._mapping) for r in rows]


class ExamSearchRequest(BaseModel):
    query: str
    limit: int = 6
    subject: Optional[str] = None
    use_exam_lane: bool = True


@router.post("/search")
def exam_search(req: ExamSearchRequest, db: Session = Depends(get_db)):
    """A7 真题双引擎检索：FTS5+vec0+RRF 三路与真题 2-gram 第 4 路融合。"""
    from services.search_service import hybrid_search_with_exam

    results = hybrid_search_with_exam(db, req.query, query_vec=None, limit=req.limit, subject=req.subject)
    return {
        "query": req.query,
        "count": len(results),
        "results": results,
    }
