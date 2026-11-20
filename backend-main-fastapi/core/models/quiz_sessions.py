"""刷题会话与作答尝试（F-03 / F-04）。

对齐 core/sql/095_quiz_sessions.sql。
"""

from __future__ import annotations

import datetime

from sqlalchemy import (Boolean, ForeignKey, Integer, REAL, SmallInteger, String, Text, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..pg_types import JSONBList, JSONBObject
from .base import Base, BigIntKey, BigIntPKMixin, DateTimeUTC


class QuizSession(BigIntPKMixin, Base):
    """刷题会话：一次章节练习/智能组卷/自由练习的完整上下文。"""

    __tablename__ = "quiz_sessions"

    # B4 行级隔离：刷题会话归属登录用户
    user_id: Mapped[int | None] = mapped_column(
        BigIntKey, ForeignKey("users.id"), comment="归属用户 ID（个人数据隔离）")

    # —— 会话元数据 —— #
    mode: Mapped[str] = mapped_column(String(30), nullable=False, server_default="free_practice",
                                      comment="会话模式：chapter_practice / smart_paper / free_practice")
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"),
                                                   comment="所属科目")
    textbook_id: Mapped[int | None] = mapped_column(ForeignKey("textbooks.id", ondelete="SET NULL"),
                                                    comment="所属教材（五层结构第2层）")
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("subject_chapters.id", ondelete="SET NULL"),
                                                   comment="所属章（五层结构第3层）")
    section_id: Mapped[int | None] = mapped_column(ForeignKey("subject_chapters.id", ondelete="SET NULL"),
                                                   comment="所属节（五层结构第4层）")
    knowledge_point_ids: Mapped[list] = mapped_column(
        JSONBList, nullable=False, server_default="[]",
        comment="选中的知识点 ID 数组，空表示该层级下全量出题")
    filters: Mapped[dict] = mapped_column(
        JSONBObject, nullable=False, server_default="{}",
        comment="额外筛选：题型/难度/限时等")

    # —— 会话统计 —— #
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0",
                                                 comment="会话总题数（快照）")
    answered_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0",
                                                comment="已作答数")
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0",
                                               comment="答对数")
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0",
                                                  comment="会话耗时（秒）")

    # —— 状态 —— #
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="in_progress",
                                        comment="in_progress / completed / abandoned")
    started_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, nullable=False,
                                                          server_default=func.now(),
                                                          comment="开始时间（UTC）")
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC,
                                                                   comment="完成时间（UTC）")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, nullable=False,
                                                          server_default=func.now(),
                                                          comment="创建时间（UTC）")
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, nullable=False,
                                                          server_default=func.now(),
                                                          onupdate=func.now(),
                                                          comment="更新时间（UTC）")

    # —— 关系 —— #
    attempts: Mapped[list["QuizAttempt"]] = relationship("QuizAttempt", back_populates="session",
                                                         cascade="all, delete-orphan")


class QuizAttempt(BigIntPKMixin, Base):
    """单题作答记录：关联到 quiz_sessions，记录每题的用户作答与评分。"""

    __tablename__ = "quiz_attempts"

    # B4 行级隔离（冗余，随 session 归属，便于直接过滤）
    user_id: Mapped[int | None] = mapped_column(
        BigIntKey, ForeignKey("users.id"), comment="归属用户 ID（随 quiz_sessions）")
    session_id: Mapped[int] = mapped_column(ForeignKey("quiz_sessions.id", ondelete="CASCADE"),
                                            nullable=False, comment="所属刷题会话")
    question_id: Mapped[int] = mapped_column(ForeignKey("quiz_questions.id", ondelete="CASCADE"),
                                             nullable=False, comment="所答题目")

    # —— 作答内容 —— #
    user_answer: Mapped[str | None] = mapped_column(Text, comment="用户作答：客观题为选项 key，主观题为文本")
    is_correct: Mapped[bool | None] = mapped_column(Boolean, comment="是否答对")
    score: Mapped[float | None] = mapped_column(REAL, comment="得分（主观题按 rubric 给分）")
    quality: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3",
                                         comment="SM-2 回答质量 0-5")

    # —— 时间与反馈 —— #
    answered_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, nullable=False,
                                                           server_default=func.now(),
                                                           comment="作答时间（UTC）")
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer, comment="本题耗时（秒）")
    feedback: Mapped[str | None] = mapped_column(Text, comment="系统反馈")
    ai_comment: Mapped[str | None] = mapped_column(Text, comment="AI 辅助评语（主观题）")
    self_rating: Mapped[str | None] = mapped_column(String(10),
                                                    comment="用户自评：correct/partial/wrong")

    # —— 派生掌握度 —— #
    mastery_before: Mapped[int | None] = mapped_column(SmallInteger, comment="作答前掌握度 0-100")
    mastery_after: Mapped[int | None] = mapped_column(SmallInteger, comment="作答后掌握度 0-100")

    # —— 关系 —— #
    session: Mapped["QuizSession"] = relationship("QuizSession", back_populates="attempts")


__all__ = ["QuizSession", "QuizAttempt"]
