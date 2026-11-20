"""研招通知域模型：通知 / 订阅 / 提醒记录 / 提醒日志 / 采集日志 / 遗留表。

对齐 core/sql/061_notices.sql。

与 core.models.schools 的分工：
    schools.py —— 院校 / 学院 / 专业 / 招生 / 分数线（相对静态的主数据）
    notices.py —— 通知采集与推送（高频写入的流水数据）
"""

from __future__ import annotations

import datetime

from sqlalchemy import ( Boolean, Float, ForeignKey, Index, Integer, REAL, SmallInteger,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..pg_types import JSONBList, JSONBObject, build_enum
from .base import Base, BigIntKey, BigIntPKMixin, DateTimeUTC


class KaoyanNotice(BigIntPKMixin, Base):
    """研招通知。"""

    __tablename__ = "kaoyan_notices"

    school_id: Mapped[int | None] = mapped_column( ForeignKey("kaoyan_schools.id", ondelete="SET NULL"),
    comment="解析出的院校 ID，未匹配上为空")
    school_name: Mapped[str | None] = mapped_column(Text, comment="通知上的院校名原文")
    title: Mapped[str] = mapped_column(Text, nullable=False, comment="通知标题")
    notice_type: Mapped[str] = mapped_column(
        build_enum("notice_type"), nullable=False, server_default="公告",
        comment="通知类型：公告 / 简章 / 复试 / 调剂 / 录取")
    publish_date: Mapped[str | None] = mapped_column(Text, comment="发布日期 YYYY-MM-DD")
    url: Mapped[str | None] = mapped_column(Text, comment="原文链接")
    source: Mapped[str | None] = mapped_column(Text, comment="采集来源")
    fetched_at: Mapped[str | None] = mapped_column(Text, comment="采集时间")
    importance_level: Mapped[str | None] = mapped_column(
        build_enum("importance_level"), comment="重要级：urgent/important/normal/low")
    importance_score: Mapped[float | None] = mapped_column(REAL, comment="重要度评分 0-1")
    importance_reason: Mapped[str | None] = mapped_column(Text, comment="重要度判定理由")
    deadline_date: Mapped[str | None] = mapped_column(Text, comment="截止日期 YYYY-MM-DD")
    events_json: Mapped[str | None] = mapped_column(Text, comment="抽取出的关键事件 JSON")
    classified_at: Mapped[str | None] = mapped_column(Text, comment="分类时间")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                          server_default="false", comment="是否已读")
    is_starred: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                             server_default="false", comment="是否星标")
    read_at: Mapped[str | None] = mapped_column(Text, comment="阅读时间")
    starred_at: Mapped[str | None] = mapped_column(Text, comment="星标时间")
    content: Mapped[str | None] = mapped_column(Text, comment="通知正文")
    is_noise: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            server_default="false", comment="是否噪声通知")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="入库时间（UTC）")


class NoticeUserState(BigIntPKMixin, Base):
    """通知已读/加星 per-user 状态（P5，对齐 core/sql/108 第 5 节）。

    kaoyan_notices 上的 is_read / is_starred 是共享单租户遗留列，已废弃读写；
    每个 (user, notice) 一行，首次标记时插入，UNIQUE(user_id, notice_id)。
    """

    __tablename__ = "notice_user_states"

    user_id: Mapped[int] = mapped_column(
        BigIntKey, ForeignKey("users.id"), nullable=False, comment="归属用户 ID")
    notice_id: Mapped[int] = mapped_column(
        BigIntKey, ForeignKey("kaoyan_notices.id", ondelete="CASCADE"), nullable=False,
        comment="关联通知 ID")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                          server_default="false", comment="是否已读（该用户）")
    is_starred: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                             server_default="false", comment="是否星标（该用户）")
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="状态更新时间（UTC）")

    __table_args__ = (
        # 约束/索引名与 108 DDL 保持一致，create_all 与迁移脚本不产生重复索引
        UniqueConstraint("user_id", "notice_id", name="uq_notice_user"),
        Index("ix_notice_user_notice", "notice_id"),
    )


