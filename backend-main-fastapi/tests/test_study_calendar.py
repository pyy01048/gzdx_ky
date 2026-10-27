"""日活台账 ``services/study_calendar`` 的回归测试（#13 仪表盘唯一口径）。

存在的意义：打卡天数原先后端 3 处 + 前端 1 处各算一套（真实时长、"任务 ×30 + 题目 ×5"
估算、两套过滤条件），同一个用户能有 4 个 streak。本模块是收敛后的**唯一口径**，
所以这里锁三件事：

1. **日界**必须按北京自然日（UTC 16:30 属于次日，不是当天）；
2. **有效学习日**门槛的边界（9 分钟不算、10 分钟算），且时长只认真实记录；
3. **streak 的"今日未学不算断签"**，以及热力图起点对齐周一。

纯计算用例（streak / fill_series / 格子）不碰 DB，直接喂台账；
聚合用例走 conftest 的临时库，并用 **2001 年** 的历史区间避开其他用例的数据。
"""
from __future__ import annotations

import datetime

import pytest

from services.study_calendar import (
    EFFECTIVE_FOCUS_MINUTES,
    EFFECTIVE_QUESTIONS,
    EFFECTIVE_WORDS,
    DayActivity,
    day_ledger,
    effective_activity_days,
    fill_series,
    streak_summary,
)

#: 本文件专用历史区间：避开 sample_data 与其他用例写在"最近 30 天"的行
HIST = (datetime.date(2001, 3, 5), datetime.date(2001, 3, 7))
MARK = "台账测试科目"
#: 落在北京 2001-03-05 当天（10:00）的 naive UTC 瞬时
_IN_WIN = datetime.datetime(2001, 3, 5, 2, 0)


def _act(day: str, **kw) -> DayActivity:
    return DayActivity(date=datetime.date.fromisoformat(day), **kw)


def _ledger(*acts: DayActivity) -> dict:
    return {a.date.isoformat(): a for a in acts}


# --------------------------------------------------------------------------- #
# 1. 有效学习日门槛（01-仪表盘 §2.7）
# --------------------------------------------------------------------------- #
def test_effective_threshold_boundaries():
    """门槛是"达到即算"：9 分钟/9 词/4 题不算，10/10/5 算。"""
    assert not _act("2026-01-01", focus_minutes=EFFECTIVE_FOCUS_MINUTES - 1).is_effective
    assert _act("2026-01-01", focus_minutes=EFFECTIVE_FOCUS_MINUTES).is_effective
    assert not _act("2026-01-01", words_done=EFFECTIVE_WORDS - 1).is_effective
    assert _act("2026-01-01", words_done=EFFECTIVE_WORDS).is_effective
    assert not _act("2026-01-01", questions_done=EFFECTIVE_QUESTIONS - 1).is_effective
    assert _act("2026-01-01", questions_done=EFFECTIVE_QUESTIONS).is_effective


def test_active_but_ineffective_day_is_distinguishable():
    """"有痕迹但没达门槛"必须能被区分出来：热力图要显示浅灰，打卡不能算。"""
    d = _act("2026-01-01", focus_minutes=4, tasks_done=1)
    assert d.is_active and not d.is_effective


def test_correct_rate_is_none_when_no_answers():
    """没答题返回 None。返回 0 会被前端画成"正确率 0%"——那是撒谎。"""
    assert _act("2026-01-01").correct_rate is None
    assert _act("2026-01-01", questions_done=4, questions_correct=0).correct_rate == 0.0
    assert _act("2026-01-01", questions_done=4, questions_correct=3).correct_rate == 75.0


def test_reviews_done_sums_all_item_types():
    d = _act("2026-01-01", words_done=3, cards_done=2, knowledge_done=4, errors_done=1)
    assert d.reviews_done == 10


# --------------------------------------------------------------------------- #
# 2. streak
# --------------------------------------------------------------------------- #
def test_streak_does_not_break_when_today_not_studied():
    """今天还没学时从昨天往前数，否则白天任何时候打开首页都显示"断签"。"""
    today = datetime.date(2026, 10, 17)
    led = _ledger(
        _act("2026-10-16", focus_minutes=60),
        _act("2026-10-15", focus_minutes=60),
    )
    out = streak_summary(led, today=today)
    assert out["current"] == 2
    assert out["checked_today"] is False


