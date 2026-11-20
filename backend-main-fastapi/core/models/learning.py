"""学习行为域模型（一）：复习调度权威表 / 目标 / 任务 / 复习记录。

对齐 core/sql/050_learning.sql。

时间口径：review_schedules.next_review_at 是唯一权威；各业务表的 next_review
列只是兼容缓存，前端 localStorage 只允许离线展示，不得反向决定到期与否。
"""

from __future__ import annotations

import datetime

from sqlalchemy import ( Boolean, Date, Float, ForeignKey, Integer, REAL, SmallInteger, String, Text,
    Time, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..pg_types import JSONBList, JSONBObject, build_enum
from .base import Base, BigIntKey, BigIntPKMixin, DateTimeUTC, TimestampMixin



class ReviewSchedule(BigIntPKMixin, TimestampMixin, Base):
    """复习调度权威表：到期判定的唯一真值源。"""

    __tablename__ = "review_schedules"

    # B4 行级隔离：同一对象，不同用户各自独立调度行
    user_id: Mapped[int | None] = mapped_column(
        BigIntKey, ForeignKey("users.id"), comment="归属用户 ID（个人数据隔离）")
    item_type: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="复习对象类型：task/error_record/flashcard/knowledge_point")
    item_id: Mapped[int] = mapped_column(BigIntKey, nullable=False, comment="复习对象 ID")
    algorithm: Mapped[str] = mapped_column(String(30), nullable=False,
                                           server_default="sm2",
                                           comment="调度算法：sm2 / ebbinghaus")
    ease_factor: Mapped[float] = mapped_column(REAL, nullable=False,
                                               server_default="2.5", comment="SM-2 难度因子")
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False,
                                                server_default="0", comment="当前间隔（天）")
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False,
                                             server_default="0", comment="连续答对次数")
    lapses: Mapped[int] = mapped_column(Integer, nullable=False,
                                        server_default="0", comment="遗忘次数")
    # FSRS 三要素（102 迁移）
    stability: Mapped[float | None] = mapped_column(REAL, comment="FSRS 稳定度（天）")
    difficulty: Mapped[float | None] = mapped_column(REAL, comment="FSRS 难度 1-10")
    retrievability: Mapped[float | None] = mapped_column(REAL, comment="本次复习时可提取概率")
    state: Mapped[int | None] = mapped_column(SmallInteger, server_default="0",
                                              comment="0新 1学习 2复习 3重学")
    last_reviewed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="上次复习时间（UTC）")
    next_review_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="下次复习时间（UTC），到期判定以此列为准")


class Goal(BigIntPKMixin, TimestampMixin, Base):
    """考研目标。"""

    __tablename__ = "goals"

    # B4 行级隔离：目标院校/考试日期按用户区分
    user_id: Mapped[int | None] = mapped_column(
        BigIntKey, ForeignKey("users.id"), comment="归属用户 ID（个人数据隔离）")
    exam_date: Mapped[datetime.date | None] = mapped_column(Date, comment="考试日期")
    total_score_target: Mapped[int | None] = mapped_column(SmallInteger,
                                                            comment="总分目标")
    politics_target: Mapped[int | None] = mapped_column(SmallInteger, comment="政治目标分")
    english_target: Mapped[int | None] = mapped_column(SmallInteger, comment="英语目标分")
    math_target: Mapped[int | None] = mapped_column(SmallInteger, comment="数学目标分")
    major_target: Mapped[int | None] = mapped_column(SmallInteger, comment="专业课目标分")
    university: Mapped[str | None] = mapped_column(String(200), comment="目标院校")
    major: Mapped[str | None] = mapped_column(String(200), comment="目标专业")
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")
    subject_codes: Mapped[list] = mapped_column(
        JSONBList, nullable=False, server_default="[]",
        comment="备考科目权威代码数组，元素须存在于 subjects.code")
    support_subject_codes: Mapped[list] = mapped_column(
        JSONBList, nullable=False, server_default="[]", comment="专业课支撑科目代码数组")
    # 每日学习目标：进度环的分母。可空 = 未设目标（故意无默认值），DDL 见 core/sql/101
    daily_focus_minutes: Mapped[int | None] = mapped_column(SmallInteger,
                                                            comment="每日专注时长目标（分钟），NULL=未设")
    daily_new_words: Mapped[int | None] = mapped_column(SmallInteger, comment="每日新词目标，NULL=未设")
    daily_review_words: Mapped[int | None] = mapped_column(SmallInteger, comment="每日复习词量目标，NULL=未设")
    daily_questions: Mapped[int | None] = mapped_column(SmallInteger, comment="每日刷题目标，NULL=未设")


class Task(BigIntPKMixin, TimestampMixin, Base):
    """学习任务。"""

    __tablename__ = "tasks"

    # B4 行级隔离
    user_id: Mapped[int | None] = mapped_column(
        BigIntKey, ForeignKey("users.id"), comment="归属用户 ID（个人数据隔离）")
    title: Mapped[str] = mapped_column(String(300), nullable=False, comment="任务标题")
    subject_id: Mapped[int | None] = mapped_column( ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID")
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    chapter_id: Mapped[int | None] = mapped_column( ForeignKey("subject_chapters.id", ondelete="SET NULL"),
    comment="权威章节 ID")
    task_type: Mapped[str | None] = mapped_column(String(50),
                                                   comment="类型：学习/复习/刷题/背诵/模拟")
    stage: Mapped[str | None] = mapped_column(
        build_enum("prep_stage"), comment="备考阶段：basic/intensive/sprint/retest")
    status: Mapped[str] = mapped_column(
        build_enum("task_status"), nullable=False, server_default="pending",
        comment="任务状态：pending/doing/done/cancelled")
    due_date: Mapped[datetime.date | None] = mapped_column(Date, comment="截止日期")
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False,
                                          server_default="0", comment="优先级 0-5")
    #: 兼容缓存列，权威在 review_schedules.next_review_at
    next_review: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="下次复习时间（UTC），兼容列，真值在 review_schedules")
    review_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                              server_default="0", comment="已复习次数")
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC,
                                                                    comment="完成时间")


class ReviewRecord(BigIntPKMixin, Base):
    """复习记录：每次复习的评分与掌握度变化。"""

    __tablename__ = "review_records"

    # B4 行级隔离
    user_id: Mapped[int | None] = mapped_column(
        BigIntKey, ForeignKey("users.id"), comment="归属用户 ID（个人数据隔离）")
    item_type: Mapped[str] = mapped_column(String(20), nullable=False,
                                           comment="复习对象类型")
    item_id: Mapped[int] = mapped_column(BigIntKey, nullable=False, comment="复习对象 ID")
    subject_id: Mapped[int | None] = mapped_column( ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID")
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    chapter: Mapped[str | None] = mapped_column(String(200), comment="章节")
    result: Mapped[str | None] = mapped_column(
        build_enum("review_result"), comment="SM-2 评分：again/hard/good/easy")
    grade: Mapped[int] = mapped_column(SmallInteger, nullable=False,
                                       server_default="0", comment="评分 0-5")
    mastery_before: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0", comment="复习前掌握度 0-100")
    mastery_after: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0", comment="复习后掌握度 0-100")
    duration: Mapped[int] = mapped_column(Integer, nullable=False,
                                           server_default="0", comment="复习耗时（秒）")
    interval_after: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="复习后新间隔（天）")
    next_review: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="本次复习后计算出的下次复习时间（UTC）")
    note: Mapped[str | None] = mapped_column(Text, comment="复习笔记")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="复习时间（UTC）")


__all__ = ["ReviewSchedule", "Goal", "Task", "ReviewRecord"]