class KaoyanSubscription(BigIntPKMixin, Base):
    """通知订阅：院校 / 专业 / 类型 / 关键词 四个维度。"""

    __tablename__ = "kaoyan_subscriptions"

    scope: Mapped[str] = mapped_column(
        build_enum("subscription_scope"), nullable=False,
        comment="订阅维度：school/major/notice_type/keyword")
    school_id: Mapped[int] = mapped_column(BigIntKey, nullable=False,
                                            server_default="0", comment="订阅的院校 ID")
    school_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="",
                                             comment="院校名")
    major_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="",
                                            comment="专业名")
    notice_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="",
                                             comment="通知类型")
    keyword: Mapped[str] = mapped_column(Text, nullable=False, server_default="",
                                         comment="关键词")
    level_min: Mapped[str] = mapped_column(
        build_enum("importance_level"), nullable=False,
        server_default="normal", comment="只推送不低于该重要级的通知")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                          server_default="true", comment="是否启用")
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class KaoyanAlertRecord(BigIntPKMixin, Base):
    """提醒记录：同一通知同一提醒类型只发一次。"""

    __tablename__ = "kaoyan_alert_records"

    notice_id: Mapped[int] = mapped_column( ForeignKey("kaoyan_notices.id", ondelete="CASCADE"), nullable=False,
        comment="关联通知 ID")
    alert_kind: Mapped[str] = mapped_column(
        build_enum("alert_kind"), nullable=False, comment="提醒类型")
    alert_date: Mapped[str] = mapped_column(Text, nullable=False,
                                            comment="提醒发生日期（北京时间 YYYY-MM-DD）")
    title: Mapped[str | None] = mapped_column(Text, comment="通知标题")
    school_name: Mapped[str | None] = mapped_column(Text, comment="院校名")
    notice_type: Mapped[str | None] = mapped_column(Text, comment="通知类型")
    importance_level: Mapped[str | None] = mapped_column(Text, comment="重要级")
    deadline_date: Mapped[str | None] = mapped_column(Text, comment="截止日期")
    days_left: Mapped[int | None] = mapped_column(Integer, comment="距截止剩余天数")
    message: Mapped[str] = mapped_column(Text, nullable=False, comment="提醒文案")
    acked: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                        server_default="false", comment="是否已确认")
    acked_at: Mapped[str | None] = mapped_column(Text, comment="确认时间")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class KaoyanAlertRun(BigIntPKMixin, Base):
    """提醒任务执行日志。"""

    __tablename__ = "kaoyan_alert_runs"

    ran_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, nullable=False, server_default=func.now(), comment="执行时间（UTC）")
    trigger_source: Mapped[str] = mapped_column(String(20), nullable=False,
                                                 server_default="schedule",
                                                 comment="触发方式：schedule / manual")
    scanned: Mapped[int] = mapped_column(Integer, nullable=False,
                                          server_default="0", comment="扫描通知条数")
    created_alerts: Mapped[int] = mapped_column(Integer, nullable=False,
                                                 server_default="0", comment="新生成提醒数")
    skipped_dup: Mapped[int] = mapped_column(Integer, nullable=False,
                                              server_default="0", comment="重复跳过数")
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False,
                                             server_default="0", comment="耗时（毫秒）")
    detail: Mapped[str | None] = mapped_column(Text, comment="执行明细")


class KaoyanCollectionRun(BigIntPKMixin, Base):
    """数据采集执行日志。"""

    __tablename__ = "kaoyan_collection_runs"

    source: Mapped[str] = mapped_column(String(50), nullable=False, comment="采集来源")
    scope: Mapped[str | None] = mapped_column(String(200), comment="采集范围")
    item_type: Mapped[str | None] = mapped_column(String(30),
                                                    comment="数据类型：school/major/notice/scoreline")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                            server_default="0", comment="写入行数")
    detail: Mapped[dict] = mapped_column(JSONBObject, nullable=False,
                                          server_default="{}", comment="执行明细")
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        server_default="success",
                                        comment="执行结果：success/partial/failed")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="执行时间（UTC）")


class KaoyanMajorKbLink(BigIntPKMixin, Base):
    """招生专业 ↔ 知识库专业课 匹配关系。"""

    __tablename__ = "kaoyan_major_kb_link"

    major_id: Mapped[int] = mapped_column( ForeignKey("kaoyan_majors.id", ondelete="CASCADE"), nullable=False,
    comment="专业 ID")
    school_id: Mapped[int] = mapped_column( ForeignKey("kaoyan_schools.id", ondelete="CASCADE"), nullable=False,
    comment="院校 ID（冗余，便于按院校聚合）")
    school_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="",
                                             comment="院校名")
    major_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="",
                                            comment="专业名")
    major_code: Mapped[str | None] = mapped_column(String(20), comment="专业代码")
    subject_name: Mapped[str] = mapped_column(Text, nullable=False,
                                              comment="专业课名（已剥离科目代码）")
    match_level: Mapped[str] = mapped_column(String(10), nullable=False,
                                             server_default="L1", comment="匹配等级 L1/L2/L3")
    match_type: Mapped[str] = mapped_column(String(20), nullable=False,
                                             server_default="exact", comment="匹配方式")
    kb_doc_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                               server_default="0", comment="关联文档数")
    confidence: Mapped[float] = mapped_column(Float, nullable=False,
                                               server_default="1.0", comment="匹配置信度")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class UniversityLegacy(BigIntPKMixin, Base):
    """历史遗留院校表（只读归档，禁止新写入）。"""

    __tablename__ = "universities_legacy"

    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="院校名称")
    type: Mapped[str | None] = mapped_column(String(50), comment="院校类型")
    city: Mapped[str | None] = mapped_column(String(50), comment="所在城市")
    major_name: Mapped[str | None] = mapped_column(String(200), comment="专业名称")
    score_lines: Mapped[dict | None] = mapped_column(JSONBObject, comment="历史分数线")
    admission_ratio: Mapped[str | None] = mapped_column(String(50), comment="历史报录比文本")
    difficulty: Mapped[int | None] = mapped_column(SmallInteger, comment="难度评级")
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


__all__ = [
    "KaoyanSchool", "SchoolAlias", "KaoyanCollege", "KaoyanMajor",
    "KaoyanAdmission", "KaoyanScoreline", "KaoyanNotice",
    "KaoyanSubscription", "KaoyanAlertRecord", "KaoyanAlertRun",
    "KaoyanCollectionRun", "KaoyanMajorKbLink", "UniversityLegacy",
]


__all__ = ["KaoyanNotice", "NoticeUserState", "KaoyanSubscription", "KaoyanAlertRecord", "KaoyanAlertRun", "KaoyanCollectionRun", "KaoyanMajorKbLink", "UniversityLegacy"]