def test_streak_counts_today_when_effective():
    today = datetime.date(2026, 10, 17)
    led = _ledger(
        _act("2026-10-17", questions_done=9),
        _act("2026-10-16", questions_done=9),
    )
    out = streak_summary(led, today=today)
    assert out["current"] == 2
    assert out["checked_today"] is True


def test_streak_gaps_and_longest():
    """中间断一天就断当前；历史最长另算，两者不能混。"""
    today = datetime.date(2026, 10, 17)
    led = _ledger(*[
        _act(f"2026-10-{d:02d}", focus_minutes=30)
        for d in (17, 16, 15, 13, 12, 11, 10, 8)
    ])
    out = streak_summary(led, today=today)
    assert out["current"] == 3          # 17/16/15，14 缺失
    assert out["longest"] == 4          # 13~10
    assert out["total_days"] == 8       # 有效天数走全量，不受窗口影响
    assert out["first_day"] == "2026-10-08"


def test_streak_below_threshold_is_not_counted():
    """估算时长进不了台账：只专注 3 分钟的日子不算打卡日。"""
    today = datetime.date(2026, 10, 17)
    led = _ledger(_act("2026-10-16", focus_minutes=3, tasks_done=2))
    assert streak_summary(led, today=today)["current"] == 0


def test_streak_on_empty_ledger():
    """空库口径：全 0 而不是 None/报错，前端才能直接渲染。"""
    out = streak_summary({}, today=datetime.date(2026, 10, 17))
    assert out == {
        "current": 0,
        "longest": 0,
        "total_days": 0,
        "checked_today": False,
        "first_day": None,
        "rule": out["rule"],
    }


# --------------------------------------------------------------------------- #
# 3. fill_series / 热力图格子
# --------------------------------------------------------------------------- #
def test_fill_series_pads_missing_days_with_zero():
    led = _ledger(_act("2026-10-01", focus_minutes=50), _act("2026-10-04", focus_minutes=50))
    series = fill_series(led, datetime.date(2026, 10, 1), datetime.date(2026, 10, 5))
    assert [d.date.isoformat() for d in series] == [
        "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05",
    ]
    assert series[1].focus_minutes == 0
    assert series[1].date == datetime.date(2026, 10, 2)


def test_heatmap_grid_starts_on_monday_and_ends_today():
    """首列对齐周一（否则前端按周分列会错位半列），末日就是今天（不铺未来格子）。"""
    today = datetime.date(2026, 10, 17)  # 周六
    cells = effective_activity_days({}, weeks=4, today=today)
    assert cells[-1]["date"] == "2026-10-17"
    first = datetime.date.fromisoformat(cells[0]["date"])
    assert first.weekday() == 0, f"起点必须是整周周一，实际 {first} 是周{first.weekday()}"
    assert len(cells) >= 4 * 7, "回看周数不足"
    # 逐日连续，中间不能缺格
    assert [c["date"] for c in cells] == [
        (first + datetime.timedelta(days=i)).isoformat() for i in range(len(cells))
    ]


def test_heatmap_carries_the_per_day_fields_the_frontend_draws():
    led = _ledger(_act("2026-10-17", focus_minutes=45, questions_done=12, questions_correct=9))
    cells = effective_activity_days(led, weeks=2, today=datetime.date(2026, 10, 17))
    today_cell = cells[-1]
    assert today_cell["focus_minutes"] == 45
    assert today_cell["questions_done"] == 12
    assert today_cell["correct_rate"] == 75.0
    assert today_cell["is_effective"] is True


# --------------------------------------------------------------------------- #
# 4. day_ledger 聚合（走临时库）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db(db_schema):  # noqa: ARG001 — db_schema 负责建表（含 core/sql 分片）
    from database import SessionLocal

    s = SessionLocal()
    try:
        yield s
    finally:
        from models import AnswerRecord, ErrorRecord, ReviewRecord, StudySession, Task

        for model, col in (
            (StudySession, StudySession.subject),
            (AnswerRecord, AnswerRecord.subject),
            (ReviewRecord, ReviewRecord.subject),
            (ErrorRecord, ErrorRecord.subject),
            (Task, Task.subject),
        ):
            s.query(model).filter(col == MARK).delete()
        s.commit()
        s.close()


