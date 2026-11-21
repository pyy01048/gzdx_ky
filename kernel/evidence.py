# -*- coding: utf-8 -*-
"""EvidenceRecord 统一证据结构（总方案 §3.5）＋ confidence grade 对齐。

grade 枚举冻结：official | inferred | anecdotal | hard_fact | needs_confirm
（S0 交付项：answer_confidence_schema / confidence_service / answer_cross_check
的 grade 字段与本结构对齐——shell 侧改造在 S1，本模块是权威定义与映射函数。）

缺失显式化（G2）：missing_fields 是一等字段；任何 None 不得被渲染成 0/"无"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

GRADE_OFFICIAL = "official"
GRADE_INFERRED = "inferred"
GRADE_ANECDOTAL = "anecdotal"
GRADE_HARD_FACT = "hard_fact"
GRADE_NEEDS_CONFIRM = "needs_confirm"

GRADES = (GRADE_OFFICIAL, GRADE_INFERRED, GRADE_ANECDOTAL,
          GRADE_HARD_FACT, GRADE_NEEDS_CONFIRM)

CONFIDENCES = ("high", "medium", "low")

#: 现有四态来源 → EvidenceRecord grade 对齐表
#: （bank/user_confirmed 经人工或题库背书=official；source_extract 检索命中=inferred；
#:  llm_generated 独立生成未经确认=needs_confirm；合规/编译结果=hard_fact）
SOURCE_TO_GRADE: Dict[str, str] = {
    "bank": GRADE_OFFICIAL,
    "user_confirmed": GRADE_OFFICIAL,
    "source_extract": GRADE_INFERRED,
    "extracted": GRADE_INFERRED,
    "llm_generated": GRADE_NEEDS_CONFIRM,
    "llm": GRADE_NEEDS_CONFIRM,
    "compliance": GRADE_HARD_FACT,
    "compile_test": GRADE_HARD_FACT,
    "self_report": GRADE_ANECDOTAL,
}


def grade_from_source(source: str) -> str:
    """来源 → grade；未知来源显式抛错，绝不静默归为最低档。"""
    try:
        return SOURCE_TO_GRADE[source]
    except KeyError:
        raise ValueError(f"未知证据来源，无法映射 grade: {source!r}") from None


def confidence_from_completeness(pct: float) -> str:
    """db.json P0 完整度 → confidence（落地方案 §7.3）：
    >=80 high；50–80 medium；<50 low。等号归属：80→high、50→medium。"""
    if pct >= 80.0:
        return "high"
    if pct >= 50.0:
        return "medium"
    return "low"


@dataclass(frozen=True)
class EvidenceRecord:
    ev_id: str
    claim: str
    grade: str
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    publish_date: Optional[str] = None      # ISO 日期串
    access_date: Optional[str] = None       # ISO 日期串
    caliber: Optional[str] = None           # 口径说明
    missing_fields: Tuple[str, ...] = ()    # 一等字段：缺什么显式写什么
    confidence: str = "low"
    firsthand: bool = False
    promotion_suspect: bool = False
    method: Optional[str] = None
    notes: Optional[str] = None
    is_sample: bool = False                 # sample 数据物理隔离标记

    def __post_init__(self) -> None:
        if self.grade not in GRADES:
            raise ValueError(f"非法 grade: {self.grade!r}（合法: {GRADES}）")
        if self.confidence not in CONFIDENCES:
            raise ValueError(f"非法 confidence: {self.confidence!r}")

    def to_dict(self) -> Dict:
        d = {
            "ev_id": self.ev_id, "claim": self.claim, "grade": self.grade,
            "source_url": self.source_url, "source_type": self.source_type,
            "publish_date": self.publish_date, "access_date": self.access_date,
            "caliber": self.caliber, "missing_fields": list(self.missing_fields),
            "confidence": self.confidence,
            "credibility_flags": {"firsthand": self.firsthand,
                                  "promotion_suspect": self.promotion_suspect},
            "method": self.method, "notes": self.notes,
            "is_sample": self.is_sample,
        }
        return d
