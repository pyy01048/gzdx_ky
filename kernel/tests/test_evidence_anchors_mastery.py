# -*- coding: utf-8 -*-
"""evidence / anchors / mastery：grade 对齐 EvidenceRecord、冲突 anchor、
六态升降级证据约束（self_report 禁升级）。"""

import pytest

from kernel.anchors import (
    SEVERITIES,
    SUBTYPES,
    AuditAnchor,
    from_conflict,
)
from kernel.evidence import (
    GRADES,
    EvidenceRecord,
    confidence_from_completeness,
    grade_from_source,
)
from kernel.mastery import (
    STATES_6,
    EvidenceEvent,
    MasteryError,
    demote,
    from_4state,
    promote,
    to_display_4state,
)


class TestEvidenceGrades:
    def test_snapshot_source_mapping(self):
        # 快照真实来源常量（answer_cross_check.py）→ grade 对齐
        assert grade_from_source("bank") == "official"
        assert grade_from_source("user_confirmed") == "official"
        assert grade_from_source("source_extract") == "inferred"
        assert grade_from_source("llm_generated") == "needs_confirm"

    def test_unknown_source_raises(self):
        with pytest.raises(ValueError):
            grade_from_source("telepathy")

    def test_grades_enum_frozen(self):
        assert set(GRADES) == {"official", "inferred", "anecdotal", "hard_fact", "needs_confirm"}

    def test_completeness_bands(self):
        assert confidence_from_completeness(80) == "high"  # 等号归 high
        assert confidence_from_completeness(79.9) == "medium"
        assert confidence_from_completeness(50) == "medium"  # 等号归 medium
        assert confidence_from_completeness(49.9) == "low"
        assert confidence_from_completeness(0) == "low"

    def test_record_rejects_bad_grade(self):
        with pytest.raises(ValueError):
            EvidenceRecord(
                ev_id="e1", claim="x", grade="definitely_true", confidence="high", missing_fields=(), is_sample=False
            )

    def test_record_is_frozen(self):
        r = EvidenceRecord(
            ev_id="e1", claim="x", grade="hard_fact", confidence="low", missing_fields=(), is_sample=False
        )
        with pytest.raises(Exception):
            r.claim = "y"  # type: ignore[misc]


class TestAnchors:
    def _anchor(self, **kw):
        base = dict(
            anchor_id="a1",
            subtype="evidence_anchor",
            claim="c",
            based_on=("e1",),
            line_hint="",
            missing=(),
            upgrade_hint="u",
            minimal_fix="f",
            severity="minor" if "minor" in SEVERITIES else "boundary",
            kp_ids=("kp1",),
            consumed_by_plan=False,
        )
        base.update(kw)
        return AuditAnchor(**base)

    def test_three_subtypes_isomorphic(self):
        for st in SUBTYPES:
            a = self._anchor(subtype=st, severity="concept")
            assert a.subtype == st
        # 总方案 §3.9：三场景同构（择校/代码/规划）
        assert set(SUBTYPES) == {"evidence_anchor", "line_anchor", "basis_anchor"}
        assert set(SEVERITIES) == {"boundary", "concept", "efficiency", "style"}

    def test_bad_subtype_rejected(self):
        with pytest.raises(ValueError):
            self._anchor(subtype="vibes")

    def test_from_conflict_needs_confirm(self):
        cc = {"question_id": 7, "conflicts": [("bank", "llm_generated")], "checked_at": "2026-11-20T00:00:00"}
        a = from_conflict(cc, anchor_id="ac1", kp_ids=("kp_math_1",))
        assert isinstance(a, AuditAnchor)
        assert a.subtype == "evidence_anchor"
        assert a.severity in SEVERITIES
        assert "7" in a.claim  # 题目 id 锚进 claim
        assert "question:7" in a.based_on
        assert a.missing  # 冲突未消解必须带 missing

    def test_from_conflict_empty_raises(self):
        with pytest.raises(ValueError):
            from_conflict({"question_id": 1, "conflicts": []}, anchor_id="x", kp_ids=())


class TestMastery:
    def test_six_states_ordered(self):
        assert STATES_6 == ("S0", "S1", "S2", "S3", "S4", "S5")

    def test_promote_requires_evidence(self):
        with pytest.raises(MasteryError):
            promote("S1", None)

    def test_self_report_cannot_promote(self):
        ev = EvidenceEvent(event_id="e1", type="self_report", source="ui")
        with pytest.raises(MasteryError):
            promote("S2", ev)

    def test_promote_with_hard_evidence(self):
        ev = EvidenceEvent(event_id="e2", type="quiz.answered", source="bank")
        out = promote("S1", ev)
        assert STATES_6.index(out) > 1

    def test_illegal_event_type_rejected(self):
        ev = EvidenceEvent(event_id="e3", type="astrology", source="x")
        with pytest.raises(MasteryError):
            promote("S0", ev)

    def test_demote_no_evidence_raises(self):
        with pytest.raises(MasteryError):
            demote("S3", None)

    def test_four_state_roundtrip(self):
        assert to_display_4state("S0") == "unlearned"
        assert to_display_4state("S5") == "mastered"
        # 六态→四态回显全覆盖且值域合法
        for s6 in STATES_6:
            assert to_display_4state(s6) in ("unlearned", "learning", "weak", "mastered")
        # 四态→六态 adapter 方向
        for s4 in ("unlearned", "learning", "weak", "mastered"):
            assert from_4state(s4) in STATES_6
        # 往返稳定：display(from_4state(x)) 对无歧义档一致
        assert to_display_4state(from_4state("unlearned")) == "unlearned"
        assert to_display_4state(from_4state("weak")) == "weak"
        assert to_display_4state(from_4state("mastered")) == "mastered"

    def test_from_4state_hint_evidence(self):
        a = from_4state("learning")
        b = from_4state("learning", has_hint_evidence=True)
        assert STATES_6.index(b) >= STATES_6.index(a)
