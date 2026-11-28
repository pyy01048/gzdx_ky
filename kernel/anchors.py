# -*- coding: utf-8 -*-
"""AuditAnchor 统一锚点对象（总方案 §3.9，落地方案 §4.8）。

三场景同构：evidence_anchor（择校）/ line_anchor（代码）/ basis_anchor（规划）。
S0 交付：cross_check 冲突 → needs_confirm anchor（from_conflict）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence, Tuple

SUBTYPE_EVIDENCE = "evidence_anchor"
SUBTYPE_LINE = "line_anchor"
SUBTYPE_BASIS = "basis_anchor"
SUBTYPES = (SUBTYPE_EVIDENCE, SUBTYPE_LINE, SUBTYPE_BASIS)

SEVERITIES = ("boundary", "concept", "efficiency", "style")


@dataclass(frozen=True)
class AuditAnchor:
    anchor_id: str
    subtype: str
    claim: str
    based_on: Tuple[str, ...] = ()  # 证据/信号引用（ev_id / event_id）
    line_hint: str = ""  # line_anchor 专用：具体语句/结构锚点
    missing: Tuple[str, ...] = ()  # 该判断缺什么证据
    upgrade_hint: str = ""  # 补什么能提升
    minimal_fix: str = ""
    severity: str = "boundary"
    kp_ids: Tuple[str, ...] = ()
    consumed_by_plan: bool = False

    def __post_init__(self) -> None:
        if self.subtype not in SUBTYPES:
            raise ValueError(f"非法 anchor subtype: {self.subtype!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"非法 severity: {self.severity!r}")

    def to_dict(self) -> Dict:
        return {
            "anchor_id": self.anchor_id,
            "subtype": self.subtype,
            "claim": self.claim,
            "based_on": list(self.based_on),
            "line_hint": self.line_hint,
            "missing": list(self.missing),
            "upgrade_hint": self.upgrade_hint,
            "minimal_fix": self.minimal_fix,
            "severity": self.severity,
            "kp_ids": list(self.kp_ids),
            "consumed_by_plan": self.consumed_by_plan,
        }


def from_conflict(cross_check_result: Mapping, *, anchor_id: str, kp_ids: Sequence[str] = ()) -> AuditAnchor:
    """answer_cross_check 冲突结果 → needs_confirm 型 evidence_anchor。

    输入是 shell 侧 cross_check_question() 返回 dict 的冲突条目形态：
    {"question_id": ..., "conflicts": [("bank","llm_generated"), ...],
     "candidates": {...可选：按来源的答案快照}}
    冲突未消解前一切判断都是 needs_confirm——人工闸门 pass 后由 shell 升级。
    """
    conflicts = tuple(cross_check_result.get("conflicts") or ())
    if not conflicts:
        raise ValueError("from_conflict 需要非空 conflicts")
    qid = cross_check_result.get("question_id")
    pairs = "；".join(f"{a} vs {b}" for a, b in conflicts)
    return AuditAnchor(
        anchor_id=anchor_id,
        subtype=SUBTYPE_EVIDENCE,
        claim=f"题目 {qid} 多来源答案冲突（{pairs}），结论待人工确认",
        based_on=(f"question:{qid}",),
        missing=("人工复核结论",),
        upgrade_hint="经 /api/conflicts resolve 采纳后可升级为 official",
        severity="concept",
        kp_ids=tuple(kp_ids),
    )
