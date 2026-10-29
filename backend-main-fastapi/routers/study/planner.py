# -*- coding: utf-8 -*-
"""学习计划表路由（V2.0 新增）。

包含：日计划、周/月计划、艾宾浩斯记忆表、早起打卡、阶段复习表。
"""

import datetime
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from database import get_db
from models import (
    DailyPlan, WeekPlan, MonthPlan,
    EbbinghausItem, EarlyBirdRecord, PhasePlan, User,
)
from utils.scope import scoped, owner_id  # B4 行级隔离：scoped 查询过滤 / owner_id 写入归属
from utils.security import current_user
from utils.timeutil import local_today, utcnow, to_naive_utc  # 统一 naive UTC 时间规范（P0-4）

router = APIRouter(prefix="/api/planner", tags=["planner"])

# 默认艾宾浩斯 9 周期：(列名, 展示名, 偏移分钟)
DEFAULT_EBBINGHAUS_CYCLES = [
    ("review_5min", "5分钟", 5),
    ("review_30min", "30分钟", 30),
    ("review_12h", "12小时", 12 * 60),
    ("review_1d", "1天", 24 * 60),
    ("review_2d", "2天", 2 * 24 * 60),
    ("review_4d", "4天", 4 * 24 * 60),
    ("review_7d", "7天", 7 * 24 * 60),
    ("review_15d", "15天", 15 * 24 * 60),
    ("review_1m", "1个月", 30 * 24 * 60),
]

# 列名 -> key（用于 review_times 的 key 字段）
CYCLE_KEY_BY_COLUMN = {col: col.replace("review_", "") for col, _, _ in DEFAULT_EBBINGHAUS_CYCLES}
# key -> 列名
COLUMN_BY_CYCLE_KEY = {v: k for k, v in CYCLE_KEY_BY_COLUMN.items()}


# --------------------------------------------------------------------------- #
# Pydantic Schemas
# --------------------------------------------------------------------------- #
class DailyPlanCreate(BaseModel):
    date: str
    tasks: Optional[dict] = None
    timeline: Optional[list] = None
    study_duration: Optional[int] = 0
    wasted_duration: Optional[int] = 0
    score: Optional[int] = 0
    summary: Optional[str] = None


class DailyPlanUpdate(BaseModel):
    tasks: Optional[dict] = None
    timeline: Optional[list] = None
    study_duration: Optional[int] = None
    wasted_duration: Optional[int] = None
    score: Optional[int] = None
    summary: Optional[str] = None


class EbbinghausCycle(BaseModel):
    """自定义复习周期点。offset_minutes 表示相对学习时间的偏移分钟数（1天=1440）。"""
    label: str
    offset_minutes: int


class EbbinghausCreate(BaseModel):
    content: str
    subject: Optional[str] = None
    learn_date: Optional[str] = None
    # 自定义复习节奏：不传则用默认 9 点（5min/30min/12h/1d/2d/4d/7d/15d/1m）。
    # 传了则完全按自定义周期生成复习时间点，并可手动修改每个点的时间。
    custom_cycles: Optional[list[EbbinghausCycle]] = None


class EbbinghausReviewTimeUpdate(BaseModel):
    """修改某个复习点的时间。"""
    key: str          # 周期 key（默认列名 review_5min 或自定义 c1/c2/...）
    review_time: str  # ISO 时间
    label: Optional[str] = None


class EbbinghausCyclesUpdate(BaseModel):
    """整体重排复习节奏：按新周期列表重新生成所有复习时间点。"""
    cycles: list[EbbinghausCycle]


class EarlyBirdCreate(BaseModel):
    date: str
    wake_time: Optional[str] = None
    sleep_time: Optional[str] = None
    note: Optional[str] = None


