# -*- coding: utf-8 -*-
"""W1 数据真实性底座 · 接口级回归（**需要真实 PostgreSQL**）。

覆盖只有连库才能验证的三件事：

1. **今日推荐量不再等于整库到期**：给测试用户灌 800 条到期单词 + 200 张到期卡片
   + 120 道到期错题，``today_plan.items_total`` 必须落在合理量之内，
   而 ``future_load`` 仍如实反映欠账（债要说，但不能当今日任务）；
2. **模块进度按科目区分且不混入工具模块**：``module_progress`` 不含 ``coding``，
   它出现在 ``tool_modules`` 且标 ``counts_toward_study=False``；
3. **阈值闸门在 HTTP 层生效**：``PUT /api/goals`` 传 2000 分返回统一错误壳。

本机 PG 不可用时这些用例跑不了（依赖 conftest 的 ``client`` / ``db_schema``）。
在配好 PG 的机器上跑::

    python -m pytest tests/test_daily_load_w1.py -q -p no:langsmith_plugin

纯逻辑部分（钳制算法、阈值表、跨字段校验）在 ``tests/test_study_limits_w1.py``，
那个文件加 ``--noconftest`` 无库也能跑。

## 数据卫生（遵守"禁跨表误删"红线）

- 种子行一律带 ``TAG`` 前缀，清理只按 ``like 'TAG%'``，**不整表删、不按 user_id 删**；
- 不写 ``goals`` 行：需要特定配额时用 ``today_plan(goal=...)`` 注入内存对象，
  避免与同库其他用例的目标行互相干扰（HTTP 层断言只写"上界"不写"恰好等于"）。
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest
from database import SessionLocal
from models import ErrorRecord, Flashcard, QuizQuestion, Task, Word
from utils.timeutil import local_today, utcnow

#: 测试主体 ID（与 utils.security.stub_principal 一致，conftest 已建 users 行）
UID = 0
TAG = "w1plan"

#: 注入用的"用户目标配额"（不落库，避免和别人的 goals 行抢顺序）
QUOTA_GOAL = SimpleNamespace(
    daily_new_words=20,
    daily_review_words=50,
    daily_questions=10,
    daily_focus_minutes=120,
)

DUE_WORDS = 800
DUE_CARDS = 200
DUE_ERRORS = 120


def _cleanup(db):
    """只删本文件按 TAG 前缀种下的行（红线：不跨表、不按 user_id 批量删）。"""
    for model, col in (
        (Word, Word.word),
        (Flashcard, Flashcard.front),
        (Task, Task.title),
        (ErrorRecord, ErrorRecord.content),
        (QuizQuestion, QuizQuestion.content),
    ):
        db.query(model).filter(col.like(f"{TAG}%")).delete(synchronize_session=False)
    db.commit()


@pytest.fixture()
def heavy_debt(db_schema):  # noqa: ARG001
    """灌入"整库当今日"级别的到期数据（全部归属测试用户）。"""
    db = SessionLocal()
    now = utcnow()
    today = local_today()
    try:
        db.add_all(
            [
                Word(word=f"{TAG}w{i}", meaning="测试", status="reviewing", due_date=today, user_id=UID)
                for i in range(DUE_WORDS)
            ]
        )
        # 未学库存（not_mastered）：今日新词轨道的分母来自本人词库库存。
        # 没有它，配额 20 会被诚实判成 stock_limited=0（新号未导入词书就该这样）；
        # 这里要验证的是"有库存时按配额排"，所以种一小批。
        db.add_all([Word(word=f"{TAG}n{i}", meaning="未学", status="not_mastered", user_id=UID) for i in range(60)])
        db.add_all(
            [
                Flashcard(front=f"{TAG}c{i}", back="b", next_review=now - datetime.timedelta(hours=1), user_id=UID)
                for i in range(DUE_CARDS)
            ]
        )
        db.add_all(
            [
                ErrorRecord(
                    content=f"{TAG}e{i}",
                    correct_answer="B",
                    my_answer="A",
                    subject="数学",
                    status="active",
                    next_review=now - datetime.timedelta(hours=1),
                    user_id=UID,
                )
                for i in range(DUE_ERRORS)
            ]
        )
        # 已完成且到期的任务：不得继续算进"今日待办"到期量（去噪点）
        db.add(
            Task(
                title=f"{TAG}t-done",
                subject="数学",
                task_type="学习",
                stage="basic",
                status="done",
                due_date=today,
                user_id=UID,
                next_review=now - datetime.timedelta(hours=1),
            )
        )
        # 可练题库存：题库轨道没有排程字段，今日刷题量 = min(配额, 有界库存)。
        # 测试库重建成空表时诚实返回 0（新号无题可练），所以这里必须种题，
        # 才能验证"有库存时按配额排 10 道"而不是永远 stock_limited。
        db.add_all(
            [QuizQuestion(content=f"{TAG}q{i}", answer="B", subject="数学", is_available=True) for i in range(30)]
        )
        db.commit()
        yield
    finally:
        _cleanup(db)
        db.close()


def test_today_plan_caps_whole_library_debt(heavy_debt):  # noqa: ARG001
    """核心回归：800 词到期 ≠ 今日 800 词任务；今日量按配额排，差额进复习债。"""
    db = SessionLocal()
    try:
        from services import daily_load, study_limits

        plan = daily_load.today_plan(db, user_id=UID, goal=QUOTA_GOAL)
        by = daily_load.plan_by_key(plan)

        assert by["review_words"]["value"] == 50, "今日复习词量应等于用户配额"
        assert by["review_words"]["over_quota"] == DUE_WORDS - 50
        assert by["review_words"]["basis"] == "goal"
        assert by["new_words"]["value"] == 20
        assert by["questions"]["value"] == 10
        assert by["focus"]["value"] == 120
        # 卡片/错题没有目标列 → 走 TODAY_TRACK_CAPS 上限，不会把 200/120 全压今天
        assert by["cards"]["value"] <= study_limits.TODAY_TRACK_CAPS["cards"]["max"]
        assert by["errors"]["value"] <= study_limits.TODAY_TRACK_CAPS["errors"]["max"]

        # 每条轨道都可追溯
        for t in plan["tracks"]:
            assert t["basis"] in {"goal", "goal_capped", "system_default", "stock_limited"}
            assert t["note"], f"{t['key']} 缺可追溯说明"

        # 总量必须落在"一天做得完"的量级（远小于 1120 条到期）
        assert plan["items_total"] < DUE_WORDS, "把整库到期当今日任务 = 制造恐慌"
        assert plan["backlog"]["due_total"] >= DUE_WORDS + DUE_CARDS + DUE_ERRORS
        assert plan["backlog"]["outside_today"] > 0
        assert plan["backlog"]["clear_days"] >= 1
        assert plan["version"] == daily_load.PLAN_VERSION
        assert plan["focus_minutes"] == 120
        # 专注是分钟，不能并进"项"
        assert all(t["countable"] is False for t in plan["tracks"] if t["key"] == "focus")
    finally:
        _cleanup(db)
        db.close()


def test_done_tasks_are_not_counted_as_due(heavy_debt):  # noqa: ARG001
    """已完成的到期任务不进复习债：否则"做完了"还被显示成欠着。"""
    db = SessionLocal()
    try:
        from services import daily_load

        due = daily_load.due_counts(db, local_today(), UID)
        tag_rows = db.query(Task).filter(Task.title.like(f"{TAG}%")).all()
        assert tag_rows, "种子任务没写进去"
        assert due["tasks"] == 0, "唯一到期的任务是 done，不该计入到期"
    finally:
        _cleanup(db)
        db.close()


def test_subject_scope_filters_due_and_reports_noise(heavy_debt):  # noqa: ARG001
    """科目去噪：所选科目不含"数学"时，数学错题不计入今日到期，但差额要可见。"""
    db = SessionLocal()
    try:
        from services import daily_load

        no_math = daily_load.due_counts(db, local_today(), UID, subjects=["英语"])
        with_math = daily_load.due_counts(db, local_today(), UID, subjects=["数学"])
        none_set = daily_load.due_counts(db, local_today(), UID)

        assert no_math["errors"] == 0
        assert with_math["errors"] == DUE_ERRORS
        # 未配置科目 = 不过滤（新号不该被"零科目"抹掉真实欠账）
        assert none_set["errors"] == DUE_ERRORS
        assert none_set["subject_scope"] is None
        assert no_math["outside_scope"] >= DUE_ERRORS
        assert no_math["total_all"] == none_set["total_all"]
    finally:
        _cleanup(db)
        db.close()


def test_endpoint_returns_plan_and_summary_carries_it(client, heavy_debt):  # noqa: ARG001
    """``/api/dashboard/today-plan`` 可单独取，且与 summary 内嵌的那份同值。"""
    plan = client.get("/api/dashboard/today-plan").json()
    assert plan["tracks"], "今日推荐量必须带轨道明细"
    summary = client.get("/api/dashboard/summary").json()
    assert summary["today_plan"]["items_total"] == plan["items_total"]
    # 复习债仍在 future_load，但语义被 rule 明确区隔，前端不会拿它当今日量
    assert "复习债" in summary["future_load"]["rule"]
    # 主数字口径：today_plan 必须显著小于整库到期，否则这次整改没生效
    assert summary["today_plan"]["items_total"] < summary["future_load"]["due_today"]["total_all"]


def test_module_progress_excludes_tool_modules(client, db_schema):  # noqa: ARG001
    """模块进度不混入代码上机（OJ 未挂载、非备考科目）。"""
    summary = client.get("/api/dashboard/summary").json()
    mods = {m["module"] for m in summary["module_progress"]}
    assert "coding" not in mods, "代码上机不该出现在学习模块进度里"
    assert "new_word" in mods or "word" in mods
    tools = {m["module"]: m for m in summary["tool_modules"]}
    assert tools["coding"]["counts_toward_study"] is False
    assert tools["coding"]["reason"]


def test_module_progress_target_is_sourced(client, db_schema):  # noqa: ARG001
    """进度环分母要么来自用户目标、要么来自今日推荐量，且一定写明来源。"""
    summary = client.get("/api/dashboard/summary").json()
    for m in summary["module_progress"]:
        if m["target"] is not None:
            assert m["target_source"] in {"goal", "today_plan"}, m
        else:
            assert m["status"] in {"no_target", "not_tracked"}, m
            assert m["percent"] is None, "没有分母却给出百分比 = 编数字"


def test_goals_put_rejects_absurd_scores_with_error_shell(client, db_schema):  # noqa: ARG001
    """PUT /api/goals 的 2000 分必须被统一错误壳挡下（不是 500、不是静默写入）。"""
    r = client.put("/api/goals", json={"total_score_target": 2000})
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == "INVALID_PARAMETER"
    assert body.get("message")

    assert client.put("/api/goals", json={"politics_target": 120}).status_code == 422
    assert client.put("/api/goals", json={"daily_new_words": 2000}).status_code == 422

    # 分项之和超 500 也要挡（跨字段规则，Pydantic 单字段边界看不到的那类）
    bad_sum = client.put(
        "/api/goals",
        json={
            "politics_target": 100,
            "english_target": 100,
            "math_target": 200,
            "major_target": 300,
            "remark": f"{TAG}-badsum",
        },
    )
    assert bad_sum.status_code == 422, bad_sum.text

    ok = client.put(
        "/api/goals",
        json={
            "total_score_target": 400,
            "politics_target": 70,
            "english_target": 70,
            "math_target": 120,
            "major_target": 140,
            "remark": f"{TAG}-ok",
        },
    )
    assert ok.status_code == 200, ok.text

    db = SessionLocal()
    try:
        db.query(Task).filter(Task.title.like(f"{TAG}%")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_words_stats_labels_stock_vs_today(client, heavy_debt):  # noqa: ARG001
    """/api/words/stats 的 ``new`` 是库存；今日量另给，界面才不会写出"一天 11653 词"。"""
    d = client.get("/api/words/stats").json()
    assert d["due_today"] >= DUE_WORDS, "到期复习债要如实反映"
    assert d["today_review"] is not None
    assert d["today_review"] < d["due_today"], "今日推荐量不得超过到期总量"
    assert "库存" in d["usage"] or "不是今日任务量" in d["usage"], d
    assert d["today_basis"]["review_words"] in {"goal", "system_default", "stock_limited", "goal_capped"}


def test_insight_today_uses_planned_counts(client, heavy_debt):  # noqa: ARG001
    """今日引导的建议卡数字改成"今日排入量"，真实队列长度另用 due_total 说明。"""
    d = client.get("/api/insight/today").json()
    review = next(s for s in d["suggestions"] if s["icon"] == "review")
    assert review["count"] <= d["today_plan"]["planned_review"]
    assert "due_total" in review, "今日量与欠账量必须同时可见"
    assert d["today_plan"]["source"] == "services.daily_load.today_plan"


def test_zero_data_account_gets_honest_empty_plan(client, db_schema):  # noqa: ARG001
    """零数据账号：本人口径下的到期类轨道必须全 0（不拿模板/他人数据冒充）。"""
    db = SessionLocal()
    try:
        _cleanup(db)
        from services import daily_load

        # 不带任何 tag 行、也不注入目标：到期类轨道应如实为 0
        plan = daily_load.today_plan(db, user_id=999999)  # 不存在的用户 = 零数据
        by = daily_load.plan_by_key(plan)
        for key in ("review_words", "cards", "errors", "tasks"):
            assert by[key]["value"] == 0, f"{key} 无到期内容却给出了今日量：{by[key]}"
            assert by[key]["basis"] == "stock_limited", by[key]
        assert plan["items_total"] == 0 or by["questions"]["value"] > 0
    finally:
        db.close()
