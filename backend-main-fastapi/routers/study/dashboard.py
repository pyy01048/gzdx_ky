"""驾驶舱路由。

本文件**只做参数接收与响应格式化**：所有取数与口径都在 ``services.dashboard_service``，
"哪天学了多少"再往下了一层都在 ``services.study_calendar``。
历史上 ``_get_today_tasks`` / ``_get_stats`` / ``_get_weakness`` 是服务层三份近似副本
（连"今日任务"的过滤条件都已经漂移到不一样），已删除 —— 任何"顺手在路由里再查一遍"
的改动都会重新制造同一应用两个答案。
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Literal, Optional

from database import get_db
from models import StudySession, User
from utils.exceptions import BusinessException, ErrorCode
from utils.scope import owner_id  # B4 行级隔离：驾驶舱个人数据只看本人
from utils.security import current_user
from utils.timeutil import local_today
from services.dashboard_service import DashboardService
from services.study_calendar import (
    FOCUS_SOURCES,
    MAX_FOCUS_MINUTES_PER_DAY,
    MAX_FOCUS_MINUTES_PER_SESSION,
    focus_minutes_on,
)

from utils.response import MAX_PAGE_SIZE

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class StudySessionCreate(BaseModel):
    """一次专注的落库请求（01-仪表盘 §2.1 D-04：手动 / 番茄钟）。

    ``duration`` **故意不给默认值**：漏传字段就自动记 25 分钟，等于替用户编一段
    没发生过的专注。规格里的「默认 25min」是界面上计时器的预设档
    （``frontend/src/components/FocusTimer.jsx``），属于 UI 默认，不是接口默认。
    """

    duration: int = Field(
        ..., ge=1, le=MAX_FOCUS_MINUTES_PER_SESSION,
        description=f"本次专注分钟数（1…{MAX_FOCUS_MINUTES_PER_SESSION}）",
    )
    subject: Optional[str] = Field(None, max_length=50, description="备考科目，留空=不限科目")
    task_type: Literal["pomodoro", "manual", "module"] = Field(
        "manual", description="来源：" + " / ".join(FOCUS_SOURCES),
    )
    remark: Optional[str] = Field(None, max_length=200)


@router.post("/study-session")
async def create_study_session(
    data: StudySessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """写入一条真实专注记录，返回落库后的行 + 当日累计。

    日界按**写入时刻的北京自然日**（``local_today()``）归属，与
    ``services/study_calendar`` 的台账同一口径；跨零点的计时段落在哪一天
    由"什么时候记"决定，不接受客户端自报日期 —— 能自报日期就能自报历史。
    """
    uid = owner_id(user)
    day = local_today()
    subject = (data.subject or "").strip() or None
    already = focus_minutes_on(db, day, user_id=uid)
    if already + data.duration > MAX_FOCUS_MINUTES_PER_DAY:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER,
            f"今天已累计 {already} 分钟，再加 {data.duration} 分钟就超过一天的长度了",
            detail={"date": day.isoformat(), "already_minutes": already,
                    "limit": MAX_FOCUS_MINUTES_PER_DAY},
            status_code=422,
        )
    session = StudySession(
        date=day,
        duration=data.duration,
        subject=subject,
        task_type=data.task_type,
        remark=data.remark,
        user_id=uid,  # B4：归属当前用户
    )
    db.add(session)
    db.commit()
    return {
        "id": session.id,
        "ok": True,
        "date": day.isoformat(),
        "duration": session.duration,
        "subject": session.subject,
        "task_type": session.task_type,
        "day_total_minutes": already + data.duration,
    }


@router.get("")
async def get_dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """返回驾驶舱所有数据（业务逻辑在 DashboardService）。B4：只看本人。"""
    uid = owner_id(user)
    countdown = DashboardService.get_countdown(db, user_id=uid)
    today_tasks = DashboardService.get_today_tasks(db, user_id=uid)
    stats = DashboardService.get_stats(db, user_id=uid)
    weakness = DashboardService.get_weakness(db, user_id=uid)
    return {
        "countdown": countdown,
        "today_tasks": today_tasks,
        "stats": stats,
        "weakness": weakness,
    }


@router.get("/summary")
async def get_dashboard_summary(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """首屏聚合唯一出口（01-仪表盘 §2.6，D-01…D-11）。

    新前端只该调这一个接口；``/api/dashboard`` 保留为旧响应壳的兼容读法，
    两者对同一个数字必然给出同一个值 —— 因为它们是同一个函数的两次调用。
    B4：目标、行为流水、待办、复习队列全部只看当前用户。
    """
    return DashboardService.get_summary(db, user_id=owner_id(user))


@router.get("/review-queue")
async def get_review_queue(
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """今日复习队列唯一出口：后端调度器统一汇总卡片、任务、错题。B4：只看本人。"""
    return DashboardService.get_review_queue(db, limit, user_id=owner_id(user))


@router.get("/countdown")
async def get_countdown(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """倒计时数据。与 /dashboard 内嵌的 countdown 同一实现，避免两个端点给出两套日期。"""
    return DashboardService.get_countdown(db, user_id=owner_id(user))


@router.get("/today-tasks")
async def get_today_tasks(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """今日任务。B4：只看本人。"""
    return DashboardService.get_today_tasks(db, user_id=owner_id(user))


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """学习数据统计。B4：只看本人。"""
    return DashboardService.get_stats(db, user_id=owner_id(user))


@router.get("/weakness")
async def get_weakness(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """AI 薄弱项预警（分析错题数据）。B4：只看本人错题。"""
    return DashboardService.get_weakness(db, user_id=owner_id(user))
