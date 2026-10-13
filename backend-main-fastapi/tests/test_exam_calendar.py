# -*- coding: utf-8 -*-
"""届数 / 初试日期推导的回归测试（M0 届数可调）。

锁住三件事，防止以后又写死：
  1. 已由教育部公布的届，初试日必须是官方值（2027 届 = 2026-12-19）；
  2. 届数与初试日必须自洽：初试日在上一年 12 月，所以 届数 = 初试年 + 1；
  3. 仪表盘倒计时、复习里程碑、届数设置三个出口必须给同一个答案。
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from services import exam_calendar as ec


# --------------------------------------------------------------------------- #
# 1. 官方日期
# --------------------------------------------------------------------------- #
def test_2027_exam_date_is_official_dec_19_2026():
    """教育部《2027 年全国硕士研究生招生工作管理规定》：初试 2026-12-19 至 20。"""
    d, official = ec.resolve_exam_date(2027)
    assert d == datetime.date(2026, 12, 19)
    assert official is True


@pytest.mark.parametrize(
    "year,expected",
    [(2025, datetime.date(2024, 12, 21)),
     (2026, datetime.date(2025, 12, 20)),
     (2027, datetime.date(2026, 12, 19))],
)
def test_known_years_match_official(year, expected):
    d, official = ec.resolve_exam_date(year)
    assert (d, official) == (expected, True)


def test_unannounced_year_is_marked_estimate():
    """未公布的届必须标 is_official=False，前端才能显示「预估」。"""
    d, official = ec.resolve_exam_date(2031)
    assert official is False
    assert d.month == 12 and d.day > 15


def test_estimate_rule_holds_for_known_years():
    """规律（上一年 12 月倒数第二个周六）与已公布年份一致 —— 这是规律可信的依据。"""
    for year in (2025, 2026, 2027):
        assert ec.estimate_exam_date(year) == datetime.date(*ec.OFFICIAL_EXAM_DATES[year])


# --------------------------------------------------------------------------- #
# 2. 届数 <-> 初试日 自洽
# --------------------------------------------------------------------------- #
def test_exam_date_is_always_in_previous_december():
    """核心不变式：初试必在上一年 12 月下旬。"""
    for year in range(2020, 2041):
        d, _ = ec.resolve_exam_date(year)
        assert d.year == year - 1, f"{year} 届推导成了 {d}"
        assert d.month == 12
        assert 18 <= d.day <= 31


def test_exam_date_falls_on_saturday():
    for year in range(2020, 2041):
        d, _ = ec.resolve_exam_date(year)
        assert d.weekday() == 5, f"{year} 届初试 {d} 不是周六"


def test_exam_year_roundtrip():
    """初试日 -> 届数 -> 初试日，必须回到原值。"""
    for year in range(2024, 2036):
        d, _ = ec.resolve_exam_date(year)
        assert ec.exam_year_of(d) == year


def test_stale_wrong_date_is_recognised_as_next_cohort():
    """真库曾存 exam_date=2027-12-25 却备注写着考 2027 届 —— 反推应是 2028 届。"""
    assert ec.exam_year_of(datetime.date(2027, 12, 25)) == 2028


# --------------------------------------------------------------------------- #
# 3. 校验
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [1999, 2101, 0, -1])
def test_out_of_range_year_rejected(bad):
    with pytest.raises(ec.ExamYearError):
        ec.validate_exam_year(bad)


@pytest.mark.parametrize("bad", ["abc", None, 3.5])
def test_non_integer_year_rejected(bad):
    with pytest.raises(ec.ExamYearError):
        ec.validate_exam_year(bad)


# --------------------------------------------------------------------------- #
# 4. 从 Goal 行解析（修「同一条记录里两套年份」）
# --------------------------------------------------------------------------- #
def _goal(exam_date):
    return SimpleNamespace(id=1, exam_date=exam_date)


def test_resolve_from_goal_uses_stored_date_and_stays_self_consistent():
    info = ec.resolve_for_db(_goal(datetime.date(2026, 12, 19)))
    assert info["exam_year"] == 2027
    assert info["exam_date"] == "2026-12-19"
    assert info["is_official"] is True
    assert info["is_estimated"] is False


def test_resolve_flags_conflicting_stored_date():
    """存了 2027-12-25（非官方日期）要如实提示，而不是当成官方。"""
    info = ec.resolve_for_db(_goal(datetime.date(2027, 12, 25)))
    assert info["exam_year"] == 2028
    assert info["is_official"] is False
    assert "核对" in info["source"]


def test_resolve_without_goal_is_estimated():
    info = ec.resolve_for_db(None)
    assert info["is_estimated"] is True
    assert info["exam_year"] in (2026, 2027, 2028)


def test_describe_exposes_days_left():
    d = ec.describe(2027)
    assert d["exam_year"] == 2027
    assert d["exam_date"] == "2026-12-19"
    assert d["is_official"] is True
    assert isinstance(d["days_left"], int)


def test_default_exam_year_switches_in_july():
    """7~12 月默认按明年 12 月算（今年报名窗口已过）。"""
    assert ec.default_exam_year(datetime.date(2026, 6, 30)) == 2027
    assert ec.default_exam_year(datetime.date(2026, 7, 1)) == 2028
    assert ec.default_exam_year(datetime.date(2026, 12, 31)) == 2028


# --------------------------------------------------------------------------- #
# 5. 三个出口必须一致（防止又出现"同一应用三个答案"）
# --------------------------------------------------------------------------- #
def test_all_three_outputs_agree_for_2027_cohort():
    """仪表盘 / 复习计划 / 届数设置三个出口对 2027 届必须给同一个初试日。"""
    from routers import plan as plan_router

    canonical = ec.resolve_exam_date(2027)[0]
    assert plan_router._exam_date(2027) == canonical
    assert ec.describe(2027)["exam_date"] == canonical.isoformat()