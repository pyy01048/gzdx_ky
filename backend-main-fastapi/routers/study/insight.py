# -*- coding: utf-8 -*-
"""学习洞察聚合路由（V11 · F1/F2/F4）。

三个端点，全部为「聚合已有数据」的只读/轻写接口，不重复造轮子：
- GET  /api/insight/today          F1 今日学习引导（倒计时/到期复习/今日任务/薄弱点/今日答题）
- GET  /api/insight/weekly-report  F4 学习周报（本周 vs 上周：答题量/正确率/时长/逐日曲线）
- POST /api/insight/smart-paper    F2 智能组卷（薄弱点/易错/随机三模式，数据源 kp 链与错题本）

数据源复用：DashboardService、review_service.due_items、
error_linker.weak_knowledge_points（今日薄弱点与智能组卷的考点依据，
与仪表盘 D-10 同一口径）、study_events 流水。
模型调用约定：本模块不调用 LLM，全部本地规则计算（快、可测、可离线）。
"""
from __future__ import annotations

import datetime
import random
from typing import List, Optional

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    ErrorRecord, Goal, QuizQuestion, StudyEvent, StudyStats, User,
)
from services.dashboard_service import DashboardService
from services import error_linker, kp_mastery, review_service
from utils.scope import owner_id  # B4 行级隔离：今日引导只看本人流水
from utils.security import current_user
from utils.timeutil import (
    day_bucket_expr,
    local_day_window,
    local_range_utc,
    local_today,
)

router = APIRouter(prefix="/api/insight", tags=["学习洞察"])