# --------------------------------------------------------------------------- #
# 日计划
# --------------------------------------------------------------------------- #
@router.get("/daily")
async def get_daily_plan(date: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取指定日期的日计划。"""
    try:
        d = datetime.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，应为 YYYY-MM-DD")

    plan = db.query(DailyPlan).filter(DailyPlan.date == d, scoped(DailyPlan, user)).first()
    if not plan:
        # 不存在则返回空模板
        return {
            "date": date,
            "days_to_exam": None,
            "tasks": {},
            "timeline": [],
            "study_duration": 0,
            "wasted_duration": 0,
            "score": 0,
            "summary": "",
            "exists": False,
        }
    return {
        "id": plan.id,
        "date": plan.date.isoformat(),
        "days_to_exam": plan.days_to_exam,
        "tasks": plan.tasks or {},
        "timeline": plan.timeline or [],
        "study_duration": plan.study_duration or 0,
        "wasted_duration": plan.wasted_duration or 0,
        "score": plan.score or 0,
        "summary": plan.summary or "",
        "exists": True,
    }


@router.post("/daily")
async def create_or_update_daily_plan(data: DailyPlanCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """创建或更新日计划。"""
    try:
        d = datetime.date.fromisoformat(data.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    plan = db.query(DailyPlan).filter(DailyPlan.date == d, scoped(DailyPlan, user)).first()
    if plan:
        if data.tasks is not None:
            plan.tasks = data.tasks
        if data.timeline is not None:
            plan.timeline = data.timeline
        if data.study_duration is not None:
            plan.study_duration = data.study_duration
        if data.wasted_duration is not None:
            plan.wasted_duration = data.wasted_duration
        if data.score is not None:
            plan.score = data.score
        if data.summary is not None:
            plan.summary = data.summary
    else:
        plan = DailyPlan(
            user_id=owner_id(user),  # B4：归属当前用户
            date=d,
            tasks=data.tasks or {},
            timeline=data.timeline or [],
            study_duration=data.study_duration or 0,
            wasted_duration=data.wasted_duration or 0,
            score=data.score or 0,
            summary=data.summary or "",
        )
        db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, "date": plan.date.isoformat(), "message": "日计划已保存"}


@router.get("/daily/range")
async def get_daily_plans_range(start: str, end: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取日期范围内的日计划列表。"""
    try:
        s = datetime.date.fromisoformat(start)
        e = datetime.date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    plans = (
        db.query(DailyPlan)
        .filter(DailyPlan.date >= s, DailyPlan.date <= e, scoped(DailyPlan, user))
        .order_by(DailyPlan.date.asc())
        .all()
    )
    return [
        {
            "id": p.id,
            "date": p.date.isoformat(),
            "study_duration": p.study_duration or 0,
            "score": p.score or 0,
            "summary": (p.summary or "")[:100],
        }
        for p in plans
    ]


# --------------------------------------------------------------------------- #
# 艾宾浩斯记忆表
# --------------------------------------------------------------------------- #
@router.get("/ebbinghaus")
async def list_ebbinghaus(subject: str = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """艾宾浩斯记忆表列表（含自定义节奏 review_times / cycle_config，前端动态渲染）。"""
    q = db.query(EbbinghausItem).filter(scoped(EbbinghausItem, user))
    if subject:
        q = q.filter(EbbinghausItem.subject == subject)
    items = q.order_by(EbbinghausItem.learn_date.desc()).limit(200).all()
    return [
        {
            "id": item.id,
            "seq": item.seq,
            "learn_date": item.learn_date.isoformat() if item.learn_date else None,
            "content": item.content,
            "subject": item.subject,
            "mastered": item.mastered,
            "review_times": item.review_times or [],
            "cycle_config": item.cycle_config or [],
            "review_1d": item.review_1d.isoformat() if item.review_1d else None,
            "review_7d": item.review_7d.isoformat() if item.review_7d else None,
            "review_15d": item.review_15d.isoformat() if item.review_15d else None,
        }
        for item in items
    ]


@router.post("/ebbinghaus")
async def create_ebbinghaus(data: EbbinghausCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """新增艾宾浩斯记忆条目。

    支持自定义复习节奏：data.custom_cycles 传入周期列表（label + offset_minutes），
    则按自定义周期生成复习时间点；不传则用默认 9 点（5min/30min/12h/1d/2d/4d/7d/15d/1m）。

    存储兼容：
    - review_times JSONB 保存实际复习时间点数组（前端动态渲染用）。
    - cycle_config JSONB 保存周期定义（前端编辑用）。
    - 默认九列 review_5min/.../1m 尽量回填（key 能映射到默认列名时），旧逻辑不崩。
    """
    now = utcnow()  # naive UTC，与 DB 的 DateTime 列对齐
    learn_dt = now
    if data.learn_date:
        try:
            learn_dt = datetime.datetime.fromisoformat(data.learn_date)
        except ValueError:
            pass
    # fromisoformat 可能解析出 aware（带 Z / +08:00），统一规整为 naive UTC
    learn_dt = to_naive_utc(learn_dt) or now

    # 确定周期定义：自定义 or 默认
    if data.custom_cycles:
        cycles = [(f"custom_{i}", c.label, int(c.offset_minutes)) for i, c in enumerate(data.custom_cycles, start=1)]
        cycle_config = [{"key": k, "label": label, "offset_minutes": off} for k, label, off in cycles]
    else:
        cycles = DEFAULT_EBBINGHAUS_CYCLES
        cycle_config = [{"key": CYCLE_KEY_BY_COLUMN[col], "label": label, "offset_minutes": off}
                         for col, label, off in DEFAULT_EBBINGHAUS_CYCLES]

    # 生成复习时间点
    review_times = []
    for col, label, offset_minutes in cycles:
        review_time = learn_dt + datetime.timedelta(minutes=offset_minutes)
        key = CYCLE_KEY_BY_COLUMN.get(col, f"custom_{col}") if col.startswith("review_") else col
        review_times.append({
            "key": key,
            "label": label,
            "time": review_time.isoformat(),
            "done": False,
        })

    # 默认九列回填（兼容旧逻辑）
    col_values = {}
    for col, label, offset_minutes in cycles:
        if col.startswith("review_") and hasattr(EbbinghausItem, col):
            col_values[col] = learn_dt + datetime.timedelta(minutes=offset_minutes)

    item = EbbinghausItem(
        user_id=owner_id(user),  # B4：归属当前用户
        seq=db.query(EbbinghausItem).filter(scoped(EbbinghausItem, user)).count() + 1,
        learn_date=learn_dt,
        content=data.content,
        subject=data.subject,
        review_times=review_times,
        cycle_config=cycle_config,
        **col_values,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "message": "已添加，复习时间点已按节奏生成（可手动修改每个复习点的时间）",
        "cycle_config": item.cycle_config,
        "review_times": item.review_times,
    }


@router.post("/ebbinghaus/{item_id}/review/{cycle}")
async def review_ebbinghaus(item_id: int, cycle: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """打卡某个复习周期（支持默认 9 点与自定义周期 key）。"""
    item = db.query(EbbinghausItem).filter(EbbinghausItem.id == item_id, scoped(EbbinghausItem, user)).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")

    now = utcnow()
    cycle_map = {
        "5min": "review_5min",
        "30min": "review_30min",
        "12h": "review_12h",
        "1d": "review_1d",
        "2d": "review_2d",
        "4d": "review_4d",
        "7d": "review_7d",
        "15d": "review_15d",
        "1m": "review_1m",
    }
    field = cycle_map.get(cycle)
    if field:
        setattr(item, field, now)
        # 默认节奏：完成1个月复习标记已掌握
        if cycle == "1m":
            item.mastered = True
    else:
        # 自定义周期：在 review_times 中标记该 key 为已打卡
        review_times = list(item.review_times or [])
        updated = False
        for rt in review_times:
            if rt.get("key") == cycle:
                rt["done"] = True
                rt["time"] = now.isoformat()
                updated = True
                break
        if not updated:
            raise HTTPException(status_code=400, detail="无效的复习周期 key")
        item.review_times = review_times
        flag_modified(item, "review_times")  # JSONB 原地修改需强制标记脏检查

    db.commit()
    return {"id": item_id, "cycle": cycle, "message": "复习打卡成功"}


@router.put("/ebbinghaus/{item_id}/review-time")
async def update_ebbinghaus_review_time(item_id: int, data: EbbinghausReviewTimeUpdate,
                                        db: Session = Depends(get_db), user: User = Depends(current_user)):
    """手动修改某个复习点的时间（默认 9 点或自定义周期均可）。"""
    item = db.query(EbbinghausItem).filter(EbbinghausItem.id == item_id, scoped(EbbinghausItem, user)).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")

    try:
        new_time = datetime.datetime.fromisoformat(data.review_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的时间格式")
    new_time = to_naive_utc(new_time) or new_time

    # 默认列映射
    cycle_map = {
        "5min": "review_5min",
        "30min": "review_30min",
        "12h": "review_12h",
        "1d": "review_1d",
        "2d": "review_2d",
        "4d": "review_4d",
        "7d": "review_7d",
        "15d": "review_15d",
        "1m": "review_1m",
    }
    field = cycle_map.get(data.key)
    if field:
        setattr(item, field, new_time)
        # 同步 review_times
        review_times = list(item.review_times or [])
        for rt in review_times:
            if rt.get("key") == data.key:
                rt["time"] = new_time.isoformat()
                break
        item.review_times = review_times
        flag_modified(item, "review_times")  # JSONB 原地修改需强制标记脏检查
    else:
        # 自定义 key
        review_times = list(item.review_times or [])
        updated = False
        for rt in review_times:
            if rt.get("key") == data.key:
                rt["time"] = new_time.isoformat()
                if data.label:
                    rt["label"] = data.label
                updated = True
                break
        if not updated:
            raise HTTPException(status_code=400, detail="无效的复习周期 key")
        item.review_times = review_times
        flag_modified(item, "review_times")  # JSONB 原地修改需强制标记脏检查

    db.commit()
    return {"id": item_id, "key": data.key, "review_time": new_time.isoformat(), "message": "复习时间已修改"}


@router.put("/ebbinghaus/{item_id}/cycles")
async def update_ebbinghaus_cycles(item_id: int, data: EbbinghausCyclesUpdate,
                                   db: Session = Depends(get_db), user: User = Depends(current_user)):
    """整体重排复习节奏：按新周期列表重新生成所有复习时间点（手动修改时间表）。"""
    item = db.query(EbbinghausItem).filter(EbbinghausItem.id == item_id, scoped(EbbinghausItem, user)).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")

    if not data.cycles:
        raise HTTPException(status_code=400, detail="周期列表不能为空")

    learn_dt = item.learn_date
    if learn_dt is not None and learn_dt.tzinfo is not None:
        learn_dt = learn_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)

    # 生成新周期定义 + 复习时间点
    cycle_config = []
    review_times = []
    col_values = {}
    for i, c in enumerate(data.cycles, start=1):
        key = f"custom_{i}"
        label = c.label
        offset = int(c.offset_minutes)
        cycle_config.append({"key": key, "label": label, "offset_minutes": offset})
        review_time = (learn_dt or utcnow()) + datetime.timedelta(minutes=offset)
        review_times.append({"key": key, "label": label, "time": review_time.isoformat(), "done": False})

    # 清空旧默认列，写入新列（尽量兼容默认列名，但自定义周期统一用 custom_N 避免歧义）
    for col, _, _ in DEFAULT_EBBINGHAUS_CYCLES:
        setattr(item, col, None)

    item.cycle_config = cycle_config
    item.review_times = review_times
    flag_modified(item, "review_times")  # 强制标记，确保 JSONB 新列表写入
    item.mastered = False
    db.commit()
    return {
        "id": item_id,
        "message": "复习节奏已重排，所有复习时间点已按新周期重新生成",
        "cycle_config": cycle_config,
        "review_times": review_times,
    }


@router.delete("/ebbinghaus/{item_id}")
async def delete_ebbinghaus(item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """删除艾宾浩斯记忆条目。"""
    item = db.query(EbbinghausItem).filter(EbbinghausItem.id == item_id, scoped(EbbinghausItem, user)).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    db.delete(item)
    db.commit()
    return {"id": item_id, "message": "已删除"}


@router.get("/ebbinghaus/due")
async def get_due_ebbinghaus(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取今日待复习的艾宾浩斯条目。

    P0 修复（两处）：
    1. `now` 改为 naive UTC（utils.timeutil.utcnow）—— DB 读回的
       `review_*` 列是 naive（tzinfo=None），原代码用 aware 的
       `datetime.UTC`，比较时抛
       `TypeError: can't compare offset-naive and offset-aware datetimes`。
    2. 原去重逻辑读的是 `{field}_done`（如 `review_1d_done`），
       但 `ebbinghaus_items` 表**根本没有这些列**，实测 `hasattr=False`，
       `getattr(..., None)` 永远返回 None → 条件恒真 → 打卡完成的周期
       仍会反复出现在待复习列表里（去重永久失效）。
       现改为：**用打卡时被写入的时间戳本身判断是否已完成**——
       打卡会把该周期的 `review_*` 字段更新为「打卡时刻」，
       而未打卡的周期保存的是「计划复习时刻」（learn_date + 间隔）。
       由于计划时刻恒早于打卡时刻，可用「该字段值是否已被改成打卡时间」
       来区分：若字段值 <= 计划基线（learn_date + 该周期间隔 + 容差），
       说明从未被打卡，视为待复习；否则视为已完成，跳过。
    3. `content[:100]` 未防 NULL：content 为 NULL 时 `None[:100]` 抛 TypeError。
    """
    now = utcnow()  # naive UTC

    # 周期定义：(字段名, 展示名, 相对 learn_date 的间隔)
    cycles = [
        ("review_5min", "5分钟", datetime.timedelta(minutes=5)),
        ("review_30min", "30分钟", datetime.timedelta(minutes=30)),
        ("review_12h", "12小时", datetime.timedelta(hours=12)),
        ("review_1d", "1天", datetime.timedelta(days=1)),
        ("review_2d", "2天", datetime.timedelta(days=2)),
        ("review_4d", "4天", datetime.timedelta(days=4)),
        ("review_7d", "7天", datetime.timedelta(days=7)),
        ("review_15d", "15天", datetime.timedelta(days=15)),
        ("review_1m", "1个月", datetime.timedelta(days=30)),
    ]

    items = db.query(EbbinghausItem).filter(EbbinghausItem.mastered == False, scoped(EbbinghausItem, user)).all()  # noqa: E712
    due = []
    for item in items:
        learn_dt = item.learn_date
        for field, label, offset in cycles:
            review_time = getattr(item, field, None)
            if review_time is None:
                continue
            # 规整为 naive，防止历史数据混入 aware 值导致比较抛错
            if review_time.tzinfo is not None:
                review_time = review_time.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            if review_time > now:
                continue  # 未到期

            # 判断该周期是否已打卡：
            # 未打卡 => review_time == learn_date + offset（计划时刻，误差内）
            # 已打卡 => review_time 被改写为打卡时刻（必然晚于计划时刻）
            is_done = False
            if learn_dt is not None:
                if learn_dt.tzinfo is not None:
                    learn_dt = learn_dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
                planned = learn_dt + offset
                # 容差 1 秒，吸收 SQLite 存储的精度/时区差异
                is_done = review_time > planned + datetime.timedelta(seconds=1)

            if is_done:
                continue  # 该周期已完成，看下一个周期

            raw_content = item.content or ""  # 防 NULL
            due.append({
                "id": item.id,
                "content": raw_content[:100],
                "subject": item.subject,
                "due_cycle": label,
                "due_time": review_time.isoformat(),
            })
            break  # 每个条目只返回最近的一个待复习周期
    return {"total": len(due), "items": due[:50]}


# --------------------------------------------------------------------------- #
# 早起打卡
# --------------------------------------------------------------------------- #
@router.get("/earlybird")
async def list_earlybird(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """早起打卡记录列表。"""
    records = db.query(EarlyBirdRecord).filter(scoped(EarlyBirdRecord, user)).order_by(EarlyBirdRecord.date.desc()).limit(120).all()
    return [
        {
            "id": r.id,
            "day_num": r.day_num,
            "date": r.date.isoformat(),
            "wake_time": r.wake_time.isoformat() if r.wake_time else None,
            "sleep_time": r.sleep_time.isoformat() if r.sleep_time else None,
            "note": r.note,
        }
        for r in records
    ]


@router.post("/earlybird")
async def create_earlybird(data: EarlyBirdCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """早起打卡。"""
    try:
        d = datetime.date.fromisoformat(data.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    record = db.query(EarlyBirdRecord).filter(EarlyBirdRecord.date == d, scoped(EarlyBirdRecord, user)).first()
    wake_t = datetime.time.fromisoformat(data.wake_time) if data.wake_time else None
    sleep_t = datetime.time.fromisoformat(data.sleep_time) if data.sleep_time else None

    if record:
        if wake_t:
            record.wake_time = wake_t
        if sleep_t:
            record.sleep_time = sleep_t
        if data.note is not None:
            record.note = data.note
    else:
        record = EarlyBirdRecord(
            user_id=owner_id(user),  # B4：归属当前用户
            day_num=db.query(EarlyBirdRecord).filter(scoped(EarlyBirdRecord, user)).count() + 1,
            date=d,
            wake_time=wake_t,
            sleep_time=sleep_t,
            note=data.note,
        )
        db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "date": record.date.isoformat(), "message": "早起打卡成功"}


@router.get("/earlybird/streak")
async def get_earlybird_streak(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取连续早起天数统计。"""
    records = db.query(EarlyBirdRecord).filter(scoped(EarlyBirdRecord, user)).order_by(EarlyBirdRecord.date.desc()).all()
    if not records:
        return {"current_streak": 0, "total_days": 0, "avg_wake_time": None}

    # 计算连续天数
    today = local_today()
    streak = 0
    for i, r in enumerate(records):
        expected = today - datetime.timedelta(days=i)
        if r.date == expected:
            streak += 1
        else:
            break

    # 平均起床时间
    wake_times = [r.wake_time for r in records if r.wake_time]
    avg_wake = None
    if wake_times:
        total_minutes = sum(t.hour * 60 + t.minute for t in wake_times)
        avg_min = total_minutes // len(wake_times)
        avg_wake = f"{avg_min // 60:02d}:{avg_min % 60:02d}"

    return {
        "current_streak": streak,
        "total_days": len(records),
        "avg_wake_time": avg_wake,
    }


# --------------------------------------------------------------------------- #
# 周/月计划
# --------------------------------------------------------------------------- #
@router.get("/month")
async def get_month_plan(year: int, month: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取月计划。"""
    plan = db.query(MonthPlan).filter(MonthPlan.year == year, MonthPlan.month == month, scoped(MonthPlan, user)).first()
    if not plan:
        return {"year": year, "month": month, "tasks": {}, "completion": "", "exists": False}
    return {
        "id": plan.id,
        "year": plan.year,
        "month": plan.month,
        "tasks": plan.tasks or {},
        "completion": plan.completion or "",
        "exists": True,
    }


@router.post("/month")
async def create_or_update_month_plan(data: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """创建或更新月计划。"""
    year = data.get("year")
    month = data.get("month")
    if not year or not month:
        raise HTTPException(status_code=400, detail="缺少 year 或 month")

    plan = db.query(MonthPlan).filter(MonthPlan.year == year, MonthPlan.month == month, scoped(MonthPlan, user)).first()
    if plan:
        if "tasks" in data:
            plan.tasks = data["tasks"]
        if "completion" in data:
            plan.completion = data["completion"]
    else:
        plan = MonthPlan(year=year, month=month, tasks=data.get("tasks", {}), completion=data.get("completion", ""),
                         user_id=owner_id(user))  # B4：归属当前用户
        db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, "message": "月计划已保存"}


@router.get("/week")
async def get_week_plan(week_start: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取周计划。"""
    try:
        ws = datetime.date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    plan = db.query(WeekPlan).filter(WeekPlan.week_start == ws, scoped(WeekPlan, user)).first()
    if not plan:
        return {"week_start": week_start, "tasks": {}, "daily_records": [], "exists": False}
    return {
        "id": plan.id,
        "week_start": plan.week_start.isoformat(),
        "tasks": plan.tasks or {},
        "daily_records": plan.daily_records or [],
        "completion": plan.completion or "",
        "exists": True,
    }


@router.post("/week")
async def create_or_update_week_plan(data: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """创建或更新周计划。"""
    week_start = data.get("week_start")
    if not week_start:
        raise HTTPException(status_code=400, detail="缺少 week_start")
    try:
        ws = datetime.date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    plan = db.query(WeekPlan).filter(WeekPlan.week_start == ws, scoped(WeekPlan, user)).first()
    if plan:
        if "tasks" in data:
            plan.tasks = data["tasks"]
        if "daily_records" in data:
            plan.daily_records = data["daily_records"]
        if "completion" in data:
            plan.completion = data["completion"]
    else:
        plan = WeekPlan(
            user_id=owner_id(user),  # B4：归属当前用户
            week_start=ws,
            tasks=data.get("tasks", {}),
            daily_records=data.get("daily_records", []),
            completion=data.get("completion", ""),
        )
        db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, "message": "周计划已保存"}


# --------------------------------------------------------------------------- #
# 阶段复习表
# --------------------------------------------------------------------------- #
@router.get("/phase")
async def list_phase_plans(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """阶段复习表列表。"""
    plans = db.query(PhasePlan).filter(scoped(PhasePlan, user)).order_by(PhasePlan.start_date.desc()).all()
    items = []
    for p in plans:
        total = db.execute(
            text("SELECT COUNT(*) FROM phase_daily_reviews WHERE phase_plan_id=:pid"),
            {"pid": p.id}).scalar() or 0
        done = db.execute(
            text("SELECT COUNT(*) FROM phase_daily_reviews WHERE phase_plan_id=:pid AND completed = TRUE"),
            {"pid": p.id}).scalar() or 0
        progress = round(done / total * 100, 1) if total else 0.0
        items.append({
            "id": p.id,
            "name": p.name,
            "start_date": p.start_date.isoformat(),
            "end_date": p.end_date.isoformat() if p.end_date else None,
            "cycle_days": p.cycle_days,
            "progress": progress,
            "task_count": len(p.tasks or []),
        })
    return items


@router.post("/phase")
async def create_phase_plan(data: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """创建阶段复习表。"""
    name = data.get("name")
    start_date = data.get("start_date")
    if not name or not start_date:
        raise HTTPException(status_code=400, detail="缺少 name 或 start_date")

    try:
        sd = datetime.date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    ed = None
    if data.get("end_date"):
        try:
            ed = datetime.date.fromisoformat(data["end_date"])
        except ValueError:
            pass

    plan = PhasePlan(
        user_id=owner_id(user),  # B4：归属当前用户
        name=name,
        start_date=sd,
        end_date=ed,
        cycle_days=data.get("cycle_days", 40),
        tasks=data.get("tasks", []),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    # 预生成 phase_daily_reviews 每日记录（表结构与模型对齐后由独立表承载）
    cycle = plan.cycle_days or 40
    created = 0
    for day in range(1, cycle + 1):
        d = sd + datetime.timedelta(days=day - 1)
        db.execute(
            text("INSERT INTO phase_daily_reviews (phase_plan_id, day_num, date, morning_reviews, evening_reviews, completed, created_at) "
                 "VALUES (:pid, :day, :dt, :m, :e, 0, :ca)"),
            {"pid": plan.id, "day": day, "dt": d.isoformat(), "m": "[]", "e": "[]",
             "ca": utcnow().strftime("%Y-%m-%d %H:%M:%S")})
        created += 1
    db.commit()
    return {"id": plan.id, "message": f"阶段复习表已创建（预生成 {created} 天打卡记录）"}


@router.get("/phase/{plan_id}/reviews")
async def get_phase_reviews(plan_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """获取阶段复习每日打卡明细。"""
    plan = db.query(PhasePlan).filter(PhasePlan.id == plan_id, scoped(PhasePlan, user)).first()
    if not plan:
        raise HTTPException(status_code=404, detail="阶段计划不存在")

    rows = db.execute(
        text("SELECT id, day_num, date, morning_reviews, evening_reviews, completed "
             "FROM phase_daily_reviews WHERE phase_plan_id=:pid ORDER BY day_num ASC"),
        {"pid": plan_id}).fetchall()
    result = []
    for r in rows:
        def _parse(v):
            if v is None:
                return []
            if isinstance(v, str):
                try:
                    return json.loads(v)
                except ValueError:
                    return []
            return v
        result.append({
            "id": r[0],
            "day_num": r[1],
            "date": r[2],
            "morning_reviews": _parse(r[3]),
            "evening_reviews": _parse(r[4]),
            "completed": bool(r[5]),
        })
    return {"plan_id": plan_id, "reviews": result, "total": len(result)}


@router.post("/phase/{plan_id}/check/{day_num}")
async def check_phase_day(plan_id: int, day_num: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """打卡阶段复习的某一天（写入 phase_daily_reviews 独立表）。"""
    plan = db.query(PhasePlan).filter(PhasePlan.id == plan_id, scoped(PhasePlan, user)).first()
    if not plan:
        raise HTTPException(status_code=404, detail="阶段计划不存在")

    row = db.execute(
        text("SELECT id FROM phase_daily_reviews WHERE phase_plan_id=:pid AND day_num=:day"),
        {"pid": plan_id, "day": day_num}).fetchone()
    if row:
        db.execute(
            text("UPDATE phase_daily_reviews SET completed = TRUE WHERE id=:rid"),
            {"rid": row[0]})
    else:
        db.execute(
            text("INSERT INTO phase_daily_reviews (phase_plan_id, day_num, date, morning_reviews, evening_reviews, completed, created_at) "
                 "VALUES (:pid, :day, :dt, :m, :e, 1, :ca)"),
            {"pid": plan_id, "day": day_num,
             "dt": (plan.start_date + datetime.timedelta(days=day_num - 1)).isoformat(),
             "m": "[]", "e": "[]",
             "ca": utcnow().strftime("%Y-%m-%d %H:%M:%S")})
    db.commit()

    total = db.execute(
        text("SELECT COUNT(*) FROM phase_daily_reviews WHERE phase_plan_id=:pid"),
        {"pid": plan_id}).scalar() or 0
    done = db.execute(
        text("SELECT COUNT(*) FROM phase_daily_reviews WHERE phase_plan_id=:pid AND completed = TRUE"),
        {"pid": plan_id}).scalar() or 0
    progress = round(done / total * 100, 1) if total else 0.0
    return {"id": plan_id, "day_num": day_num, "progress": progress, "message": "打卡成功"}
