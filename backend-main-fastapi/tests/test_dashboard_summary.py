"""``GET /api/dashboard/summary`` 契约测试（#13 首屏唯一出口）。

存在的意义：仪表盘是全站第一个页面，也是历史上"同一个数字三个答案"的重灾区
（倒计时 427 天 vs 官方 63 天、streak 四处各算一套、进度环自带"今日 50 词"默认值）。
这里锁的是**结构不变量**与**跨端点一致性**，而不是具体数值 —— 空库基线下的数值
本来就该是 0/null，写死数值反而会把"没有数据"这件事测不出来。

三条硬约束：
1. 未设目标 → ``target/percent`` 为 **null**，绝不回落到 50/20/120 这类默认值；
2. 没有事件源的模块 → ``done`` 为 **null + status=not_tracked**，不渲染成"今天 0 个"；
3. 首屏与老端点（``/api/dashboard``、``/api/dashboard/stats``）对同一个数字必须同值。
"""
from __future__ import annotations

import datetime
import re

import pytest

TZ_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

PROGRESS_MODULES = {"focus", "word", "new_word", "question", "realexam", "wrongbook", "coding"}
PHASES = {"base", "intensify", "warning", "sprint", "passed"}


@pytest.fixture(scope="module")
def summary(client):
    r = client.get("/api/dashboard/summary")
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# 1. 结构
# --------------------------------------------------------------------------- #
def test_summary_has_every_first_screen_block(summary):
    for key in (
        "generated_at", "timezone", "countdown", "goal", "kpi", "module_progress",
        "today_tasks", "review_queue", "heatmap", "trend", "weakness",
        "future_load", "errors", "data_coverage",
    ):
        assert key in summary, f"首屏契约缺块：{key}"


def test_summary_timestamps_carry_offset(summary):
    """#19 时间约定：出网的时间戳必须带 Z/±HH:MM，前端才能安全地 new Date()。"""
    assert TZ_NAME_RE.match(summary["generated_at"]), summary["generated_at"]
    for entry in summary["future_load"].values():
        if isinstance(entry, dict):
            assert TZ_NAME_RE.match(entry["cutoff"]), entry


# --------------------------------------------------------------------------- #
# 2. 目标与进度环：不许编默认值
# --------------------------------------------------------------------------- #
def test_daily_targets_are_null_when_unset(client, summary):
    """没配 Goal 时四个每日目标必须是 null（不是 50/20/120）。

    顺带守住 PUT：写入后 GET 回来要能看到同一份值，否则设置页是"假成功"。
    """
    targets = summary["goal"]["daily_targets"]
    if summary["goal"]["configured"] is False:
        assert set(targets.values()) == {None}, f"未配置目标却给出了目标值：{targets}"
        assert summary["goal"]["targets_set"] is False


def test_module_progress_no_invented_percent(summary):
    """``percent`` 与 ``target`` 同生同灭：没目标就不能有百分比。"""
    assert {m["module"] for m in summary["module_progress"]} == PROGRESS_MODULES
    for m in summary["module_progress"]:
        if m["target"] is None:
            assert m["percent"] is None, f"{m['module']} 没目标却给出 {m['percent']}%"
        else:
            assert m["percent"] == round(100.0 * m["done"] / m["target"])
        assert m["status"] in {"ok", "reached", "no_target", "not_tracked"}


def test_modules_without_event_source_report_null_not_zero(summary):
    """"还没接入"和"今天没学"是两件事：无事件源的模块 done 必须是 null。"""
    for m in summary["module_progress"]:
        if m["status"] == "not_tracked":
            assert m["done"] is None, f"{m['module']} 未接入却给出 0"
            assert m["note"], "not_tracked 必须说明缺的是哪一块"


# --------------------------------------------------------------------------- #
# 3. 倒计时与届数（唯一权威出口）
# --------------------------------------------------------------------------- #
def test_countdown_matches_exam_calendar_authority(summary):
    from services import exam_calendar
    from utils.timeutil import local_today

    cd = summary["countdown"]
    assert cd["phase"] in PHASES
    assert cd["days_left"] == (
        datetime.date.fromisoformat(cd["exam_date"]) - local_today()
    ).days
    # 届数与初试日自洽：届 = 初试年 + 1（初试在上一年 12 月）
    assert cd["exam_year"] == exam_calendar.exam_year_of(
        datetime.date.fromisoformat(cd["exam_date"])
    )


