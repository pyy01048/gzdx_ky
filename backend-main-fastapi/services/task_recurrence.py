# -*- coding: utf-8 -*-
"""W3 循环任务展开（/api/tasks/calendar 的权威口径，后端单源）。

循环规则存在 ``tasks.recurrence`` JSON：

    {
      "freq": "none|daily|workdays|weekly|monthly|specific|custom|ebbinghaus",
      "weekdays": [0..6],           # weekly：周几（0=周一 … 5=周六 … 6=周日；"每周六"=[5]）
      "interval": N,                # custom：每 N 天一次（>=1）
      "dates": ["YYYY-MM-DD", ...], # specific：显式日期清单（"特定日期"）
      "until": "YYYY-MM-DD"         # 可选循环截止（与 tasks.end_date 取更早者）
    }

锚点日 = ``start_date``，缺省回落 ``due_date``，再缺省不落任何发生日
（宁可不显示，不凭空造一天——与"诚实初始化"原则一致）。

诚实边界：
* ``ebbinghaus`` 只展开**日粒度**复习点（锚点后 1/2/4/7/15/30 天 + 锚点当天）。
  5min/30min/12h 这类日内分钟级点位不属于日期日历，归 planner 的
  ``EbbinghausItem`` 分钟级表，这里不硬凑。
* ``remind`` 字段只存储展示（时间点/时间段），**未接系统推送**。
* 前端离线模式在 ``frontend/src/utils/recurrence.js`` 有同口径 JS 实现，
  两处必须同步改；后端口径由 tests/test_tasks_w3.py 钉死。
"""

from __future__ import annotations

import calendar as _calendar
import datetime
from typing import Any, Dict, Iterable, List, Optional

#: 艾宾浩斯日粒度偏移（天），与 planner.DEFAULT_EBBINGHAUS_CYCLES 的"天级"点子集一致
EBBINGHAUS_DAY_OFFSETS = [0, 1, 2, 4, 7, 15, 30]

VALID_FREQS = {"none", "daily", "workdays", "weekly", "monthly", "specific", "custom", "ebbinghaus"}

#: 单次展开的硬上限（防御病态区间/病态 interval；日历接口本身已限制查询跨度）
MAX_OCCURRENCES = 3660


def is_recurring(task: Any) -> bool:
    """任务是否为循环任务（recurrence.freq 有效且不是 none）。"""
    rec = getattr(task, "recurrence", None)
    return bool(isinstance(rec, dict) and rec.get("freq") in (VALID_FREQS - {"none"}))


def _parse_date(value: Any) -> Optional[datetime.date]:
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _clamp_day(year: int, month: int, day: int) -> int:
    return min(day, _calendar.monthrange(year, month)[1])


def expand_task_dates(task: Any, range_start: datetime.date, range_end: datetime.date) -> List[datetime.date]:
    """把单个任务展开成 [range_start, range_end] 内的发生日期（升序、去重）。"""
    rec = getattr(task, "recurrence", None)
    freq = rec.get("freq") if isinstance(rec, dict) else None

    anchor = _parse_date(getattr(task, "start_date", None)) or _parse_date(getattr(task, "due_date", None))
    end = _parse_date(getattr(task, "end_date", None))
    if isinstance(rec, dict):
        until = _parse_date(rec.get("until"))
        if until and (end is None or until < end):
            end = until

    # 非循环 / 无有效规则：退化为"截止日单日任务"（历史口径 due_date）
    if freq not in VALID_FREQS or freq == "none" or freq is None:
        due = _parse_date(getattr(task, "due_date", None)) or anchor
        if due and range_start <= due <= range_end:
            return [due]
        return []

    if anchor is None:
        return []

    lo = max(anchor, range_start)
    hi = min(end, range_end) if end else range_end
    if lo > hi:
        return []

    out: List[datetime.date] = []

    if freq == "daily":
        d = lo
        while d <= hi and len(out) < MAX_OCCURRENCES:
            out.append(d)
            d += datetime.timedelta(days=1)
    elif freq == "workdays":
        d = lo
        while d <= hi and len(out) < MAX_OCCURRENCES:
            if d.weekday() < 5:
                out.append(d)
            d += datetime.timedelta(days=1)
    elif freq == "weekly":
        weekdays = _weekdays_of(rec)
        d = lo
        while d <= hi and len(out) < MAX_OCCURRENCES:
            if d.weekday() in weekdays:
                out.append(d)
            d += datetime.timedelta(days=1)
    elif freq == "monthly":
        d = lo
        while d <= hi and len(out) < MAX_OCCURRENCES:
            if d.day == _clamp_day(d.year, d.month, anchor.day):
                out.append(d)
            d += datetime.timedelta(days=1)
    elif freq == "specific":
        dates = rec.get("dates")
        if isinstance(dates, str):
            dates = [s.strip() for s in dates.split(",")]
        for raw in dates or []:
            d = _parse_date(raw)
            if d and anchor <= d <= (end or d) and range_start <= d <= range_end:
                out.append(d)
        out = sorted(set(out))
    elif freq == "custom":
        try:
            interval = int(rec.get("interval") or 0)
        except (TypeError, ValueError):
            interval = 0
        if interval < 1:
            interval = 1
        # 从锚点对齐步长，避免"窗口滑动导致每隔几天错位"
        k = (lo - anchor).days // interval
        d = anchor + datetime.timedelta(days=k * interval)
        while d <= hi and len(out) < MAX_OCCURRENCES:
            if d >= lo:
                out.append(d)
            d += datetime.timedelta(days=interval)
    elif freq == "ebbinghaus":
        for off in EBBINGHAUS_DAY_OFFSETS:
            d = anchor + datetime.timedelta(days=off)
            if lo <= d <= hi:
                out.append(d)
        out.sort()

    return out