def test_day_bucket_uses_beijing_midnight(db):
    """UTC 16:30 = 北京次日 00:30：必须落到**次日**的桶里，这是日界唯一口径。"""
    from models import AnswerRecord

    db.add_all([
        # 北京 3/5 23:30（UTC 15:30）
        AnswerRecord(created_at=datetime.datetime(2001, 3, 5, 15, 30), subject=MARK, is_correct=True),
        # 北京 3/6 00:30（UTC 3/5 16:30）—— 同一 UTC 日、不同北京日
        AnswerRecord(created_at=datetime.datetime(2001, 3, 5, 16, 30), subject=MARK, is_correct=False),
    ])
    db.commit()

    led = day_ledger(db, start_day=HIST[0], end_day=HIST[1])
    assert led["2001-03-05"].questions_done == 1
    assert led["2001-03-06"].questions_done == 1
    assert led["2001-03-05"].questions_correct == 1
    assert led["2001-03-06"].questions_correct == 0


def test_focus_minutes_only_from_study_sessions(db):
    """study_sessions.date 是 Date 列（本身就是本地日），直接求和、不参与时区换算。"""
    from models import StudySession

    db.add_all([
        StudySession(date=HIST[0], duration=30, subject=MARK),
        StudySession(date=HIST[0], duration=15, subject=MARK),
        StudySession(date=HIST[1], duration=60, subject=MARK),
    ])
    db.commit()

    led = day_ledger(db, start_day=HIST[0], end_day=HIST[1])
    assert led["2001-03-05"].focus_minutes == 45
    assert led["2001-03-07"].focus_minutes == 60
    # 有专注记录但没有答题记录 → 正确率仍是 None，不是 0
    assert led["2001-03-05"].correct_rate is None


def test_review_records_split_by_item_type(db):
    from models import ReviewRecord

    db.add_all([
        ReviewRecord(item_type="word", item_id=1, subject=MARK, created_at=_IN_WIN),
        ReviewRecord(item_type="word", item_id=2, subject=MARK, created_at=_IN_WIN),
        ReviewRecord(item_type="flashcard", item_id=3, subject=MARK, created_at=_IN_WIN),
        ReviewRecord(item_type="knowledge", item_id=4, subject=MARK, created_at=_IN_WIN),
        ReviewRecord(item_type="error", item_id=5, subject=MARK, created_at=_IN_WIN),
    ])
    db.commit()

    led = day_ledger(db, start_day=HIST[0], end_day=HIST[0])
    day = led["2001-03-05"]
    assert (day.words_done, day.cards_done, day.knowledge_done, day.errors_done) == (2, 1, 1, 1)
    assert day.reviews_done == 5


def test_tasks_counted_only_by_completed_at(db):
    """status=done 但没有 completed_at 的老数据不能算"今天完成"——那只是今天改过状态。"""
    from models import Task

    done_today = Task(title="台账-已完成", subject=MARK, status="done",
                      completed_at=datetime.datetime(2001, 3, 5, 2, 0))
    stale = Task(title="台账-缺完成时间", subject=MARK, status="done", completed_at=None)
    db.add_all([done_today, stale])
    db.commit()

    led = day_ledger(db, start_day=HIST[0], end_day=HIST[0])
    assert led["2001-03-05"].tasks_done == 1


def test_window_excludes_days_outside_range(db):
    from models import AnswerRecord

    db.add_all([
        AnswerRecord(created_at=datetime.datetime(2001, 2, 4, 2, 0), subject=MARK),
        AnswerRecord(created_at=datetime.datetime(2001, 3, 5, 2, 0), subject=MARK),
        AnswerRecord(created_at=datetime.datetime(2001, 4, 5, 2, 0), subject=MARK),
    ])
    db.commit()

    led = day_ledger(db, start_day=HIST[0], end_day=HIST[1])
    assert set(led) == {"2001-03-05"}, f"窗口外的日子漏进来了：{sorted(led)}"


def test_end_day_is_inclusive(db):
    """``end_day`` 是**闭**区间端点：start==end 时也要拿到那一天。
    右开边界一旦算成"end_day 当天零点"，最后一天整列静默丢失（今日 KPI 恒为 0）。
    """
    from models import AnswerRecord

    db.add(AnswerRecord(created_at=_IN_WIN, subject=MARK, is_correct=True))
    db.commit()

    led = day_ledger(db, start_day=HIST[0], end_day=HIST[0])
    assert led["2001-03-05"].questions_done == 1


def test_empty_range_gives_empty_ledger(db):
    """空库基线：没有数据的日子不编造，台账为空让上层走空态。"""
    assert day_ledger(db, start_day=datetime.date(1999, 1, 1),
                      end_day=datetime.date(1999, 1, 3)) == {}
