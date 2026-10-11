# -*- coding: utf-8 -*-
"""学习洞察聚合路由（V11 · F1/F2/F4）。

三个端点，全部为「聚合已有数据」的只读/轻写接口，不重复造轮子：
- GET  /api/insight/today          F1 今日学习引导（倒计时/到期复习/今日任务/薄弱点/今日答题）
- GET  /api/insight/weekly-report  F4 学习周报（本周 vs 上周：答题量/正确率/时长/逐日曲线）
- POST /api/insight/smart-paper    F2 智能组卷（薄弱点/易错/随机三模式，数据源 kp 链与错题本）

数据源复用：DashboardService、review_service.due_items、
LearningAnalyticsService.diagnose_weak_points、study_events 流水。
模型调用约定：本模块不调用 LLM，全部本地规则计算（快、可测、可离线）。
"""
from __future__ import annotations

import datetime
import random
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    ErrorRecord, Goal, QuizQuestion, StudyEvent, StudyStats,
)
from services.dashboard_service import DashboardService
from services.learning_analytics_service import LearningAnalyticsService
from services import review_service

router = APIRouter(prefix="/api/insight", tags=["学习洞察"])


# --------------------------------------------------------------------------- #
# F1 · 今日学习引导
# --------------------------------------------------------------------------- #
@router.get("/today")
def today_insight(db: Session = Depends(get_db)):
    """首页引导层聚合：打开就知道该干什么。

    返回 items：{icon,label,count,to,hint} 行动清单，前端按顺序渲染。
    """
    today = datetime.date.today()

    # 倒计时（复用 DashboardService）
    try:
        countdown = DashboardService.get_countdown(db)
    except Exception:
        countdown = {"days": None}

    # 今日到期复习（艾宾浩斯）
    try:
        due_items = review_service.due_items(db, limit=200)
        due_count = len(due_items) if isinstance(due_items, list) else 0
    except Exception:
        due_count = 0

    # 今日任务数（复用 DashboardService）
    try:
        today_tasks = DashboardService.get_today_tasks(db) or []
        task_count = len(today_tasks) if isinstance(today_tasks, list) else 0
    except Exception:
        task_count = 0

    # 今日答题流水（study_events）
    day_start = datetime.datetime.combine(today, datetime.time.min)
    q = db.query(
        func.count(StudyEvent.id),
        func.sum(func.coalesce(StudyEvent.is_correct, 0).cast(__import__("sqlalchemy").Integer)),
    ).filter(
        StudyEvent.event_type == "answer",
        StudyEvent.occurred_at >= day_start,
    ).first()
    today_answered = int(q[0] or 0)
    today_correct = int(q[1] or 0)

    # 薄弱点 TOP3（复用诊断服务）
    weak_top: List[Dict] = []
    try:
        diag = LearningAnalyticsService(db).diagnose_weak_points(limit=3)
        for w in (diag.get("weak_points") or [])[:3]:
            weak_top.append({
                "kp": w.get("knowledge_point"),
                "mastery": w.get("mastery"),
                "level": w.get("level"),
            })
    except Exception:
        weak_top = []

    suggestions = [
        {"icon": "📚", "label": "到期复习", "count": due_count, "to": "/quiz?tab=review",
         "hint": "艾宾浩斯队列到期，先复习再学新的" if due_count else "暂无到期复习"},
        {"icon": "✍️", "label": "今日待办", "count": task_count, "to": "/tasks",
         "hint": "按计划推进今天的任务" if task_count else "还没有安排今日任务"},
        {"icon": "🎯", "label": "薄弱点练习", "count": len(weak_top), "to": "/quiz?mode=weak",
         "hint": "、".join([w["kp"] for w in weak_top[:2]]) if weak_top else "暂无薄弱点数据"},
        {"icon": "🧠", "label": "今日已答", "count": today_answered, "to": "/quiz",
         "hint": f"正确 {today_correct} 题" if today_answered else "今天还没开始刷题"},
    ]

    return {
        "countdown": countdown,
        "suggestions": suggestions,
        "weak_top": weak_top,
        "today_answered": today_answered,
        "today_correct": today_correct,
        "due_review_count": due_count,
    }


