# -*- coding: utf-8 -*-
"""FSRS 调度适配（落地方案 §4.1，签名级实现）。

S0 边界：本模块是**内核侧纯函数实现**，不做 shell 切流（S1 才委托
ReviewScheduler）。依赖 py-fsrs（fsrs>=6）＋标准库；时间一律 naive UTC。

公式基准（总方案 §5.1）：R(t,S) = (1 + 19/81 · t/S)^(-0.5)。
"""
from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from fsrs import Rating, Scheduler, State as FsrsState
from fsrs import Card as FsrsCard
from fsrs import ReviewLog as FsrsReviewLog

from kernel.config_loader import FsrsConfig

_R_COEF = 19.0 / 81.0


@dataclass(frozen=True)
class CardState:
    """与 ORM 解耦的卡片 DTO。"""

    card_id: str
    kind: str                       # word | flashcard | error | task
    stability: float
    difficulty: float
    due: datetime.datetime          # naive UTC
    last_review: Optional[datetime.datetime]  # naive UTC | None
    reps: int
    lapses: int
    mastered: bool = False
    learning: bool = False          # FSRS state==Learning（新卡首间隔口径用）
    legacy: Optional[dict] = None   # {quality,repetitions,interval_days,ef} 迁移期保留


@dataclass(frozen=True)
class ReviewLogDTO:
    """ReviewLog 全字段（第一天就完整保留；duration 毫秒必录）。"""

    card_id: str
    rating: int
    review_ts: datetime.datetime     # naive UTC
    review_duration_ms: Optional[int]
    state: int
    stability: float
    difficulty: float
    elapsed_days: int
    scheduled_days: int


def _clamp(lo: float, hi: float, v: float) -> float:
    return max(lo, min(hi, v))


def from_legacy(quality: int, repetitions: int, interval_days: int,
                ef: float, *, now: Optional[datetime.datetime] = None) -> CardState:
    """SM-2 → FSRS 初始估算（首版保守，影子期校准）：
    S_init = max(0.5, interval_days)；D_init = clamp(1, 10, 10-(ef-1.3)*4)。
    lapses 由 quality<3 历史推算（此处只有最近一次 quality，回填脚本统计全史）。"""
    t0 = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    s_init = max(0.5, float(interval_days))
    d_init = _clamp(1.0, 10.0, 10.0 - (ef - 1.3) * 4.0)
    lapses = 1 if quality < 3 else 0
    due = t0 + datetime.timedelta(days=max(1, int(round(s_init))))
    return CardState(
        card_id="", kind="word", stability=s_init, difficulty=d_init,
        due=due, last_review=None, reps=int(repetitions), lapses=lapses,
        mastered=(repetitions >= 5 and interval_days >= 15),
        learning=False,
        legacy={"quality": int(quality), "repetitions": int(repetitions),
                "interval_days": int(interval_days), "ef": float(ef)},
    )


def rating_from_quality(q: int, cfg: FsrsConfig) -> Rating:
    """SM-2 quality 0-5 → FSRS Rating：0-2→Again, 3→Hard(可配 Good),
    4→Good, 5→Good（默认）/Easy（配置 familiar_maps_to）。"""
    if not 0 <= q <= 5:
        raise ValueError(f"quality 必须在 0-5: {q!r}")
    if q <= 2:
        return Rating.Again
    if q == 3:
        return Rating.Good if cfg.impression_maps_to == "Good" else Rating.Hard
    if q == 4:
        return Rating.Good
    return Rating.Easy if cfg.familiar_maps_to == "Easy" else Rating.Good


def rating_from_ui(level: str, cfg: FsrsConfig) -> Rating:
    """三档 UI：陌生→Again、有印象→Hard（可配 Good）、熟悉→Good（可配 Easy）。"""
    if level == "陌生":
        return Rating.Again
    if level == "有印象":
        return Rating.Good if cfg.impression_maps_to == "Good" else Rating.Hard
    if level == "熟悉":
        return Rating.Easy if cfg.familiar_maps_to == "Easy" else Rating.Good
    raise ValueError(f"未知 UI 档位: {level!r}（可用: 陌生|有印象|熟悉）")


def recall_prob(elapsed_days: float, stability: float) -> float:
    """FSRS 幂律遗忘曲线 R(t,S) = (1 + 19/81 · t/S)^(-0.5)。"""
    if stability <= 0:
        raise ValueError(f"stability 必须为正: {stability!r}")
    t = max(0.0, float(elapsed_days))
    return (1.0 + _R_COEF * t / float(stability)) ** -0.5


