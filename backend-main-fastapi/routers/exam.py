"""组卷-模考路由（A5）：前缀 /api/exam。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.dbapi_compat import wrap_conn
from database import get_db
from services import exam_builder
from services.exam_report import session_report
from services.module_a_schema import ensure_module_a_schema
from utils.security import current_user
from models import User

router = APIRouter(prefix="/api/exam", tags=["组卷模考"])


class ExamBuildRequest(BaseModel):
    subject: str
    paper: Optional[str] = None
    year: Optional[int] = None
    mode: str = "normal"          # normal | weakest | random
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
def build_exam(req: ExamBuildRequest, db: Session = Depends(get_db)):
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
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return session


@router.post("/{session_id}/submit")
def submit_exam(session_id: int, req: ExamSubmitRequest, db: Session = Depends(get_db)):
    """交卷判分：客观题 auto、主观题 ai|self，错题回流 error_records。"""
    ensure_module_a_schema(db)
    answers = [a.model_dump() for a in req.answers]
    try:
        result = exam_builder.submit_session(db, session_id, answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/sessions")
def list_exam_sessions(
    subject: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """模考会话列表。"""
    return exam_builder.list_sessions(db, subject=subject, status=status)


@router.get("/sessions/{session_id}")
def exam_session_detail(session_id: int, db: Session = Depends(get_db)):
    """会话详情（含逐题快照）。"""
    result = exam_builder.session_detail(db, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return result


@router.get("/sessions/{session_id}/report")
def exam_session_report(
    session_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(current_user),
):
    """模考考后报告：基于 exam_answers 逐题作答现算聚合（不新增表）。

    归属口径与 ``session_detail`` 一致：exam_sessions 尚未纳入 B4 用户隔离
    （无 user_id 列），故不做 scoped 过滤；若未来 B4 为该表补 user_id 列，
    应在此处增加 ``scoped`` 归属校验。
    """
    result = session_report(db, session_id)
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

    results = hybrid_search_with_exam(
        db, req.query, query_vec=None, limit=req.limit, subject=req.subject
    )
    return {
        "query": req.query,
        "count": len(results),
        "results": results,
    }
