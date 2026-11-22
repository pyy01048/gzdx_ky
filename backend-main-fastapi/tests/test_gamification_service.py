# -*- coding: utf-8 -*-
"""金币激励服务单测（W6）。

**刻意不依赖 conftest**：本仓库的 ``tests/conftest.py`` 会把整会话绑到共享的
``kaoyan_test`` PostgreSQL 库（session 级 autouse 重建 schema，首轮 >120s）。
激励逻辑（幂等、上限、补签、兑换、双记账）是纯服务层规则，用**独立内存 SQLite**
跑既能本机常跑、又不会和并行波次互相污染数据。

表结构来自 ORM（``core/models/gamification.py`` 带 sqlite variant，与
``core/sql/125_gamification_coins.sql`` 同构）；台账侧只建 ``day_ledger`` 真正查的
几张表，其余一律不建 —— 建少了会在测试里当场炸，比在生产里"表不存在所以静默 0"好。

跑法（PG 起不起都无关）：
    LANGSMITH_TRACING=false python -m pytest tests/test_gamification_service.py -q \\
        --noconftest -p no:cacheprovider -p no:langsmith_plugin
"""

from __future__ import annotations

import datetime
import os
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import core.models.gamification as gami_models  # noqa: E402,F401  (把激励表挂进元数据)
from core.models.base import Base as CoreBase  # noqa: E402
from database import Base as LegacyBase  # noqa: E402
from models import AnswerRecord, ReviewRecord, StudySession, Task  # noqa: E402
from services import gamification as gami  # noqa: E402
from services.study_calendar import day_ledger  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from utils.exceptions import BusinessException  # noqa: E402
from utils.timeutil import local_today, local_window_for_day  # noqa: E402

USER_ID = 777
OTHER_ID = 778

_TABLES = (
    "coin_accounts",
    "coin_ledger",
    "checkin_logs",
    "gamification_rules",
    "gamification_settings",
    "reward_items",
    "redemptions",
    "user_profiles",
)


