# -*- coding: utf-8 -*-
"""复试代码题库路由（V15）。

GET  /api/codebank/questions          LeetCode 式列表（subject/difficulty/tag/q/考频过滤+分页）
GET  /api/codebank/questions/{id}     题目详情（题面/示例/多语言模板/考频/年份）
GET  /api/codebank/panorama           知识点全景（subject→tag→题数/均考频/最热题）
GET  /api/codebank/exam-strategy      考频分析（高频TOP10/科目分布/方向权重）
GET  /api/codebank/subjects           科目清单（含题目数）
POST /api/codebank/subjects           添加科目（用户可随时扩展模块）
POST /api/codebank/import             批量灌题（dry_run 支持）
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services import codebank_service as svc
from services.kaoyan.codebank_seed import SEED_QUESTIONS

router = APIRouter(prefix="/api/codebank", tags=["复试代码题库"])


@router.get("/questions")
def questions(
    subject: Optional[str] = Query(None), difficulty: Optional[str] = Query(None),
    tag: Optional[str] = Query(None), q: Optional[str] = Query(None, max_length=100),
    min_frequency: int = Query(0, ge=0, le=5),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return svc.list_questions(db, subject=subject, difficulty=difficulty, tag=tag,
                              q=q, min_frequency=min_frequency, limit=limit, offset=offset)


@router.get("/questions/{qid}")
def question_detail(qid: int, db: Session = Depends(get_db)):
    d = svc.get_question(db, qid)
    if not d:
        raise HTTPException(status_code=404, detail="题目不存在")
    return d


@router.get("/panorama")
def panorama(subject: Optional[str] = Query(None), db: Session = Depends(get_db)):
    return svc.panorama(db, subject=subject)


@router.get("/exam-strategy")
def exam_strategy(db: Session = Depends(get_db)):
    return svc.exam_strategy(db)


@router.get("/subjects")
def subjects(db: Session = Depends(get_db)):
    return svc.list_subjects(db)


class SubjectReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    direction: Optional[str] = None


@router.post("/subjects")
def add_subject(req: SubjectReq, db: Session = Depends(get_db)):
    return svc.add_subject(db, req.name, req.direction)


class ImportReq(BaseModel):
    questions: List[dict] = Field(default_factory=list)
    seed_builtin: bool = Field(True, description="同时导入内置 12 道种子题")
    dry_run: bool = False


@router.post("/syllabus/crawl")
def syllabus_crawl(school_id: int = Query(...), dry_run: bool = Query(True),
                   db: Session = Depends(get_db)):
    """复试大纲爬取（工科/理科）：栏目发现→章节抽取→codebank 灌入。"""
    from services.kaoyan import syllabus_spider
    return syllabus_spider.crawl_syllabus(db, school_id, dry_run=dry_run)


@router.post("/school-type/enrich")
def school_type_enrich(dry_run: bool = Query(True), db: Session = Depends(get_db)):
    """院校类型补全（kaoyan.cn 筛选第三维）：从 tags/intro 提取，留空不编造。"""
    from services.kaoyan.school_type_enrich import enrich_from_tags
    return enrich_from_tags(db, dry_run=dry_run)


@router.post("/import")
def import_questions(req: ImportReq, db: Session = Depends(get_db)):
    """批量灌题：dry_run 只统计不入库；seed_builtin 导入内置种子（幂等）。"""
    items = list(req.questions)
    seeded = 0
    if req.seed_builtin:
        items = list(SEED_QUESTIONS) + items
    ids = []
    for it in items:
        if req.dry_run:
            seeded += 1
            continue
        ids.append(svc.upsert_question(db, it))
    return {"dry_run": req.dry_run, "would_import": seeded if req.dry_run else 0,
            "imported": 0 if req.dry_run else len(ids),
            "question_ids": ids}
