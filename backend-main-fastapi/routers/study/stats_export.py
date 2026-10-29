"""统计聚合与导出路由（2026-10-14 扩容：一次请求返回全站概览 + 错题 CSV 导出 + 批量操作）。"""

import csv
import datetime
import io
from collections import Counter
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Integer, cast, func
from sqlalchemy.orm import Session

from database import get_db
from models import AnswerRecord, ErrorRecord, QuizQuestion, StudySession, User
from utils.scope import scoped  # B4 行级隔离（只读不写，不需 owner_id）
from utils.security import current_user
from utils.timeutil import local_date_of, local_range_utc, local_today

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
async def stats_overview(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """学习概览聚合（一次请求，前端免多次拉取后自行聚合；B4：只统计本人数据）。

    返回：
    - subjects: 各科目题量/正确率（来自 answer_records）
    - trend_7d: 近 7 天每日答题数与正确数
    - top_error_tags: 错题标签 Top10
    - study_time: 学习时长分布（按科目，来自 study_sessions）
    """
    today = local_today()

    # 1) 科目维度题量/正确率
    subject_rows = (
        db.query(
            AnswerRecord.subject,
            func.count(AnswerRecord.id),
            func.sum(cast(AnswerRecord.is_correct, Integer)),
        )
        .filter(AnswerRecord.subject.isnot(None), AnswerRecord.subject != "", scoped(AnswerRecord, user))
        .group_by(AnswerRecord.subject)
        .all()
    )
    subjects = [
        {
            "subject": s or "未分类",
            "answered": int(total or 0),
            "correct": int(correct or 0),
            "accuracy": round((correct or 0) / total * 100, 1) if total else 0.0,
        }
        for s, total, correct in subject_rows
    ]
    subjects.sort(key=lambda x: -x["answered"])

    # 2) 近 7 天答题趋势
    week_ago = today - datetime.timedelta(days=6)
    trend_start, _trend_end = local_range_utc(week_ago, today + datetime.timedelta(days=1))
    trend_rows = (
        db.query(AnswerRecord.created_at, AnswerRecord.is_correct)
        .filter(scoped(AnswerRecord, user), AnswerRecord.created_at >= trend_start)
        .all()
    )
    trend = {
        (today - datetime.timedelta(days=i)).isoformat(): {"answered": 0, "correct": 0}
        for i in range(6, -1, -1)
    }
    for created_at, is_correct in trend_rows:
        key = local_date_of(created_at).isoformat() if created_at else None
        if key in trend:
            trend[key]["answered"] += 1
            if is_correct:
                trend[key]["correct"] += 1

    # 3) 错题标签 Top10（tags 为 JSON 数组）
    tag_counter: Counter = Counter()
    for (tags,) in db.query(ErrorRecord.tags).filter(ErrorRecord.tags.isnot(None), scoped(ErrorRecord, user)):
        if isinstance(tags, list):
            tag_counter.update([str(t) for t in tags if t])
    top_error_tags = [{"tag": t, "count": c} for t, c in tag_counter.most_common(10)]

    # 4) 学习时长分布（按科目）
    time_rows = (
        db.query(StudySession.subject, func.sum(StudySession.duration))
        .filter(StudySession.subject.isnot(None), StudySession.subject != "", scoped(StudySession, user))
        .group_by(StudySession.subject)
        .all()
    )
    study_time = [
        {"subject": s or "未分类", "minutes": int(d or 0)} for s, d in time_rows
    ]
    study_time.sort(key=lambda x: -x["minutes"])

    return {
        "subjects": subjects,
        "trend_7d": trend,
        "top_error_tags": top_error_tags,
        "study_time": study_time,
    }


# ---------------------------------------------------------------- 错题导出/批量 --
errors_router = APIRouter(prefix="/api/errors", tags=["errors"])


@errors_router.get("/export")
async def export_errors(
    subject: Optional[str] = None,
    status: Optional[str] = None,
    ids: Optional[List[int]] = Query(None, description="按 ID 精确导出（前端多选场景）"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """错题 CSV 导出（Excel 兼容：UTF-8 with BOM；B4：仅导出本人错题）。"""
    query = db.query(ErrorRecord).filter(scoped(ErrorRecord, user))
    if subject:
        query = query.filter(ErrorRecord.subject == subject)
    if status:
        query = query.filter(ErrorRecord.status == status)
    if ids:
        query = query.filter(ErrorRecord.id.in_(ids))
    rows = query.order_by(ErrorRecord.created_at.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "科目", "题干", "我的答案", "正确答案", "错误原因", "标签", "状态", "复习次数", "创建时间"])
    for r in rows:
        writer.writerow([
            r.id, r.subject or "", r.content or "", r.my_answer or "", r.correct_answer or "",
            r.error_reason or "", " ".join(r.tags) if isinstance(r.tags, list) else (r.tags or ""),
            r.status or "", r.review_count or 0,
            r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        ])
    buf.seek(0)
    filename = f"errors_{local_today().isoformat()}.csv"
    return StreamingResponse(
        iter(["\ufeff" + buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@errors_router.post("/batch-delete")
async def batch_delete_errors(ids: List[int], db: Session = Depends(get_db), user: User = Depends(current_user)):
    """错题批量删除（硬删除，B4：仅本人错题）。"""
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="单次最多删除 500 条")
    deleted = db.query(ErrorRecord).filter(ErrorRecord.id.in_(ids), scoped(ErrorRecord, user)).delete(synchronize_session=False)
    db.commit()
    return {"deleted": deleted}


# ---------------------------------------------------------------- 题库导出/批量 --
quiz_export_router = APIRouter(prefix="/api/quiz", tags=["quiz"])


def _options_to_text(options) -> str:
    """options JSON → 可读文本（A. xxx | B. xxx）。"""
    if not options:
        return ""
    if isinstance(options, dict):
        return " | ".join(f"{k}. {v}" for k, v in options.items())
    if isinstance(options, list):
        return " | ".join(str(o) for o in options)
    return str(options)


@quiz_export_router.get("/export")
async def export_quiz_questions(
    subject: Optional[str] = None,
    question_type: Optional[str] = None,
    is_available: Optional[bool] = None,
    year: Optional[int] = None,
    is_retest: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """题库 CSV 导出（Excel 兼容：UTF-8 with BOM）。默认排除 OCR 碎片题。"""
    query = db.query(QuizQuestion)
    if subject:
        query = query.filter(QuizQuestion.subject == subject)
    if question_type:
        query = query.filter(QuizQuestion.question_type == question_type)
    if is_available is not None:
        query = query.filter(QuizQuestion.is_available == is_available)
    if year:
        query = query.filter(QuizQuestion.year == year)
    if is_retest is not None:
        query = query.filter(QuizQuestion.is_retest == is_retest)
    rows = query.filter(QuizQuestion.is_junk.is_(False)).order_by(QuizQuestion.id).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "ID", "科目", "章节", "知识点", "题型", "题干", "选项", "答案", "解析",
        "难度", "真题年份", "来源", "质量评级", "AI生成", "已校验", "可用", "创建时间",
    ])
    for r in rows:
        writer.writerow([
            r.id, r.subject or "", r.chapter or "", r.knowledge_point or "",
            r.question_type or "", r.content or "", _options_to_text(r.options),
            r.answer or "", r.analysis or "",
            r.difficulty or "", r.year or "", r.source_label or "", r.quality or "",
            "是" if r.ai_generated else "否", "是" if r.verified else "否",
            "是" if r.is_available else "否",
            r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        ])
    buf.seek(0)
    filename = f"quiz_questions_{local_today().isoformat()}.csv"
    return StreamingResponse(
        iter(["\ufeff" + buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@quiz_export_router.post("/batch-delete")
async def batch_delete_quiz_questions(ids: List[int], db: Session = Depends(get_db)):
    """题库批量删除（硬删除，连带知识点链路由外键 CASCADE 处理）。"""
    if not ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="单次最多删除 500 条")
    deleted = (
        db.query(QuizQuestion)
        .filter(QuizQuestion.id.in_(ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted}
