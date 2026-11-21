"""学习行为域模型（三）：计划体系 / 专注 / 艾宾浩斯 / 早起 / 统计事件流 / 节点。

对齐 core/sql/050_learning.sql 与 051_planning.sql。
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..pg_types import JSONBList, JSONBObject
from .base import Base, BigIntKey, BigIntPKMixin, DateTimeUTC, TimestampMixin


class FocusSession(BigIntPKMixin, Base):
    """专注计时会话。"""

    __tablename__ = "focus_sessions"

    start_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, nullable=False, comment="开始时间（UTC）")
    end_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="结束时间（UTC）")
    duration_minutes: Mapped[int | None] = mapped_column(Integer, comment="专注时长（分钟）")
    tag: Mapped[str | None] = mapped_column(String(50), comment="专注标签")
    note: Mapped[str | None] = mapped_column(Text, comment="备注")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="记录创建时间（UTC）"
    )


class EbbinghausItem(BigIntPKMixin, Base):
    """艾宾浩斯记忆条目：默认 9 档复习时点，支持自定义节奏（cycle_config/review_times）。"""

    __tablename__ = "ebbinghaus_items"

    seq: Mapped[int | None] = mapped_column(Integer, comment="序号")
    learn_date: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, nullable=False, comment="首次学习时间（UTC）")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="记忆内容")
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID"
    )
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    review_5min: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="5 分钟后复习时点")
    review_30min: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="30 分钟后复习时点")
    review_12h: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="12 小时后复习时点")
    review_1d: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="1 天后复习时点")
    review_2d: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="2 天后复习时点")
    review_4d: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="4 天后复习时点")
    review_7d: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="7 天后复习时点")
    review_15d: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="15 天后复习时点")
    review_1m: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="1 个月后复习时点")
    cycle_config: Mapped[list | None] = mapped_column(JSONBList, comment="自定义周期定义")
    review_times: Mapped[list | None] = mapped_column(JSONBList, comment="实际复习时间点")
    mastered: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", comment="是否已掌握")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class EarlyBirdRecord(BigIntPKMixin, Base):
    """早起打卡，按日期唯一。"""

    __tablename__ = "early_bird_records"

    day_num: Mapped[int] = mapped_column(Integer, nullable=False, comment="连续打卡第几天")
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False, unique=True, comment="打卡日期")
    wake_time: Mapped[datetime.time | None] = mapped_column(Time, comment="起床时间")
    sleep_time: Mapped[datetime.time | None] = mapped_column(Time, comment="入睡时间")
    note: Mapped[str | None] = mapped_column(String(500), comment="备注")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class MonthPlan(BigIntPKMixin, Base):
    """月度计划。"""

    __tablename__ = "month_plans"

    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="年份")
    month: Mapped[int] = mapped_column(Integer, nullable=False, comment="月份 1-12")
    tasks: Mapped[list] = mapped_column(JSONBList, nullable=False, server_default="[]", comment="月度任务列表")
    completion: Mapped[str | None] = mapped_column(Text, comment="完成情况说明")
    summary: Mapped[str | None] = mapped_column(Text, comment="月度总结")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class WeekPlan(BigIntPKMixin, Base):
    """周计划，归属月计划。"""

    __tablename__ = "week_plans"

    month_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("month_plans.id", ondelete="SET NULL"), comment="所属月计划 ID"
    )
    week_start: Mapped[datetime.date] = mapped_column(Date, nullable=False, unique=True, comment="周起始日期（周一）")
    tasks: Mapped[list] = mapped_column(JSONBList, nullable=False, server_default="[]", comment="周任务列表")
    daily_records: Mapped[dict] = mapped_column(
        JSONBObject, nullable=False, server_default="{}", comment="每日完成记录"
    )
    completion: Mapped[str | None] = mapped_column(Text, comment="完成情况说明")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class DailyPlan(BigIntPKMixin, TimestampMixin, Base):
    """每日计划，含时间轴与自评分。"""

    __tablename__ = "daily_plans"

    date: Mapped[datetime.date] = mapped_column(Date, nullable=False, unique=True, comment="计划日期")
    days_to_exam: Mapped[int | None] = mapped_column(Integer, comment="距考试天数")
    tasks: Mapped[list] = mapped_column(JSONBList, nullable=False, server_default="[]", comment="当日任务列表")
    timeline: Mapped[list] = mapped_column(JSONBList, nullable=False, server_default="[]", comment="当日时间轴")
    study_duration: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="有效学习分钟")
    wasted_duration: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="浪费分钟")
    score: Mapped[int | None] = mapped_column(SmallInteger, comment="当日自评分")
    summary: Mapped[str | None] = mapped_column(Text, comment="当日总结")


class PhasePlan(BigIntPKMixin, Base):
    """阶段计划：基础 / 强化 / 冲刺。"""

    __tablename__ = "phase_plans"

    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="阶段名称")
    start_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, comment="开始日期")
    end_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, comment="结束日期")
    cycle_days: Mapped[int | None] = mapped_column(Integer, comment="循环周期天数")
    tasks: Mapped[list] = mapped_column(JSONBList, nullable=False, server_default="[]", comment="阶段任务列表")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class PhaseDailyReview(BigIntPKMixin, Base):
    """阶段计划内的每日复习安排（早 / 晚各一组）。"""

    __tablename__ = "phase_daily_reviews"

    phase_plan_id: Mapped[int] = mapped_column(
        ForeignKey("phase_plans.id", ondelete="CASCADE"), nullable=False, comment="所属阶段计划 ID"
    )
    day_num: Mapped[int] = mapped_column(Integer, nullable=False, comment="阶段内第几天")
    date: Mapped[datetime.date | None] = mapped_column(Date, comment="对应日期")
    morning_reviews: Mapped[list] = mapped_column(JSONBList, nullable=False, server_default="[]", comment="早晨复习项")
    evening_reviews: Mapped[list] = mapped_column(JSONBList, nullable=False, server_default="[]", comment="晚间复习项")
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", comment="是否完成")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class StudySession(BigIntPKMixin, Base):
    """学习会话流水。"""

    __tablename__ = "study_sessions"

    date: Mapped[datetime.date] = mapped_column(Date, nullable=False, comment="学习日期")
    duration: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="学习时长（分钟）")
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID"
    )
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    task_type: Mapped[str | None] = mapped_column(String(50), comment="任务类型")
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class StudyStat(BigIntPKMixin, Base):
    """每日学习统计聚合。"""

    __tablename__ = "study_stats"

    date: Mapped[datetime.date] = mapped_column(Date, nullable=False, unique=True, comment="统计日期")
    total_duration: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="总学习分钟")
    subject_durations: Mapped[dict] = mapped_column(
        JSONBObject, nullable=False, server_default="{}", comment="各科时长（JSON 对象，key 为科目 code）"
    )
    task_completed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="完成任务数")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="错题数")
    new_knowledge_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="新增知识点数"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class StudyEvent(BigIntPKMixin, Base):
    """学习事件流：所有学习行为的统一事件日志。"""

    __tablename__ = "study_events"

    event_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="事件类型")
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID"
    )
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("subject_chapters.id", ondelete="SET NULL"), comment="权威章节 ID"
    )
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), comment="知识点 ID"
    )
    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="SET NULL"), comment="题目 ID"
    )
    session_id: Mapped[int | None] = mapped_column(BigIntKey, comment="关联会话 ID")
    is_correct: Mapped[bool | None] = mapped_column(Boolean, comment="是否答对")
    duration_seconds: Mapped[int | None] = mapped_column(Integer, comment="持续秒数")
    payload: Mapped[dict] = mapped_column(JSONBObject, nullable=False, server_default="{}", comment="事件附加数据")
    occurred_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, nullable=False, server_default=func.now(), comment="事件发生时间（UTC），统计以此列为准"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="入库时间（UTC）"
    )


class Milestone(BigIntPKMixin, Base):
    """考研关键节点。"""

    __tablename__ = "milestones"

    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="考试年份")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="节点名称")
    category: Mapped[str] = mapped_column(String(50), nullable=False, comment="节点分类")
    start_date: Mapped[datetime.date | None] = mapped_column(Date, comment="开始日期")
    end_date: Mapped[datetime.date | None] = mapped_column(Date, comment="结束日期")
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="2", comment="重要级 1-5")
    action: Mapped[str | None] = mapped_column(Text, comment="应做动作")
    pitfalls: Mapped[str | None] = mapped_column(Text, comment="常见坑提示")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", comment="是否启用")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class Misconception(BigIntPKMixin, Base):
    """错因模式库。"""

    __tablename__ = "misconceptions"

    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="SET NULL"), comment="关联题目 ID"
    )
    error_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("error_records.id", ondelete="SET NULL"), comment="关联错题 ID"
    )
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), comment="关联知识点 ID"
    )
    pattern: Mapped[str] = mapped_column(Text, nullable=False, comment="错误模式描述")
    category: Mapped[str | None] = mapped_column(String(50), comment="错误分类")
    suggestion: Mapped[str | None] = mapped_column(Text, comment="改进建议")
    evidence: Mapped[str | None] = mapped_column(Text, comment="支撑证据")
    synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="最近一次外部同步时间")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


__all__ = [
    "FocusSession",
    "EbbinghausItem",
    "EarlyBirdRecord",
    "MonthPlan",
    "WeekPlan",
    "DailyPlan",
    "PhasePlan",
    "PhaseDailyReview",
    "StudySession",
    "StudyStat",
    "StudyEvent",
    "Milestone",
    "Misconception",
]
