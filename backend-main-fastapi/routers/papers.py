"""组题网路由：组卷 / 试卷管理 / 导出。"""
from __future__ import annotations

import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Paper, PaperQuestion, QuizQuestion
from services import paper_builder

router = APIRouter(prefix="/api/papers", tags=["组题网"])

LECTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lectures")


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
async def paper_subjects(db: Session = Depends(get_db)):
    """组卷入口：题库可用科目与题目数（供前端组卷筛选）。"""
    from sqlalchemy import func
    rows = (
        db.query(QuizQuestion.subject, func.count(QuizQuestion.id))
        .group_by(QuizQuestion.subject)
        .order_by(func.count(QuizQuestion.id).desc())
        .all()
    )
    return {"items": [{"subject": s or "综合", "count": c} for s, c in rows]}


@router.post("/build")
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


@router.post("/save")
async def save_paper(req: SaveRequest, db: Session = Depends(get_db)):
    """保存试卷（题目快照，独立于题库）。"""
    try:
        paper = paper_builder.save_paper(
            db, title=req.title, subject=req.subject,
            description=req.description, rules=req.rules, items=req.items,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"保存失败: {e}")
    return {"id": paper.id, "title": paper.title, "message": "试卷已保存"}


@router.get("")
async def list_papers(
    subject: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
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
                "id": p.id, "title": p.title, "subject": p.subject,
                "total_score": p.total_score, "question_count": len(p.questions),
                "created_at": p.created_at,
            }
            for p in rows
        ],
    }


@router.get("/{paper_id}")
async def paper_detail(paper_id: int, db: Session = Depends(get_db)):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    questions = (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper_id)
        .order_by(PaperQuestion.seq)
        .all()
    )
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
                "seq": q.seq, "question_id": q.question_id, "content": q.content,
                "options": q.options, "answer": q.answer, "analysis": q.analysis,
                "question_type": q.question_type, "difficulty": q.difficulty, "score": q.score,
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
    questions = (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper_id)
        .order_by(PaperQuestion.seq)
        .all()
    )
    path = paper_builder.paper_to_lecture_html(paper, questions, LECTURES_DIR)
    return {"message": "已导出", "file_path": path}


@router.delete("/{paper_id}")
async def delete_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    db.delete(paper)
    db.commit()
    return {"message": "试卷已删除", "id": paper_id}
