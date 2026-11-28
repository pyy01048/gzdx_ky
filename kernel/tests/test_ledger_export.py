# -*- coding: utf-8 -*-
"""ledger_export：study_calendar 行 → DayLedger DTO（patch 出口）+ drift 串联。"""

import datetime

import pytest

from kernel.drift_detector import STATUS_ON_TRACK, compute_drift
from kernel.ledger_export import export_ledger, export_ledger_from_activities


class _Row:
    def __init__(self, date, planned_minutes, focus_minutes):
        self.date = date
        self.planned_minutes = planned_minutes
        self.focus_minutes = focus_minutes


class TestExportLedger:
    def test_dict_rows(self, drift_cfg):
        rows = [{"date": f"2026-11-{10 + i:02d}", "planned_minutes": 120, "focus_minutes": 110} for i in range(7)]
        led = export_ledger(rows)
        assert all(isinstance(d, __import__("kernel.drift_detector", fromlist=["DayLedger"]).DayLedger) for d in led)
        r = compute_drift(led, drift_cfg)
        assert r.status == STATUS_ON_TRACK

    def test_orm_like_rows(self):
        rows = [_Row(datetime.date(2026, 11, 10) + datetime.timedelta(days=i), 100, 95) for i in range(5)]
        led = export_ledger(rows)
        assert led[0].date == "2026-11-10" and led[0].planned_min == 100
        assert led[0].completed_min == 95

    def test_missing_date_raises(self):
        with pytest.raises(ValueError):
            export_ledger([{"planned_minutes": 10}])

    def test_none_fields_zero_keeps_row(self, drift_cfg):
        rows = [{"date": "2026-11-10", "planned_minutes": None, "focus_minutes": None}] * 7
        led = export_ledger(rows)
        assert len(led) == 7  # 不吞行
        from kernel.drift_detector import STATUS_NO_PLAN

        assert compute_drift(led, drift_cfg).status == STATUS_NO_PLAN

    def test_dates_iso_naive(self):
        led = export_ledger(
            [{"date": datetime.datetime(2026, 11, 10, 13, 0), "planned_minutes": 60, "focus_minutes": 60}]
        )
        assert led[0].date == "2026-11-10"
        assert datetime.datetime.fromisoformat(led[0].date).tzinfo is None


class TestFromActivities:
    def test_planned_map_applied(self, drift_cfg):
        acts = [datetime.date(2026, 11, 10) + datetime.timedelta(days=i) for i in range(4)]
        items = [{"date": d.isoformat(), "focus_minutes": 60} for d in acts]
        pb = {d.isoformat(): 60 for d in acts}
        led = export_ledger_from_activities(items, pb)
        assert sum(x.planned_min for x in led) == 240

    def test_no_plan_map_explicit(self):
        led = export_ledger_from_activities([{"date": "2026-11-10", "focus_minutes": 30}])
        assert led[0].planned_min == 0  # 缺计划→0，由状态显式化而非伪造
