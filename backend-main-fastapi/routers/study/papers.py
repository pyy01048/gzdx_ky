"""组题网路由：组卷 / 试卷管理 / 导出。"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from services import paper_builder
from services.quiz_query import question_owner_expr
from sqlalchemy import and_, or_
from sqlalchemy import text as _text
from sqlalchemy.orm import Session
from utils.response import MAX_PAGE_SIZE
from utils.security import current_user, optional_user, require_admin

from models import Paper, PaperQuestion, QuizQuestion, User

router = APIRouter(prefix="/api/papers", tags=["组题网"])

LECTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lectures")

# 客观题题型：options 为空时不进入练习/模考
_OBJECTIVE_TYPES = ("single", "multiple", "judge")


def _gate_question_ids(db: Session, question_ids: list[int]) -> set[int]:
    """内容可用性门禁（T2）：从给定题目 ID 中筛出通过门禁的子集。

    门禁条件：validation_status='pass' AND is_available=true；
    客观题（single/multiple/judge）额外要求 options 非空（NOT NULL 且文本形态非 '[]'/'null'/'{}'）。
    用于对 PaperQuestion 快照 / service 返回的题目做后置过滤，确保练习/模考不出现
    无答案、无选项的题。
    """
    if not question_ids:
        return set()
    objective_has_options = or_(
        QuizQuestion.question_type.notin_(_OBJECTIVE_TYPES),
        and_(
            QuizQuestion.options.isnot(None),
            _text("quiz_questions.options::text NOT IN ('[]','null','{}')"),
        ),
    )
    rows = (
        db.query(QuizQuestion.id)
        .filter(
            QuizQuestion.id.in_(question_ids),
            QuizQuestion.validation_status == "pass",
            QuizQuestion.is_available.is_(True),
            objective_has_options,
        )
        .all()
    )
    return {r[0] for r in rows}


class BuildRequest(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    knowledge_points: Optional[List[str]] = None
    chapters: Optional[List[str]] = None
    difficulties: Optional[List[int]] = None
    question_types: Optional[List[str]] = None
    counts: Optional[dict] = None
    total_questions: Optional[int] = None
    use_ai: bool = False
    prefer: Optional[str] = None


class SaveRequest(BaseModel):
    title: str
    subject: Optional[str] = None
    description: Optional[str] = None
    rules: dict
    items: List[dict]


@router.get("/subjects")
async def paper_subjects(
    db: Session = Depends(get_db),
    user: User | None = Depends(optional_user),
):
    """组卷入口：题库可用科目与题目数（供前端组卷筛选）。

    M0-4 学科统一收口：数据源改为 `services.subject_registry` 唯一聚合器，
    响应字段结构**保持不变**（``{"items":[{"subject","count"}]}``），前端无需改动。

    口径说明：科目集合以 ``subject_config`` 字典为权威（含 0854 电子信息等
    尚无题目的科目，count=0），并按题目数降序返回；字典缺项的脏科目也会带出。
    """
    from services import subject_registry

    owner_filter = question_owner_expr(user) if user is not None else QuizQuestion.owner_user_id.is_(None)
    data = subject_registry.list_subjects(db, question_filter=owner_filter)["subjects"]
    items = [{"subject": s["subject"], "count": s["question_count"]} for s in data]
    items.sort(key=lambda it: (-it["count"], it["subject"]))
    return {"items": items}


@router.post("/build", dependencies=[Depends(require_admin)])
async def build_paper(req: BuildRequest, db: Session = Depends(get_db)):
    """组卷：按知识点/难度/题型/配额自动组卷（可选 AI 辅助）。"""
    rules = paper_builder.build_rules(
        subject=req.subject,
        knowledge_points=req.knowledge_points,
        chapters=req.chapters,
        difficulties=req.difficulties,
        question_types=req.question_types,
        counts=req.counts,
        total_questions=req.total_questions,
        prefer=req.prefer,
    )
    title = req.title or f"{req.subject or '综合'}模拟卷"
    out = paper_builder.build_paper(db, title, rules, use_ai=req.use_ai)
    if not out.get("ok"):
        raise HTTPException(status_code=404, detail=out.get("message", "组卷失败"))
    return out


@router.post("/save", dependencies=[Depends(require_admin)])
async def save_paper(req: SaveRequest, db: Session = Depends(get_db)):
    """保存试卷（题目快照，独立于题库）。"""
    try:
        paper = paper_builder.save_paper(
            db,
            title=req.title,
            subject=req.subject,
            description=req.description,
            rules=req.rules,
            items=req.items,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"保存失败: {e}")
    return {"id": paper.id, "title": paper.title, "message": "试卷已保存"}


@router.get("")
async def list_papers(
    subject: Optional[str] = None,
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    q = db.query(Paper)
    if subject:
        q = q.filter(Paper.subject == subject)
    rows = q.order_by(Paper.created_at.desc()).limit(limit).all()
    return {
        "total": len(rows),
        "items": [
            {
                "id": p.id,
                "title": p.title,
                "subject": p.subject,
                "total_score": p.total_score,
                "question_count": len(p.questions),
                "created_at": p.created_at,
            }
            for p in rows
        ],
    }


# `:int` 路径转换器：只匹配纯数字段。否则本路由先于下方的 GET /indexed 注册，
# 会把 /api/papers/indexed 吞掉并报 422「paper_id 不是整数」，P2-M4 新接口永远不可达。
@router.get("/{paper_id:int}")
async def paper_detail(paper_id: int, db: Session = Depends(get_db)):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    questions = db.query(PaperQuestion).filter(PaperQuestion.paper_id == paper_id).order_by(PaperQuestion.seq).all()
    # T2 内容可用性门禁：练习/模考只展示 validation_status='pass' AND is_available=true 的题
    gate_ids = _gate_question_ids(db, [q.question_id for q in questions if q.question_id])
    questions = [q for q in questions if q.question_id in gate_ids]
    return {
        "id": paper.id,
        "title": paper.title,
        "subject": paper.subject,
        "description": paper.description,
        "rules": paper.rules,
        "total_score": paper.total_score,
        "created_at": paper.created_at,
        "items": [
            {
                "seq": q.seq,
                "question_id": q.question_id,
                "content": q.content,
                "options": q.options,
                "answer": q.answer,
                "analysis": q.analysis,
                "question_type": q.question_type,
                "difficulty": q.difficulty,
                "score": q.score,
            }
            for q in questions
        ],
    }


@router.get("/{paper_id}/export")
async def export_paper(paper_id: int, db: Session = Depends(get_db)):
    """导出试卷为可打印 HTML（含 KaTeX 公式渲染）。"""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    questions = db.query(PaperQuestion).filter(PaperQuestion.paper_id == paper_id).order_by(PaperQuestion.seq).all()
    # T2 内容可用性门禁：导出试卷同样只含通过门禁的题
    gate_ids = _gate_question_ids(db, [q.question_id for q in questions if q.question_id])
    questions = [q for q in questions if q.question_id in gate_ids]
    path = paper_builder.paper_to_lecture_html(paper, questions, LECTURES_DIR)
    return {"message": "已导出", "file_path": path}


@router.delete("/{paper_id}", dependencies=[Depends(require_admin)])
async def delete_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    db.delete(paper)
    db.commit()
    return {"message": "试卷已删除", "id": paper_id}


# --------------------------------------------------------------------------- #
# P2-M4 真题模块：年份/卷种轴 + 整卷模考
# --------------------------------------------------------------------------- #

from services import paper_exam_service


@router.get("/filters/years")
async def paper_years(
    subject: str = Query(..., description="科目"),
    db: Session = Depends(get_db),
):
    """获取某科目下所有可用的真题年份。"""
    years = paper_exam_service.get_available_years(db, subject)
    return {"years": years}


@router.get("/filters/paper-types")
async def paper_types(
    subject: str = Query(..., description="科目"),
    year: Optional[int] = Query(None, description="可选年份筛选"),
    db: Session = Depends(get_db),
):
    """获取某科目(可选年份)下所有可用的卷种。"""
    types = paper_exam_service.get_available_paper_types(db, subject, year)
    return {"paper_types": types}


@router.get("/indexed")
async def list_papers_indexed(
    subject: Optional[str] = Query(None, description="科目"),
    year: Optional[int] = Query(None, description="年份"),
    paper_type: Optional[str] = Query(None, description="卷种"),
    is_mock: Optional[bool] = Query(None, description="是否模拟卷"),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """按年份/卷种筛选试卷列表（P2-M4 新接口）。"""
    items = paper_exam_service.list_papers_by_year_type(
        db,
        subject=subject,
        year=year,
        paper_type=paper_type,
        is_mock=is_mock,
        limit=limit,
    )
    return {"total": len(items), "items": items}


class StartAttemptRequest(BaseModel):
    paper_id: int


@router.post("/attempts/start")
async def start_attempt(
    req: StartAttemptRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """开始一份试卷的模考作答。"""
    # T2 内容可用性门禁：模考只含 validation_status='pass' AND is_available=true 的题。
    # 先取出该卷题目 ID，按门禁筛子集，再把合格子集透传给 service（service 据此创建会话）。
    paper = db.query(Paper).filter(Paper.id == req.paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    all_items = db.query(PaperQuestion).filter(PaperQuestion.paper_id == req.paper_id).order_by(PaperQuestion.seq).all()
    all_qids = [item.question_id for item in all_items if item.question_id]
    gate_qids = _gate_question_ids(db, all_qids)
    # 仅保留通过门禁的题目；service 内部按 paper_id 取题时也会受此子集约束
    try:
        result = paper_exam_service.start_paper_attempt(
            db, req.paper_id, user_id=user.id, question_ids=list(gate_qids) if gate_qids else None
        )
    except TypeError:
        # 兼容 service 不接受 question_ids 参数的旧签名：回落原行为后做后置过滤
        result = paper_exam_service.start_paper_attempt(db, req.paper_id, user_id=user.id)
        if isinstance(result, dict):
            for key in ("questions", "items"):
                items = result.get(key)
                if isinstance(items, list):
                    result[key] = [it for it in items if not isinstance(it, dict) or it.get("question_id") in gate_qids]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


class SubmitAttemptRequest(BaseModel):
    attempt_id: int
    answers: List[Dict[str, Any]]


# Pydantic V2: rebuild to resolve forward references from __future__ annotations
SubmitAttemptRequest.model_rebuild()


@router.post("/attempts/submit")
async def submit_attempt(
    req: SubmitAttemptRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """提交试卷作答并生成报告。"""
    try:
        result = paper_exam_service.submit_paper_attempt(db, req.attempt_id, req.answers, user_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/attempts/{attempt_id}/report")
async def attempt_report(
    attempt_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """查看某次作答的报告（仅本人）。"""
    try:
        report = paper_exam_service.generate_paper_report(db, attempt_id, user_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return report


@router.get("/attempts/history")
async def attempt_history(
    paper_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """获取历史作答记录（仅本人）。"""
    items = paper_exam_service.get_attempt_history(db, paper_id=paper_id, limit=limit, user_id=user.id)
    # 分页约定：items 必须与 total 成对（tests/test_api_conventions.py），与 /indexed 同口径
    return {"total": len(items), "items": items}
