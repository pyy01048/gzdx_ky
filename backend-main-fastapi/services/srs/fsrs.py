# -*- coding: utf-8 -*-
"""FSRS（Free Spaced Repetition Scheduler）轻量实现。

目标：让单词 / 卡片 / 错题 / 知识点共用同一套调度表 review_schedules。
- 四档评分：1=Again 2=Hard 3=Good 4=Easy
- 维护 stability（稳定度）、difficulty（难度）、state（新/学习/复习/重学）
- 目标保留率默认 0.9；90% 时下次间隔约等于稳定度（天）
- 公式基于 FSRS-4.5 的公开参数；SM-2 字段保留为兼容快照

注意：这里不追求与 py-fsrs 数值完全一致，但遵循同一记忆曲线与更新方向；
后续如需严格对齐，可替换 W 参数与 update 公式，不动调用方。
"""
from __future__ import annotations

import datetime
import math
from typing import Any, Optional

from sqlalchemy.orm import Session

from models import ReviewSchedule
from utils.timeutil import utcnow

# FSRS-4.5 默认参数
W = [
    0.4872, 1.4003, 3.7145, 13.8206,  # 初始稳定度（Again/Hard/Good/Easy）
    5.1618, 1.2298,                    # 初始难度
    0.8975, 0.031,                     # 难度更新 / 均值回归
    1.6474, 0.1367, 1.0461,            # 稳定度增长
    2.1072, 0.0793, 0.3246, 1.587,     # 遗忘后的稳定度
    0.2272, 2.8755,                    # Hard 惩罚 / Easy 奖励
]

DECAY = -0.5
FACTOR = 19.0 / 81.0
DEFAULT_RETENTION = 0.9

STATE_NEW, STATE_LEARNING, STATE_REVIEW, STATE_RELEARNING = 0, 1, 2, 3


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def retrievability(elapsed_days: float, stability: float) -> float:
    """当前可提取概率 R(t)。"""
    if not stability or stability <= 0:
        return 0.0
    return (1.0 + FACTOR * max(0.0, elapsed_days) / stability) ** DECAY


def interval_from_stability(stability: float, retention: float = DEFAULT_RETENTION) -> int:
    """由稳定度反解间隔天数：90% 保留率时约等于 stability。"""
    s = max(0.1, float(stability or 0.1))
    r = _clamp(float(retention or DEFAULT_RETENTION), 0.7, 0.99)
    days = s / FACTOR * (r ** (1.0 / DECAY) - 1.0)
    return int(_clamp(round(days), 1, 365))


def initial_difficulty(rating: int) -> float:
    return _clamp(W[4] - (rating - 3) * W[5], 1.0, 10.0)


def next_state(
    *,
    stability: Optional[float],
    difficulty: Optional[float],
    rating: int,
    elapsed_days: float,
    had_history: bool,
) -> dict[str, Any]:
    """根据本次评分计算新的 FSRS 状态。"""
    g = int(_clamp(int(rating or 3), 1, 4))

    if not had_history or not stability:
        s = W[g - 1]
        d = initial_difficulty(g)
        state = STATE_LEARNING if g < 3 else STATE_REVIEW
        return {
            "stability": round(s, 3),
            "difficulty": round(d, 3),
            "retrievability": 0.0,
            "state": state,
            "interval_days": 1 if g == 1 else interval_from_stability(s),
            "lapses": 1 if g == 1 else 0,
        }

    s_old = max(0.1, float(stability))
    d_old = _clamp(float(difficulty or initial_difficulty(g)), 1.0, 10.0)
    r = retrievability(elapsed_days, s_old)

    # 难度：先按评分调整，再向初始难度均值回归
    d_new = d_old - W[6] * (g - 3)
    d_new = W[7] * initial_difficulty(4) + (1 - W[7]) * d_new
    d_new = _clamp(d_new, 1.0, 10.0)

    if g == 1:
        # 遗忘：稳定度回落到一个与难度相关的低值
        s_new = W[11] * (d_new ** -W[12]) * (((s_old + 1) ** W[13]) - 1) * math.exp(W[14] * (1 - r))
        s_new = max(0.1, min(s_new, s_old))
        interval = 1
        lapses = 1
        state = STATE_RELEARNING if s_old > 1 else STATE_LEARNING
    else:
        hard_penalty = W[15] if g == 2 else 1.0
        easy_bonus = W[16] if g == 4 else 1.0
        s_new = s_old * (
            1
            + math.exp(W[8])
            * (11 - d_new)
            * (s_old ** -W[9])
            * (math.exp((1 - r) * W[10]) - 1)
            * hard_penalty
            * easy_bonus
        )
        s_new = _clamp(s_new, 0.1, 36500.0)
        interval = interval_from_stability(s_new)
        lapses = 0
        state = STATE_REVIEW

    return {
        "stability": round(s_new, 3),
        "difficulty": round(d_new, 3),
        "retrievability": round(r, 3),
        "state": state,
        "interval_days": interval,
        "lapses": lapses,
    }


