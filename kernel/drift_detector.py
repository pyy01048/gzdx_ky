# -*- coding: utf-8 -*-
"""节奏漂移检测（落地方案 §4.3，纯函数）。

等号归属（验收规范 §2.2-1，入测试断言）：
- drift = -0.15      → on_track
- drift = -0.150001  → micro_adjust
- drift = -0.35      → micro_adjust
- drift = -0.350001  → recovery
冷启动保护：< min_days(3) 天数据 → insufficient_data，零触发；
planned=0 → no_plan，零触发。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from kernel.config_loader import DriftConfig

STATUS_INSUFFICIENT = "insufficient_data"
STATUS_NO_PLAN = "no_plan"
STATUS_ON_TRACK = "on_track"
STATUS_MICRO_ADJUST = "micro_adjust"
STATUS_RECOVERY = "recovery"


@dataclass(frozen=True)
class DayLedger:
    """study_calendar 出口 DTO（唯一口径）。"""

    date: str            # ISO 日期串 YYYY-MM-DD
    planned_min: int
    completed_min: int


@dataclass(frozen=True)
class DriftResult:
    drift: Optional[float]     # None = 无有效漂移值（冷启动/无计划）
    status: str
    window_days: int
    planned_avg: float
    completed_avg: float


def compute_drift(ledger: List[DayLedger], cfg: DriftConfig, *,
                  window_days: Optional[int] = None) -> DriftResult:
    """按滑动窗口均值计算漂移率并分带。

    Args:
        ledger: 逐日台账（按日期升序传入即可，内部取最近 window 天）。
        cfg: 冻结的漂移配置（带宽/窗口/最小天数）。
        window_days: 覆盖配置窗口（测试用），None 用 cfg.window_days。
    """
    win = window_days if window_days is not None else cfg.window_days
    recent = list(ledger[-win:]) if win > 0 else []
    if len(recent) < cfg.min_days:
        return DriftResult(drift=None, status=STATUS_INSUFFICIENT,
                           window_days=len(recent), planned_avg=0.0,
                           completed_avg=0.0)
    planned = sum(d.planned_min for d in recent) / len(recent)
    completed = sum(d.completed_min for d in recent) / len(recent)
    if planned == 0:
        return DriftResult(drift=0.0, status=STATUS_NO_PLAN,
                           window_days=len(recent), planned_avg=0.0,
                           completed_avg=completed)
    drift = (completed - planned) / planned   # 负值 = 落后
    if drift >= -cfg.on_track_band:
        status = STATUS_ON_TRACK
    elif drift >= -cfg.recovery_band:
        status = STATUS_MICRO_ADJUST
    else:
        status = STATUS_RECOVERY
    return DriftResult(drift=round(drift, 6), status=status,
                       window_days=len(recent),
                       planned_avg=round(planned, 4),
                       completed_avg=round(completed, 4))
