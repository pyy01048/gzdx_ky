# -*- coding: utf-8 -*-
"""drift_detector：分带端点、等号归属、冷启动保护、边界值必测（规范 §2.2-1/2）。"""
import datetime

import pytest

from kernel.drift_detector import (
    STATUS_INSUFFICIENT, STATUS_MICRO_ADJUST, STATUS_NO_PLAN, STATUS_ON_TRACK,
    STATUS_RECOVERY, DayLedger, compute_drift,
)


def _ledger(pairs, start="2026-11-01"):
    d0 = datetime.date.fromisoformat(start)
    return [DayLedger(date=(d0 + datetime.timedelta(days=i)).isoformat(),
                      planned_min=p, completed_min=c)
            for i, (p, c) in enumerate(pairs)]


class TestBandEndpoints:
    """等号归属精确断言（验收红线）。"""

    def test_exact_minus_015_is_on_track(self, drift_cfg):
        # planned=1000, completed=850 → drift=-0.15 → on_track（含等号）
        r = compute_drift(_ledger([(1000, 850)] * 3), drift_cfg)
        assert r.status == STATUS_ON_TRACK
        assert r.drift == pytest.approx(-0.15)

    def test_just_below_minus_015_is_micro(self, drift_cfg):
        # -0.150001... → micro_adjust
        r = compute_drift(_ledger([(1_000_000, 849_999)] * 3), drift_cfg)
        assert r.drift < -0.15
        assert r.status == STATUS_MICRO_ADJUST

    def test_exact_minus_035_is_micro(self, drift_cfg):
        # planned=1000, completed=650 → drift=-0.35 → micro_adjust（含等号）
        r = compute_drift(_ledger([(1000, 650)] * 3), drift_cfg)
        assert r.drift == pytest.approx(-0.35)
        assert r.status == STATUS_MICRO_ADJUST

    def test_just_below_minus_035_is_recovery(self, drift_cfg):
        r = compute_drift(_ledger([(1_000_000, 649_999)] * 3), drift_cfg)
        assert r.drift < -0.35
        assert r.status == STATUS_RECOVERY

    def test_positive_drift_on_track(self, drift_cfg):
        r = compute_drift(_ledger([(100, 130)] * 3), drift_cfg)
        assert r.status == STATUS_ON_TRACK and r.drift > 0


class TestColdStart:
    def test_fewer_than_min_days_insufficient(self, drift_cfg):
        r = compute_drift(_ledger([(100, 50), (100, 50)]), drift_cfg)
        assert r.status == STATUS_INSUFFICIENT
        assert r.drift is None
        assert r.window_days == 2

    def test_empty_ledger_insufficient(self, drift_cfg):
        r = compute_drift([], drift_cfg)
        assert r.status == STATUS_INSUFFICIENT

    def test_exactly_min_days_ok(self, drift_cfg):
        r = compute_drift(_ledger([(100, 100)] * 3), drift_cfg)
        assert r.status == STATUS_ON_TRACK

    def test_zero_planned_no_plan(self, drift_cfg):
        r = compute_drift(_ledger([(0, 0)] * 7), drift_cfg)
        assert r.status == STATUS_NO_PLAN
        assert r.drift == 0.0

    def test_window_only_takes_recent_days(self, drift_cfg):
        # 前 10 天全 0，最近 7 天正常 → 窗口只看最近 7 天
        led = _ledger([(100, 0)] * 10 + [(100, 100)] * 7)
        r = compute_drift(led, drift_cfg)
        assert r.status == STATUS_ON_TRACK
        assert r.window_days == 7


class TestNaiveUtc:
    def test_result_has_no_datetime(self, drift_cfg):
        # DriftResult 不含 datetime；date 字段是 ISO 串（naive UTC 口径由 shell 保证）
        led = _ledger([(60, 60)] * 3)
        r = compute_drift(led, drift_cfg)
        assert isinstance(r, object)
        assert all(isinstance(d.date, str) for d in led)

    def test_day_ledger_dates_parse_naive(self):
        led = _ledger([(60, 60)] * 3)
        for d in led:
            dt = datetime.datetime.fromisoformat(d.date)
            assert dt.tzinfo is None
