"""今日任务清单按模块到期聚合（01-仪表盘 §2.3 / D-03）。

锁四件事：
1. 模块集合与 `_DUE_ROLLUP` 一致，且**没有 percent**（到期数与今日完成数是两条
   独立的事，相除必然编出"进度 120%"这种答案）；
2. 无排程源的模块（刷题/真题）给 `due=null` + `not_tracked` + note，
   **不给 0** —— "0 个到期"会把"调度器没接入"渲染成"你今天没欠东西"；
3. 清单里的到期数和 `future_load.due_today` **逐个模块相等**（同一份 `_due_counts`，
   不可能出现两个"今日到期"）；
4. 今日到期的任务连 `done` 状态一起进清单 —— 否则进度环永远显示 0/N。
"""
from __future__ import annotations

import datetime

import pytest

MODULES = {"word", "card", "wrongbook", "task", "question", "realexam"}


@pytest.fixture()
def seeded(db_schema):  # noqa: ARG001
    """写入可识别的到期数据（唯一前缀），用完即删，别污染同库其他用例。"""
    from database import SessionLocal
    from models import ErrorRecord, Flashcard, Task, Word
    from utils.timeutil import local_today

    tag = "d03rollup"
    db = SessionLocal()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    today = local_today()
    try:
        db.add_all([
            Flashcard(front=f"{tag}-f1", back="b", next_review=now - datetime.timedelta(hours=2)),
            Flashcard(front=f"{tag}-f2", back="b", next_review=now - datetime.timedelta(minutes=5)),
            # 未来的排程不该计入今日到期
            Flashcard(front=f"{tag}-future", back="b",
                      next_review=now + datetime.timedelta(days=3)),
            ErrorRecord(content=f"{tag}-e", correct_answer="B", my_answer="A",
                        subject="数学", status="active",
                        next_review=now - datetime.timedelta(hours=1)),
            # status=resolved 的错题不计入到期队列
            ErrorRecord(content=f"{tag}-gone", correct_answer="B", my_answer="A",
                        subject="数学", status="resolved",
                        next_review=now - datetime.timedelta(hours=1)),
            Task(title=f"{tag}-todo", subject="数学", task_type="学习",
                 stage="basic", status="pending", due_date=today,
                 next_review=now - datetime.timedelta(hours=1), priority=5),
            Task(title=f"{tag}-done", subject="英语", task_type="刷题",
                 stage="basic", status="done", due_date=today, priority=3),
            Word(word=f"{tag}w1", meaning="测试", status="not_mastered", due_date=today),
        ])
        db.commit()
        yield tag
    finally:
        db.query(Flashcard).filter(Flashcard.front.like(f"{tag}%")).delete(synchronize_session=False)
        db.query(ErrorRecord).filter(ErrorRecord.content.like(f"{tag}%")).delete(synchronize_session=False)
        db.query(Task).filter(Task.title.like(f"{tag}%")).delete(synchronize_session=False)
        db.query(Word).filter(Word.word.like(f"{tag}%")).delete(synchronize_session=False)
        db.commit()
        db.close()


def _by_module(payload):
    return {m["module"]: m for m in payload["modules"]}


def test_module_set_and_no_invented_percent(seeded):
    from services.dashboard_service import DashboardService
    from database import SessionLocal

    db = SessionLocal()
    try:
        payload = DashboardService.get_today_tasks(db)
    finally:
        db.close()

    got = _by_module(payload)
    assert set(got) == MODULES, f"D-03 模块集合漂移：{sorted(got)}"
    for m in payload["modules"]:
        assert "percent" not in m, f"{m['module']} 给出了 percent：到期数÷完成数是假进度"
        assert m["status"] in {"pending", "clear", "not_tracked"}
        assert m["due"] is None or m["due"] >= 0


def test_modules_without_scheduler_report_null_with_note(seeded):
    """刷题/真题没有排程源：due=null + not_tracked + 说明缺的是哪一块。"""
    from services.dashboard_service import DashboardService
    from database import SessionLocal

    db = SessionLocal()
    try:
        got = _by_module(DashboardService.get_today_tasks(db))
    finally:
        db.close()

    for module in ("question", "realexam"):
        assert got[module]["due"] is None, f"{module} 没有排程源却给出了到期数"
        assert got[module]["status"] == "not_tracked"
        assert got[module]["note"], f"{module} not_tracked 必须说明原因"
        # 完成数另有台账来源（study_events），不因 due=None 而连带抹成 None
        assert isinstance(got[module]["done"], int)


def test_scheduled_modules_count_only_due(seeded):
    """到期数只数真到期的：未来排程与 resolved 错题都不该进账。"""
    from services.dashboard_service import DashboardService
    from database import SessionLocal
    from utils.timeutil import local_today

    db = SessionLocal()
    try:
        got = _by_module(DashboardService.get_today_tasks(db))
        due = DashboardService._due_counts(db, local_today())
    finally:
        db.close()

    assert got["card"]["due"] == due["flashcards"] >= 2, "两张到期卡 + 一张未来卡：未来卡不得计入"
    assert got["wrongbook"]["due"] == due["errors"] >= 1, "resolved 错题不得计入到期"
    assert got["word"]["due"] == due["words"] >= 1
    assert got["task"]["due"] == due["tasks"] >= 1
    assert got["card"]["status"] == got["wrongbook"]["status"] == "pending"


def test_rollup_agrees_with_future_load(client, seeded):
    """首屏两处「今日到期」必须同值：一次查询两处用，不是两份实现。"""
    summary = client.get("/api/dashboard/summary").json()
    due = summary["future_load"]["due_today"]
    got = _by_module(summary["today_tasks"])
    assert got["word"]["due"] == due["words"]
    assert got["card"]["due"] == due["flashcards"]
    assert got["wrongbook"]["due"] == due["errors"]
    assert got["task"]["due"] == due["tasks"]


def test_today_done_tasks_are_still_listed(seeded):
    """已完成的任务要留在清单里：否则"完成 0/N"的进度环永远显示 0%。"""
    from database import SessionLocal
    from services.dashboard_service import DashboardService

    db = SessionLocal()
    try:
        payload = DashboardService.get_today_tasks(db)
    finally:
        db.close()

    titles = {t["title"] for t in payload["tasks"]}
    assert f"{seeded}-done" in titles, "今日已到期的 done 任务被过滤掉了"
    assert payload["done"] >= 1
    assert payload["total"] == payload["pending"] + payload["doing"] + payload["done"]


def test_legacy_dashboard_endpoint_carries_the_same_modules(client, seeded):
    """/api/dashboard 与 /summary 的清单同源（同一个函数的两次调用）。"""
    legacy = client.get("/api/dashboard").json()["today_tasks"]
    summary = client.get("/api/dashboard/summary").json()["today_tasks"]
    assert _by_module(legacy) == _by_module(summary)