def _utc(dt: datetime.datetime) -> datetime.datetime:
    """naive UTC → py-fsrs 要求的 aware-UTC（kernel 对外口径仍是 naive）。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _to_fsrs_card(state: CardState) -> FsrsCard:
    card = FsrsCard()
    card.card_id = abs(hash(state.card_id)) % (2**62) + 1
    card.state = FsrsState.Learning if state.learning else FsrsState.Review
    card.step = 0
    card.stability = max(0.1, state.stability)
    card.difficulty = _clamp(1.0, 10.0, state.difficulty)
    card.due = _utc(state.due)
    card.last_rating = Rating.Good
    card.reps = state.reps
    card.lapses = state.lapses
    card.learning_steps = []
    card.relearning_steps = []
    card.scheduled_days = 0
    return card


def review(state: CardState, rating: Rating, now: datetime.datetime,
           duration_ms: Optional[int],
           cfg: Optional[FsrsConfig] = None) -> Tuple[CardState, ReviewLogDTO]:
    """委托 fsrs.Scheduler.review_card，全字段落日志。

    V12 口径：复习后新卡（reps==0 且 Again）首间隔 ≥ first_interval_min_days。
    now 必须 naive UTC（aware 输入显式拒绝）。
    """
    if now.tzinfo is not None:
        raise ValueError("now 必须是 naive UTC datetime（P0-4 红线）")
    sched = Scheduler(enable_fuzzing=False)
    card = _to_fsrs_card(state)
    elapsed_days = max(0, (now - (state.last_review or now)).days)
    new_card, log = sched.review_card(card, rating, _utc(now))
    due = new_card.due
    if due.tzinfo is not None:      # py-fsrs 返回 aware-UTC → 折回 naive
        due = due.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    min_days = cfg.first_interval_min_days if cfg else 1
    if state.reps == 0 and (due - now).total_seconds() < min_days * 86400:
        due = now + datetime.timedelta(days=min_days)
    out_state = CardState(
        card_id=state.card_id, kind=state.kind,
        stability=float(new_card.stability), difficulty=float(new_card.difficulty),
        due=due, last_review=now, reps=int(new_card.reps),
        lapses=int(new_card.lapses), mastered=state.mastered,
        learning=bool(new_card.state == FsrsState.Learning),
        legacy=state.legacy)
    dto = ReviewLogDTO(
        card_id=state.card_id, rating=int(rating), review_ts=now,
        review_duration_ms=duration_ms, state=int(new_card.state),
        stability=float(new_card.stability), difficulty=float(new_card.difficulty),
        elapsed_days=int(getattr(log, "elapsed_days", elapsed_days) or 0),
        scheduled_days=int(getattr(log, "scheduled_days", 0) or 0))
    return out_state, dto


def _risk_key(state: CardState, now: datetime.datetime):
    overdue_days = max(0.0, (now - state.due).total_seconds() / 86400.0)
    r = recall_prob(overdue_days, state.stability)
    return (r, -overdue_days, state.card_id)


def queue(states: List[CardState], now: datetime.datetime, cfg: FsrsConfig,
          *, quota_new: Optional[int] = None,
          quota_review: Optional[int] = None) -> List[CardState]:
    """到期队列：过滤 mastered → R 升序（最危险优先）→ 逾期天数降序 →
    配额裁剪（新卡/复习分池，超配额顺延不丢弃）。"""
    if now.tzinfo is not None:
        raise ValueError("now 必须是 naive UTC datetime")
    qn = cfg.queue_quota_new if quota_new is None else quota_new
    qr = cfg.queue_quota_review if quota_review is None else quota_review
    due_states = [s for s in states if not s.mastered and s.due <= now]
    review_pool = sorted((s for s in due_states if s.reps > 0),
                         key=lambda s: _risk_key(s, now))
    new_pool = sorted((s for s in due_states if s.reps == 0),
                      key=lambda s: (s.due, s.card_id))
    return review_pool[:qr] + new_pool[:qn]


def reinsert_positions(session_queue: List[str], again_ids: List[str],
                       offset: int = 4) -> List[str]:
    """轮内 +offset 重现：只动会话队列，不写 FSRS 状态。

    语义：对每个刚答 Again 的词，把它插到当前队首之后第 offset 位；
    已在窗口内的不重复插。确定性输出（同输入同结果）。
    """
    q = list(session_queue)
    for aid in again_ids:
        if not aid:
            continue
        # 移除旧位置（若还在队列中），再插到队首+offset 处
        if aid in q:
            q.remove(aid)
        pos = min(offset, len(q))
        q.insert(pos, aid)
    return q


def due_forecast(states: List[CardState], now: datetime.datetime,
                 days: int = 7) -> Dict[str, int]:
    """未来 N 日逐日到期数（含今日），key 为 ISO 日期串。"""
    if now.tzinfo is not None:
        raise ValueError("now 必须是 naive UTC datetime")
    base = now.date()
    out: Dict[str, int] = {(base + datetime.timedelta(days=i)).isoformat(): 0
                           for i in range(days)}
    for s in states:
        if s.mastered:
            continue
        d = s.due.date()
        key = d.isoformat()
        if key in out:
            out[key] += 1
    return out