# --------------------------------------------------------------------------- #
# F1 · 今日学习引导
# --------------------------------------------------------------------------- #
@router.get("/today")
def today_insight(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """首页引导层聚合：打开就知道该干什么。

    返回 items：{icon,label,count,to,hint} 行动清单，前端按顺序渲染。
    B4：倒计时、答题流水、薄弱点全部按当前用户隔离。
    """
    uid = owner_id(user)
    # 「今天」按北京自然日切，DB 列是 naive UTC —— 两者相差 8 小时，
    # 直接用 date.today() 会在北京 00:00~08:00 之间把昨天的流水算进今天。
    _, day_start, day_end = local_day_window()

    # 倒计时（复用 DashboardService）
    try:
        countdown = DashboardService.get_countdown(db, user_id=uid)
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
        # get_today_tasks 返回的是**字典壳**（{total, pending, doing, done, tasks, modules}），
        # 旧写法 `or []` + isinstance(list) 永远不成立，导致「今日待办」建议数恒为 0。
        today_tasks = DashboardService.get_today_tasks(db, user_id=uid)
        task_count = int(today_tasks.get("total") or 0)
    except Exception:
        task_count = 0

    # 今日答题流水（study_events）—— B4：只看当前用户，否则会串其他用户的答题数
    q = db.query(
        func.count(StudyEvent.id),
        func.sum(func.cast(func.coalesce(StudyEvent.is_correct, sa.false()), sa.Integer)),
    ).filter(
        StudyEvent.event_type == "answer",
        StudyEvent.user_id == uid,
        StudyEvent.occurred_at >= day_start,
        StudyEvent.occurred_at < day_end,
    ).first()
    today_answered = int(q[0] or 0)
    today_correct = int(q[1] or 0)

    # 薄弱点 TOP3 —— 与仪表盘 D-10、/api/review/weak-points、学习画像 TOP10
    # 同一个出口（services/error_linker.weak_points_view）。此前这里走
    # analytics 的正则猜词：从错题正文抓 `[\u4e00-\u9fa5]{2,6}(?:定理|公式|…)`
    # 当考点名，再用 100 − 错误次数×15 造掌握度 —— 首屏「薄弱点练习」卡片
    # 显示的是一批 knowledge_points 表里根本不存在的「考点」。
    weak_top = [
        {
            "kp": p["name"],
            "knowledge_point_id": p["knowledge_point_id"],
            "subject": p["subject"],
            "error_count": p["error_count"],
            "mastery": p["mastery"],
            # level 保持中文标签口径不变（"薄弱"/"已掌握"），前端沿用旧展示。
            "level": kp_mastery.STATE_LABELS[
                kp_mastery.STATE_MASTERED if p["mastery"] >= kp_mastery.MASTERED_THRESHOLD
                else kp_mastery.STATE_WEAK
            ],
        }
        for p in error_linker.weak_points_view(db, limit=3, user_id=uid)
    ]

    # 建议卡片的图标用**语义 key**（前端映射到 SVG 图标），不返回 emoji。
    # 原因：emoji 在不同系统/字体下渲染差异大，且与产品图标体系风格冲突
    # （设计铁律 P0-1：禁止 emoji 作功能图标）。前端见 components/Icon.jsx。
    suggestions = [
        {"icon": "review", "label": "到期复习", "count": due_count, "to": "/quiz?tab=review",
         "hint": "艾宾浩斯队列到期，先复习再学新的" if due_count else "暂无到期复习"},
        {"icon": "todo", "label": "今日待办", "count": task_count, "to": "/tasks",
         "hint": "按计划推进今天的任务" if task_count else "还没有安排今日任务"},
        {"icon": "target", "label": "薄弱点练习", "count": len(weak_top), "to": "/quiz?mode=weak",
         "hint": "、".join([w["kp"] for w in weak_top[:2]]) if weak_top else "暂无薄弱点数据"},
        {"icon": "brain", "label": "今日已答", "count": today_answered, "to": "/quiz",
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
    today = local_today()
    this_first = today - datetime.timedelta(days=6)
    last_first = this_first - datetime.timedelta(days=7)
    tomorrow = today + datetime.timedelta(days=1)

    this_start, this_end = local_range_utc(this_first, tomorrow)
    last_start, last_end = local_range_utc(last_first, this_first)

    def _period_stats(start, end, day_from, day_to):
        row = db.query(
            func.count(StudyEvent.id),
            func.sum(func.cast(func.coalesce(StudyEvent.is_correct, sa.false()), sa.Integer)),
        ).filter(
            StudyEvent.event_type == "answer",
            StudyEvent.occurred_at >= start,
            StudyEvent.occurred_at < end,
        ).first()
        answered = int(row[0] or 0)
        correct = int(row[1] or 0)
        # 时长：study_stats 按日（Date 列存的也是北京自然日）
        dur_row = db.query(func.coalesce(func.sum(StudyStats.total_duration), 0)).filter(
            StudyStats.date >= day_from, StudyStats.date < day_to
        ).first()
        duration = int(dur_row[0] or 0)
        return {"answered": answered, "correct": correct, "accuracy": (correct / answered) if answered else None, "duration": duration}

    this_week = _period_stats(this_start, this_end, this_first, tomorrow)
    last_week = _period_stats(last_start, last_end, last_first, this_first)

    # 逐日曲线（近7天）：分桶口径必须与上面的窗口同源
    day_col = day_bucket_expr(StudyEvent.occurred_at, db)
    daily_rows = db.query(
        day_col,
        func.count(StudyEvent.id),
        func.sum(func.cast(func.coalesce(StudyEvent.is_correct, sa.false()), sa.Integer)),
    ).filter(
        StudyEvent.event_type == "answer",
        StudyEvent.occurred_at >= this_start,
        StudyEvent.occurred_at < this_end,
    ).group_by(day_col).all()
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
        # 抽题依据的考点名同样取自 error_linker（活跃错题挂接聚合而来），
        # 不再用正则从错题正文猜关键词 —— 猜出来的名字在 knowledge_points 表里
        # 并不存在，却会原样出现在返回给前端的 basis 文案里。
        # 这里仍按 QuizQuestion.knowledge_point 文本做 LIKE 匹配：题→考点的权威
        # 关系是 question_knowledge_links，等 #14 五层知识树一起做（见任务备注）。
        weak_kps = [p["name"] for p in error_linker.weak_knowledge_points(
            db, subject=req.subject, limit=10
        ) if p["name"]]
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
            if picked:
                basis = f"按易错知识点抽同类新题：{'、'.join(hot_kps[:5])}"
            else:
                # 易错知识点命中但没有“未错过”的同类题（常见于小库/刚练过）：
                # 退化为随机，而不是返回 404 让前端「智能组卷」整块不可用。
                picked = base_q.order_by(func.random()).limit(size).all()
                basis = "易错知识点暂无未练同类题，已退化为随机抽题"
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
