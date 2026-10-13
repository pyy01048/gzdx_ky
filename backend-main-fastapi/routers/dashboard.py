"""驾驶舱路由。"""

import datetime
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Task, ErrorRecord, StudySession, StudyStats
from services.review_scheduler import ReviewScheduler
from services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class StudySessionCreate(BaseModel):
    duration: int = 25
    subject: Optional[str] = None
    task_type: str = "pomodoro"
    remark: Optional[str] = None


@router.post("/study-session")
async def create_study_session(
    data: StudySessionCreate,
    db: Session = Depends(get_db),
):
    """创建一条学习会话记录（番茄钟完成时调用）。支持JSON请求体。"""
    session = StudySession(
        date=datetime.date.today(),
        duration=data.duration,
        subject=data.subject,
        task_type=data.task_type,
        remark=data.remark,
    )
    db.add(session)
    db.commit()
    return {"id": session.id, "ok": True}


@router.get("")
async def get_dashboard(db: Session = Depends(get_db)):
    """返回驾驶舱所有数据（业务逻辑在 DashboardService）。"""
    countdown = DashboardService.get_countdown(db)
    today_tasks = DashboardService.get_today_tasks(db)
    stats = DashboardService.get_stats(db)
    weakness = DashboardService.get_weakness(db)
    return {
        "countdown": countdown,
        "today_tasks": today_tasks,
        "stats": stats,
        "weakness": weakness,
    }


@router.get("/countdown")
async def get_countdown(db: Session = Depends(get_db)):
    """倒计时数据。与 /dashboard 内嵌的 countdown 同一实现，避免两个端点给出两套日期。"""
    return DashboardService.get_countdown(db)


@router.get("/today-tasks")
async def get_today_tasks(db: Session = Depends(get_db)):
    """今日任务。"""
    return _get_today_tasks(db)


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """学习数据统计。"""
    return _get_stats(db)


@router.get("/weakness")
async def get_weakness(db: Session = Depends(get_db)):
    """AI 薄弱项预警（分析错题数据）。"""
    return _get_weakness(db)


# ----------------------------------------------------------------------- #
# 内部函数
# ----------------------------------------------------------------------- #
def _get_today_tasks(db: Session) -> dict:
    today = datetime.date.today()
    # 今日任务 = 今日到期 + 进行中（不包括所有pending，避免数量虚高）
    tasks = (
        db.query(Task)
        .filter(
            (Task.due_date == today) | (Task.status == "doing")
        )
        .order_by(Task.priority.desc(), Task.due_date.asc())
        .all()
    )
    pending = [t for t in tasks if t.status == "pending"]
    doing = [t for t in tasks if t.status == "doing"]
    done = [t for t in tasks if t.status == "done"]
    return {
        "total": len(tasks),
        "pending": len(pending),
        "doing": len(doing),
        "done": len(done),
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "subject": t.subject,
                "task_type": t.task_type,
                "stage": t.stage,
                "status": t.status,
                "priority": t.priority,
                "due_date": t.due_date.isoformat() if t.due_date else None,
            }
            for t in tasks[:20]
        ],
    }


def _get_stats(db: Session) -> dict:
    """学习统计 - 使用 SQL 聚合优化，避免 N+1 查询"""
    from sqlalchemy import func

    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)

    # 1. 本周学习总时长（SQL 聚合）
    total_duration = (
        db.query(func.coalesce(func.sum(StudySession.duration), 0))
        .filter(StudySession.date >= week_ago)
        .scalar()
    ) or 0

    # 2. 按科目统计学习时长（SQL GROUP BY）
    subject_rows = (
        db.query(StudySession.subject, func.coalesce(func.sum(StudySession.duration), 0))
        .filter(StudySession.date >= week_ago, StudySession.subject != None)
        .group_by(StudySession.subject)
        .all()
    )
    subject_durations = {sub: dur for sub, dur in subject_rows if sub}

    # 3. 7 天趋势（SQL GROUP BY date）
    daily_rows = (
        db.query(StudySession.date, func.coalesce(func.sum(StudySession.duration), 0))
        .filter(StudySession.date >= week_ago)
        .group_by(StudySession.date)
        .all()
    )
    daily_map = {d.isoformat(): dur for d, dur in daily_rows}
    daily_durations = []
    for i in range(6, -1, -1):
        day = today - datetime.timedelta(days=i)
        day_str = day.isoformat()
        daily_durations.append({
            "date": day_str,
            "duration": daily_map.get(day_str, 0),
        })

    # 4. 今日学习时长
    #    ⚠️ 原实现读 StudyStats 表，但**全项目没有任何地方写这张表** ——
    #    导致 today_duration 永远是 0。改为与 week_duration 一致，
    #    直接从 study_sessions 聚合，不依赖预先物化的统计表。
    today_duration = (
        db.query(func.coalesce(func.sum(StudySession.duration), 0))
        .filter(StudySession.date == today)
        .scalar()
    ) or 0

    # 5. 错题数（唯一口径：services/error_linker.error_stats —— 与
    #    DashboardService.get_stats、GET /api/errors/stats 同源，避免各算一套）
    from services import error_linker

    estats = error_linker.error_stats(db)
    error_count = estats["active_errors"]

    # 6. 本周任务完成数（SQL 直接过滤）
    weekly_completed = (
        db.query(func.count(Task.id))
        .filter(
            Task.status == "done",
            Task.completed_at != None,
            func.date(Task.completed_at) >= week_ago,
        )
        .scalar()
    ) or 0

    return {
        "today_duration": int(today_duration),
        "week_duration": total_duration,
        "subject_durations": subject_durations,
        "weekly_completed_tasks": weekly_completed,
        "active_errors": error_count,
        "due_errors": estats["due_errors"],
        "daily_trend": daily_durations,
    }


def _get_weakness(db: Session) -> dict:
    """分析错题数据，生成薄弱项预警。"""
    errors = db.query(ErrorRecord).filter(ErrorRecord.status == "active").all()

    if not errors:
        return {
            "has_weakness": False,
            "message": "暂无错题数据，继续保持！",
            "weak_subjects": [],
            "weak_chapters": [],
            "common_reasons": [],
        }

    # 按科目统计错题数
    subject_counter = Counter()
    reason_counter = Counter()
    for e in errors:
        if e.subject:
            subject_counter[e.subject] += 1
        if e.error_reason:
            reason_counter[e.error_reason] += 1

    weak_subjects = [
        {"subject": s, "count": c, "level": "high" if c >= 10 else "medium" if c >= 5 else "low"}
        for s, c in subject_counter.most_common(5)
    ]

    common_reasons = [
        {"reason": r, "count": c}
        for r, c in reason_counter.most_common(5)
    ]

    return {
        "has_weakness": True,
        "total_errors": len(errors),
        "weak_subjects": weak_subjects,
        "common_reasons": common_reasons,
        "suggestion": (
            f"你在 {'、'.join(s['subject'] for s in weak_subjects[:3])} 科目错题较多，"
            f"建议重点复习。常见错误原因为：{'、'.join(r['reason'] for r in common_reasons[:3])}。"
        ),
    }
