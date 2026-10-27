"""任务路由。"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Task, Goal, User
from schemas import TaskCreate, TaskUpdate, TaskResponse, GenericResponse
from services.review_scheduler import ReviewScheduler
from utils.scope import owner_id, scoped  # B4 行级隔离
from utils.security import current_user
from utils.timeutil import local_today, utcnow  # 统一 naive UTC 时间规范（P0-4）

from utils.response import MAX_PAGE_SIZE

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(
    subject: Optional[str] = None,
    task_type: Optional[str] = None,
    stage: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """任务列表（支持筛选和分页，B4：只看本人任务）。"""
    query = db.query(Task).filter(scoped(Task, user))
    if subject:
        query = query.filter(Task.subject == subject)
    if task_type:
        query = query.filter(Task.task_type == task_type)
    if stage:
        query = query.filter(Task.stage == stage)
    if status:
        query = query.filter(Task.status == status)

    # 计算总数
    total = query.count()

    # 分页
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    offset = (page - 1) * page_size

    tasks = (
        query.order_by(Task.priority.desc(), Task.due_date.asc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": [
            {
                "id": t.id,
                "title": t.title,
                "subject": t.subject,
                "task_type": t.task_type,
                "stage": t.stage,
                "status": t.status,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "priority": t.priority,
                "next_review": t.next_review.isoformat() if t.next_review else None,
                "review_count": t.review_count,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
    }


@router.post("")
async def create_task(
    task: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """创建任务。"""
    new_task = Task(**task.model_dump())
    new_task.user_id = owner_id(user)  # B4：写入归属当前用户
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return {"id": new_task.id, "message": "任务创建成功"}


@router.put("/{task_id}")
async def update_task(
    task_id: int,
    task: TaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """更新任务。"""
    db_task = db.query(Task).filter(Task.id == task_id, scoped(Task, user)).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="任务不存在")

    update_data = task.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_task, key, value)

    db.commit()
    db.refresh(db_task)
    return {"id": db_task.id, "message": "任务更新成功"}


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """删除任务。"""
    db_task = db.query(Task).filter(Task.id == task_id, scoped(Task, user)).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="任务不存在")

    db.delete(db_task)
    db.commit()
    return {"message": "任务已删除"}


@router.post("/{task_id}/complete")
async def complete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """打卡完成。"""
    db_task = db.query(Task).filter(Task.id == task_id, scoped(Task, user)).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="任务不存在")

    db_task.status = "done"
    db_task.completed_at = utcnow()  # naive UTC，与 DB 列对齐（P0-4）

    # 设置艾宾浩斯下次复习时间
    db_task.review_count = (db_task.review_count or 0) + 1
    db_task.next_review = ReviewScheduler.ebinghaus_next_review(db_task.review_count - 1)

    db.commit()
    return {
        "id": db_task.id,
        "status": db_task.status,
        "next_review": db_task.next_review.isoformat() if db_task.next_review else None,
        "message": "打卡成功，已安排复习提醒",
    }


@router.post("/{task_id}/uncomplete")
async def uncomplete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """撤销打卡完成。"""
    db_task = db.query(Task).filter(Task.id == task_id, scoped(Task, user)).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="任务不存在")

    db_task.status = "pending"
    db_task.completed_at = None

    db.commit()
    return {
        "id": db_task.id,
        "status": db_task.status,
        "message": "已撤销打卡",
    }


@router.get("/review-schedule")
async def review_schedule(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """艾宾浩斯复习提醒。"""
    due_tasks = ReviewScheduler.get_due_tasks(db, user_id=owner_id(user))
    return {
        "total": len(due_tasks),
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "subject": t.subject,
                "next_review": t.next_review.isoformat() if t.next_review else None,
                "review_count": t.review_count,
            }
            for t in due_tasks
        ],
    }


class AiPlanRequest(BaseModel):
    """AI 规划入参。topic 必须真的进提示词：前端「主题」输入框此前被后端整个丢掉，
    用户填了"线性代数特征值强化"仍拿到一份全科计划。"""

    topic: Optional[str] = None


@router.post("/ai-generate")
async def ai_generate_tasks(
    req: Optional[AiPlanRequest] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """AI 自动生成每日计划。"""
    from services.ai_service import AIService

    goal = db.query(Goal).filter(scoped(Goal, user)).order_by(Goal.id.asc()).first()
    goal_text = ""
    if goal:
        goal_text = f"目标院校：{goal.university or ''}，专业：{goal.major or ''}"
    topic = (req.topic or "").strip() if req else ""
    if topic:
        goal_text = f"{goal_text}；本次主题：{topic}" if goal_text else f"本次主题：{topic}"

    pending_tasks = db.query(Task).filter(Task.status != "done", scoped(Task, user)).count()
    today = local_today().isoformat()

    ai = AIService(db)
    try:
        plan = await ai.generate_plan(
            goal=goal_text or "考研全科复习",
            available_time=f"今日 {today}，当前待办 {pending_tasks} 项",
        )
        return {"plan": plan, "message": "AI 计划生成成功"}
    except Exception as e:
        # E2E2-002 补漏：ai-generate 的 detail 曾透传上游 401 与服务商地址；原文只进服务端日志
        logging.getLogger(__name__).exception("任务 AI 生成失败")
        raise HTTPException(status_code=502, detail="AI 服务暂时不可用：请到「设置 → AI 服务」检查 API Key 与网络后重试。")
