# -*- coding: utf-8 -*-
"""金币激励服务（W6）：获取规则、签到/补签、商店兑换、防刷闸、管理端调参。

策略文档：``docs/design/gamification-coin-strategy-v1.md``。

## 三条不可动摇的口径

1. **金额永远由服务端算**。本模块**不提供**"客户端报个数就发币"的入口：
   发币只从 :func:`services.study_calendar.day_ledger`（全站唯一的日活台账）
   折算出来。前端能调的只有 ``/sync``（"把今天已发生的行为折算成金币"），
   重放它一次和一百次结果相同 —— ``coin_ledger(user_id, dedup_key)`` 唯一索引兜底。

2. **两个"连续"是两件事，各自命名、同屏都展示，不互相冒充**：
   - ``study_streak``（连续学习）= ``streak_summary(day_ledger)`` 的 current，
     门槛是"有效学习日"（专注 ≥10 分钟 / 复习单词 ≥10 / 答题 ≥5），与首页 KPI 同源；
   - ``checkin_streak``（连续签到）= 上述有效日 **∪** 显式签到/补签记录，
     是金币里程碑的依据，也是补签卡唯一能影响的东西。
     它是 ``study_streak`` 的**超集**（有效日自动视为已签到），
     所以绝不会出现"首页 7 天、金币页 3 天"这种互相打脸的数。

3. **零数据新号 = 全 0 + 空列表 + ``state="empty"``**，不播种假流水、不给"欢迎奖励"
   式的白送币（诚实初始化整改的铁律：不能用平台数据冒充个人成果）。

## 数值可配

默认值只在本模块声明一次（:data:`DEFAULT_RULES` / :data:`DEFAULT_SETTINGS` /
:data:`DEFAULT_ITEMS`）。首次访问时把**库里缺失的行**幂等补齐；管理员改过的值
永不被代码覆盖（只补新增规则码）。所有参数改动都落在库表里并带 ``updated_at``。
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.models.gamification import (
    CheckinLog,
    CoinAccount,
    CoinLedger,
    GamificationRule,
    GamificationSetting,
    Redemption,
    RewardItem,
)
from sqlalchemy import case, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session
from utils.exceptions import BusinessException, ErrorCode
from utils.timeutil import local_today, local_window_for_day, utcnow

from services.study_calendar import day_ledger, streak_summary

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 一、默认数值（唯一权威源）
# --------------------------------------------------------------------------- #

#: 获取规则。kind 语义：
#:   batch      —— 每 ``per_units`` 个真实行为折算 1 次，单日最多 ``daily_cap`` 次
#:   per_item   —— 每个行为折算 1 次（等价于 per_units=1，但语义上"论个给"）
#:   daily_fixed —— 一日一次（签到）；发币走 :data:`DEFAULT_SETTINGS.checkin_base_coins`
DEFAULT_RULES: List[Dict[str, Any]] = [
    {
        "rule_code": "word_review",
        "label": "背单词",
        "kind": "batch",
        "per_units": 10,
        "unit_label": "个单词",
        "coins": 10,
        "daily_cap": 3,
        "sort_order": 10,
    },
    {
        "rule_code": "error_review",
        "label": "复习错题",
        "kind": "batch",
        "per_units": 5,
        "unit_label": "道错题",
        "coins": 20,
        "daily_cap": 2,
        "sort_order": 20,
    },
    {
        "rule_code": "card_review",
        "label": "复习卡片",
        "kind": "batch",
        "per_units": 10,
        "unit_label": "张卡片",
        "coins": 8,
        "daily_cap": 2,
        "sort_order": 30,
    },
    {
        "rule_code": "knowledge_review",
        "label": "复习知识点",
        "kind": "batch",
        "per_units": 5,
        "unit_label": "个知识点",
        "coins": 6,
        "daily_cap": 2,
        "sort_order": 40,
    },
    {
        "rule_code": "quiz_correct",
        "label": "答对题目",
        "kind": "batch",
        "per_units": 10,
        "unit_label": "道题",
        "coins": 12,
        "daily_cap": 3,
        "sort_order": 50,
    },
    {
        "rule_code": "focus_pomodoro",
        "label": "专注计时",
        "kind": "batch",
        "per_units": 25,
        "unit_label": "分钟专注",
        "coins": 6,
        "daily_cap": 4,
        "sort_order": 60,
    },
    {
        "rule_code": "task_done",
        "label": "完成任务",
        "kind": "per_item",
        "per_units": 1,
        "unit_label": "个任务",
        "coins": 6,
        "daily_cap": 5,
        "sort_order": 70,
    },
    {
        "rule_code": "exam_submit",
        "label": "模考交卷",
        "kind": "per_item",
        "per_units": 1,
        "unit_label": "场模考",
        "coins": 50,
        "daily_cap": 1,
        "sort_order": 80,
    },
    {
        "rule_code": "checkin",
        "label": "每日签到",
        "kind": "daily_fixed",
        "per_units": 1,
        "unit_label": "次",
        "coins": 5,
        "daily_cap": 1,
        "sort_order": 90,
    },
]

#: 全局参数。存库时统一包成 ``{"v": <值>}``（列是 JSON object，不能放裸数字）。
DEFAULT_SETTINGS: Dict[str, Dict[str, Any]] = {
    "daily_earn_cap": {"v": 260, "label": "单日发放上限（金币，含里程碑）"},
    "checkin_base_coins": {"v": 5, "label": "每日签到基础金币"},
    "streak_milestones": {"v": {"3": 10, "7": 25, "14": 60, "30": 150}, "label": "连续签到里程碑（天数→金币）"},
    "makeup_window_days": {"v": 7, "label": "补签可回溯窗口（天）"},
    "makeup_monthly_limit": {"v": 3, "label": "每月补签次数上限"},
    "boost_hours": {"v": 24, "label": "加成卡持续小时数"},
    "boost_multiplier": {"v": 1.5, "label": "加成卡倍率"},
    "admin_adjust_max": {"v": 2000, "label": "管理员单次人工调整上限（绝对值）"},
}

#: 商店商品：只上架**系统真能兑现**的权益。
DEFAULT_ITEMS: List[Dict[str, Any]] = [
    {
        "code": "makeup_card",
        "name": "补签卡",
        "description": "补一次 7 天内有学习痕迹的漏签，保住连续签到（不送金币）",
        "kind": "makeup_card",
        "cost_coins": 80,
        "payload": {},
        "monthly_limit": 2,
        "sort_order": 10,
    },
    {
        "code": "coin_boost",
        "name": "金币加成卡 ×1.5",
        "description": "兑换后立即生效，24 小时内所有发放按 1.5 倍计入",
        "kind": "boost",
        "cost_coins": 200,
        "payload": {"multiplier": 1.5, "hours": 24},
        "monthly_limit": 2,
        "sort_order": 20,
    },
    {
        "code": "frame_flame",
        "name": "头像框 · 烈焰",
        "description": "永久解锁，在「设置 - 个人资料」选用",
        "kind": "avatar_frame",
        "cost_coins": 200,
        "payload": {"frame": "flame"},
        "monthly_limit": 0,
        "sort_order": 30,
    },
    {
        "code": "frame_scholar",
        "name": "头像框 · 学者",
        "description": "永久解锁，在「设置 - 个人资料」选用",
        "kind": "avatar_frame",
        "cost_coins": 300,
        "payload": {"frame": "scholar"},
        "monthly_limit": 0,
        "sort_order": 40,
    },
    {
        "code": "frame_star",
        "name": "头像框 · 星辰",
        "description": "永久解锁，在「设置 - 个人资料」选用",
        "kind": "avatar_frame",
        "cost_coins": 400,
        "payload": {"frame": "star"},
        "monthly_limit": 0,
        "sort_order": 50,
    },
    {
        "code": "title_persist",
        "name": "称号 · 七日不辍",
        "description": "永久解锁，佩戴后展示在头像旁",
        "kind": "title",
        "cost_coins": 250,
        "payload": {"title": "七日不辍"},
        "monthly_limit": 0,
        "sort_order": 60,
    },
    {
        "code": "title_master",
        "name": "称号 · 百题斩将",
        "description": "永久解锁，佩戴后展示在头像旁",
        "kind": "title",
        "cost_coins": 500,
        "payload": {"title": "百题斩将"},
        "monthly_limit": 0,
        "sort_order": 70,
    },
]

#: 规则码 → 日活台账字段（发币的**唯一**数据来源）。
RULE_COUNT_FIELD: Dict[str, str] = {
    "word_review": "words_done",
    "error_review": "errors_done",
    "card_review": "cards_done",
    "knowledge_review": "knowledge_done",
    "quiz_correct": "questions_correct",
    "focus_pomodoro": "focus_minutes",
    "task_done": "tasks_done",
    "exam_submit": "exams_done",
}

VALID_RULE_KINDS = ("batch", "per_item", "daily_fixed")
VALID_ITEM_KINDS = ("makeup_card", "boost", "avatar_frame", "title")

_TABLE_NAMES = (
    "coin_accounts",
    "coin_ledger",
    "checkin_logs",
    "gamification_rules",
    "gamification_settings",
    "reward_items",
    "redemptions",
    "user_profiles",
)

#: 已确认过建表的连接串（避免每请求 inspect 一次）
_ensured_urls: set[str] = set()


# --------------------------------------------------------------------------- #
# 二、建表兜底 + 默认值播种
# --------------------------------------------------------------------------- #
def ensure_gamification_schema(db: Session) -> None:
    """缺表时用 ORM 元数据补建，然后幂等播种默认规则/参数/商品。

    生产 PG 的结构权威是 ``core/sql/125_gamification_coins.sql``（启动时由
    ``core.migrations.run_pending`` 执行）。这里是**兜底**：SQLite 线、新库、
    或分片尚未跑到的环境，第一次访问接口就能自愈，不会 500 在"表不存在"上。
    ``create_all(checkfirst=True)`` 生成的 DDL 与分片一致（模型带 sqlite variant），
    分片已建好时一条语句都不会发。
    """
    engine = db.get_bind()
    key = str(engine.url)
    if key not in _ensured_urls:
        try:
            from sqlalchemy import inspect

            insp = inspect(engine)
            missing = [t for t in _TABLE_NAMES if not insp.has_table(t)]
            if missing:
                from core.models.base import Base

                tables = [Base.metadata.tables[t] for t in missing if t in Base.metadata.tables]
                if tables:
                    Base.metadata.create_all(bind=engine, tables=tables, checkfirst=True)
                    logger.info("[gamification] 兜底建表：%s", ", ".join(t.name for t in tables))
        except Exception as exc:  # noqa: BLE001 —— 建表失败不能让接口 500，降级为"激励暂不可用"
            logger.warning("[gamification] 建表自检失败（将由后续查询自然报错并降级）：%s", exc)
            return
        # 播种只做一次（每进程每库）：播种本身幂等，但每请求三次 SELECT 不值当
        _seed_defaults(db)
        _ensured_urls.add(key)


def _seed_defaults(db: Session) -> None:
    """把库里**缺失**的默认行补进去；已存在的（含管理员改过的）一律不动。"""
    try:
        have_rules = {r[0] for r in db.query(GamificationRule.rule_code).all()}
        for spec in DEFAULT_RULES:
            if spec["rule_code"] in have_rules:
                continue
            db.add(GamificationRule(**spec, is_active=True))
        have_settings = {r[0] for r in db.query(GamificationSetting.setting_key).all()}
        for code, spec in DEFAULT_SETTINGS.items():
            if code in have_settings:
                continue
            db.add(GamificationSetting(setting_key=code, value={"v": spec["v"]}, label=spec["label"]))
        have_items = {r[0] for r in db.query(RewardItem.code).all()}
        for spec in DEFAULT_ITEMS:
            if spec["code"] in have_items:
                continue
            db.add(RewardItem(**spec, is_active=True))
        db.commit()
    except IntegrityError:
        # 并发首访同时播种 ⇒ 唯一键撞车。回滚后重跑一次即可，不是错误。
        db.rollback()
        logger.info("[gamification] 默认值播种撞唯一键（并发首访），本次跳过")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("[gamification] 默认值播种失败：%s", exc)


# --------------------------------------------------------------------------- #
# 三、规则与参数读取
# --------------------------------------------------------------------------- #
def _rule_dict(row: GamificationRule) -> Dict[str, Any]:
    return {
        "rule_code": row.rule_code,
        "label": row.label,
        "kind": row.kind,
        "per_units": int(row.per_units or 1),
        "unit_label": row.unit_label or "",
        "coins": int(row.coins or 0),
        "daily_cap": int(row.daily_cap or 0),
        "is_active": bool(row.is_active),
        "sort_order": int(row.sort_order or 0),
    }


def list_rules(db: Session, *, only_active: bool = False) -> List[Dict[str, Any]]:
    rows = db.query(GamificationRule).order_by(GamificationRule.sort_order, GamificationRule.rule_code).all()
    rules = [_rule_dict(r) for r in rows]
    if not rows:
        # 表还没建好/没播种：退回代码默认值，保证规则说明页不会一片空白
        rules = [dict(s, is_active=True) for s in DEFAULT_RULES]
    return [r for r in rules if r["is_active"]] if only_active else rules


def rule_map(db: Session) -> Dict[str, Dict[str, Any]]:
    return {r["rule_code"]: r for r in list_rules(db, only_active=True)}


def get_settings(db: Session) -> Dict[str, Any]:
    """全局参数（缺行回落代码默认值）。"""
    out = {k: v["v"] for k, v in DEFAULT_SETTINGS.items()}
    try:
        for row in db.query(GamificationSetting).all():
            val = row.value if isinstance(row.value, dict) else {}
            if "v" in val:
                out[row.setting_key] = val["v"]
    except Exception as exc:  # noqa: BLE001 —— 参数读不到就用默认值，不能挡掉整个接口
        logger.warning("[gamification] 读取全局参数失败，回落默认值：%s", exc)
    return out


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _milestones(settings: Dict[str, Any]) -> List[Tuple[int, int]]:
    """连续签到里程碑 → 升序 ``[(天数, 金币)]``。"""
    raw = settings.get("streak_milestones") or {}
    items: List[Tuple[int, int]] = []
    if isinstance(raw, dict):
        for k, v in raw.items():
            days, coins = _int(k, 0), _int(v, 0)
            if days > 0 and coins > 0:
                items.append((days, coins))
    return sorted(items)


# --------------------------------------------------------------------------- #
# 四、账户
# --------------------------------------------------------------------------- #
def find_account(db: Session, user_id: int) -> Optional[CoinAccount]:
    return db.query(CoinAccount).filter(CoinAccount.user_id == user_id).one_or_none()


def get_account(db: Session, user_id: int, *, create: bool = True) -> Optional[CoinAccount]:
    """取账户行；``create=True`` 时惰性建一行（只在真要发/扣币时调用）。"""
    acct = find_account(db, user_id)
    if acct is None and create:
        acct = CoinAccount(user_id=user_id, balance=0, total_earned=0, total_spent=0, makeup_cards=0)
        try:
            with db.begin_nested():
                db.add(acct)
                db.flush()
        except IntegrityError:
            # 并发首建：另一个请求已经插了这行，取回来用即可（savepoint 已回滚本条）
            acct = find_account(db, user_id)
    return acct


def _boost_multiplier(acct: Optional[CoinAccount], settings: Dict[str, Any], now: datetime.datetime) -> float:
    if acct is None or acct.boost_until is None:
        return 1.0
    boost_until = acct.boost_until
    if boost_until.tzinfo is not None:
        boost_until = boost_until.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    if boost_until <= now:
        return 1.0
    try:
        mult = float(settings.get("boost_multiplier", 1.5))
    except (TypeError, ValueError):
        mult = 1.5
    return mult if 1.0 < mult <= 5.0 else 1.5


# --------------------------------------------------------------------------- #
# 五、发币（幂等 + 双重上限）
# --------------------------------------------------------------------------- #
def granted_units(db: Session, user_id: int, rule_code: str, biz_date: datetime.date) -> int:
    """某规则某日**已经**发放的单位数（幂等基准）。"""
    return _int(
        db.query(func.count(CoinLedger.id))
        .filter(CoinLedger.user_id == user_id, CoinLedger.rule_code == rule_code, CoinLedger.biz_date == biz_date)
        .scalar()
    )


def earned_on(db: Session, user_id: int, biz_date: datetime.date) -> int:
    """某日**通过行为**已获得金币（全局日上限判定用）。

    只算 ``direction='earn'``：管理员补偿（adjust）是审计过的个案发放，
    不该占用用户当天的"刷币额度"；反过来说，人工发放也不受日上限保护——
    它由 ``admin_adjust_max`` 与"必填原因"两道闸管。
    """
    return _int(
        db.query(func.coalesce(func.sum(CoinLedger.coins), 0))
        .filter(
            CoinLedger.user_id == user_id,
            CoinLedger.biz_date == biz_date,
            CoinLedger.direction == "earn",
            CoinLedger.coins > 0,
        )
        .scalar()
    )


def _insert_ledger(
    db: Session,
    *,
    user_id: int,
    biz_date: datetime.date,
    rule_code: str,
    direction: str,
    coins: int,
    dedup_key: str,
    unit_index: int = 0,
    title: Optional[str] = None,
    meta: Optional[dict] = None,
    actor_id: Optional[int] = None,
) -> bool:
    """写一行流水；撞唯一键返回 ``False``（= 别的请求已经发过了）。"""
    row = CoinLedger(
        user_id=user_id,
        biz_date=biz_date,
        rule_code=rule_code,
        direction=direction,
        coins=coins,
        unit_index=unit_index,
        dedup_key=dedup_key,
        title=title,
        meta=meta or {},
        actor_id=actor_id,
    )
    try:
        # SAVEPOINT 而不是直接 flush：撞唯一键（并发重放）时只回滚这一条，
        # 已经写进去的同批流水与后面要更新的余额都不受影响。
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        return False
    return True


def grant(
    db: Session,
    *,
    user_id: int,
    rule: Dict[str, Any],
    biz_date: datetime.date,
    units: int,
    title: Optional[str] = None,
    meta_extra: Optional[dict] = None,
) -> Dict[str, Any]:
    """按规则发放 ``units`` 个单位（已经发过的不重发）。

    三道闸：``rule.daily_cap``（按次）→ 全局 ``daily_earn_cap``（按币）→
    ``dedup_key`` 唯一（按单位）。被截断时**如实**在返回里给 ``capped``，
    不静默吞掉（吞掉就等于骗用户"发了"）。
    """
    rule_code = rule["rule_code"]
    per_unit_coins = _int(rule.get("coins"), 0)
    daily_cap = _int(rule.get("daily_cap"), 0)
    wanted = max(0, _int(units, 0))
    if per_unit_coins <= 0 or wanted <= 0:
        return {
            "rule_code": rule_code,
            "units": 0,
            "coins": 0,
            "capped": False,
            "cap_reason": None,
            "skipped": "no_payout",
        }

    already = granted_units(db, user_id, rule_code, biz_date)
    target_units = min(wanted, daily_cap) if daily_cap > 0 else wanted
    # 单规则"按次"封顶是否被顶到：顶到了要如实报出去，不能让用户以为"做了没算"
    rule_cap_hit = bool(daily_cap) and target_units < wanted
    delta = target_units - already
    if delta <= 0:
        return {
            "rule_code": rule_code,
            "label": rule.get("label") or rule_code,
            "units": 0,
            "coins": 0,
            "capped": rule_cap_hit or already >= target_units,
            "cap_reason": "rule_daily_cap" if rule_cap_hit else None,
            "skipped": "already_granted",
        }

    settings = get_settings(db)
    acct = get_account(db, user_id)
    multiplier = _boost_multiplier(acct, settings, utcnow())
    unit_coins = max(1, int(round(per_unit_coins * multiplier)))

    cap_total = _int(settings.get("daily_earn_cap"), 260)
    remaining = max(0, cap_total - earned_on(db, user_id, biz_date))
    global_cap_hit = False
    affordable = remaining // unit_coins if unit_coins else 0
    if affordable < delta:
        delta, global_cap_hit = max(0, affordable), True
    if delta <= 0:
        return {
            "rule_code": rule_code,
            "label": rule.get("label") or rule_code,
            "units": 0,
            "coins": 0,
            "capped": True,
            "cap_reason": "earn_daily_cap" if global_cap_hit else "rule_daily_cap",
            "skipped": "daily_cap",
        }

    total = 0
    inserted = 0
    for offset in range(delta):
        unit_index = already + offset + 1
        ok = _insert_ledger(
            db,
            user_id=user_id,
            biz_date=biz_date,
            rule_code=rule_code,
            direction="earn",
            coins=unit_coins,
            dedup_key=f"{rule_code}:{biz_date.isoformat()}:{unit_index}",
            unit_index=unit_index,
            title=title or rule.get("label") or rule_code,
            meta={
                "unit_price": unit_coins,
                "base_price": per_unit_coins,
                "multiplier": multiplier,
                "label": rule.get("label") or rule_code,
                **(meta_extra or {}),
            },
        )
        if not ok:
            # 并发重放：那一条已存在，别把余额加两遍
            continue
        total += unit_coins
        inserted += 1

    if inserted:
        db.execute(
            update(CoinAccount)
            .where(CoinAccount.user_id == user_id)
            .values(
                balance=CoinAccount.balance + total,
                total_earned=CoinAccount.total_earned + total,
                updated_at=utcnow(),
            )
        )
        db.commit()
        db.expire_all()  # expire_on_commit=False：批量 update 后必须重载，否则读到的余额是旧值
    else:
        db.rollback()

    return {
        "rule_code": rule_code,
        "label": rule.get("label") or rule_code,
        "units": inserted,
        "coins": total,
        "capped": bool(global_cap_hit or rule_cap_hit),
        "cap_reason": ("earn_daily_cap" if global_cap_hit else ("rule_daily_cap" if rule_cap_hit else None)),
    }


def sync_day(db: Session, user_id: int, *, day: Optional[datetime.date] = None) -> Dict[str, Any]:
    """把某个北京自然日的**真实学习痕迹**折算成金币（幂等，可反复调）。

    数据来源只有一个：``services/study_calendar.day_ledger``。所以
    "今天背了 12 个单词"在首页、热力图、成长页、金币页是同一个 12。
    """
    biz_date = day or local_today()
    ledger = day_ledger(db, start_day=biz_date, end_day=biz_date, user_id=user_id)
    slot = ledger.get(biz_date.isoformat())
    counts = {
        field: _int(getattr(slot, field, 0) if slot is not None else 0, 0) for field in set(RULE_COUNT_FIELD.values())
    }
    rules = rule_map(db)
    items: List[Dict[str, Any]] = []
    total_units = 0
    total_coins = 0
    for rule_code, field in RULE_COUNT_FIELD.items():
        rule = rules.get(rule_code)
        if not rule:
            continue
        count = max(0, counts.get(field, 0))
        per = max(1, _int(rule.get("per_units"), 1))
        units = count // per if rule.get("kind") == "batch" else count
        if units <= 0:
            continue
        res = grant(
            db,
            user_id=user_id,
            rule=rule,
            biz_date=biz_date,
            units=units,
            title=f"{rule['label']}×{units}",
            meta_extra={"source_count": count, "per_units": per, "field": field},
        )
        items.append({**res, "source_count": count})
        total_units += res["units"]
        total_coins += res["coins"]

    acct = find_account(db, user_id)
    return {
        "biz_date": biz_date.isoformat(),
        "granted_units": total_units,
        "granted_coins": total_coins,
        "items": items,
        "balance": int(acct.balance) if acct else 0,
        "activity": {
            "is_active": bool(slot and slot.is_active),
            "is_effective": bool(slot and slot.is_effective),
            "counts": counts,
        },
    }


# --------------------------------------------------------------------------- #
# 六、签到 / 补签 / 连续签到
# --------------------------------------------------------------------------- #
def _activity(db: Session, user_id: int, start_day: datetime.date, end_day: datetime.date) -> Dict[str, Any]:
    """区间内的日活台账（``{iso日期: DayActivity}``）。"""
    return day_ledger(db, start_day=start_day, end_day=end_day, user_id=user_id)


def checkin_calendar(db: Session, user_id: int, *, days: int = 35) -> Dict[str, Any]:
    """签到日历：合并「有效学习日（自动视为已签到）」与显式签到/补签记录。

    返回 ``{"days": [{date,is_active,is_effective,checked,kind,coins}], ...}``，
    ``days`` 覆盖 [今天-(days-1), 今天]。
    """
    today = local_today()
    start = today - datetime.timedelta(days=max(1, days) - 1)
    ledger = _activity(db, user_id, start, today)
    logs = {
        str(r[0]): (r[1], r[2])
        for r in db.query(CheckinLog.biz_date, CheckinLog.kind, CheckinLog.coins)
        .filter(CheckinLog.user_id == user_id, CheckinLog.biz_date >= start, CheckinLog.biz_date <= today)
        .all()
    }
    out: List[Dict[str, Any]] = []
    cursor = start
    while cursor <= today:
        iso = cursor.isoformat()
        slot = ledger.get(iso)
        eff = bool(slot and slot.is_effective)
        manual = logs.get(iso)
        out.append(
            {
                "date": iso,
                "is_active": bool(slot and slot.is_active),
                "is_effective": eff,
                "checked": bool(manual) or eff,
                "kind": (manual[0] if manual else ("auto" if eff else None)),
                "coins": _int(manual[1], 0) if manual else 0,
            }
        )
        cursor += datetime.timedelta(days=1)
    return {"today": today.isoformat(), "days": out}


def checkin_streak(db: Session, user_id: int, *, today: Optional[datetime.date] = None) -> int:
    """连续签到天数 = 有效学习日 ∪ 显式签到/补签 的连续段长度。

    与 ``study_calendar`` 同一处理：今天还没签到不算断（从昨天起算）。
    """
    today = today or local_today()
    cal = checkin_calendar(db, user_id, days=400)
    checked = {d["date"] for d in cal["days"] if d["checked"]}
    cursor = today if today.isoformat() in checked else today - datetime.timedelta(days=1)
    streak = 0
    while cursor.isoformat() in checked:
        streak += 1
        cursor -= datetime.timedelta(days=1)
    return streak


def _study_streak(db: Session, user_id: int) -> Dict[str, Any]:
    """首页口径的连续学习（直接取台账，不在这里另算一套）。"""
    return streak_summary(
        _activity(db, user_id, local_today() - datetime.timedelta(days=400), local_today()), today=local_today()
    )


def checkin(db: Session, user_id: int) -> Dict[str, Any]:
    """当日签到：必须有真实学习痕迹，发基础币 + 命中里程碑的补差。"""
    today = local_today()
    if db.query(CheckinLog.id).filter(CheckinLog.user_id == user_id, CheckinLog.biz_date == today).first():
        raise BusinessException(
            ErrorCode.CONFLICT,
            "今天已经签到过了，明天再来",
            detail={"biz_date": today.isoformat()},
            status_code=409,
        )
    slot = _activity(db, user_id, today, today).get(today.isoformat())
    if not slot or not slot.is_active:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER,
            "今天还没有学习痕迹，签到不计。背几个单词、做几道题或专注一会儿再来",
            detail={"biz_date": today.isoformat(), "why": "no_activity"},
            status_code=422,
        )

    prev_streak = checkin_streak(db, user_id, today=today - datetime.timedelta(days=1))
    settings = get_settings(db)
    rules = rule_map(db)
    base = _int(settings.get("checkin_base_coins"), 5)

    db.add(
        CheckinLog(
            user_id=user_id,
            biz_date=today,
            kind="manual",
            coins=0,
            streak_days=prev_streak + 1,
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BusinessException(ErrorCode.CONFLICT, "今天已经签到过了，明天再来", status_code=409) from None

    coins = 0
    rule = rules.get("checkin") or {
        "rule_code": "checkin",
        "label": "每日签到",
        "kind": "daily_fixed",
        "coins": base,
        "daily_cap": 1,
        "per_units": 1,
    }
    rule = dict(rule)
    rule["coins"] = base
    res = grant(db, user_id=user_id, rule=rule, biz_date=today, units=1, title="每日签到")
    coins += res["coins"]

    new_streak = checkin_streak(db, user_id, today=today)
    milestones = _milestones(settings)
    bonus_items: List[Dict[str, Any]] = []
    for days_needed, bonus in milestones:
        # 只在"本次跨过"该档时发：prev < 档 <= new。否则连着签 30 天会天天领 7 天奖。
        if prev_streak < days_needed <= new_streak:
            b = grant(
                db,
                user_id=user_id,
                rule={
                    "rule_code": "streak_bonus",
                    "label": f"连续签到 {days_needed} 天",
                    "kind": "daily_fixed",
                    "coins": bonus,
                    "daily_cap": 1,
                    "per_units": 1,
                },
                biz_date=today,
                units=1,
                title=f"连续签到 {days_needed} 天奖励",
                meta_extra={"milestone": days_needed, "prev_streak": prev_streak, "streak": new_streak},
            )
            bonus_items.append({"days": days_needed, "coins": b["coins"]})
            coins += b["coins"]

    db.execute(
        update(CheckinLog)
        .where(CheckinLog.user_id == user_id, CheckinLog.biz_date == today)
        .values(coins=coins, streak_days=new_streak)
    )
    db.execute(
        update(CoinAccount).where(CoinAccount.user_id == user_id).values(last_checkin_date=today, updated_at=utcnow())
    )
    db.commit()
    db.expire_all()  # expire_on_commit=False：批量 update 后必须重载，否则读到的余额是旧值

    final_acct = find_account(db, user_id)
    return {
        "biz_date": today.isoformat(),
        "kind": "manual",
        "coins": coins,
        "checkin_streak": new_streak,
        "milestones": [b for b in bonus_items if b["coins"]],
        "balance": _int(final_acct.balance) if final_acct else 0,
    }


def makeup(db: Session, user_id: int, day: datetime.date) -> Dict[str, Any]:
    """补签：消耗 1 张补签卡，给**过去**某天补一个签到标记（不发金币）。"""
    today = local_today()
    settings = get_settings(db)
    window = max(1, _int(settings.get("makeup_window_days"), 7))
    month_limit = max(0, _int(settings.get("makeup_monthly_limit"), 3))

    if day >= today:
        raise BusinessException(ErrorCode.INVALID_PARAMETER, "补签只能补今天之前的日子", status_code=422)
    if (today - day).days > window:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER,
            f"超出补签窗口：只能补最近 {window} 天内的日子",
            detail={"window_days": window, "target": day.isoformat()},
            status_code=422,
        )
    slot = _activity(db, user_id, day, day).get(day.isoformat())
    if not slot or not slot.is_active:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER,
            "那天没有任何学习痕迹，补不了签（补签是「补记一次到场」，不是凭空造一天）",
            detail={"target": day.isoformat(), "why": "no_activity"},
            status_code=422,
        )
    if db.query(CheckinLog.id).filter(CheckinLog.user_id == user_id, CheckinLog.biz_date == day).first():
        raise BusinessException(ErrorCode.CONFLICT, "那天已经有签到记录了", status_code=409)
    if slot.is_effective:
        raise BusinessException(
            ErrorCode.CONFLICT,
            "那天已经是有效学习日，本来就计入连续签到，无需补签",
            status_code=409,
        )

    # 月度补签次数按"这次动作发生在哪个自然月"计（按 created_at，而不是被补的那天：
    # 1 月补 12 月的签要占 1 月的额度）。计数器不在账户上另存一份 —— 两份必然漂移。
    month_first = today.replace(day=1)
    next_month = (month_first + datetime.timedelta(days=32)).replace(day=1)
    used_in_month = _int(
        db.query(func.count(CheckinLog.id))
        .filter(
            CheckinLog.user_id == user_id,
            CheckinLog.kind == "makeup",
            CheckinLog.created_at >= local_window_for_day(month_first)[0],
            CheckinLog.created_at < local_window_for_day(next_month)[0],
        )
        .scalar()
    )
    if month_limit and used_in_month >= month_limit:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER,
            f"本月补签次数已用完（上限 {month_limit} 次）",
            detail={"monthly_limit": month_limit, "used": used_in_month},
            status_code=422,
        )

    acct = find_account(db, user_id)
    if not acct or _int(acct.makeup_cards) <= 0:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER,
            "没有补签卡，可在金币商店用 80 币兑换（全勤一天就够买一张）",
            detail={"need": "makeup_card", "balance": _int(acct.balance) if acct else 0},
            status_code=422,
        )

    # 扣卡走条件更新：库存不足时 rowcount=0，天然挡住并发双花
    res = db.execute(
        update(CoinAccount)
        .where(CoinAccount.user_id == user_id, CoinAccount.makeup_cards > 0)
        .values(makeup_cards=CoinAccount.makeup_cards - 1, last_checkin_date=day, updated_at=utcnow())
    )
    if res.rowcount == 0:  # pragma: no cover —— 上面已拦，并发兜底
        db.rollback()
        raise BusinessException(ErrorCode.CONFLICT, "补签卡已被用掉，请刷新后重试", status_code=409)

    db.add(CheckinLog(user_id=user_id, biz_date=day, kind="makeup", coins=0, streak_days=0))
    # 使用记录也进流水（币数 0：卡的钱在兑换那一步已经付过），审计才连得起来。
    # 这里**不能**复用 _insert_ledger：它撞唯一键时会 rollback 整个事务，
    # 会把刚扣掉的补签卡一起回滚掉，语义变成"卡没扣、签没补"，用户白折腾。
    db.add(
        CoinLedger(
            user_id=user_id,
            biz_date=day,
            rule_code="makeup_card",
            direction="adjust",
            coins=0,
            dedup_key=f"makeup:{day.isoformat()}",
            title="使用补签卡",
            meta={"card_cost": 0, "target": day.isoformat()},
        )
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise BusinessException(ErrorCode.CONFLICT, "那天已经有签到记录了", status_code=409) from None
    db.commit()
    db.expire_all()  # expire_on_commit=False：批量 update 后必须重载，否则读到的余额是旧值

    after = find_account(db, user_id)
    return {
        "biz_date": day.isoformat(),
        "kind": "makeup",
        "coins": 0,
        "cards_left": _int(after.makeup_cards) if after else 0,
        "checkin_streak": checkin_streak(db, user_id),
    }


# --------------------------------------------------------------------------- #
# 七、商店
# --------------------------------------------------------------------------- #
def _item_dict(row: RewardItem) -> Dict[str, Any]:
    return {
        "code": row.code,
        "name": row.name,
        "description": row.description or "",
        "kind": row.kind,
        "cost_coins": _int(row.cost_coins),
        "payload": row.payload if isinstance(row.payload, dict) else {},
        "monthly_limit": _int(row.monthly_limit),
        "is_active": bool(row.is_active),
        "sort_order": _int(row.sort_order),
    }


def list_items(db: Session, *, only_active: bool = False) -> List[Dict[str, Any]]:
    q = db.query(RewardItem)
    if only_active:
        q = q.filter(RewardItem.is_active.is_(True))
    rows = q.order_by(RewardItem.sort_order, RewardItem.code).all()
    if not rows:
        return [dict(s, is_active=True) for s in DEFAULT_ITEMS]
    return [_item_dict(r) for r in rows]


def shop(db: Session, user_id: int) -> Dict[str, Any]:
    """商店视图：余额 + 每件商品的可兑换状态（已拥有 / 本月已达上限 / 币不够）。"""
    acct = find_account(db, user_id)
    balance = _int(acct.balance) if acct else 0
    month = _month_key(local_today())
    bought = {}
    for code, n in (
        db.query(Redemption.item_code, func.count(Redemption.id))
        .filter(Redemption.user_id == user_id, Redemption.status == "ok", Redemption.biz_month == month)
        .group_by(Redemption.item_code)
        .all()
    ):
        bought[code] = _int(n)
    unlocked = _unlocked_maps(db, user_id)
    items = []
    for it in list_items(db, only_active=True):
        owned = it["kind"] in ("avatar_frame", "title") and it["code"] in unlocked.get(
            "frames" if it["kind"] == "avatar_frame" else "titles", []
        )
        used = bought.get(it["code"], 0)
        limit_hit = bool(it["monthly_limit"]) and used >= it["monthly_limit"]
        reason = None
        if owned:
            reason = "owned"
        elif limit_hit:
            reason = "monthly_limit"
        elif balance < it["cost_coins"]:
            reason = "insufficient"
        items.append(
            {
                **it,
                "owned": owned,
                "used_this_month": used,
                "affordable": balance >= it["cost_coins"],
                "blocked": reason,
            }
        )
    return {
        "balance": balance,
        "makeup_cards": _int(acct.makeup_cards) if acct else 0,
        "boost_until": acct.boost_until if acct and acct.boost_until else None,
        "items": items,
    }


def _month_key(day: datetime.date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _unlocked_maps(db: Session, user_id: int) -> Dict[str, List[str]]:
    from core.models.gamification import UserProfile

    row = db.query(UserProfile).filter(UserProfile.user_id == user_id).one_or_none()
    if row is None:
        return {"frames": [], "titles": []}
    data = row.unlocked if isinstance(row.unlocked, dict) else {}
    return {
        "frames": [x for x in (data.get("frames") or []) if isinstance(x, str)],
        "titles": [x for x in (data.get("titles") or []) if isinstance(x, str)],
    }


def redeem(db: Session, user_id: int, code: str) -> Dict[str, Any]:
    """兑换：扣款与发货同事务，余额不足直接拒绝（不会先扣后发）。"""
    item = db.query(RewardItem).filter(RewardItem.code == code, RewardItem.is_active.is_(True)).one_or_none()
    if item is None:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "商品不存在或已下架", status_code=404)
    cost = _item_dict(item)["cost_coins"]
    kind = item.kind
    month = _month_key(local_today())

    unlocked = _unlocked_maps(db, user_id)
    if kind in ("avatar_frame", "title") and code in (
        unlocked["frames"] if kind == "avatar_frame" else unlocked["titles"]
    ):
        raise BusinessException(ErrorCode.CONFLICT, "该权益已拥有，无需重复兑换", status_code=409)
    limit = _int(item.monthly_limit)
    if limit:
        used = _int(
            db.query(func.count(Redemption.id))
            .filter(
                Redemption.user_id == user_id,
                Redemption.item_code == code,
                Redemption.status == "ok",
                Redemption.biz_month == month,
            )
            .scalar()
        )
        if used >= limit:
            raise BusinessException(
                ErrorCode.INVALID_PARAMETER,
                f"本月兑换已达上限（{limit} 次）",
                detail={"used": used, "limit": limit},
                status_code=422,
            )

    # 条件扣款：balance >= cost 才更新，rowcount=0 即余额不足（并发双花也挡得住）
    res = db.execute(
        update(CoinAccount)
        .where(CoinAccount.user_id == user_id, CoinAccount.balance >= cost)
        .values(balance=CoinAccount.balance - cost, total_spent=CoinAccount.total_spent + cost, updated_at=utcnow())
    )
    if res.rowcount == 0:
        db.rollback()
        acct = find_account(db, user_id)
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER,
            f"金币不足，还差 {max(0, cost - (_int(acct.balance) if acct else 0))} 币",
            detail={"cost": cost, "balance": _int(acct.balance) if acct else 0},
            status_code=422,
        )

    now = utcnow()
    detail: Dict[str, Any] = {"kind": kind, "cost": cost}
    if kind == "makeup_card":
        db.execute(
            update(CoinAccount).where(CoinAccount.user_id == user_id).values(makeup_cards=CoinAccount.makeup_cards + 1)
        )
        acct = find_account(db, user_id)
        detail["cards_left"] = _int(acct.makeup_cards) if acct else 0
    elif kind == "boost":
        payload = item.payload if isinstance(item.payload, dict) else {}
        hours = max(1, _int(payload.get("hours"), 24))
        db.execute(
            update(CoinAccount)
            .where(CoinAccount.user_id == user_id)
            .values(boost_until=now + datetime.timedelta(hours=hours))
        )
        detail["boost_until"] = (now + datetime.timedelta(hours=hours)).isoformat()
        detail["multiplier"] = payload.get("multiplier", 1.5)
    elif kind in ("avatar_frame", "title"):
        from core.models.gamification import UserProfile

        row = db.query(UserProfile).filter(UserProfile.user_id == user_id).one_or_none()
        if row is None:
            row = UserProfile(user_id=user_id, avatar_kind="initials", prefs={}, unlocked={"frames": [], "titles": []})
            db.add(row)
            db.flush()
        data = row.unlocked if isinstance(row.unlocked, dict) else {}
        frames = list(data.get("frames") or [])
        titles = list(data.get("titles") or [])
        bucket = "frames" if kind == "avatar_frame" else "titles"
        if code not in (frames if bucket == "frames" else titles):
            (frames if bucket == "frames" else titles).append(code)
        row.unlocked = {"frames": frames, "titles": titles}
        detail["unlocked"] = bucket

    token = uuid.uuid4().hex[:12]
    _insert_ledger(
        db,
        user_id=user_id,
        biz_date=local_today(),
        rule_code=f"redeem:{code}",
        direction="spend",
        coins=-cost,
        dedup_key=f"redeem:{code}:{token}",
        title=f"兑换 · {item.name}",
        meta=detail,
    )
    db.add(Redemption(user_id=user_id, item_code=code, cost_coins=cost, status="ok", biz_month=month, detail=detail))
    db.commit()
    db.expire_all()  # expire_on_commit=False：批量 update 后必须重载，否则读到的余额是旧值

    acct = find_account(db, user_id)
    return {
        "code": code,
        "name": item.name,
        "cost": cost,
        "detail": detail,
        "balance": _int(acct.balance) if acct else 0,
    }


# --------------------------------------------------------------------------- #
# 八、读侧：汇总 / 流水 / 规则说明
# --------------------------------------------------------------------------- #
def _account_dict(acct: Optional[CoinAccount]) -> Dict[str, Any]:
    boost_until = acct.boost_until if acct and acct.boost_until else None
    if isinstance(boost_until, datetime.datetime) and boost_until.tzinfo is not None:
        boost_until = boost_until.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return {
        "balance": _int(acct.balance) if acct else 0,
        "total_earned": _int(acct.total_earned) if acct else 0,
        "total_spent": _int(acct.total_spent) if acct else 0,
        "makeup_cards": _int(acct.makeup_cards) if acct else 0,
        "boost_active": bool(boost_until and boost_until > utcnow()),
        "boost_until": boost_until,
        "last_checkin_date": (acct.last_checkin_date.isoformat() if acct and acct.last_checkin_date else None),
    }


def summary(db: Session, user_id: int) -> Dict[str, Any]:
    """金币中心总览（零数据新号给诚实空态，不播种假奖励）。"""
    acct = find_account(db, user_id)
    settings = get_settings(db)
    today = local_today()
    slot = _activity(db, user_id, today, today).get(today.isoformat())
    checked_today = bool(
        db.query(CheckinLog.id).filter(CheckinLog.user_id == user_id, CheckinLog.biz_date == today).first()
    )
    study = _study_streak(db, user_id)
    streak = checkin_streak(db, user_id, today=today)
    milestones = _milestones(settings)
    next_milestone = next(((d, c) for d, c in milestones if d > streak), None)
    cap_total = _int(settings.get("daily_earn_cap"), 260)
    today_earned = earned_on(db, user_id, today)
    return {
        "account": _account_dict(acct),
        "state": "empty" if not acct or _int(acct.total_earned) == 0 else "ready",
        "today": {
            "date": today.isoformat(),
            "is_active": bool(slot and slot.is_active),
            "is_effective": bool(slot and slot.is_effective),
            "checked": checked_today,
            "earned": today_earned,
            "cap": cap_total,
            "remaining": max(0, cap_total - today_earned),
        },
        "streak": {
            "checkin_days": streak,
            "study_days": study["current"],
            "study_longest": study["longest"],
            "study_rule": study["rule"],
            "next_milestone": ({"days": next_milestone[0], "coins": next_milestone[1]} if next_milestone else None),
            "note": "连续签到 = 有效学习日或已签到/已补签的连续天数；有效学习日自动算已签到，两者不会互相打脸",
        },
        "checkin_base_coins": _int(settings.get("checkin_base_coins"), 5),
        "makeup_window_days": _int(settings.get("makeup_window_days"), 7),
        "milestones": [{"days": d, "coins": c} for d, c in milestones],
    }


def history(db: Session, user_id: int, *, page: int = 1, page_size: int = 20, direction: Optional[str] = None) -> Query:
    """个人金币流水（分页壳由 utils.response 统一给）。"""
    q = db.query(CoinLedger).filter(CoinLedger.user_id == user_id)
    if direction in ("earn", "spend", "adjust"):
        q = q.filter(CoinLedger.direction == direction)
    return q.order_by(CoinLedger.created_at.desc(), CoinLedger.id.desc())


def ledger_dict(row: CoinLedger) -> Dict[str, Any]:
    meta = row.meta if isinstance(row.meta, dict) else {}
    return {
        "id": row.id,
        "biz_date": row.biz_date.isoformat() if row.biz_date else None,
        "rule_code": row.rule_code,
        "direction": row.direction,
        "coins": _int(row.coins),
        "title": row.title or row.rule_code,
        "meta": meta,
        "created_at": row.created_at,
    }


def rules_doc(db: Session) -> Dict[str, Any]:
    """规则说明页数据（公开给登录用户：钱怎么算的必须能查到）。"""
    settings = get_settings(db)
    return {
        "rules": list_rules(db, only_active=True),
        "settings": {
            "daily_earn_cap": _int(settings.get("daily_earn_cap"), 260),
            "checkin_base_coins": _int(settings.get("checkin_base_coins"), 5),
            "makeup_window_days": _int(settings.get("makeup_window_days"), 7),
            "makeup_monthly_limit": _int(settings.get("makeup_monthly_limit"), 3),
            "boost_hours": _int(settings.get("boost_hours"), 24),
            "boost_multiplier": settings.get("boost_multiplier", 1.5),
        },
        "milestones": [{"days": d, "coins": c} for d, c in _milestones(settings)],
        "count_fields": RULE_COUNT_FIELD,
        "currency_note": "金币（可赚可花）与成长积分（等级口径，见 /api/growth）是两套东西：金币只做激励兑换，不影响等级。",
    }


# --------------------------------------------------------------------------- #
# 九、管理端
# --------------------------------------------------------------------------- #
def admin_overview(db: Session, *, days: int = 14) -> Dict[str, Any]:
    """发放/消耗大盘（管理台「激励运营」首屏）。"""
    days = max(7, min(90, days))
    today = local_today()
    start = today - datetime.timedelta(days=days - 1)
    totals = db.query(
        func.coalesce(func.sum(case((CoinLedger.coins > 0, CoinLedger.coins), else_=0)), 0),
        func.coalesce(func.sum(case((CoinLedger.coins < 0, -CoinLedger.coins), else_=0)), 0),
        func.count(func.distinct(CoinLedger.user_id)),
    ).first()
    per_day = (
        db.query(
            CoinLedger.biz_date,
            func.coalesce(func.sum(CoinLedger.coins), 0),
            func.count(func.distinct(CoinLedger.user_id)),
        )
        .filter(CoinLedger.biz_date >= start, CoinLedger.biz_date <= today)
        .group_by(CoinLedger.biz_date)
        .order_by(CoinLedger.biz_date)
        .all()
    )
    per_rule = (
        db.query(CoinLedger.rule_code, func.coalesce(func.sum(CoinLedger.coins), 0), func.count(CoinLedger.id))
        .filter(CoinLedger.biz_date >= start, CoinLedger.biz_date <= today, CoinLedger.coins > 0)
        .group_by(CoinLedger.rule_code)
        .order_by(func.coalesce(func.sum(CoinLedger.coins), 0).desc())
        .all()
    )
    top_items = (
        db.query(Redemption.item_code, func.count(Redemption.id), func.coalesce(func.sum(Redemption.cost_coins), 0))
        .filter(Redemption.status == "ok")
        .group_by(Redemption.item_code)
        .order_by(func.count(Redemption.id).desc())
        .limit(10)
        .all()
    )
    rule_labels = {r["rule_code"]: r["label"] for r in list_rules(db)}
    item_names = {i["code"]: i["name"] for i in list_items(db)}
    return {
        "window_days": days,
        "total_earned": _int(totals[0]) if totals else 0,
        "total_spent": _int(totals[1]) if totals else 0,
        "participants": _int(totals[2]) if totals else 0,
        "accounts": _int(db.query(func.count(CoinAccount.id)).scalar()),
        "holders": _int(db.query(func.count(CoinAccount.id)).filter(CoinAccount.balance > 0).scalar()),
        "per_day": [{"date": str(d), "coins": _int(c), "users": _int(u)} for d, c, u in per_day if d is not None],
        "per_rule": [
            {"rule_code": r, "label": rule_labels.get(r, r), "coins": _int(c), "rows": _int(n)} for r, c, n in per_rule
        ],
        "top_items": [
            {"code": c, "name": item_names.get(c, c), "count": _int(n), "coins": _int(coins)}
            for c, n, coins in top_items
        ],
    }


def admin_user_detail(db: Session, user_id: int) -> Dict[str, Any]:
    """某个用户的激励画像（管理台详情抽屉）。"""
    acct = find_account(db, user_id)
    study = _study_streak(db, user_id)
    rows = (
        db.query(CoinLedger)
        .filter(CoinLedger.user_id == user_id)
        .order_by(CoinLedger.created_at.desc(), CoinLedger.id.desc())
        .limit(20)
        .all()
    )
    return {
        "account": _account_dict(acct),
        "checkin_streak": checkin_streak(db, user_id),
        "study_streak": study["current"],
        "recent_ledger": [ledger_dict(r) for r in rows],
        "checkins": [
            {"biz_date": str(d), "kind": k, "coins": _int(c)}
            for d, k, c in db.query(CheckinLog.biz_date, CheckinLog.kind, CheckinLog.coins)
            .filter(CheckinLog.user_id == user_id)
            .order_by(CheckinLog.biz_date.desc())
            .limit(15)
            .all()
        ],
    }


def admin_update_rule(db: Session, code: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """改一条规则（只允许动数值/开关，规则码与台账字段映射固定在代码里）。"""
    row = db.query(GamificationRule).filter(GamificationRule.rule_code == code).one_or_none()
    if row is None:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, f"规则 {code} 不存在", status_code=404)
    if "coins" in fields:
        v = _int(fields["coins"], -1)
        if not 0 <= v <= 500:
            raise BusinessException(ErrorCode.INVALID_PARAMETER, "单价需在 0~500 金币之间", status_code=422)
        row.coins = v
    if "daily_cap" in fields:
        v = _int(fields["daily_cap"], -1)
        if not 0 <= v <= 50:
            raise BusinessException(
                ErrorCode.INVALID_PARAMETER, "单日上限需在 0~50 次之间（0=停用发放）", status_code=422
            )
        row.daily_cap = v
    if "per_units" in fields:
        v = _int(fields["per_units"], 0)
        if not 1 <= v <= 200:
            raise BusinessException(ErrorCode.INVALID_PARAMETER, "计量单位需在 1~200 之间", status_code=422)
        row.per_units = v
    if "label" in fields:
        label = str(fields["label"] or "").strip()[:60]
        if not label:
            raise BusinessException(ErrorCode.INVALID_PARAMETER, "展示名不能为空", status_code=422)
        row.label = label
    if "is_active" in fields:
        row.is_active = bool(fields["is_active"])
    row.updated_at = utcnow()
    db.commit()
    return _rule_dict(row)


_NUMBER_SETTINGS = {
    "daily_earn_cap": (10, 5000),
    "checkin_base_coins": (0, 100),
    "makeup_window_days": (1, 60),
    "makeup_monthly_limit": (0, 31),
    "boost_hours": (1, 168),
    "admin_adjust_max": (0, 20000),
}


def admin_update_settings(db: Session, patch: Dict[str, Any]) -> Dict[str, Any]:
    """改全局参数（逐键校验范围；不认识的键直接拒，防止前端拼错静默失效）。"""
    if not patch:
        raise BusinessException(ErrorCode.INVALID_PARAMETER, "没有要改的参数", status_code=422)
    for key, raw in patch.items():
        if key not in DEFAULT_SETTINGS:
            raise BusinessException(ErrorCode.INVALID_PARAMETER, f"未知参数 {key}", status_code=422)
        row = db.query(GamificationSetting).filter(GamificationSetting.setting_key == key).one_or_none()
        if key == "streak_milestones":
            if not isinstance(raw, dict) or not raw:
                raise BusinessException(ErrorCode.INVALID_PARAMETER, "里程碑需是 {天数: 金币} 映射", status_code=422)
            clean: Dict[str, int] = {}
            for d, c in raw.items():
                days, coins = _int(d, 0), _int(c, 0)
                if not 1 <= days <= 3650 or not 0 <= coins <= 5000:
                    raise BusinessException(
                        ErrorCode.INVALID_PARAMETER,
                        f"里程碑 {d}→{c} 超出范围（天数 1~3650，金币 0~5000）",
                        status_code=422,
                    )
                if coins:
                    clean[str(days)] = coins
            value = {"v": dict(sorted(clean.items(), key=lambda kv: int(kv[0])))}
        elif key == "boost_multiplier":
            try:
                mult = float(raw)
            except (TypeError, ValueError):
                raise BusinessException(ErrorCode.INVALID_PARAMETER, "倍率需是数字", status_code=422) from None
            if not 1.0 < mult <= 5.0:
                raise BusinessException(ErrorCode.INVALID_PARAMETER, "倍率需大于 1 且不超过 5", status_code=422)
            value = {"v": mult}
        else:
            lo, hi = _NUMBER_SETTINGS[key]
            v = _int(raw, lo - 1)
            if not lo <= v <= hi:
                raise BusinessException(ErrorCode.INVALID_PARAMETER, f"{key} 需在 {lo}~{hi} 之间", status_code=422)
            value = {"v": v}
        if row is None:
            db.add(GamificationSetting(setting_key=key, value=value, label=DEFAULT_SETTINGS[key]["label"]))
        else:
            row.value = value
            row.updated_at = utcnow()
    db.commit()
    return get_settings(db)


def admin_upsert_item(db: Session, code: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """新增/修改商品。发货种类必须是系统已实现的四种之一（不做发不出去的商品）。"""
    if not code or not str(code).strip():
        raise BusinessException(ErrorCode.INVALID_PARAMETER, "商品码不能为空", status_code=422)
    code = str(code).strip()[:40]
    kind = str(fields.get("kind") or "").strip()
    if kind not in VALID_ITEM_KINDS:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER, f"权益类型只能是 {'/'.join(VALID_ITEM_KINDS)}", status_code=422
        )
    name = str(fields.get("name") or "").strip()[:60]
    if not name:
        raise BusinessException(ErrorCode.INVALID_PARAMETER, "商品名不能为空", status_code=422)
    cost = _int(fields.get("cost_coins"), -1)
    if not 0 <= cost <= 100000:
        raise BusinessException(ErrorCode.INVALID_PARAMETER, "价格需在 0~100000 金币之间", status_code=422)
    payload = fields.get("payload") if isinstance(fields.get("payload"), dict) else {}
    row = db.query(RewardItem).filter(RewardItem.code == code).one_or_none()
    created = row is None
    if created:
        row = RewardItem(code=code, name=name, kind=kind, cost_coins=cost, payload=payload)
        db.add(row)
    row.name = name
    row.kind = kind
    row.cost_coins = cost
    row.payload = payload
    row.description = str(fields.get("description") or "")[:200]
    row.monthly_limit = max(0, _int(fields.get("monthly_limit"), 0))
    row.sort_order = _int(fields.get("sort_order"), 0)
    # router 传 body.model_dump() 时未带的 is_active 恒为 None：只接受显式布尔值，
    # None 跳过——新增落到列默认（上架），编辑维持原状，避免 bool(None)=False 静默下架。
    if fields.get("is_active") is not None:
        row.is_active = bool(fields["is_active"])
    row.updated_at = utcnow()
    db.commit()
    return _item_dict(row)


def admin_toggle_item(db: Session, code: str, active: bool) -> Dict[str, Any]:
    """上架/下架。**不做物理删除**：已发放的权益要能被历史流水解释。"""
    row = db.query(RewardItem).filter(RewardItem.code == code).one_or_none()
    if row is None:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "商品不存在", status_code=404)
    row.is_active = bool(active)
    row.updated_at = utcnow()
    db.commit()
    return _item_dict(row)


def admin_adjust(db: Session, *, actor_id: Optional[int], user_id: int, coins: int, reason: str) -> Dict[str, Any]:
    """人工调整金币（发补偿 / 收回异常发放）。必填原因 + 记操作者 + 走流水。"""
    delta = _int(coins, 0)
    if delta == 0:
        raise BusinessException(ErrorCode.INVALID_PARAMETER, "调整数额不能为 0", status_code=422)
    note = str(reason or "").strip()
    if len(note) < 4:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER, "请填写不少于 4 个字的调整原因（审计要能看懂）", status_code=422
        )
    limit = _int(get_settings(db).get("admin_adjust_max"), 2000)
    if limit and abs(delta) > limit:
        raise BusinessException(ErrorCode.INVALID_PARAMETER, f"单次调整不得超过 {limit} 币", status_code=422)
    acct = get_account(db, user_id, create=delta > 0)
    if acct is None:
        raise BusinessException(
            ErrorCode.RESOURCE_NOT_FOUND, "该用户还没有金币账户（余额为 0，无法扣减）", status_code=404
        )
    if delta < 0 and _int(acct.balance) + delta < 0:
        raise BusinessException(
            ErrorCode.INVALID_PARAMETER,
            f"扣减后余额为负（当前 {_int(acct.balance)}），请改用较小的数额",
            detail={"balance": _int(acct.balance)},
            status_code=422,
        )

    ok = _insert_ledger(
        db,
        user_id=user_id,
        biz_date=local_today(),
        rule_code="admin_adjust",
        direction="adjust",
        coins=delta,
        dedup_key=f"admin_adjust:{uuid.uuid4().hex}",
        title=("管理员发放" if delta > 0 else "管理员收回"),
        meta={"reason": note[:300], "actor_id": actor_id},
        actor_id=actor_id,
    )
    if not ok:  # pragma: no cover —— uuid 键几乎不可能撞
        db.rollback()
        raise BusinessException(ErrorCode.CONFLICT, "调整记录写入冲突，请重试", status_code=409)
    db.execute(
        update(CoinAccount)
        .where(CoinAccount.user_id == user_id, CoinAccount.balance + delta >= 0)
        .values(
            balance=CoinAccount.balance + delta,
            total_earned=CoinAccount.total_earned + max(0, delta),
            total_spent=CoinAccount.total_spent + max(0, -delta),
            updated_at=utcnow(),
        )
    )
    db.commit()
    db.expire_all()  # expire_on_commit=False：批量 update 后必须重载，否则读到的余额是旧值
    acct = find_account(db, user_id)
    return {"user_id": user_id, "coins": delta, "balance": _int(acct.balance) if acct else 0, "reason": note}


def admin_ledger_query(
    db: Session, *, user_id: Optional[int] = None, rule_code: Optional[str] = None, direction: Optional[str] = None
) -> Query:
    q = db.query(CoinLedger)
    if user_id is not None:
        q = q.filter(CoinLedger.user_id == user_id)
    if rule_code:
        q = q.filter(CoinLedger.rule_code == rule_code)
    if direction in ("earn", "spend", "adjust"):
        q = q.filter(CoinLedger.direction == direction)
    return q.order_by(CoinLedger.created_at.desc(), CoinLedger.id.desc())


def ledger_with_user(db: Session, row: CoinLedger) -> Dict[str, Any]:
    """流水 + 归属用户名（管理端审计列表用，查不到用户就留空不编造）。"""
    d = ledger_dict(row)
    d["user_id"] = row.user_id
    try:
        from models import User

        u = db.query(User.username, User.display_name).filter(User.id == row.user_id).first()
        d["username"] = u[0] if u else None
        d["display_name"] = u[1] if u and u[1] else None
    except Exception as exc:  # noqa: BLE001 —— 审计列表不能因为一次用户表查询失败就 500
        logger.warning("[gamification] 流水归属用户查询失败 user_id=%s: %s", row.user_id, exc)
        d["username"] = None
    return d


def calendar_dict(db: Session, user_id: int, *, days: int = 35) -> Dict[str, Any]:
    out = checkin_calendar(db, user_id, days=days)
    out["streak"] = checkin_streak(db, user_id)
    return out


def available_rules(db: Session) -> List[str]:
    return [r["rule_code"] for r in list_rules(db)]
