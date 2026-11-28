"""任务路由。

W3（2026-11）体验重做后端侧：
* 任务新建器字段落库：多科目 subjects / 子科目模块 modules / 起止 start_date~end_date /
  循环 recurrence / 提醒 remind（仅存储展示，未接推送）/ 进度条 show_progress+progress_*。
* 循环任务的"完成"落在具体某一天：task_checkins 按日打卡表（非循环任务维持 status 旧口径）。
* /api/tasks/calendar 把循环规则展开成日历发生日（口径单源 services/task_recurrence.py）。
* /api/tasks/modules 个人子科目模块字典（可增删）。
"""

import datetime
import logging
from typing import Optional

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from schemas import TaskCreate, TaskUpdate
from services.review_scheduler import ReviewScheduler
from services.task_recurrence import expand_task_dates, is_recurring, normalize_recurrence, normalize_remind
from sqlalchemy.orm import Session
from utils.response import MAX_PAGE_SIZE
from utils.scope import owner_id, scoped  # B4 行级隔离
from utils.security import current_user
from utils.timeutil import local_today, utcnow  # 统一 naive UTC 时间规范（P0-4）

from models import Goal, Task, TaskCheckIn, TaskModuleDict, User

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

#: 日历接口单次查询跨度上限（天）：一个学期级别够用，防病态区间放大响应
CALENDAR_MAX_SPAN_DAYS = 400


class CheckInRequest(BaseModel):
    """打卡入参：date 为空 = 旧口径（整个任务完成/撤销，非循环任务沿用）。"""

    date: Optional[str] = None


class ProgressRequest(BaseModel):
    delta: int = 1


class ModuleIn(BaseModel):
    subject: str
    name: str


# --------------------------------------------------------------------------- #
# 入参规整（诚实原则：非法结构当场 400，不静默吞掉后在日历上造假象）
# --------------------------------------------------------------------------- #
def _normalize_subjects(
    subjects: Optional[list[str] | str], subject: Optional[str]
) -> tuple[Optional[list[str]], Optional[str]]:
    """多选科目去空去重；返回 (列表或 None, 兼容列 subject 值)。"""
    if subjects is None:
        return None, subject
    if isinstance(subjects, str):
        subjects = [subjects]
    cleaned = []
    for s in subjects:
        s = str(s or "").strip()
        if s and s not in cleaned:
            cleaned.append(s)
    compat = cleaned[0] if cleaned else None
    return cleaned, (compat or subject)


