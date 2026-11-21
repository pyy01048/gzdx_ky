# -*- coding: utf-8 -*-
"""audit_school：五风险阈值等号归属、缺数据绝不"无风险"、sample 隔离。"""
import pytest

from kernel.audit_school import (
    RISK_EXAM_CHANGE, RISK_FAKE_LOW_LINE, RISK_HEAT, RISK_SHRINK, RISK_TUIMIAN,
    AdmissionRow, audit,
)


def _row(year, **kw):
    base = dict(school_id="tsinghua", program_code="085400", year=year,
                total_plan=100, recommended_exempt=10, actual_exam_quota=90,
                applicants=180, first_choice_admitted=60, retest_count=90,
                retest_line=330.0, access_date=f"{year}-04-01",
                confidence="high")
    base.update(kw)
    return AdmissionRow(**base)


def _clean_rows(base_year=2027, **over):
    """三年全量、全部不达阈值的基线行。"""
    kw = dict(total_plan=100, recommended_exempt=10, actual_exam_quota=90,
              applicants=180, first_choice_admitted=60, retest_count=60,
              retest_line=330.0)
    kw.update(over)
    return [_row(y, **kw) for y in (base_year - 3, base_year - 2, base_year - 1)]


def _find(res, risk):
    return next(f for f in res.risks if f.risk == risk)


class TestThresholdsEqualSign:
    def test_tuimian_exact_10pp_hits(self, audit_cfg):
        rows = _clean_rows()
        rows[0] = _row(2024, recommended_exempt=10)     # 10%
        rows[2] = _row(2026, recommended_exempt=20)     # 20% → +10pp 恰好触发（>=）
        res = audit(rows, 2027, audit_cfg, catalog_diff="")
        assert _find(res, RISK_TUIMIAN).verdict == "hit"

    def test_shrink_exact_20pct_hits(self, audit_cfg):
        rows = _clean_rows()
        rows[1] = _row(2025, actual_exam_quota=100)
        rows[2] = _row(2026, actual_exam_quota=80)      # 恰降 20%（>=）
        res = audit(rows, 2027, audit_cfg, catalog_diff="")
        assert _find(res, RISK_SHRINK).verdict == "hit"

    def test_heat_requires_both_conditions(self, audit_cfg):
        rows = _clean_rows()
        rows[1] = _row(2025, applicants=180)            # 比 2.0
        rows[2] = _row(2026, applicants=234)            # 比 2.6：升 30%（>=）但绝对值未 >8
        res = audit(rows, 2027, audit_cfg, catalog_diff="")
        assert _find(res, RISK_HEAT).verdict == "checked_pass"
        rows2 = _clean_rows()
        rows2[1] = _row(2025, applicants=1000, actual_exam_quota=100)   # 10
        rows2[2] = _row(2026, applicants=1300, actual_exam_quota=100)   # 13：升30% 且 >8
        res2 = audit(rows2, 2027, audit_cfg, catalog_diff="")
        assert _find(res2, RISK_HEAT).verdict == "hit"

    def test_fake_low_line_exact_ratio(self, audit_cfg):
        rows = _clean_rows()
        rows[2] = _row(2026, retest_count=90, first_choice_admitted=60)  # 1.5 恰好（>=）
        res = audit(rows, 2027, audit_cfg, catalog_diff="")
        assert _find(res, RISK_FAKE_LOW_LINE).verdict == "hit"

    def test_exam_change_hit_on_diff(self, audit_cfg):
        res = audit(_clean_rows(), 2027, audit_cfg, catalog_diff="408→自命题")
        assert _find(res, RISK_EXAM_CHANGE).verdict == "hit"
        res2 = audit(_clean_rows(), 2027, audit_cfg, catalog_diff="   ")
        assert _find(res2, RISK_EXAM_CHANGE).verdict == "checked_pass"


class TestInsufficientNeverNoRisk:
    def test_missing_rows_never_no_risk(self, audit_cfg):
        # 单年行：推免/缩招/爆热缺同比；复试线字段置空 → 全 insufficient
        row = _row(2026, retest_line=None, retest_count=None)
        res = audit([row], 2027, audit_cfg)             # 无 catalog_diff
        verdicts = {f.verdict for f in res.risks}
        assert "hit" not in verdicts
        for f in res.risks:
            assert f.verdict in ("insufficient", "checked_pass")
            if f.verdict == "insufficient":
                assert "无法审计" in f.detail and f.missing
        assert _find(res, RISK_EXAM_CHANGE).verdict == "insufficient"

    def test_null_fields_insufficient(self, audit_cfg):
        rows = _clean_rows(recommended_exempt=None, applicants=None,
                           retest_line=None)
        res = audit(rows, 2027, audit_cfg)
        assert _find(res, RISK_TUIMIAN).verdict == "insufficient"
        assert _find(res, RISK_HEAT).verdict == "insufficient"
        assert _find(res, RISK_FAKE_LOW_LINE).verdict == "insufficient"


class TestSampleIsolationAndStale:
    def test_demo_rows_isolated(self, audit_cfg):
        rows = _clean_rows() + [_row(2026, is_sample=True, total_plan=1)]
        res = audit(rows, 2027, audit_cfg, catalog_diff="")
        assert res.demo_isolated_rows == 1
        # sample 行的异常值不得进入审计结论（缩招仍按真实行判）
        assert _find(res, RISK_SHRINK).verdict == "checked_pass"

    def test_all_demo_evidence_quality(self, audit_cfg):
        rows = [_row(y, is_sample=True) for y in (2024, 2025, 2026)]
        res = audit(rows, 2027, audit_cfg)
        assert res.evidence_quality == "demo_only"

    def test_stale_access_date_flagged(self, audit_cfg):
        rows = _clean_rows()
        for r in rows:
            object.__setattr__(r, "access_date", "2020-04-01")
        res = audit(rows, 2027, audit_cfg, today="2026-11-21")
        assert res.stale_review_needed is True

    def test_worst_confidence_propagates(self, audit_cfg):
        rows = _clean_rows()
        object.__setattr__(rows[1], "confidence", "low")
        res = audit(rows, 2027, audit_cfg, catalog_diff="")
        assert res.evidence_quality == "low"

    def test_disclaimer_present(self, audit_cfg):
        res = audit(_clean_rows(), 2027, audit_cfg)
        assert "不预测录取概率" in res.disclaimer
