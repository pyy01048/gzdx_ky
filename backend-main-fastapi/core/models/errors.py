"""学习行为域模型（二）：错题 / 错题-知识点关联 / 记忆卡片 / 错因模式库。

对齐 core/sql/050_learning.sql。

注意：错题与卡片的 next_review 列均为兼容缓存，
权威值在 review_schedules 表。
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    REAL,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..pg_types import JSONBList, build_enum
from .base import Base, BigIntPKMixin, DateTimeUTC, TimestampMixin


class ErrorRecord(BigIntPKMixin, TimestampMixin, Base):
    """错题记录。"""

    __tablename__ = "error_records"

    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="SET NULL"), comment="关联题目 ID，题目删除时置空保留错题"
    )
    content: Mapped[str | None] = mapped_column(Text, comment="题目内容快照")
    my_answer: Mapped[str | None] = mapped_column(Text, comment="我的作答")
    correct_answer: Mapped[str | None] = mapped_column(Text, comment="正确答案")
    error_reason: Mapped[str | None] = mapped_column(String(200), comment="错误原因")
    error_category: Mapped[str | None] = mapped_column(String(50), comment="错误分类")
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID"
    )
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), comment="关联知识点 ID"
    )
    accuracy: Mapped[float | None] = mapped_column(REAL, comment="该错题历史正确率 0-1")
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="复习次数")
    last_review: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="上次复习时间（UTC）")
    next_review: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="下次复习时间（UTC），兼容列，真值在 review_schedules"
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="unreviewed", comment="处理状态：unreviewed/reviewing/mastered"
    )
    mastery_level: Mapped[str] = mapped_column(
        build_enum("mastery_level"), nullable=False, server_default="not_mastered", comment="掌握等级"
    )
    tags: Mapped[list] = mapped_column(JSONBList, nullable=False, server_default="[]", comment="错题标签数组")
    analysis: Mapped[str | None] = mapped_column(Text, comment="错因分析")
    ease_factor: Mapped[float] = mapped_column(REAL, nullable=False, server_default="2.5", comment="SM-2 难度因子")
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="当前间隔（天）")
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="连续答对次数")
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="遗忘次数")
    pass_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="当前轮次")
    recent_weight: Mapped[float] = mapped_column(
        REAL, nullable=False, server_default="1.0", comment="近期权重，用于时间衰减加权"
    )
    user_note: Mapped[str | None] = mapped_column(Text, comment="用户备注")

    knowledge_links: Mapped[list["ErrorKnowledgeLink"]] = relationship("ErrorKnowledgeLink", back_populates="error")


class ErrorKnowledgeLink(BigIntPKMixin, Base):
    """错题 ↔ 知识点/分块/文档 关联。"""

    __tablename__ = "error_knowledge_links"

    error_id: Mapped[int] = mapped_column(
        ForeignKey("error_records.id", ondelete="CASCADE"), nullable=False, comment="错题 ID"
    )
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), comment="知识点 ID"
    )
    chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"), comment="分块 ID"
    )
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), comment="文档 ID")
    relevance: Mapped[float] = mapped_column(REAL, nullable=False, server_default="0", comment="相关度 0-1")
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="auto", comment="关联来源：auto / manual"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )

    error: Mapped["ErrorRecord | None"] = relationship("ErrorRecord", back_populates="knowledge_links")


class Flashcard(BigIntPKMixin, TimestampMixin, Base):
    """记忆卡片（SM-2 调度）。"""

    __tablename__ = "flashcards"

    front: Mapped[str] = mapped_column(Text, nullable=False, comment="卡片正面")
    back: Mapped[str] = mapped_column(Text, nullable=False, comment="卡片背面")
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), comment="关联知识点 ID"
    )
    next_review: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="下次复习时间（UTC），兼容列，真值在 review_schedules"
    )
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="复习次数")
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="当前间隔（天）")
    ease_factor: Mapped[float] = mapped_column(REAL, nullable=False, server_default="2.5", comment="SM-2 难度因子")
    mastery: Mapped[str] = mapped_column(
        build_enum("mastery_level"), nullable=False, server_default="not_mastered", comment="掌握状态"
    )


__all__ = ["ErrorRecord", "ErrorKnowledgeLink", "Flashcard"]
