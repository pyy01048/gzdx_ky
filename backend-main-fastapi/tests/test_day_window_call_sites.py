# -*- coding: utf-8 -*-
"""日界口径的**调用点**回归（P1-C2 / P1-C3）。

``utils/timeutil`` 的单测只锁工具自身；本文件锁真实聚合接口是否按北京自然日切日：

1. ``/api/analysis/profile`` 的逐日趋势与学习天数（services/learner_profile）——
   旧写法 ``substring(CAST(ts AS text),1,10)`` 切的是 UTC 日，凌晨答题掉前一天；
2. 仪表盘「本周」窗口（``DashboardService.get_stats``，#13 后路由只做委派，
   聚合口径的唯一出口在 service 层）——聚合与逐日曲线必须覆盖
   同一组 7 天，写成 ``today-7`` 就是 8 天，多一天也是失真。

库里可能有其他测试种下的数据，所以断言一律用「同口径重算 + 对照差值」，
不假设全表只有我这几行；用例结束时把自己插的行删掉，避免加剧跨文件污染。
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import func

from database import SessionLocal
from models import AnswerRecord, StudySession
from utils import timeutil as tu


@pytest.fixture()
def db(db_schema):  # noqa: ARG001  依赖 db_schema 确保临时库已建表
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_profile_trend_and_study_days_use_beijing_day(db):
    """北京凌晨 2 点的答题必须记在**北京今天**，不是 UTC 昨天。"""
    from services import learner_profile

    day, start, _end = tu.local_day_window()
    at = start + dt.timedelta(hours=2)
    assert at.date() != day, "用例要落在能区分 UTC 日与北京日的时刻，否则等于没测"

    row = AnswerRecord(subject="数学", is_correct=True, created_at=at)
    db.add(row)
    db.commit()
    try:
        profile = learner_profile.build_profile(db, days=7)
    finally:
        db.delete(row)
        db.commit()

    trend = {r["date"]: r for r in profile["trend"]}
    assert day.isoformat() in trend, f"北京日 {day} 不在趋势里：{sorted(trend)}"
    assert trend[day.isoformat()]["answers"] >= 1
    assert trend[day.isoformat()]["correct"] >= 1
    assert profile["overview"]["study_days"] >= 1


def test_dashboard_week_window_is_exactly_seven_beijing_days(db):
    """「本周」= 含今天的 7 个北京自然日；第 8 天的数据必须被排除。"""
    from services.dashboard_service import DashboardService

    today = tu.local_today()
    week_ago = today - dt.timedelta(days=6)
    seeded = [
        StudySession(date=today, duration=11, subject="数学"),
        StudySession(date=week_ago, duration=13, subject="数学"),
        StudySession(date=week_ago - dt.timedelta(days=1), duration=17, subject="数学"),
    ]
    for s in seeded:
        db.add(s)
    db.commit()
    try:
        stats = DashboardService.get_stats(db)
        in_window = int(
            db.query(func.coalesce(func.sum(StudySession.duration), 0))
            .filter(StudySession.date >= week_ago)
            .scalar() or 0
        )
        outside = int(
            db.query(func.coalesce(func.sum(StudySession.duration), 0))
            .filter(StudySession.date < week_ago)
            .scalar() or 0
        )
        assert outside >= 17, "库里没有窗口外的数据，这条断言就锁不住 off-by-one"
        assert stats["week_duration"] == in_window, (
            f"week_duration={stats['week_duration']} 与「近 7 天」重算值 {in_window} 不符"
        )
        assert stats["today_duration"] >= 11
        assert len(stats["daily_trend"]) == 7
        assert stats["daily_trend"][0]["date"] == week_ago.isoformat()
        assert stats["daily_trend"][-1]["date"] == today.isoformat()
    finally:
        for s in seeded:
            db.delete(s)
        db.commit()
