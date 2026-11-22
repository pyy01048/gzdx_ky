# -*- coding: utf-8 -*-
"""金币激励域模型（W6 · 对齐 core/sql/125_gamification_coins.sql）。

设计口径见 docs/design/gamification-coin-strategy-v1.md，三条硬约定：

1. **不设外键**：users 表归 database.Base（models.py）所有，跨 Base 声明 FK 会在
   flush 期抛 ``NoReferencedTableError``（``routers/study/goals.py`` 头注释记录过
   这个 500）；且 users 是软删除，CASCADE 会无声抹掉审计流水。故一律
   ``user_id`` + 索引（与 121 分片同风格），归属由 ``utils.scope.scoped/owner_id`` 保证。
2. **主键用 BigIntKey**（PG=BIGINT / SQLite=INTEGER）：只有类型恰好是 INTEGER 时
   SQLite 才把它当 rowid 别名，声明 BIGINT 会让不带 id 的插入直接 NOT NULL 失败。
3. **流水只增不改**：``coin_ledger`` / ``checkin_logs`` / ``redemptions`` 没有 updated_at，
   余额是流水的物化缓存，任何改账都走新的一行 ``adjust`` 流水。
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, Date, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ..pg_types import JSONBObject
from .base import Base, BigIntKey, DateTimeUTC, TimestampMixin


class CoinAccount(TimestampMixin, Base):
    """金币账户：一人一行，余额 = 流水累加的物化缓存。"""

    __tablename__ = "coin_accounts"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigIntKey, nullable=False, index=True, comment="归属用户 ID（行级隔离键）")
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="当前金币余额")
    total_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="历史累计获得")
    total_spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="历史累计消耗")
    makeup_cards: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="补签卡库存")
    boost_until: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="加成卡生效截止（naive UTC，NULL=未激活）"
    )
    last_checkin_date: Mapped[datetime.date | None] = mapped_column(Date, comment="最近签到/补签的北京自然日")

    __table_args__ = (UniqueConstraint("user_id", name="uq_coin_accounts_user"),)


class CoinLedger(Base):
    """金币流水（append-only）：一行 = 一个最小发放单位或一次消耗。"""

    __tablename__ = "coin_ledger"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigIntKey, nullable=False, index=True, comment="归属用户 ID")
    biz_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, comment="业务归属北京自然日")
    rule_code: Mapped[str] = mapped_column(String(40), nullable=False, comment="规则码")
    direction: Mapped[str] = mapped_column(String(8), nullable=False, comment="earn | spend | adjust")
    coins: Mapped[int] = mapped_column(Integer, nullable=False, comment="变动量：收入正、支出负")
    unit_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="同日同规则第 N 个单位（幂等序号）"
    )
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False, comment="幂等键，(user_id, dedup_key) 唯一")
    title: Mapped[str | None] = mapped_column(String(80), comment="展示标题")
    meta: Mapped[dict] = mapped_column(JSONBObject, nullable=False, default=dict, comment="结构化附注 JSON")
    actor_id: Mapped[int | None] = mapped_column(BigIntKey, comment="管理员操作者（仅后台动作）")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="落库时间（UTC）"
    )

    __table_args__ = (UniqueConstraint("user_id", "dedup_key", name="uq_coin_ledger_dedup"),)


class CheckinLog(Base):
    """签到日志：一人一日一行（唯一约束即"重复签到"的硬闸）。"""

    __tablename__ = "checkin_logs"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigIntKey, nullable=False, index=True, comment="归属用户 ID")
    biz_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, comment="签到所属北京自然日")
    kind: Mapped[str] = mapped_column(String(12), nullable=False, comment="manual 当日签到 | makeup 补签")
    coins: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="该次发放金币（补签恒 0）")
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="签到时连续天数快照")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="落库时间（UTC）"
    )

    __table_args__ = (UniqueConstraint("user_id", "biz_date", name="uq_checkin_logs_user_day"),)


class GamificationRule(Base):
    """金币获取规则（单价 / 计量 / 单日上限），管理台可改。"""

    __tablename__ = "gamification_rules"

    rule_code: Mapped[str] = mapped_column(String(40), primary_key=True, comment="规则码（服务层 DEFAULT_RULES 键）")
    label: Mapped[str] = mapped_column(String(60), nullable=False, comment="展示名")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, comment="batch | per_item | daily_fixed")
    per_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="多少个真实行为折算一次")
    unit_label: Mapped[str | None] = mapped_column(String(20), comment="行为单位名（个/题/张/分钟）")
    coins: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="一次发放的金币数")
    daily_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="单日最多计次数")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="展示排序")
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), onupdate=func.now(), nullable=False, comment="最后更新时间（UTC）"
    )


class GamificationSetting(Base):
    """全局参数（日上限 / 签到基础币 / 里程碑 / 补签窗口 / 加成倍率）。"""

    __tablename__ = "gamification_settings"

    setting_key: Mapped[str] = mapped_column(String(48), primary_key=True, comment="参数键")
    value: Mapped[dict] = mapped_column(JSONBObject, nullable=False, comment="参数值 JSON")
    label: Mapped[str] = mapped_column(String(80), nullable=False, comment="中文说明")
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), onupdate=func.now(), nullable=False, comment="最后更新时间（UTC）"
    )


class RewardItem(Base):
    """商店商品：只上架系统真能兑现的权益。"""

    __tablename__ = "reward_items"

    code: Mapped[str] = mapped_column(String(40), primary_key=True, comment="商品码")
    name: Mapped[str] = mapped_column(String(60), nullable=False, comment="商品名")
    description: Mapped[str | None] = mapped_column(String(200), comment="说明（含兑现方式）")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, comment="makeup_card | boost | avatar_frame | title")
    cost_coins: Mapped[int] = mapped_column(Integer, nullable=False, comment="兑换所需金币")
    payload: Mapped[dict] = mapped_column(JSONBObject, nullable=False, default=dict, comment="类型参数 JSON")
    monthly_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="每人每月上限（0=不限）")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否上架")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="展示排序")
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), onupdate=func.now(), nullable=False, comment="最后更新时间（UTC）"
    )


class Redemption(Base):
    """兑换流水：与 coin_ledger(spend) 同事务双记账。"""

    __tablename__ = "redemptions"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigIntKey, nullable=False, index=True, comment="兑换人")
    item_code: Mapped[str] = mapped_column(String(40), nullable=False, comment="商品码（逻辑关联）")
    cost_coins: Mapped[int] = mapped_column(Integer, nullable=False, comment="实扣金币（正数）")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ok", comment="ok | refunded")
    biz_month: Mapped[str | None] = mapped_column(String(7), comment="归属月份 YYYY-MM（月度限购计数键）")
    detail: Mapped[dict] = mapped_column(JSONBObject, nullable=False, default=dict, comment="发货明细 JSON")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="兑换时间（UTC）"
    )


class UserProfile(TimestampMixin, Base):
    """用户档案扩展（设置页：头像 / 个人信息 / 偏好 / 已解锁权益）。"""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(BigIntKey, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigIntKey, nullable=False, index=True, comment="归属用户 ID（一人一行）")
    avatar_kind: Mapped[str] = mapped_column(
        String(12), nullable=False, default="initials", comment="initials | preset | url"
    )
    avatar_value: Mapped[str | None] = mapped_column(String(300), comment="色块色名 / 表情键 / 图片 URL")
    avatar_frame: Mapped[str | None] = mapped_column(String(40), comment="使用中的头像框商品码")
    title: Mapped[str | None] = mapped_column(String(40), comment="佩戴中的称号商品码")
    bio: Mapped[str | None] = mapped_column(String(200), comment="个人简介")
    grade: Mapped[str | None] = mapped_column(String(20), comment="年级/届别（展示用）")
    major: Mapped[str | None] = mapped_column(String(60), comment="专业方向（自由文本）")
    prefs: Mapped[dict] = mapped_column(JSONBObject, nullable=False, default=dict, comment="偏好 JSON")
    unlocked: Mapped[dict] = mapped_column(JSONBObject, nullable=False, default=dict, comment="已解锁权益 JSON")

    __table_args__ = (UniqueConstraint("user_id", name="uq_user_profiles_user"),)


__all__ = [
    "CheckinLog",
    "CoinAccount",
    "CoinLedger",
    "GamificationRule",
    "GamificationSetting",
    "Redemption",
    "RewardItem",
    "UserProfile",
]