# --------------------------------------------------------------------------- #
# F4 · 学习周报
# --------------------------------------------------------------------------- #
@router.get("/weekly-report")
def weekly_report(db: Session = Depends(get_db)):
    """近 7 天 vs 前 7 天：答题量 / 正确率 / 学习时长 / 逐日曲线，附一句总结。"""
    today = datetime.date.today()
    this_start = datetime.datetime.combine(today - datetime.timedelta(days=6), datetime.time.min)
    last_start = this_start - datetime.timedelta(days=7)
    this_end = datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time.min)
    last_end = this_start

    def _period_stats(start, end):
        row = db.query(
            func.count(StudyEvent.id),
            func.sum(func.coalesce(StudyEvent.is_correct, 0).cast(__import__("sqlalchemy").Integer)),
        ).filter(
            StudyEvent.event_type == "answer",
            StudyEvent.occurred_at >= start,
            StudyEvent.occurred_at < end,
        ).first()
        answered = int(row[0] or 0)
        correct = int(row[1] or 0)
        # 时长：study_stats 按日
        dur_row = db.query(func.coalesce(func.sum(StudyStats.total_duration), 0)).filter(
            StudyStats.date >= start.date(), StudyStats.date < end.date()
        ).first()
        duration = int(dur_row[0] or 0)
        return {"answered": answered, "correct": correct, "accuracy": (correct / answered) if answered else None, "duration": duration}

    this_week = _period_stats(this_start, this_end)
    last_week = _period_stats(last_start, last_end)

    # 逐日曲线（近7天）
    daily_rows = db.query(
        func.date(StudyEvent.occurred_at),
        func.count(StudyEvent.id),
        func.sum(func.coalesce(StudyEvent.is_correct, 0).cast(__import__("sqlalchemy").Integer)),
    ).filter(
        StudyEvent.event_type == "answer",
        StudyEvent.occurred_at >= this_start,
    ).group_by(func.date(StudyEvent.occurred_at)).all()
    daily_map = {str(r[0]): {"answered": int(r[1] or 0), "correct": int(r[2] or 0)} for r in daily_rows}
    daily = []
    for i in range(7):
        d = today - datetime.timedelta(days=6 - i)
        item = daily_map.get(d.isoformat(), {"answered": 0, "correct": 0})
        daily.append({"date": d.isoformat(), **item})

    # 差值与总结（本地规则文案，不走 LLM）
    def _delta(cur, prev):
        if prev == 0:
            return None
        return round((cur - prev) / prev * 100, 1)

    parts = []
    if this_week["answered"] == 0:
        parts.append("本周还没有答题记录，从一道小题开始")
    else:
        if last_week["answered"] == 0:
            parts.append(f"本周答题 {this_week['answered']} 题，重新启动了学习节奏")
        elif this_week["answered"] >= last_week["answered"]:
            parts.append(f"答题量环比 +{_delta(this_week['answered'], last_week['answered'])}%")
        else:
            parts.append(f"答题量环比 {_delta(this_week['answered'], last_week['answered'])}%，注意保持")
        if this_week["accuracy"] is not None:
            parts.append(f"正确率 {round(this_week['accuracy'] * 100)}%")
    if this_week["duration"]:
        parts.append(f"学习 {this_week['duration']} 分钟")

    return {
        "this_week": this_week,
        "last_week": last_week,
        "answered_delta": _delta(this_week["answered"], last_week["answered"]),
        "daily": daily,
        "summary": "，".join(parts) + "。" if parts else "暂无学习数据",
    }


# --------------------------------------------------------------------------- #
# F2 · 智能组卷
# --------------------------------------------------------------------------- #
class SmartPaperReq(BaseModel):
    """POST /insight/smart-paper 请求体。"""
    mode: str = Field("weak", description="weak=薄弱点 / error_prone=易错 / random=随机")
    size: int = Field(10, ge=1, le=50, description="抽题数量")
    subject: Optional[str] = Field(None, description="限定科目")


@router.post("/smart-paper")
def smart_paper(req: SmartPaperReq, db: Session = Depends(get_db)):
    """按模式智能抽题组卷（只返回可练题目，供前端直接进入练习会话）。"""
    size = req.size
    base_q = db.query(QuizQuestion).filter(QuizQuestion.is_available == True)  # noqa: E712
    if req.subject:
        base_q = base_q.filter(QuizQuestion.subject == req.subject)

    basis = ""
    picked: List[QuizQuestion] = []

    if req.mode == "weak":
        try:
            diag = LearningAnalyticsService(db).diagnose_weak_points(subject=req.subject, limit=10)
            weak_kps = [w.get("knowledge_point") for w in (diag.get("weak_points") or []) if w.get("knowledge_point")]
        except Exception:
            weak_kps = []
        if weak_kps:
            # 知识点模糊匹配（quiz_questions.knowledge_point 文本）
            conds = [QuizQuestion.knowledge_point.like(f"%{kp}%") for kp in weak_kps]
            from sqlalchemy import or_
            picked = base_q.filter(or_(*conds)).order_by(func.random()).limit(size).all()
            basis = f"按薄弱知识点抽题：{'、'.join(weak_kps[:5])}"
        else:
            picked = base_q.order_by(func.random()).limit(size).all()
            basis = "暂无薄弱点数据，已退化为随机抽题"
    elif req.mode == "error_prone":
        # 错题高频知识点：error_records 按题聚合 → 同知识点未错过题优先
        rows = db.query(
            QuizQuestion.knowledge_point, func.count(ErrorRecord.id).label("n")
        ).join(ErrorRecord, ErrorRecord.question_id == QuizQuestion.id).group_by(
            QuizQuestion.knowledge_point
        ).order_by(func.count(ErrorRecord.id).desc()).limit(8).all()
        hot_kps = [r[0] for r in rows if r[0]]
        if hot_kps:
            from sqlalchemy import or_
            missed_ids = [r[0] for r in db.query(ErrorRecord.question_id).all() if r[0] is not None]
            conds = [QuizQuestion.knowledge_point.like(f"%{kp}%") for kp in hot_kps]
            picked = base_q.filter(or_(*conds)).filter(
                ~QuizQuestion.id.in_(missed_ids) if missed_ids else True
            ).order_by(func.random()).limit(size).all()
            basis = f"按易错知识点抽同类新题：{'、'.join(hot_kps[:5])}"
        else:
            picked = base_q.order_by(func.random()).limit(size).all()
            basis = "暂无错题数据，已退化为随机抽题"
    else:  # random
        picked = base_q.order_by(func.random()).limit(size).all()
        basis = "随机抽题"

    if not picked:
        raise HTTPException(status_code=404, detail="题库中没有可用题目，请先调整筛选条件")

    return {
        "mode": req.mode,
        "basis": basis,
        "size": len(picked),
        "questions": [
            {
                "id": q.id, "content": q.content, "options": q.options,
                "answer": q.answer, "analysis": q.analysis, "subject": q.subject,
                "knowledge_point": q.knowledge_point, "question_type": q.question_type,
                "difficulty": q.difficulty,
            } for q in picked
        ],
    }
