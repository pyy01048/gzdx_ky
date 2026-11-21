"""知识点域模型。

对齐 core/sql/030_knowledge.sql。

重要：本模型**没有 mastery 字段**。掌握度是派生值，读取请走
core/sql/080 定义的视图 v_knowledge_mastery（30 天指数衰减加权正确率）。
"""

from __future__ import annotations

import datetime

from sqlalchemy import REAL, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..pg_types import JSONBList, build_enum
from .base import Base, BigIntPKMixin, DateTimeUTC, TimestampMixin


class KnowledgePoint(BigIntPKMixin, TimestampMixin, Base):
    """知识点：章节 → 知识点 → 题型 三级结构中的第 2 级。"""

    __tablename__ = "knowledge_points"

    name: Mapped[str] = mapped_column(String(300), nullable=False, comment="知识点名称")

    # —— 归属 —— #
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID"
    )
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("subject_chapters.id", ondelete="SET NULL"), comment="权威章节 ID"
    )
    chapter: Mapped[str | None] = mapped_column(String(200), comment="兼容列：章节名")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), comment="父知识点 ID，顶级为 NULL"
    )

    # —— 溯源 —— #
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), comment="来源文档 ID"
    )
    source_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="SET NULL"), comment="来源分块 ID，可反查原文片段"
    )
    source_chunk_index: Mapped[int | None] = mapped_column(Integer, comment="来源分块篇内序号")
    extract_source: Mapped[str | None] = mapped_column(build_enum("extract_source"), comment="抽取来源")
    subject_source: Mapped[str | None] = mapped_column(String(20), comment="学科判定来源")

    # —— 考情 —— #
    exam_frequency: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0", comment="考频 0-5，0 表示未统计"
    )
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3", comment="难度 1-5")
    question_types: Mapped[list] = mapped_column(
        JSONBList, nullable=False, server_default="[]", comment='考过的题型数组，如 ["选择","计算"]'
    )
    description: Mapped[str | None] = mapped_column(Text, comment="知识点描述")

    # —— SM-2 调度状态（冗余展示用，权威在 review_schedules）—— #
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="累计复习次数")
    last_review: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="上次复习时间（UTC）")
    ease_factor: Mapped[float] = mapped_column(
        REAL, nullable=False, server_default="2.5", comment="SM-2 难度因子 1.3-3.5"
    )
    interval_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="当前复习间隔（天）"
    )
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="遗忘次数")
    question_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="关联题目数（触发器维护）"
    )

    children: Mapped[list["KnowledgePoint"]] = relationship("KnowledgePoint", back_populates="parent")
    parent: Mapped["KnowledgePoint | None"] = relationship(
        "KnowledgePoint", back_populates="children", remote_side="KnowledgePoint.id"
    )
    question_links: Mapped[list["QuestionKnowledgeLink"]] = relationship(
        "QuestionKnowledgeLink", back_populates="knowledge_point"
    )


class KnowledgePointRelation(BigIntPKMixin, Base):
    """知识点关系：前置 / 并列 / 包含。"""

    __tablename__ = "knowledge_point_relations"

    source_kp_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, comment="源知识点 ID"
    )
    target_kp_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False, comment="目标知识点 ID"
    )
    relation_type: Mapped[str] = mapped_column(
        build_enum("relation_type"), nullable=False, comment="关系类型：prerequisite/parallel/contains"
    )
    source: Mapped[str | None] = mapped_column(String(100), comment="关系来源留痕")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


__all__ = ["KnowledgePoint", "KnowledgePointRelation"]
