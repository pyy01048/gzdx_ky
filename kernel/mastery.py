# -*- coding: utf-8 -*-
"""六态掌握度 + 四态↔六态 adapter（落地方案 §4.8）。

六态（总方案 §3.3）：S0 未接触 → S1 已理解 → S2 提示下能做 → S3 独立完成
→ S4 迁移验证 → S5 自动化。
升降级必须由证据事件驱动（规范 §3.3：禁止 LLM 直改）；promote/demote
不带 evidence_event 一律显式拒绝。

四态回显（私有 UI 零改动）：MASTERY_MAP_4TO6 提供正向映射，
to_display_4state 提供六态→四态回显（与 services/kp_mastery.py 的
unlearned/learning/weak/mastered 标签一致）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Mapping, Optional, Tuple

S0, S1, S2, S3, S4, S5 = "S0", "S1", "S2", "S3", "S4", "S5"
STATES_6 = (S0, S1, S2, S3, S4, S5)
_RANK = {s: i for i, s in enumerate(STATES_6)}

#: 四态 → 六态候选集（落地方案 §4.8 MASTERY_MAP_4TO6）
#: 未学→S0；学习中→S1|S2（按 hint 证据定档）；薄弱→S2（置信降档）；已掌握→S3+
MASTERY_MAP_4TO6: Mapping[str, Tuple[str, ...]] = {
    "unlearned": (S0,),
    "learning": (S1, S2),
    "weak": (S2,),
    "mastered": (S3, S4, S5),
}

#: 六态 → 四态回显（UI 继续显示旧口径）
_TO_4STATE = {S0: "unlearned", S1: "learning", S2: "weak",
              S3: "mastered", S4: "mastered", S5: "mastered"}

#: 升降级允许的证据事件类型（source 权重：硬证据 > self_report）
PROMOTE_EVENTS: Mapping[Tuple[str, str], FrozenSet[str]] = {
    (S0, S1): frozenset({"quiz.answered", "task.partial", "signal.focus"}),
    (S1, S2): frozenset({"quiz.answered", "word.reviewed", "task.reviewed"}),
    (S2, S3): frozenset({"quiz.answered", "exam.submitted", "dictation.result"}),
    (S3, S4): frozenset({"quiz.answered", "exam.submitted"}),
    (S4, S5): frozenset({"word.mastered", "exam.submitted"}),
}
#: self_report 永远不能单独作为升级证据（验证真实进度而非相信自报）
_SELF_REPORT_ONLY_BLOCKED = True


@dataclass(frozen=True)
class EvidenceEvent:
    event_id: str
    type: str                 # v2.0 事件码（event_store.EVENT_MAP 值域）
    source: str = "fsrs_review"   # quiz_result/fsrs_review/dictation/compliance/self_report/...

    def is_hard(self) -> bool:
        return self.source in ("quiz_result", "fsrs_review", "dictation",
                               "compliance")


class MasteryError(ValueError):
    pass


def promote(state: str, evidence_event: Optional[EvidenceEvent]) -> str:
    """升一级；必须带合法证据事件，否则显式拒绝。"""
    if state not in _RANK:
        raise MasteryError(f"非法掌握态: {state!r}")
    if _RANK[state] == len(STATES_6) - 1:
        return state    # S5 顶格不再升
    if evidence_event is None:
        raise MasteryError("升降级必须携带证据事件（规范 §3.3），拒绝无证据升级")
    allowed = PROMOTE_EVENTS.get((state, STATES_6[_RANK[state] + 1]))
    if evidence_event.type not in (allowed or frozenset()):
        raise MasteryError(
            f"事件类型 {evidence_event.type!r} 不支持 {state}→"
            f"{STATES_6[_RANK[state] + 1]} 升级")
    if _SELF_REPORT_ONLY_BLOCKED and not evidence_event.is_hard() \
            and evidence_event.source == "self_report":
        raise MasteryError("self_report 不能作为升级证据")
    return STATES_6[_RANK[state] + 1]


def demote(state: str, evidence_event: Optional[EvidenceEvent]) -> str:
    """降一级（答错/概念性错误等硬负证据触发）；同样必须带证据事件。"""
    if state not in _RANK:
        raise MasteryError(f"非法掌握态: {state!r}")
    if _RANK[state] == 0:
        return state
    if evidence_event is None:
        raise MasteryError("升降级必须携带证据事件，拒绝无证据降级")
    return STATES_6[_RANK[state] - 1]


def to_display_4state(state6: str) -> str:
    """六态 → 四态回显（私有 UI 零改动）。"""
    try:
        return _TO_4STATE[state6]
    except KeyError:
        raise MasteryError(f"非法掌握态: {state6!r}") from None


def from_4state(state4: str, *, has_hint_evidence: bool = False) -> str:
    """四态 → 六态初始估算（adapter 方向）。

    learning 档需按 hint 证据定 S1/S2：有提示下完成证据 → S2，否则 S1。
    """
    cand = MASTERY_MAP_4TO6.get(state4)
    if not cand:
        raise MasteryError(f"非法四态值: {state4!r}")
    if len(cand) == 1:
        return cand[0]
    if state4 == "learning":
        return S2 if has_hint_evidence else S1
    return cand[0]   # mastered → S3（最低档回显，保守估算）