def _weekdays_of(rec: Dict[str, Any]) -> Iterable[int]:
    raw = rec.get("weekdays")
    if raw is None and rec.get("weekday") is not None:
        raw = [rec.get("weekday")]
    out = set()
    for v in raw or []:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if 0 <= iv <= 6:
            out.add(iv)
    return out or {0}


def normalize_recurrence(rec: Optional[dict]) -> Optional[dict]:
    """入库前规整循环规则：非法 freq 直接拒绝（400 由路由层抛），字段裁剪。"""
    if rec is None:
        return None
    if not isinstance(rec, dict):
        raise ValueError("recurrence 必须是对象")
    freq = str(rec.get("freq") or "none").strip().lower()
    if freq not in VALID_FREQS:
        raise ValueError(f"不支持的循环类型：{freq}")
    if freq == "none":
        return {"freq": "none"}
    clean: Dict[str, Any] = {"freq": freq}
    if freq == "weekly":
        clean["weekdays"] = sorted({int(v) for v in _weekdays_of(rec)})
    if freq == "custom":
        try:
            clean["interval"] = max(1, int(rec.get("interval") or 1))
        except (TypeError, ValueError):
            clean["interval"] = 1
    if freq == "specific":
        dates = rec.get("dates")
        if isinstance(dates, str):
            dates = [s.strip() for s in dates.split(",")]
        parsed = sorted({d.isoformat() for d in map(_parse_date, dates or []) if d})
        if not parsed:
            raise ValueError("特定日期循环至少给出一个有效日期")
        clean["dates"] = parsed
    until = _parse_date(rec.get("until"))
    if until:
        clean["until"] = until.isoformat()
    return clean


def normalize_remind(remind: Optional[dict]) -> Optional[dict]:
    """规整提醒：只认 point（时间点 HH:MM）/ range（时间段 HH:MM-HH:MM），非法抛错。"""
    if remind is None:
        return None
    if not isinstance(remind, dict):
        raise ValueError("remind 必须是对象")
    rtype = str(remind.get("type") or "").strip().lower()
    if rtype in ("", "none", "off"):
        return None

    def _hm(value: Any) -> Optional[str]:
        s = str(value or "").strip()
        try:
            t = datetime.time.fromisoformat(s)
        except ValueError:
            return None
        return t.strftime("%H:%M")

    if rtype == "point":
        t = _hm(remind.get("time"))
        if not t:
            raise ValueError("时间点提醒需要合法的 time（HH:MM）")
        return {"type": "point", "time": t}
    if rtype == "range":
        s, e = _hm(remind.get("start")), _hm(remind.get("end"))
        if not s or not e:
            raise ValueError("时间段提醒需要合法的 start/end（HH:MM）")
        if s > e:
            raise ValueError("时间段提醒的结束不能早于开始")
        return {"type": "range", "start": s, "end": e}
    raise ValueError(f"不支持的提醒类型：{rtype}")