@pytest.fixture()
def db():
    """独立内存库：激励表（core Base）+ 日活台账会读到的四张业务表。

    ``check_same_thread=False`` + ``StaticPool`` 是给下面的 HTTP 用例准备的：
    ``TestClient`` 把请求跑在它自己的工作线程里，默认的 in-memory 连接跨线程
    直接 ``ProgrammingError``（StaticPool 让所有线程共用同一条内存连接，
    顺带也保证 ``sqlite://`` 只有一个库，不会各线程各建一个空库）。
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    CoreBase.metadata.create_all(engine, tables=[CoreBase.metadata.tables[t] for t in _TABLES])
    legacy = LegacyBase.metadata
    ledger_tables = [
        t
        for t in ("study_sessions", "review_records", "answer_records", "tasks", "error_records")
        if t in legacy.tables
    ]
    legacy.create_all(engine, tables=[legacy.tables[t] for t in ledger_tables])
    session = sessionmaker(bind=engine)()
    gami._ensured_urls.clear()
    yield session
    session.close()


# --------------------------------------------------------------------------- #
# 造数：所有时间都落在"目标北京日的正午"，避免任何日界歧义
# --------------------------------------------------------------------------- #
def _noon(day: datetime.date) -> datetime.datetime:
    return local_window_for_day(day)[0] + datetime.timedelta(hours=12)


def add_words(session, day, count, *, user_id=USER_ID):
    for i in range(count):
        session.add(ReviewRecord(user_id=user_id, item_type="word", item_id=1000 + i, created_at=_noon(day)))


def add_error_reviews(session, day, count, *, user_id=USER_ID):
    for i in range(count):
        session.add(ReviewRecord(user_id=user_id, item_type="error", item_id=2000 + i, created_at=_noon(day)))


def add_answers(session, day, total, correct, *, user_id=USER_ID):
    for i in range(total):
        session.add(
            AnswerRecord(
                user_id=user_id,
                question_id=3000 + i,
                is_correct=bool(i < correct),
                created_at=_noon(day),
            )
        )


def add_focus(session, day, minutes, *, user_id=USER_ID):
    session.add(StudySession(user_id=user_id, date=day, duration=minutes, task_type="pomodoro"))


def add_tasks(session, day, count, *, user_id=USER_ID):
    for i in range(count):
        session.add(
            Task(
                user_id=user_id,
                title=f"任务{i}",
                status="done",
                completed_at=_noon(day),
            )
        )


def rows_of(session, user_id=USER_ID, rule=None):
    q = session.query(gami_models.CoinLedger).filter(gami_models.CoinLedger.user_id == user_id)
    if rule:
        q = q.filter(gami_models.CoinLedger.rule_code == rule)
    return q.all()


def balance(session, user_id=USER_ID):
    acct = gami.find_account(session, user_id)
    return int(acct.balance) if acct else 0


# --------------------------------------------------------------------------- #
# 播种与默认值
# --------------------------------------------------------------------------- #
def test_schema_and_defaults_are_seeded(db):
    gami.ensure_gamification_schema(db)
    rules = {r["rule_code"] for r in gami.list_rules(db)}
    assert {"word_review", "error_review", "checkin"} <= rules
    settings = gami.get_settings(db)
    assert settings["daily_earn_cap"] == 260
    assert settings["streak_milestones"] == {"3": 10, "7": 25, "14": 60, "30": 150}
    assert {i["code"] for i in gami.list_items(db)} >= {"makeup_card", "coin_boost", "frame_flame"}
    # 幂等：第二次播种不得重复插、也不得覆盖已有行
    gami.admin_update_rule(db, "word_review", {"coins": 15})
    gami.ensure_gamification_schema(db)
    assert gami.rule_map(db)["word_review"]["coins"] == 15


def test_zero_data_user_is_honest_empty(db):
    gami.ensure_gamification_schema(db)
    s = gami.summary(db, USER_ID)
    assert s["state"] == "empty"
    assert s["account"]["balance"] == 0
    assert s["streak"]["checkin_days"] == 0 and s["streak"]["study_days"] == 0
    assert s["today"]["is_active"] is False
    # 零数据用户不能被顺手建出行（避免"为了显示 0 而插入"的伪记录）
    assert gami.find_account(db, USER_ID) is None


# --------------------------------------------------------------------------- #
# sync：折算、幂等、上限
# --------------------------------------------------------------------------- #
def test_sync_pays_per_batch_and_is_idempotent(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    add_words(db, today, 12)  # 1 轮（10 词）→ 10 币，余 2 词不计
    add_error_reviews(db, today, 6)  # 1 批（5 题）→ 20 币
    db.commit()

    res = gami.sync_day(db, USER_ID)
    assert res["granted_coins"] == 30, res
    assert balance(db) == 30
    assert {r.rule_code: r.coins for r in rows_of(db)} == {"word_review": 10, "error_review": 20}

    again = gami.sync_day(db, USER_ID)
    assert again["granted_coins"] == 0
    assert balance(db) == 30  # 重放十次也还是 30：这就是 dedup_key 唯一索引的意义


def test_sync_grants_next_unit_when_count_grows(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    add_words(db, today, 10)
    db.commit()
    assert gami.sync_day(db, USER_ID)["granted_coins"] == 10

    add_words(db, today, 10)  # 累计 20 词 = 2 轮，只补第 2 轮
    db.commit()
    res = gami.sync_day(db, USER_ID)
    assert res["granted_coins"] == 10
    assert len(rows_of(db, rule="word_review")) == 2


def test_per_rule_daily_cap(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    add_words(db, today, 100)  # 10 轮，但 word_review 单日 3 次封顶
    db.commit()
    res = gami.sync_day(db, USER_ID)
    word = next(r for r in res["items"] if r["rule_code"] == "word_review")
    assert word["units"] == 3 and word["coins"] == 30
    assert word["capped"] is True


def test_global_daily_cap_is_honest_not_silent(db):
    """单日把所有规则刷满也只有约 238 币（低于 260 上限），所以这里把上限调低来验证截断。

    这条同时锁死一个产品结论：**正常一天不可能顶到全局上限**，
    全局上限只是兜住"管理员把某条规则调飞"的极端情况。
    """
    gami.ensure_gamification_schema(db)
    today = local_today()
    add_words(db, today, 100)
    add_error_reviews(db, today, 50)
    add_answers(db, today, 100, 100)
    add_focus(db, today, 600)
    db.commit()
    full = gami.sync_day(db, USER_ID)
    assert full["granted_coins"] <= gami.get_settings(db)["daily_earn_cap"]
    assert full["granted_coins"] == 130  # 30 + 40 + 36 + 24：各规则单日上限之和
    assert not any(i.get("capped") and i["cap_reason"] == "earn_daily_cap" for i in full["items"])

    gami.admin_update_settings(db, {"daily_earn_cap": 40})
    other = local_today() - datetime.timedelta(days=1)
    add_words(db, other, 100)
    add_error_reviews(db, other, 50)
    db.commit()
    res = gami.sync_day(db, USER_ID, day=other)
    assert res["granted_coins"] <= 40
    assert any(i.get("capped") and i["cap_reason"] == "earn_daily_cap" for i in res["items"])
    assert balance(db) == full["granted_coins"] + res["granted_coins"]


def test_disabled_rule_stops_paying(db):
    gami.ensure_gamification_schema(db)
    gami.admin_update_rule(db, "word_review", {"is_active": False})
    today = local_today()
    add_words(db, today, 40)
    db.commit()
    res = gami.sync_day(db, USER_ID)
    assert res["granted_coins"] == 0
    assert rows_of(db, rule="word_review") == []


def test_future_day_has_no_coins(db):
    gami.ensure_gamification_schema(db)
    res = gami.sync_day(db, USER_ID, day=local_today() + datetime.timedelta(days=3))
    assert res["granted_coins"] == 0 and res["activity"]["is_active"] is False


def test_isolation_between_users(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    add_words(db, today, 30, user_id=USER_ID)
    add_words(db, today, 30, user_id=OTHER_ID)
    db.commit()
    gami.sync_day(db, USER_ID)
    assert balance(db, OTHER_ID) == 0
    assert gami.summary(db, OTHER_ID)["state"] == "empty"
    assert rows_of(db, user_id=OTHER_ID) == []


# --------------------------------------------------------------------------- #
# 签到 / 连续 / 里程碑
# --------------------------------------------------------------------------- #
def test_checkin_requires_real_activity(db):
    gami.ensure_gamification_schema(db)
    with pytest.raises(BusinessException) as exc:
        gami.checkin(db, USER_ID)
    assert exc.value.status_code == 422
    assert exc.value.detail["why"] == "no_activity"


def test_checkin_pays_base_once_per_day(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    add_words(db, today, 3)  # 有痕迹但未达"有效日"门槛
    db.commit()
    res = gami.checkin(db, USER_ID)
    assert res["coins"] == gami.get_settings(db)["checkin_base_coins"]
    assert res["checkin_streak"] == 1
    with pytest.raises(BusinessException) as again:
        gami.checkin(db, USER_ID)
    assert again.value.status_code == 409
    assert balance(db) == 5


def test_effective_day_counts_as_checked_in_for_streak(db):
    """有效学习日自动算签到：金币页的连续数只会 ≥ 首页的连续学习，不会互相打脸。"""
    gami.ensure_gamification_schema(db)
    today = local_today()
    for back in (2, 1):
        day = today - datetime.timedelta(days=back)
        add_focus(db, day, 30)
        add_words(db, day, 12)
    db.commit()
    ledger = day_ledger(db, start_day=today - datetime.timedelta(days=5), end_day=today, user_id=USER_ID)
    assert ledger  # 前置条件：台账里确实有这两天
    streak = gami.checkin_streak(db, USER_ID, today=today)
    assert streak == 2
    # 同步后金币页与首页口径一致（今天没学 → 从昨天起算）
    assert streak == gami.summary(db, USER_ID)["streak"]["study_days"]


def test_milestone_paid_only_when_crossed(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    # 先造出 2 天连续签到（手动签），第 3 天签到应命中「3 天 +10」
    for back in (2, 1):
        day = today - datetime.timedelta(days=back)
        add_words(db, day, 3)
        db.add(gami_models.CheckinLog(user_id=USER_ID, biz_date=day, kind="manual", coins=5, streak_days=back))
        gami.grant(
            db,
            user_id=USER_ID,
            rule=gami.rule_map(db)["checkin"],
            biz_date=day,
            units=1,
            title="每日签到",
        )
    db.commit()
    add_words(db, today, 3)
    db.commit()

    before = balance(db)
    res = gami.checkin(db, USER_ID)
    assert res["checkin_streak"] == 3
    assert res["coins"] == 5 + 10  # 基础币 + 里程碑
    assert balance(db) == before + 15
    # 里程碑只在"本次跨过"时发：同一天重复调签到会被 409 挡，第 4 天也不会再拿 3 天档
    assert len([r for r in rows_of(db) if r.rule_code == "streak_bonus"]) == 1


def test_milestone_not_repaid_on_later_days(db):
    """连续 4/5/6 天不再重复发「3 天」档的币（否则躺赢式重复领奖）。"""
    gami.ensure_gamification_schema(db)
    today = local_today()
    rules = gami.rule_map(db)
    for back in (2, 1):
        day = today - datetime.timedelta(days=back)
        add_words(db, day, 3)
        db.add(gami_models.CheckinLog(user_id=USER_ID, biz_date=day, kind="manual", coins=5, streak_days=3 - back))
        gami.grant(db, user_id=USER_ID, rule=rules["checkin"], biz_date=day, units=1, title="每日签到")
    db.commit()
    add_words(db, today, 3)
    db.commit()
    gami.checkin(db, USER_ID)
    bonus_rows = [r for r in rows_of(db) if r.rule_code == "streak_bonus"]
    assert [r.coins for r in bonus_rows] == [10]
    assert bonus_rows[0].meta["milestone"] == 3


# --------------------------------------------------------------------------- #
# 商店兑换
# --------------------------------------------------------------------------- #
def test_redeem_rejects_insufficient_balance(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    add_words(db, today, 10)
    db.commit()
    gami.sync_day(db, USER_ID)
    with pytest.raises(BusinessException) as exc:
        gami.redeem(db, USER_ID, "makeup_card")  # 80 币，只有 10
    assert exc.value.status_code == 422
    assert balance(db) == 10  # 拒绝时一分都不能扣


def test_redeem_delivers_card_and_double_books(db):
    gami.ensure_gamification_schema(db)
    gami.admin_adjust(db, actor_id=None, user_id=USER_ID, coins=500, reason="测试预算")
    res = gami.redeem(db, USER_ID, "makeup_card")
    assert res["cost"] == 80 and res["balance"] == 420
    acct = gami.find_account(db, USER_ID)
    assert int(acct.makeup_cards) == 1 and int(acct.total_spent) == 80
    spend = [r for r in rows_of(db) if r.direction == "spend"]
    assert len(spend) == 1 and spend[0].coins == -80
    assert db.query(gami_models.Redemption).filter_by(user_id=USER_ID).count() == 1


def test_redeem_monthly_limit_and_owned_guard(db):
    gami.ensure_gamification_schema(db)
    gami.admin_adjust(db, actor_id=None, user_id=USER_ID, coins=2000, reason="测试预算")
    gami.redeem(db, USER_ID, "makeup_card")
    gami.redeem(db, USER_ID, "makeup_card")
    with pytest.raises(BusinessException) as exc:
        gami.redeem(db, USER_ID, "makeup_card")  # 每月 2 张
    assert "上限" in exc.value.message
    gami.redeem(db, USER_ID, "frame_flame")
    with pytest.raises(BusinessException) as owned:
        gami.redeem(db, USER_ID, "frame_flame")
    assert owned.value.status_code == 409


def test_shop_reports_blocking_reason(db):
    gami.ensure_gamification_schema(db)
    gami.admin_adjust(db, actor_id=None, user_id=USER_ID, coins=1000, reason="测试预算")
    gami.redeem(db, USER_ID, "makeup_card")
    gami.redeem(db, USER_ID, "makeup_card")
    view = gami.shop(db, USER_ID)
    by_code = {i["code"]: i for i in view["items"]}
    assert by_code["makeup_card"]["used_this_month"] == 2
    assert by_code["makeup_card"]["blocked"] == "monthly_limit"
    assert by_code["coin_boost"]["blocked"] is None  # 1000-160-200 后仍够 200
    gami.redeem(db, USER_ID, "frame_flame")
    after = {i["code"]: i for i in gami.shop(db, USER_ID)["items"]}
    assert after["frame_flame"]["owned"] is True and after["frame_flame"]["blocked"] == "owned"


def test_boost_multiplier_applies_to_grants(db):
    gami.ensure_gamification_schema(db)
    gami.admin_adjust(db, actor_id=None, user_id=USER_ID, coins=400, reason="测试预算")
    gami.redeem(db, USER_ID, "coin_boost")
    today = local_today()
    add_words(db, today, 10)
    db.commit()
    res = gami.sync_day(db, USER_ID)
    unit = [r for r in rows_of(db, rule="word_review")]
    assert unit and unit[-1].coins == 15  # 10 × 1.5
    assert res["granted_coins"] == 15
    assert gami.summary(db, USER_ID)["account"]["boost_active"] is True


# --------------------------------------------------------------------------- #
# 补签
# --------------------------------------------------------------------------- #
def _seed_cards(session, coins=1000, times=1):
    gami.ensure_gamification_schema(session)
    gami.admin_adjust(db=session, actor_id=None, user_id=USER_ID, coins=coins, reason="测试预算")
    for _ in range(times):
        session.expire_all()
        gami.redeem(session, USER_ID, "makeup_card")
    session.expire_all()


def test_makeup_needs_card_window_and_activity(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    day = today - datetime.timedelta(days=1)
    add_words(db, day, 3)  # 有痕迹但没到"有效日"门槛 ⇒ 正是补签该救的那种日子
    db.commit()
    with pytest.raises(BusinessException) as exc:
        gami.makeup(db, USER_ID, day)
    assert "补签卡" in exc.value.message
    assert gami.checkin_streak(db, USER_ID, today=today) == 0

    _seed_cards(db)
    # 今天（该走签到）/ 无痕迹日 / 超窗口 都要被挡住
    with pytest.raises(BusinessException):
        gami.makeup(db, USER_ID, today)
    with pytest.raises(BusinessException) as noact:
        gami.makeup(db, USER_ID, today - datetime.timedelta(days=3))
    assert noact.value.detail["why"] == "no_activity"
    with pytest.raises(BusinessException) as far:
        gami.makeup(db, USER_ID, today - datetime.timedelta(days=40))
    assert "窗口" in far.value.message

    res = gami.makeup(db, USER_ID, day)
    assert res["coins"] == 0 and res["kind"] == "makeup"
    assert res["cards_left"] == 0
    assert res["checkin_streak"] == 1  # 补上昨天，连续签到从 0 变 1
    assert balance(db) == 920  # 卡的钱在兑换时付掉了，补签本身不再给币
    with pytest.raises(BusinessException) as dup:
        gami.makeup(db, USER_ID, day)
    assert dup.value.status_code == 409


def test_makeup_refuses_effective_day(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    day = today - datetime.timedelta(days=1)
    add_words(db, day, 20)  # 20 词 = 有效学习日，本来就计入连续，补签是浪费卡
    db.commit()
    _seed_cards(db)
    with pytest.raises(BusinessException) as exc:
        gami.makeup(db, USER_ID, day)
    assert exc.value.status_code == 409
    assert int(gami.find_account(db, USER_ID).makeup_cards) == 1  # 卡不能被扣掉


# --------------------------------------------------------------------------- #
# 管理端
# --------------------------------------------------------------------------- #
def test_admin_adjust_requires_reason_and_nonzero(db):
    gami.ensure_gamification_schema(db)
    with pytest.raises(BusinessException):  # 原因太短：审计看不懂
        gami.admin_adjust(db, actor_id=None, user_id=USER_ID, coins=10, reason="x")
    with pytest.raises(BusinessException):  # 0 币调整没有意义
        gami.admin_adjust(db, actor_id=None, user_id=USER_ID, coins=0, reason="测试一下")
    with pytest.raises(BusinessException):  # 超出单次上限
        gami.admin_adjust(db, actor_id=None, user_id=USER_ID, coins=99999, reason="超出单次上限的调整")
    with pytest.raises(BusinessException):  # 无账户时不允许扣成负数
        gami.admin_adjust(db, actor_id=None, user_id=USER_ID, coins=-5, reason="扣回并不存在的发放")
    assert balance(db) == 0


def test_admin_adjust_positive_then_overdraw_blocked(db):
    gami.ensure_gamification_schema(db)
    gami.admin_adjust(db, actor_id=1, user_id=USER_ID, coins=100, reason="补发上周漏给的签到")
    assert balance(db) == 100
    with pytest.raises(BusinessException) as exc:
        gami.admin_adjust(db, actor_id=1, user_id=USER_ID, coins=-500, reason="扣过头了")
    assert exc.value.status_code == 422
    assert balance(db) == 100
    adj = [r for r in rows_of(db) if r.rule_code == "admin_adjust"]
    assert adj[0].meta["actor_id"] == 1 and "补发" in adj[0].meta["reason"]


def test_admin_settings_range_check(db):
    gami.ensure_gamification_schema(db)
    with pytest.raises(BusinessException):
        gami.admin_update_settings(db, {"daily_earn_cap": 1})
    with pytest.raises(BusinessException):
        gami.admin_update_settings(db, {"nope": 3})
    with pytest.raises(BusinessException):
        gami.admin_update_settings(db, {"streak_milestones": {"0": 10}})
    out = gami.admin_update_settings(db, {"daily_earn_cap": 300, "streak_milestones": {"5": 20}})
    assert out["daily_earn_cap"] == 300 and out["streak_milestones"] == {"5": 20}


def test_admin_rule_and_item_validation(db):
    gami.ensure_gamification_schema(db)
    with pytest.raises(BusinessException):
        gami.admin_update_rule(db, "word_review", {"coins": 5000})
    with pytest.raises(BusinessException):
        gami.admin_update_rule(db, "not_a_rule", {"coins": 3})
    item = gami.admin_upsert_item(
        db,
        "frame_custom",
        {"name": "自定义框", "kind": "avatar_frame", "cost_coins": 120, "payload": {"frame": "custom"}},
    )
    assert item["code"] == "frame_custom"
    with pytest.raises(BusinessException):
        gami.admin_upsert_item(db, "bogus_kind", {"name": "x", "kind": "free_lunch", "cost_coins": 1})
    assert gami.admin_toggle_item(db, "frame_custom", False)["is_active"] is False
    assert "frame_custom" not in {i["code"] for i in gami.list_items(db, only_active=True)}


def test_admin_overview_counts(db):
    gami.ensure_gamification_schema(db)
    today = local_today()
    add_words(db, today, 10)
    add_error_reviews(db, today, 5)
    db.commit()
    gami.sync_day(db, USER_ID)
    gami.admin_adjust(db, actor_id=None, user_id=OTHER_ID, coins=50, reason="给另一个用户记账")
    ov = gami.admin_overview(db, days=7)
    assert ov["total_earned"] == 80  # 30（USER_ID）+ 50（OTHER_ID）
    assert ov["participants"] == 2
    assert {r["rule_code"] for r in ov["per_rule"]} >= {"word_review", "error_review", "admin_adjust"}
    detail = gami.admin_user_detail(db, USER_ID)
    assert detail["account"]["balance"] == 30 and len(detail["recent_ledger"]) == 2


# --------------------------------------------------------------------------- #
# 个人资料与偏好（routers/auth/profile.py 的校验层）
# --------------------------------------------------------------------------- #
from types import SimpleNamespace  # noqa: E402

import routers.auth.profile as prof  # noqa: E402


def test_avatar_validation(db):
    gami.ensure_gamification_schema(db)
    assert prof._clean_avatar("initials", None) == ("initials", "teal")
    assert prof._clean_avatar("preset", "🦉") == ("preset", "🦉")
    assert prof._clean_avatar("url", "https://cdn.example.com/a.png")[0] == "url"
    for kind, value in (
        ("url", "javascript:alert(1)"),
        ("url", "file:///etc/passwd"),
        ("url", "https://example.com/a b.png"),
        ("preset", "💣"),
        ("initials", "notacolor"),
        ("emoji", "🦉"),
    ):
        with pytest.raises(BusinessException):
            prof._clean_avatar(kind, value)


def test_prefs_whitelist_and_limits(db):
    gami.ensure_gamification_schema(db)
    merged, ignored = prof._clean_prefs({"week_start": "sun", "font_scale": "lg", "nope": 1, "calendar_days": 60})
    assert merged == {"week_start": "sun", "font_scale": "lg", "calendar_days": 60}
    assert ignored == ["nope"]
    with pytest.raises(BusinessException):
        prof._clean_prefs({"font_scale": "huge"})
    with pytest.raises(BusinessException):
        prof._clean_prefs({"calendar_days": 9999})
    assert prof.default_prefs()["reduce_motion"] is False


def _fake_user(uid=USER_ID):
    return SimpleNamespace(
        id=uid,
        username="stu",
        display_name="stu",
        role="user",
        email=None,
        email_verified_at=None,
        created_at=None,
        last_login_at=None,
        must_change_password=False,
    )


def test_profile_read_and_update(db):
    gami.ensure_gamification_schema(db)
    body = prof.ProfileUpdateBody(bio="  电气 834，冲 130 分  ", grade="2027 届", prefs={"coin_toast": False})
    out = prof.update_profile(body, None, db, _fake_user())
    assert out["bio"] == "电气 834，冲 130 分"
    assert out["prefs"]["coin_toast"] is False
    assert out["prefs"]["week_start"] == "mon"  # 未传的偏好回落默认值，不是 None
    assert out["avatar_kind"] == "initials"


def test_profile_equipped_must_be_unlocked(db):
    gami.ensure_gamification_schema(db)
    with pytest.raises(BusinessException):
        prof.update_profile(prof.ProfileUpdateBody(avatar_frame="frame_flame"), None, db, _fake_user())
    gami.admin_adjust(db, actor_id=None, user_id=USER_ID, coins=300, reason="测试预算")
    gami.redeem(db, USER_ID, "frame_flame")
    out = prof.update_profile(prof.ProfileUpdateBody(avatar_frame="frame_flame"), None, db, _fake_user())
    assert out["avatar_frame"] == "frame_flame"
    assert "frame_flame" in out["unlocked"]["frames"]
    # 卸下一切：传空串即取消佩戴，不报错
    out2 = prof.update_profile(prof.ProfileUpdateBody(avatar_frame=""), None, db, _fake_user())
    assert out2["avatar_frame"] is None


def test_profile_display_name_too_long(db):
    """超长显示名：Pydantic 层先挡（422 校验壳），服务层再挡一遍，两道闸都算拦住。"""
    from pydantic import ValidationError

    gami.ensure_gamification_schema(db)
    with pytest.raises((ValidationError, BusinessException)):
        prof.ProfileUpdateBody(display_name="长" * 80)
    with pytest.raises(BusinessException):
        prof.update_profile(prof.ProfileUpdateBody(display_name="   "), None, db, _fake_user())


# --------------------------------------------------------------------------- #
# 路由层：/api/gamification 与 /api/profile 真的挂得上吗（W6 接线回归）
# --------------------------------------------------------------------------- #
# 只建一个**只装这两组 router** 的迷你 app，因此不会碰 conftest 的 session 级
# kaoyan_test schema 重建（那一下就是 120s+），也不会被全局 enforce_access 牵连：
# 全局策略层的分类断言另有 test_policy_classification 直接打函数，不走 HTTP。
# 覆盖的是服务层测试摸不到的四类接缝：
#   1. router 是否被 registry 收录（漏挂 = 契约在前端、接口在 404）；
#   2. _gate/_uid/_parse_day 这些依赖壳（401 / 422 的翻译对不对）；
#   3. paginate_query(...).dict() 的分页壳字段；
#   4. BusinessException 的 status_code 是否真透传成 HTTP 状态码。
@pytest.fixture()
def api(db):
    """TestClient + 假登录态；退出时清掉 override，避免污染同会话其它用例。"""
    import routers.auth.profile as prof_mod
    import routers.study.gamification as gami_router
    from database import get_db
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from utils.exceptions import register_exception_handlers
    from utils.security import current_user

    app = FastAPI()
    # 与 main.py 同一套异常映射：BusinessException 的 status_code 要真变成 HTTP 状态码，
    # 否则这里测的是"服务层抛得对"，而不是"用户看到的码对"（两者在裸 FastAPI 上会分叉）。
    register_exception_handlers(app)
    app.include_router(gami_router.router)
    app.include_router(prof_mod.router)
    app.dependency_overrides[get_db] = lambda: db
    # 两组 router 都走 ``user=Depends(current_user)``（与 goals.py / growth.py 同构），
    # 所以注入身份只需 dependency_overrides 这一处 —— 与 conftest 给全站用的是同一个接缝。
    app.dependency_overrides[current_user] = lambda: _fake_user()
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_routers_are_registered_in_registry():
    """registry 漏挂是这类"服务全绿但线上 404"的唯一成因，必须直接断言。"""
    from routers.registry import iter_routers

    prefixes = {getattr(r, "prefix", "") for r in iter_routers()}
    assert "/api/gamification" in prefixes
    assert "/api/profile" in prefixes


def test_personal_routes_need_login_and_admin_routes_need_admin():
    """access_policy 分类：个人域要登录且不对外放访客；admin 子树只给管理员。"""
    from utils.access_policy import is_guest_readable, needs_admin

    for path in ("/api/gamification/summary", "/api/gamification/shop", "/api/profile"):
        assert needs_admin("GET", path) is False
        assert is_guest_readable("GET", path) is False  # 个人余额绝不给未登录
    assert is_guest_readable("POST", "/api/gamification/sync") is False

    for method, path in (
        ("GET", "/api/gamification/admin/overview"),
        ("PUT", "/api/gamification/admin/settings"),
        ("POST", "/api/gamification/admin/adjust"),
        ("PATCH", "/api/gamification/admin/items/frame_flame"),
        ("GET", "/api/gamification/admin/users/12"),
    ):
        assert needs_admin(method, path) is True
        assert is_guest_readable("GET", path) is False


def test_sync_and_replay_over_http(api, db):
    """HTTP 线上把幂等再走一遍：重放 granted=0，余额不变。"""
    today = local_today()
    add_words(db, today, 20)
    db.commit()

    first = api.post("/api/gamification/sync", json={})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["granted_coins"] == 20 and body["balance"] == 20
    assert body["activity"]["counts"]["words_done"] == 20

    replay = api.post("/api/gamification/sync", json={}).json()
    assert replay["granted_coins"] == 0 and replay["balance"] == 20


def test_future_day_and_bad_date_are_422(api):
    """路由层把 INVALID_PARAMETER 翻成 422（不是 200 错误壳，也不是 500）。"""
    future = (local_today() + datetime.timedelta(days=2)).isoformat()
    assert api.post("/api/gamification/sync", json={"date": future}).status_code == 422
    assert api.post("/api/gamification/sync", json={"date": "2026-13-45"}).status_code == 422
    assert api.post("/api/gamification/checkin/makeup", json={"date": "not-a-date"}).status_code == 422


def test_checkin_conflict_is_409_over_http(api, db):
    today = local_today()
    add_words(db, today, 3)
    db.commit()
    assert api.post("/api/gamification/checkin").status_code == 200
    again = api.post("/api/gamification/checkin")
    assert again.status_code == 409
    assert "签到" in again.json()["message"]


def test_ledger_pagination_shell(api, db):
    today = local_today()
    add_words(db, today, 100)  # word_review 单日 3 次封顶 → 3 行流水
    add_error_reviews(db, today, 10)
    db.commit()
    api.post("/api/gamification/sync", json={})

    data = api.get("/api/gamification/ledger").json()
    assert {"items", "total", "page", "page_size", "total_pages"} <= set(data)
    assert data["total"] == 5 and len(data["items"]) == 5
    assert data["items"][0]["coins"] != 0
    earned = api.get("/api/gamification/ledger", params={"direction": "spend"}).json()
    assert earned["total"] == 0
    # 越界页码由 page_params 的 ge=1 挡成 422，而不是静默给空列表
    assert api.get("/api/gamification/ledger", params={"page": 0}).status_code == 422


def test_summary_rules_shop_calendar_over_http(api, db):
    summary = api.get("/api/gamification/summary").json()
    assert summary["state"] == "empty"
    assert summary["account"]["balance"] == 0
    assert {"checkin_days", "study_days", "study_longest", "next_milestone"} <= set(summary["streak"])

    rules = api.get("/api/gamification/rules").json()
    assert {r["rule_code"] for r in rules["rules"]} >= {"word_review", "error_review", "checkin"}
    assert rules["settings"]["daily_earn_cap"] == 260

    shop = api.get("/api/gamification/shop").json()
    by_code = {i["code"]: i for i in shop["items"]}
    assert shop["balance"] == 0
    assert by_code["makeup_card"]["blocked"] == "insufficient"

    cal = api.get("/api/gamification/calendar", params={"days": 14}).json()
    assert len(cal["days"]) == 14 and cal["streak"] == 0


def test_redeem_guard_over_http(api, db):
    resp = api.post("/api/gamification/redeem", json={"code": "makeup_card"})
    assert resp.status_code == 422  # 余额 0，币不够
    assert balance(db) == 0
    assert api.post("/api/gamification/redeem", json={"code": "no_such_item"}).status_code == 404


def test_admin_endpoints_reject_plain_user(api):
    """require_admin 在路由内层兜底（与 access_policy 的 ADMIN_PREFIXES 是两道独立闸）。"""
    assert api.get("/api/gamification/admin/overview").status_code == 403
    assert api.put("/api/gamification/admin/settings", json={"values": {"daily_earn_cap": 300}}).status_code == 403
    assert (
        api.post("/api/gamification/admin/adjust", json={"user_id": 1, "coins": 5, "reason": "给点补贴"}).status_code
        == 403
    )


def test_profile_endpoints_over_http(api):
    payload = api.get("/api/profile").json()
    assert {"account", "profile", "coins", "options"} <= set(payload)
    assert payload["account"]["id"] == USER_ID
    prof_body = payload["profile"]
    assert prof_body["avatar_kind"] == "initials"
    assert prof_body["prefs"]["week_start"] == "mon"
    assert prof_body["unlocked"] == {"frames": [], "titles": []}
    assert payload["coins"] == {"balance": 0, "makeup_cards": 0}

    upd = api.put("/api/profile", json={"bio": "电气 834，冲 130 分", "prefs": {"week_start": "sun", "nope": 1}})
    assert upd.status_code == 200
    out = upd.json()
    assert out["bio"] == "电气 834，冲 130 分"
    assert out["prefs"]["week_start"] == "sun"
    assert out["prefs"]["font_scale"] == "md"  # 未传的偏好回落默认值而非 None
    assert out["ignored_pref_keys"] == ["nope"]  # 未知键如实告知，不静默吞
    assert api.put("/api/profile", json={"avatar_frame": "frame_flame"}).status_code == 422