def _validate_payload(data: dict, current: Optional[Task] = None) -> dict:
    """就地校验/规整 recurrence、remind、subjects，返回（可能修补过的）data。

    current：更新场景传存量任务行，用于"只改循环没改日期"时按合并后的值校验。
    """
    if "recurrence" in data:
        try:
            data["recurrence"] = normalize_recurrence(data["recurrence"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "remind" in data:
        try:
            data["remind"] = normalize_remind(data["remind"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "subjects" in data:
        cleaned, compat = _normalize_subjects(data.get("subjects"), data.get("subject"))
        data["subjects"] = cleaned
        if cleaned:
            data["subject"] = compat
    if "modules" in data and data["modules"] is not None:
        mods = data["modules"]
        if isinstance(mods, str):
            mods = [mods]
        cleaned_mods = []
        for m in mods:
            m = str(m or "").strip()[:50]
            if m and m not in cleaned_mods:
                cleaned_mods.append(m)
        data["modules"] = cleaned_mods
    # 起止日期 sanity：结束不得早于开始（None 视为不限；更新时与存量值合并判断）
    sd = data.get("start_date", getattr(current, "start_date", None)) if current else data.get("start_date")
    ed = data.get("end_date", getattr(current, "end_date", None)) if current else data.get("end_date")
    if sd and ed and ed < sd:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    # 循环任务必须有锚点日期，否则日历上永远展不出来（宁缺不假）
    rec = data.get("recurrence")
    if isinstance(rec, dict) and rec.get("freq") not in (None, "none"):
        due = data.get("due_date", getattr(current, "due_date", None)) if current else data.get("due_date")
        if not sd and not due:
            raise HTTPException(status_code=400, detail="循环任务需要开始日期（或截止日期）作为锚点")
    show_progress = data.get("show_progress")
    if show_progress is True:
        total = (
            data.get("progress_total", getattr(current, "progress_total", None))
            if current
            else data.get("progress_total")
        )
        if not isinstance(total, int) or total < 1:
            raise HTTPException(status_code=400, detail="开启进度条需要目标量 progress_total（>=1）")
    return data


def _task_dict(t: Task, checkin_dates: Optional[list[str]] = None) -> dict:
    payload = {
        "id": t.id,
        "title": t.title,
        "subject": t.subject,
        "subjects": t.subjects or ([t.subject] if t.subject else []),
        "modules": t.modules or [],
        "task_type": t.task_type,
        "stage": t.stage,
        "status": t.status,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "start_date": t.start_date.isoformat() if t.start_date else None,
        "end_date": t.end_date.isoformat() if t.end_date else None,
        "recurrence": t.recurrence or {"freq": "none"},
        "remind": t.remind,
        "show_progress": bool(t.show_progress),
        "progress_total": t.progress_total,
        "progress_done": t.progress_done or 0,
        "priority": t.priority,
        "next_review": t.next_review.isoformat() if t.next_review else None,
        "review_count": t.review_count,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "is_recurring": is_recurring(t),
    }
    if checkin_dates is not None:
        payload["checkin_dates"] = checkin_dates
    return payload


def _parse_date_or_400(value: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="日期格式错误，应为 YYYY-MM-DD") from None


def _checkins_by_task(db: Session, user: User, task_ids: list[int], start=None, end=None) -> dict[int, list[str]]:
    """批量取按日打卡（一次查询，避免 N+1）。"""
    if not task_ids:
        return {}
    q = db.query(TaskCheckIn).filter(TaskCheckIn.task_id.in_(task_ids), scoped(TaskCheckIn, user))
    if start:
        q = q.filter(TaskCheckIn.checkin_date >= start)
    if end:
        q = q.filter(TaskCheckIn.checkin_date <= end)
    out: dict[int, list[str]] = {}
    for ci in q.order_by(TaskCheckIn.checkin_date.asc()).all():
        out.setdefault(ci.task_id, []).append(ci.checkin_date.isoformat())
    return out


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

    tasks = query.order_by(Task.priority.desc(), Task.due_date.asc()).offset(offset).limit(page_size).all()

    checkins = _checkins_by_task(db, user, [t.id for t in tasks])

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": [_task_dict(t, checkins.get(t.id, [])) for t in tasks],
    }


# --------------------------------------------------------------------------- #
# 日历视图（W3）：区间内把循环规则展开成发生日 + 按日打卡状态
# --------------------------------------------------------------------------- #
@router.get("/calendar")
async def task_calendar(
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """[start, end] 区间的任务日历（回看过去 / 预览未来同一口径）。

    返回 items：一条 = 某任务在某天的一次发生；done 由 task_checkins（循环）
    或 tasks.status（非循环单日）判定，绝不把未完成标成完成。
    不传区间 = 今天前后各 45 天（API 契约巡检要求 GET 无参可得 2xx，不给 422）。
    """
    if not start or not end:
        anchor = local_today()
        start = start or (anchor - datetime.timedelta(days=45)).isoformat()
        end = end or (anchor + datetime.timedelta(days=45)).isoformat()
    s = _parse_date_or_400(start)
    e = _parse_date_or_400(end)
    if e < s:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    if (e - s).days > CALENDAR_MAX_SPAN_DAYS:
        raise HTTPException(status_code=400, detail=f"日历查询跨度最大 {CALENDAR_MAX_SPAN_DAYS} 天")

    tasks = db.query(Task).filter(scoped(Task, user)).all()
    checkins = _checkins_by_task(db, user, [t.id for t in tasks], start=s, end=e)

    items = []
    for t in tasks:
        dates = expand_task_dates(t, s, e)
        if not dates:
            continue
        done_dates = set(checkins.get(t.id, []))
        recurring = is_recurring(t)
        base = _task_dict(t)
        for d in dates:
            iso = d.isoformat()
            done = iso in done_dates or (not recurring and t.status == "done")
            items.append({**base, "date": iso, "done": done, "checkin": iso in done_dates})
    items.sort(key=lambda x: (x["date"], -(x["priority"] or 0), x["id"]))
    return {"start": s.isoformat(), "end": e.isoformat(), "total": len(items), "items": items}


# --------------------------------------------------------------------------- #
# 子科目模块字典（W3：任务新建器「可增删/选择」的落点）
# --------------------------------------------------------------------------- #
@router.get("/modules")
async def list_task_modules(
    subject: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """个人模块字典列表（可按科目过滤）。"""
    q = db.query(TaskModuleDict).filter(scoped(TaskModuleDict, user))
    if subject:
        q = q.filter(TaskModuleDict.subject == subject)
    rows = q.order_by(TaskModuleDict.subject.asc(), TaskModuleDict.id.asc()).all()
    return {"items": [{"id": r.id, "subject": r.subject, "name": r.name} for r in rows]}


@router.post("/modules")
async def create_task_module(
    data: ModuleIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """新增模块（同科目重名幂等返回既有行）。"""
    subject = (data.subject or "").strip()[:50]
    name = (data.name or "").strip()[:50]
    if not subject or not name:
        raise HTTPException(status_code=400, detail="科目与模块名都不能为空")
    exist = (
        db.query(TaskModuleDict)
        .filter(TaskModuleDict.subject == subject, TaskModuleDict.name == name, scoped(TaskModuleDict, user))
        .first()
    )
    if exist:
        return {"id": exist.id, "subject": exist.subject, "name": exist.name, "message": "模块已存在"}
    row = TaskModuleDict(user_id=owner_id(user), subject=subject, name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "subject": row.subject, "name": row.name, "message": "模块已添加"}


@router.delete("/modules/{module_id}")
async def delete_task_module(
    module_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """删除模块（只删字典行；存量任务里的 modules 标签快照不受影响）。"""
    row = db.query(TaskModuleDict).filter(TaskModuleDict.id == module_id, scoped(TaskModuleDict, user)).first()
    if not row:
        raise HTTPException(status_code=404, detail="模块不存在")
    db.delete(row)
    db.commit()
    return {"message": "模块已删除"}


@router.post("")
async def create_task(
    task: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """创建任务（W3：含多科目/模块/起止/循环/提醒/进度条配置，校验见 _validate_payload）。"""
    data = _validate_payload(task.model_dump())
    new_task = Task(**data)
    new_task.user_id = owner_id(user)  # B4：写入归属当前用户
    if new_task.show_progress is None:
        new_task.show_progress = False
    new_task.progress_done = 0
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

    update_data = _validate_payload(task.model_dump(exclude_unset=True), current=db_task)
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
    req: Optional[CheckInRequest] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """打卡完成。

    W3 两口径：
    * 带 date 或循环任务 → 写 task_checkins（完成状态落在某一天），
      进度条任务同时把 progress_done 累加 1（封顶 total），两者都是真实持久化。
    * 不带 date 的非循环任务 → 旧行为不变（status=done + 艾宾浩斯排程），
      老前端/老调用方零感知。
    """
    db_task = db.query(Task).filter(Task.id == task_id, scoped(Task, user)).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="任务不存在")

    day = _parse_date_or_400(req.date) if req and req.date else None
    if day is None and is_recurring(db_task):
        day = local_today()

    if day is not None:
        exist = db.query(TaskCheckIn).filter(TaskCheckIn.task_id == db_task.id, TaskCheckIn.checkin_date == day).first()
        if not exist:
            db.add(
                TaskCheckIn(
                    user_id=owner_id(user),
                    task_id=db_task.id,
                    checkin_date=day,
                    completed_at=utcnow(),
                )
            )
        if db_task.show_progress and db_task.progress_total:
            db_task.progress_done = min(db_task.progress_total, (db_task.progress_done or 0) + 1)
        db.commit()
        return {
            "id": db_task.id,
            "date": day.isoformat(),
            "checkin": True,
            "progress_done": db_task.progress_done or 0,
            "message": "已打卡",
        }

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
    req: Optional[CheckInRequest] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """撤销打卡完成（带 date/循环任务 → 删当天打卡行并回退进度 1；否则旧口径）。"""
    db_task = db.query(Task).filter(Task.id == task_id, scoped(Task, user)).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="任务不存在")

    day = _parse_date_or_400(req.date) if req and req.date else None
    if day is None and is_recurring(db_task):
        day = local_today()

    if day is not None:
        deleted = (
            db.query(TaskCheckIn).filter(TaskCheckIn.task_id == db_task.id, TaskCheckIn.checkin_date == day).delete()
        )
        if db_task.show_progress and db_task.progress_total and deleted:
            db_task.progress_done = max(0, (db_task.progress_done or 0) - 1)
        db.commit()
        return {"id": db_task.id, "date": day.isoformat(), "checkin": False, "message": "已撤销该日打卡"}

    db_task.status = "pending"
    db_task.completed_at = None

    db.commit()
    return {
        "id": db_task.id,
        "status": db_task.status,
        "message": "已撤销打卡",
    }


@router.post("/{task_id}/progress")
async def adjust_progress(
    task_id: int,
    req: ProgressRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """进度条增减（仅在任务开启进度条且有目标量时可用；钳位 [0, total]）。"""
    db_task = db.query(Task).filter(Task.id == task_id, scoped(Task, user)).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not db_task.show_progress or not db_task.progress_total:
        raise HTTPException(status_code=400, detail="该任务未开启进度条目标")
    db_task.progress_done = max(0, min(db_task.progress_total, (db_task.progress_done or 0) + int(req.delta)))
    db.commit()
    return {"id": db_task.id, "progress_done": db_task.progress_done, "progress_total": db_task.progress_total}


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
    except Exception:
        # E2E2-002 补漏：ai-generate 的 detail 曾透传上游 401 与服务商地址；原文只进服务端日志
        logging.getLogger(__name__).exception("任务 AI 生成失败")
        raise HTTPException(
            status_code=502, detail="AI 服务暂时不可用：请到「设置 → AI 服务」检查 API Key 与网络后重试。"
        ) from None
