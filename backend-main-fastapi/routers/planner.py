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

from database import get_db
from models import (
    DailyPlan, WeekPlan, MonthPlan,
    EbbinghausItem, EarlyBirdRecord, PhasePlan,
)
from utils.timeutil import utcnow, to_naive_utc  # 统一 naive UTC 时间规范（P0-4）

router = APIRouter(prefix="/api/planner", tags=["planner"])


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


class EbbinghausCreate(BaseModel):
    content: str
    subject: Optional[str] = None
    learn_date: Optional[str] = None


class EarlyBirdCreate(BaseModel):
    date: str
    wake_time: Optional[str] = None
    sleep_time: Optional[str] = None
    note: Optional[str] = None


# --------------------------------------------------------------------------- #
# 日计划
# --------------------------------------------------------------------------- #
@router.get("/daily")
async def get_daily_plan(date: str, db: Session = Depends(get_db)):
    """获取指定日期的日计划。"""
    try:
        d = datetime.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，应为 YYYY-MM-DD")

    plan = db.query(DailyPlan).filter(DailyPlan.date == d).first()
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
async def create_or_update_daily_plan(data: DailyPlanCreate, db: Session = Depends(get_db)):
    """创建或更新日计划。"""
    try:
        d = datetime.date.fromisoformat(data.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    plan = db.query(DailyPlan).filter(DailyPlan.date == d).first()
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
async def get_daily_plans_range(start: str, end: str, db: Session = Depends(get_db)):
    """获取日期范围内的日计划列表。"""
    try:
        s = datetime.date.fromisoformat(start)
        e = datetime.date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    plans = (
        db.query(DailyPlan)
        .filter(DailyPlan.date >= s, DailyPlan.date <= e)
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
async def list_ebbinghaus(subject: str = None, db: Session = Depends(get_db)):
    """艾宾浩斯记忆表列表。"""
    q = db.query(EbbinghausItem)
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
            "review_1d": item.review_1d.isoformat() if item.review_1d else None,
            "review_7d": item.review_7d.isoformat() if item.review_7d else None,
            "review_15d": item.review_15d.isoformat() if item.review_15d else None,
        }
        for item in items
    ]