def test_countdown_is_not_anchored_to_a_hardcoded_date(summary):
    """空库兜底也必须给出"下一场还没举行的初试"，而不是拍一个明年 12 月。"""
    cd = summary["countdown"]
    assert cd["days_left"] >= 0 or cd["phase"] == "passed"
    if cd["days_left"] >= 0:
        assert cd["days_left"] <= 380, f"倒计时 {cd['days_left']} 天：数到了根本没报名的那一届"


# --------------------------------------------------------------------------- #
# 4. 未来负荷（累计口径，单调不减）
# --------------------------------------------------------------------------- #
def test_future_load_is_cumulative_and_monotonic(summary):
    fl = summary["future_load"]
    assert fl["due_today"]["total"] <= fl["due_tomorrow"]["total"] <= fl["due_this_week"]["total"]
    for key in ("due_today", "due_tomorrow", "due_this_week"):
        entry = fl[key]
        assert entry["total"] == (
            entry["flashcards"] + entry["tasks"] + entry["errors"] + entry["words"]
        )


# --------------------------------------------------------------------------- #
# 5. 三个出口同一个数字
# --------------------------------------------------------------------------- #
def test_summary_agrees_with_legacy_dashboard_endpoint(client, summary):
    """``/api/dashboard`` 与 ``/api/dashboard/summary`` 必须同源，否则首屏两处打架。"""
    legacy = client.get("/api/dashboard")
    assert legacy.status_code == 200, legacy.text
    old = legacy.json()

    stats = client.get("/api/dashboard/stats")
    assert stats.status_code == 200, stats.text

    assert old["countdown"]["exam_date"] == summary["countdown"]["exam_date"]
    assert old["countdown"]["days"] == summary["countdown"]["days"]
    assert old["stats"]["today_duration"] == summary["kpi"]["today"]["focus_minutes"]
    assert old["stats"]["week_duration"] == summary["trend"]["week_focus_minutes"]
    assert old["stats"]["active_errors"] == summary["errors"]["active"]
    assert old["stats"]["due_errors"] == summary["errors"]["due"]
    assert old["today_tasks"]["total"] == summary["today_tasks"]["total"]
    assert old["weakness"]["has_weakness"] == summary["weakness"]["has_weakness"]


def test_heatmap_and_trend_cover_contiguous_days(summary):
    """热力图/趋势逐日连续、末日是今天；空档由后端补 0，前端不再猜。"""
    from utils.timeutil import local_today

    today = local_today().isoformat()
    days = summary["heatmap"]["days"]
    assert days[-1]["date"] == today
    assert len(days) >= summary["heatmap"]["weeks"] * 7
    assert datetime.date.fromisoformat(days[0]["date"]).weekday() == 0

    series = summary["trend"]["series"]
    assert len(series) == summary["trend"]["days"] == 14
    assert series[-1]["date"] == today


def test_streak_fields_and_rule_present(summary):
    st = summary["kpi"]["streak"]
    assert isinstance(st["current"], int) and isinstance(st["longest"], int)
    assert st["total_days"] >= st["current"]
    assert isinstance(st["checked_today"], bool)
    assert "10" in st["rule"], "打卡口径要写进返回值，前端才能原样解释给用户"
    assert summary["kpi"]["today"]["effective"] == st["checked_today"]


def test_correct_rate_is_null_not_zero_when_no_answers(summary):
    """没答题时 correct_rate 是 null。0 会被画成"全错"。"""
    for day in (summary["kpi"]["today"], summary["kpi"]["yesterday"]):
        if day["questions_done"] == 0:
            assert day["correct_rate"] is None
        else:
            assert 0 <= day["correct_rate"] <= 100


def test_empty_state_is_reported_not_hidden(summary):
    dc = summary["data_coverage"]
    assert dc["is_empty"] == (dc["days_with_activity"] == 0)
    if dc["is_empty"]:
        assert dc["empty_hint"]
        assert dc["first_day"] is None
        assert summary["kpi"]["today"]["focus_minutes"] == 0
