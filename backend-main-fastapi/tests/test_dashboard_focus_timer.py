"""D-04「今日学习时长（专注计时）」的写入口回归（01-仪表盘 §2.1）。

这块历史上被删过一次（独立的 pomodoro_sessions 表 + 专属页面，长期 1 行数据），
所以测试锁的不是"能不能计时"，而是**写进来的东西会不会撒谎**：

1. 一次计时的落库必须立刻被 ``study_calendar`` 台账读到 ——
   计时器说记了 25 分钟，KPI 卡就必须显示 25 分钟，同一 ``sum(duration)``；
2. ``duration`` 没有默认值：漏字段不能自动记 25 分钟（那是编出来的专注）；
3. 来源是闭集（pomodoro / manual / module），写错直接 422，不进库；
4. 单日总量超过一天该有的分钟数一律拒，且**不留半条记录**；
5. 空科目串归一成 NULL —— ``study_sessions.subject`` 会直接进分科目时长，
   存一个空格字符串等于凭空多出一个科目。

隔离方式：本文件所有行都带 ``remark == MARK``，teardown 按它删；
断言只看**增量**，因此不受临时库里别人留下的"今天"的数据影响。
"""
from __future__ import annotations

import datetime

import pytest

from conftest import TEST_USER_ID
from models import StudySession
from services.study_calendar import (
    FOCUS_SOURCES,
    MAX_FOCUS_MINUTES_PER_DAY,
    MAX_FOCUS_MINUTES_PER_SESSION,
    focus_minutes_on,
)

#: 本文件专属标记：写库的行用它自证来源，也用它清理。
MARK = "专注计时测试科目"
URL = "/api/dashboard/study-session"


@pytest.fixture()
def db(db_schema):  # noqa: ARG001 — db_schema 负责建表（含 core/sql 分片）
    from database import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        s.query(StudySession).filter(StudySession.remark == MARK).delete()
        s.commit()
        s.close()


def _today():
    from utils.timeutil import local_today

    return local_today()