def schedule(
    db: Session,
    *,
    item_type: str,
    item_id: int,
    rating: int,
    now: Optional[datetime.datetime] = None,
    commit: bool = False,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    """读写 review_schedules，返回本次 FSRS 调度结果。

    B4 行级隔离：``user_id`` 传入时按用户过滤既有调度行、创建时落归属用户
    （review_schedules 的唯一键已放宽为 (user_id, item_type, item_id)，同一
    条目各用户独立排程）；不传（默认 None）保持旧行为——不加过滤、创建 NULL，
    兼容尚未接线的调用方。调用方（路由层）一律传 ``owner_id(user)``。
    """
    now = now or utcnow()
    sched_q = (
        db.query(ReviewSchedule)
        .filter(ReviewSchedule.item_type == item_type, ReviewSchedule.item_id == int(item_id))
    )
    if user_id is not None:
        # 同一 item 的排程按用户隔离，避免读到/覆写他人的调度状态
        sched_q = sched_q.filter(ReviewSchedule.user_id == user_id)
    row = sched_q.first()
    had_history = bool(row and row.last_reviewed_at and (row.stability or row.interval_days))
    elapsed = 0.0
    if row and row.last_reviewed_at:
        elapsed = max(0.0, (now - row.last_reviewed_at).total_seconds() / 86400.0)

    stability = row.stability if row else None
    difficulty = row.difficulty if row else None
    if row and stability is None and (row.interval_days or 0) > 0:
        # 历史 SM-2 记录热启动：90% 保留率下 interval ≈ stability，
        # 难度由 ease_factor 反推（EF 越高越容易，FSRS 难度越低）。
        # 否则回填过的老用户第一次复习会被当成新卡，间隔从 4 天重来。
        stability = max(0.5, float(row.interval_days))
        ef = _clamp(float(row.ease_factor or 2.5), 1.3, 3.5)
        difficulty = _clamp(10.0 - (ef - 1.3) / 2.2 * 8.0, 1.0, 10.0)

    out = next_state(
        stability=stability,
        difficulty=difficulty,
        rating=rating,
        elapsed_days=elapsed,
        had_history=had_history,
    )

    if not row:
        # user_id=None 时落 NULL（旧行为）；传入时随用户归属
        row = ReviewSchedule(item_type=item_type, item_id=int(item_id), user_id=user_id)
        db.add(row)
        db.flush()

    row.algorithm = "fsrs"
    row.stability = out["stability"]
    row.difficulty = out["difficulty"]
    row.retrievability = out["retrievability"]
    row.state = out["state"]
    row.interval_days = out["interval_days"]
    row.repetitions = (row.repetitions or 0) + 1 if int(rating) >= 3 else 0
    row.lapses = (row.lapses or 0) + out["lapses"]
    row.last_reviewed_at = now
    row.next_review_at = now + datetime.timedelta(days=out["interval_days"])
    if commit:
        db.commit()

    return {
        "item_type": item_type,
        "item_id": int(item_id),
        "algorithm": "fsrs",
        **out,
        "due": row.next_review_at.isoformat() if row.next_review_at else None,
    }


def rating_from_grade(grade: Optional[int]) -> int:
    """SM-2 0-5 评分 → FSRS 四档。

    SM-2 与 FSRS 的分档语义并不等价：
      SM-2 <3 表示没记住（Again）；3 = 想起但很吃力（Hard）；
      4 = 想起但需努力（Good）；5 = 脱口而出（Easy）。
    直接按数值透传会把「Hard(3)」错记成 FSRS Good(3)，
    导致难度偏低、间隔被拉长，这里显式对齐。
    """
    try:
        g = int(grade)
    except (TypeError, ValueError):
        return 3
    if g <= 2:
        return 1
    if g == 3:
        return 2
    if g == 4:
        return 3
    return 4


def rating_from_result(result: Optional[str]) -> int:
    """旧三档结果 → FSRS 四档。"""
    return {"forgotten": 1, "fuzzy": 2, "mastered": 4}.get(str(result or ""), 3)
