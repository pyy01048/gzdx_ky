# -*- coding: utf-8 -*-
"""默写选词（落地方案 §4.7，纯函数·reportlab 不进 kernel）。

规则：R 升序 Top-N ∪ 昨日错词；mastered 排除（豁免彻底）；
确定性——同一状态两次导出词集完全一致（排序键含 card_id 稳定 tie-break）。
"""
from __future__ import annotations

import datetime
from typing import List, Sequence

from kernel.fsrs_adapter import CardState, recall_prob


def select(states: Sequence[CardState], yesterday_errors: Sequence[str],
           now: datetime.datetime, n: int = 30) -> List[str]:
    """返回选中的 card_id 列表（高危 Top-N ∪ 昨日错词，错词必选不受 N 限制）。"""
    if now.tzinfo is not None:
        raise ValueError("now 必须是 naive UTC datetime")
    if n <= 0:
        raise ValueError(f"n 必须为正整数: {n!r}")
    pool = [s for s in states if not s.mastered]

    def key(s: CardState):
        overdue = max(0.0, (now - s.due).total_seconds() / 86400.0)
        return (recall_prob(overdue, s.stability), -overdue, s.card_id)

    ranked = sorted(pool, key=key)
    top = [s.card_id for s in ranked[:n]]
    topset = set(top)
    known_ids = {s.card_id for s in pool}
    # 昨日错词必选（仍在池中且未被高危 Top-N 覆盖的追加在尾部，保持确定性顺序）
    extra = [cid for cid in dict.fromkeys(yesterday_errors)
             if cid in known_ids and cid not in topset]
    return top + extra
