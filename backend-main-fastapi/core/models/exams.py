"""模考与组卷域模型：试卷 / 卷内题目 / 蓝图 / 场次 / 作答 / 答疑待办。

对齐 core/sql/041_papers_exams.sql。

与 core.models.questions 的分工：
    questions.py —— 题目主表与其直接关联（知识点关联、答案候选、作答流水）
    exams.py     —— 容器侧：试卷、模考场次与作答明细、答疑待办
"""

from __future__ import annotations

import datetime

from sqlalchemy import ( Boolean, Float, ForeignKey, Integer, REAL, SmallInteger, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..pg_types import JSONBList, JSONBObject, build_enum
from .base import Base, BigIntKey, BigIntPKMixin, DateTimeUTC


class ExamBlueprint(BigIntPKMixin, Base):
    """模考试卷结构蓝图。"""

    __tablename__ = "exam_blueprints"

    subject_id: Mapped[int | None] = mapped_column( ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID")
    subject: Mapped[str] = mapped_column(Text, nullable=False, comment="兼容列：科目中文名")
    paper: Mapped[str] = mapped_column(Text, nullable=False, comment="试卷标识")
    year: Mapped[int | None] = mapped_column(Integer, comment="年份")
    section: Mapped[str] = mapped_column(Text, nullable=False, comment="卷内分区")
    blueprint_question_type: Mapped[str] = mapped_column(
        build_enum("question_type"), nullable=False, comment="该分区题型")
    count: Mapped[int] = mapped_column(Integer, nullable=False, comment="题量")
    score_per_question: Mapped[float] = mapped_column(REAL, nullable=False,
                                                      comment="单题分值")
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, comment="建议时限")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False,
                                            server_default="0", comment="排序权重")
    kp_filters: Mapped[str | None] = mapped_column(Text, comment="知识点过滤条件")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            server_default="true", comment="是否启用")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class ExamSession(BigIntPKMixin, Base):
    """模考场次。"""

    __tablename__ = "exam_sessions"

    blueprint_key: Mapped[str | None] = mapped_column(String(100), comment="使用的蓝图标识")
    subject_id: Mapped[int | None] = mapped_column( ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID")
    subject: Mapped[str] = mapped_column(Text, nullable=False, comment="兼容列：科目中文名")
    paper: Mapped[str | None] = mapped_column(Text, comment="试卷标识")
    mode: Mapped[str] = mapped_column(String(30), nullable=False, server_default="normal",
                                      comment="模式：normal 普通 / strict 严格计时")
    question_source: Mapped[str] = mapped_column(
        build_enum("source_kind"), nullable=False, server_default="external_import",
        comment="抽题范围性质")
    config: Mapped[dict] = mapped_column(
        JSONBObject, nullable=False, server_default="{}", comment="场次配置快照")
    total_count: Mapped[int | None] = mapped_column(Integer, comment="总题数")
    total_score: Mapped[float | None] = mapped_column(REAL, comment="总分")
    correct_count: Mapped[int | None] = mapped_column(Integer, comment="答对题数")
    score: Mapped[float | None] = mapped_column(REAL, comment="实得分")
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, comment="时限（分钟）")
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="开始时间（UTC）")
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="截止时间（UTC）")
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="交卷时间（UTC）")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ongoing",
        comment="场次状态：ongoing/submitted/expired/abandoned")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")

    answers: Mapped[list["ExamAnswer"]] = relationship(
        "ExamAnswer", back_populates="session")


class ExamAnswer(BigIntPKMixin, Base):
    """模考作答明细。"""

    __tablename__ = "exam_answers"

    session_id: Mapped[int] = mapped_column( ForeignKey("exam_sessions.id", ondelete="CASCADE"), nullable=False,
        comment="所属场次 ID")
    question_id: Mapped[int | None] = mapped_column( ForeignKey("quiz_questions.id", ondelete="SET NULL"), comment="题目 ID")
    question_snapshot: Mapped[str | None] = mapped_column(Text, comment="题干快照")
    section: Mapped[str | None] = mapped_column(Text, comment="卷内分区")
    order_no: Mapped[int | None] = mapped_column(Integer, comment="卷内作答序号")
    user_answer: Mapped[str | None] = mapped_column(Text, comment="用户作答")
    is_correct: Mapped[bool | None] = mapped_column(Boolean, comment="是否答对")
    time_spent: Mapped[int | None] = mapped_column(Integer, comment="作答耗时（秒）")
    ai_score: Mapped[float | None] = mapped_column(REAL, comment="AI 评分")
    self_score: Mapped[float | None] = mapped_column(REAL, comment="自评分")
    final_score: Mapped[float | None] = mapped_column(REAL, comment="最终得分")
    scored_by: Mapped[str | None] = mapped_column(String(30), comment="评分方：ai/self/teacher")
    error_category: Mapped[str | None] = mapped_column(String(50), comment="错误分类")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")

    session: Mapped["ExamSession | None"] = relationship(
        "ExamSession", back_populates="answers")