@router.post("/ebbinghaus")
async def create_ebbinghaus(data: EbbinghausCreate, db: Session = Depends(get_db)):
    """新增艾宾浩斯记忆条目，自动计算9个复习时间点。

    P0 修复：原来用 `datetime.datetime.now(datetime.UTC)` 得到 aware 时间，
    而 DB 列是 naive，后续 `/ebbinghaus/due` 里 `review_time <= now` 会抛
    `TypeError: can't compare offset-naive and offset-aware datetimes`。
    统一改用 utils.timeutil.utcnow()（naive UTC）。
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

    # 计算9个复习周期
    item = EbbinghausItem(
        seq=db.query(EbbinghausItem).count() + 1,
        learn_date=learn_dt,
        content=data.content,
        subject=data.subject,
        review_5min=learn_dt + datetime.timedelta(minutes=5),
        review_30min=learn_dt + datetime.timedelta(minutes=30),
        review_12h=learn_dt + datetime.timedelta(hours=12),
        review_1d=learn_dt + datetime.timedelta(days=1),
        review_2d=learn_dt + datetime.timedelta(days=2),
        review_4d=learn_dt + datetime.timedelta(days=4),
        review_7d=learn_dt + datetime.timedelta(days=7),
        review_15d=learn_dt + datetime.timedelta(days=15),
        review_1m=learn_dt + datetime.timedelta(days=30),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "message": "已添加，9个复习时间点已自动计算"}


@router.post("/ebbinghaus/{item_id}/review/{cycle}")
async def review_ebbinghaus(item_id: int, cycle: str, db: Session = Depends(get_db)):
    """打卡某个复习周期。"""
    item = db.query(EbbinghausItem).filter(EbbinghausItem.id == item_id).first()
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
    if not field:
        raise HTTPException(status_code=400, detail="无效的复习周期")

    setattr(item, field, now)
    # 如果完成了1个月复习，标记为已掌握
    if cycle == "1m":
        item.mastered = True
    db.commit()
    return {"id": item_id, "cycle": cycle, "message": "复习打卡成功"}


@router.delete("/ebbinghaus/{item_id}")
async def delete_ebbinghaus(item_id: int, db: Session = Depends(get_db)):
    """删除艾宾浩斯记忆条目。"""
    item = db.query(EbbinghausItem).filter(EbbinghausItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    db.delete(item)
    db.commit()
    return {"id": item_id, "message": "已删除"}


@router.get("/ebbinghaus/due")
async def get_due_ebbinghaus(db: Session = Depends(get_db)):
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

    items = db.query(EbbinghausItem).filter(EbbinghausItem.mastered == False).all()  # noqa: E712
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
async def list_earlybird(db: Session = Depends(get_db)):
    """早起打卡记录列表。"""
    records = db.query(EarlyBirdRecord).order_by(EarlyBirdRecord.date.desc()).limit(120).all()
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
async def create_earlybird(data: EarlyBirdCreate, db: Session = Depends(get_db)):
    """早起打卡。"""
    try:
        d = datetime.date.fromisoformat(data.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    record = db.query(EarlyBirdRecord).filter(EarlyBirdRecord.date == d).first()
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
            day_num=db.query(EarlyBirdRecord).count() + 1,
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
async def get_earlybird_streak(db: Session = Depends(get_db)):
    """获取连续早起天数统计。"""
    records = db.query(EarlyBirdRecord).order_by(EarlyBirdRecord.date.desc()).all()
    if not records:
        return {"current_streak": 0, "total_days": 0, "avg_wake_time": None}

    # 计算连续天数
    today = datetime.date.today()
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
async def get_month_plan(year: int, month: int, db: Session = Depends(get_db)):
    """获取月计划。"""
    plan = db.query(MonthPlan).filter(MonthPlan.year == year, MonthPlan.month == month).first()
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
async def create_or_update_month_plan(data: dict, db: Session = Depends(get_db)):
    """创建或更新月计划。"""
    year = data.get("year")
    month = data.get("month")
    if not year or not month:
        raise HTTPException(status_code=400, detail="缺少 year 或 month")

    plan = db.query(MonthPlan).filter(MonthPlan.year == year, MonthPlan.month == month).first()
    if plan:
        if "tasks" in data:
            plan.tasks = data["tasks"]
        if "completion" in data:
            plan.completion = data["completion"]
    else:
        plan = MonthPlan(year=year, month=month, tasks=data.get("tasks", {}), completion=data.get("completion", ""))
        db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, "message": "月计划已保存"}


@router.get("/week")
async def get_week_plan(week_start: str, db: Session = Depends(get_db)):
    """获取周计划。"""
    try:
        ws = datetime.date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    plan = db.query(WeekPlan).filter(WeekPlan.week_start == ws).first()
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
async def create_or_update_week_plan(data: dict, db: Session = Depends(get_db)):
    """创建或更新周计划。"""
    week_start = data.get("week_start")
    if not week_start:
        raise HTTPException(status_code=400, detail="缺少 week_start")
    try:
        ws = datetime.date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误")

    plan = db.query(WeekPlan).filter(WeekPlan.week_start == ws).first()
    if plan:
        if "tasks" in data:
            plan.tasks = data["tasks"]
        if "daily_records" in data:
            plan.daily_records = data["daily_records"]
        if "completion" in data:
            plan.completion = data["completion"]
    else:
        plan = WeekPlan(
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
async def list_phase_plans(db: Session = Depends(get_db)):
    """阶段复习表列表。"""
    plans = db.query(PhasePlan).order_by(PhasePlan.start_date.desc()).all()
    items = []
    for p in plans:
        total = db.execute(
            text("SELECT COUNT(*) FROM phase_daily_reviews WHERE phase_plan_id=:pid"),
            {"pid": p.id}).scalar() or 0
        done = db.execute(
            text("SELECT COUNT(*) FROM phase_daily_reviews WHERE phase_plan_id=:pid AND completed=1"),
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
async def create_phase_plan(data: dict, db: Session = Depends(get_db)):
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
async def get_phase_reviews(plan_id: int, db: Session = Depends(get_db)):
    """获取阶段复习每日打卡明细。"""
    plan = db.query(PhasePlan).filter(PhasePlan.id == plan_id).first()
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
async def check_phase_day(plan_id: int, day_num: int, db: Session = Depends(get_db)):
    """打卡阶段复习的某一天（写入 phase_daily_reviews 独立表）。"""
    plan = db.query(PhasePlan).filter(PhasePlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="阶段计划不存在")

    row = db.execute(
        text("SELECT id FROM phase_daily_reviews WHERE phase_plan_id=:pid AND day_num=:day"),
        {"pid": plan_id, "day": day_num}).fetchone()
    if row:
        db.execute(
            text("UPDATE phase_daily_reviews SET completed=1 WHERE id=:rid"),
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
        text("SELECT COUNT(*) FROM phase_daily_reviews WHERE phase_plan_id=:pid AND completed=1"),
        {"pid": plan_id}).scalar() or 0
    progress = round(done / total * 100, 1) if total else 0.0
    return {"id": plan_id, "day_num": day_num, "progress": progress, "message": "打卡成功"}