# --------------------------------------------------------------------------- #
# 1. 写入 → 台账读到同一个数（单一口径）
# --------------------------------------------------------------------------- #
def test_a_recorded_session_moves_the_dashboard_number_by_exactly_its_minutes(
    client, db
):
    from services.dashboard_service import DashboardService

    day = _today()
    before = focus_minutes_on(db, day)

    r = client.post(URL, json={
        "duration": 25, "task_type": "pomodoro", "subject": MARK, "remark": MARK,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["date"] == day.isoformat()
    assert body["duration"] == 25
    # 接口回的是"这一天的合计"，不是"这条记录"：前端不必再猜
    assert body["day_total_minutes"] == before + 25

    db.expire_all()
    assert focus_minutes_on(db, day) == before + 25
    kpi = DashboardService.get_summary(db)["kpi"]["today"]
    assert kpi["focus_minutes"] == before + 25, (
        "专注计时写的是 study_sessions，KPI 读的也必须是它 —— 两处不同就是两个答案"
    )


def test_streak_effective_threshold_is_reached_by_real_minutes(client, db):
    """D-04 的意义之一：记满 ``EFFECTIVE_FOCUS_MINUTES`` 分钟今天才算打卡日。"""
    from services import study_calendar
    from services.dashboard_service import DashboardService

    day = _today()
    focus = focus_minutes_on(db, day)
    need = max(study_calendar.EFFECTIVE_FOCUS_MINUTES - focus, 1)

    r = client.post(URL, json={"duration": need, "task_type": "manual", "remark": MARK})
    assert r.status_code == 200, r.text

    db.expire_all()
    assert focus_minutes_on(db, day) == focus + need
    kpi = DashboardService.get_summary(db)["kpi"]["today"]
    assert kpi["focus_minutes"] >= study_calendar.EFFECTIVE_FOCUS_MINUTES
    assert kpi["effective"] is True


# --------------------------------------------------------------------------- #
# 2. duration 必填 + 上下限
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("payload", [
    {},                                             # 漏传：绝不能默认记 25 分钟
    {"duration": 0},                                # 0 分钟不是"学过"
    {"duration": -5},
    {"duration": MAX_FOCUS_MINUTES_PER_SESSION + 1},  # 一次专注不可能 10 小时+
    {"duration": "twenty five"},
])
def test_invalid_duration_is_rejected_and_nothing_is_written(client, db, payload):
    r = client.post(URL, json={"remark": MARK, **payload})
    assert r.status_code == 422, f"{payload} 竟然被接受：{r.text}"
    assert db.query(StudySession).filter(StudySession.remark == MARK).count() == 0, (
        "校验失败的请求也必须一行不写 —— 半条记录比报错更难查"
    )


def test_boundary_durations_are_accepted(client, db):
    day = _today()
    before = focus_minutes_on(db, day)
    for minutes in (1, MAX_FOCUS_MINUTES_PER_SESSION):
        r = client.post(URL, json={"duration": minutes, "task_type": "manual", "remark": MARK})
        assert r.status_code == 200, r.text
    db.expire_all()
    assert focus_minutes_on(db, day) == before + 1 + MAX_FOCUS_MINUTES_PER_SESSION
    assert db.query(StudySession).filter(StudySession.remark == MARK).count() == 2


# --------------------------------------------------------------------------- #
# 3. 来源是闭集（01-仪表盘 §3.1 的 source ENUM）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("source", FOCUS_SOURCES)
def test_every_declared_source_is_accepted(client, db, source):
    r = client.post(URL, json={"duration": 1, "task_type": source, "remark": MARK})
    assert r.status_code == 200, r.text
    assert r.json()["task_type"] == source


def test_unknown_source_is_rejected(client, db):
    r = client.post(URL, json={"duration": 25, "task_type": "pomodoro_app", "remark": MARK})
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# 4. 科目串归一
# --------------------------------------------------------------------------- #
def test_blank_subject_becomes_null_instead_of_an_invisible_subject(client, db):
    day = _today()
    before = focus_minutes_on(db, day)
    r = client.post(URL, json={"duration": 10, "subject": "   ", "remark": MARK})
    assert r.status_code == 200, r.text
    assert r.json()["subject"] is None, "空格科目会多出一个空白科目名"

    db.expire_all()
    row = db.query(StudySession).filter(StudySession.remark == MARK).one()
    assert row.subject is None
    # 没科目也照样算时长：分科目统计里不出现它，日总量里必须有它
    assert focus_minutes_on(db, day) == before + 10


def test_subject_is_stored_verbatim_for_per_subject_totals(client, db):
    from services.dashboard_service import DashboardService

    r = client.post(URL, json={"duration": 30, "subject": MARK, "remark": MARK})
    assert r.status_code == 200, r.text
    assert r.json()["subject"] == MARK
    db.expire_all()
    stats = DashboardService.get_stats(db)
    assert stats["subject_durations"].get(MARK, 0) >= 30


# --------------------------------------------------------------------------- #
# 5. 单日总量闸门
# --------------------------------------------------------------------------- #
def test_a_day_cannot_accumulate_more_minutes_than_a_day_has(client, db):
    day = _today()
    already_minutes = MAX_FOCUS_MINUTES_PER_DAY - 10
    db.add(StudySession(
        date=day, duration=already_minutes, subject=MARK, task_type="manual", remark=MARK,
        user_id=TEST_USER_ID,  # B4：种子数据归属测试主体
    ))
    db.commit()

    r = client.post(URL, json={"duration": 20, "task_type": "manual", "remark": MARK})
    assert r.status_code == 422, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("limit") == MAX_FOCUS_MINUTES_PER_DAY
    assert detail.get("already_minutes") == already_minutes

    db.expire_all()
    assert focus_minutes_on(db, day, user_id=TEST_USER_ID) == already_minutes, (
        "被拒绝的请求不能留下任何时长：当天合计必须还是拒绝前那个数"
    )
    assert db.query(StudySession).filter(StudySession.remark == MARK).count() == 1


def test_day_gate_is_date_scoped(client, db):
    """闸门只看**当天**：昨天记满 1440 分钟不该挡住今天的第一次专注。"""
    yesterday = _today() - datetime.timedelta(days=1)
    db.add(StudySession(
        date=yesterday, duration=MAX_FOCUS_MINUTES_PER_DAY,
        subject=MARK, task_type="manual", remark=MARK,
        user_id=TEST_USER_ID,  # B4：种子数据归属测试主体
    ))
    db.commit()

    r = client.post(URL, json={"duration": 25, "task_type": "pomodoro", "remark": MARK})
    assert r.status_code == 200, r.text
    assert r.json()["day_total_minutes"] == 25