class PendingQuestion(BigIntPKMixin, Base):
    """待解答问题：AI 无据可依时登记的知识缺口。"""

    __tablename__ = "pending_questions"

    # B4 行级隔离：盲区池属个人学习缺口数据（108 已加列）
    user_id: Mapped[int | None] = mapped_column(
        BigIntKey, ForeignKey("users.id"), comment="归属用户 ID（个人数据隔离）")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="问题原文")
    subject_id: Mapped[int | None] = mapped_column( ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID")
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    asked_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="提问时间（UTC）")
    have_basis: Mapped[str | None] = mapped_column(Text, comment="现有依据描述")
    have_basis_ids: Mapped[str | None] = mapped_column(Text, comment="依据分块 ID 列表")
    gap: Mapped[str] = mapped_column(Text, nullable=False, comment="缺口描述")
    gap_type: Mapped[str | None] = mapped_column(String(50),
                                                  comment="缺口类型：missing_doc/outdated/conflict")
    suggestion: Mapped[str | None] = mapped_column(Text, comment="补齐建议")
    suggested_action: Mapped[str | None] = mapped_column(String(100), comment="建议动作")
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                        server_default="open",
                                        comment="处理状态：open/resolved/ignored")
    resolved_by: Mapped[str | None] = mapped_column(String(50), comment="解决人")
    resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC,
                                                                   comment="解决时间")
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                                  server_default="1",
                                                  comment="同一问题出现次数")
    last_occurred_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="最近一次出现时间")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class AnswerCandidate(BigIntPKMixin, Base):
    """答案候选：同一题多来源答案，供多角色校验与仲裁。"""

    __tablename__ = "answer_candidates"

    question_id: Mapped[int] = mapped_column( ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False,
        comment="题目 ID")
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="候选答案")
    explanation: Mapped[str | None] = mapped_column(Text, comment="候选解释")
    confidence: Mapped[float] = mapped_column(Float, nullable=False,
                                              server_default="0.5",
                                              comment="该候选的置信度 0-1")
    source: Mapped[str] = mapped_column(
        build_enum("answer_source"), nullable=False,
        server_default="llm_generated", comment="答案来源")
    used_for_grading: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                   server_default="false",
                                                   comment="是否被采纳为判分依据")
    verified_by: Mapped[str | None] = mapped_column(String(50), comment="校验人")
    verified_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC,
                                                                   comment="校验时间")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")

    question: Mapped["QuizQuestion | None"] = relationship(
        "QuizQuestion", back_populates="answer_candidates")


class AnswerRecord(BigIntPKMixin, Base):
    """作答流水：掌握度派生的核心数据源。"""

    __tablename__ = "answer_records"

    question_id: Mapped[int | None] = mapped_column( ForeignKey("quiz_questions.id", ondelete="SET NULL"),
    comment="题目 ID，题目删除时置空保留历史")
    my_answer: Mapped[str | None] = mapped_column(Text, comment="用户作答")
    correct_answer: Mapped[str | None] = mapped_column(Text, comment="当时判定的正确答案快照")
    is_correct: Mapped[bool | None] = mapped_column(
        Boolean, comment="是否答对；NULL 表示未判分（主观题待评）")
    subject_id: Mapped[int | None] = mapped_column( ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID")
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    mode: Mapped[str | None] = mapped_column(String(50),
                                              comment="练习模式：practice/exam/review")
    cost_seconds: Mapped[int | None] = mapped_column(Integer, comment="作答耗时（秒）")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False,
        comment="作答时间（UTC），掌握度时间衰减以此列为准")


__all__ = [
    "QuizQuestion", "QuestionKnowledgeLink", "Paper", "PaperQuestion",
    "ExamBlueprint", "ExamSession", "ExamAnswer", "PendingQuestion",
    "AnswerCandidate", "AnswerRecord",
]
