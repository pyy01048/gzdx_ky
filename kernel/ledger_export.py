# -*- coding: utf-8 -*-
"""study_calendar ledger DTO 出口（patch 形式交付，不改动快照原文件）。

背景：services/study_calendar.py 的 day_ledger(db, ...) 直接返回 ORM/DB 聚合
结果，kernel.drift_detector.compute_drift 需要纯 DTO 输入。S0 硬约束不允许
重构快照现有文件，因此以**新增适配模块**提供 ledger DTO 出口：

    from kernel.ledger_export import export_ledger
    days = export_ledger(day_rows)          # → list[DayLedger]
    result = compute_drift(days, cfg.rules.drift)

shell 侧接线方式（S1 落地时一行调用）：把 study_calendar.day_ledger 返回的
逐日行（含 date/planned_minutes/focus_minutes 等字段）传入本函数即可；
本模块零 DB、零 ORM——只接受普通对象/dict/MappedSeq，鸭子类型取字段。

口径对齐快照 study_calendar：completed_min 取"有效专注分钟"（focus），
planned_min 取当日计划总时长；缺失字段按 0 计但保留日期行（G2 由
compute_drift 的 no_plan/insufficient_data 状态显式化，不在这里吞掉）。
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Iterable, List, Optional

from kernel.drift_detector import DayLedger


def _get(row: Any, *names: str, default: float = 0.0) -> float:
    """dict / dataclass / ORM Row 通用取字段；依次尝试候选名。"""
    for n in names:
        if isinstance(row, Dict):
            if n in row and row[n] is not None:
                return float(row[n])
        else:
            v = getattr(row, n, None)
            if v is not None:
                return float(v)
    return default


def _date_str(row: Any) -> str:
    if isinstance(row, Dict):
        d = row.get("date") or row.get("day")
    else:
        d = getattr(row, "date", None) or getattr(row, "day", None)
    if d is None:
        raise ValueError(f"ledger 行缺少 date 字段: {row!r}")
    if isinstance(d, (datetime.date, datetime.datetime)):
        return d.isoformat()[:10]
    return str(d)[:10]


def export_ledger(day_rows: Iterable[Any], *,
                  planned_fields: tuple = ("planned_minutes", "planned_min",
                                           "plan_minutes"),
                  completed_fields: tuple = ("focus_minutes", "completed_min",
                                             "completed_minutes")) -> List[DayLedger]:
    """day_ledger 输出行 → kernel DayLedger DTO 列表（纯函数）。

    Args:
        day_rows: study_calendar.day_ledger 返回的逐日行（dict/dataclass/Row 均可）。
        planned_fields/completed_fields: 字段候选名（适配不同版本 shell 输出）。

    Returns:
        list[DayLedger]，可直接喂给 drift_detector.compute_drift。
    """
    out: List[DayLedger] = []
    for row in day_rows:
        out.append(DayLedger(
            date=_date_str(row),
            planned_min=int(_get(row, *planned_fields)),
            completed_min=int(_get(row, *completed_fields)),
        ))
    return out


def export_ledger_from_activities(activities: Iterable[Any],
                                  planned_by_date: Optional[Dict[str, int]] = None
                                  ) -> List[DayLedger]:
    """便捷入口：DayActivity 序列 + 可选计划映射 → DayLedger。

    planned_by_date 缺省时计划为 0（compute_drift 将给出 no_plan 显式状态，
    绝不伪造计划量——G2 缺失显式化）。
    """
    pb = planned_by_date or {}
    out: List[DayLedger] = []
    for a in activities:
        ds = _date_str(a) if not isinstance(a, Dict) else str(a.get("date"))[:10]
        focus = _get(a, "focus_minutes", "focus_min")
        out.append(DayLedger(date=ds,
                             planned_min=int(pb.get(ds, 0)),
                             completed_min=int(focus)))
    return out
