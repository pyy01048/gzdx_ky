"""题库域模型：题目 / 题目-知识点关联 / 试卷 / 模考。

对齐 core/sql/040_questions.sql。

题目标准 schema（问题 2 + 问题 4 的落地）：
  options      : [{"key":"A","text":"..."}]，长度 2-10，由 is_canonical_options 校验
  option_count : 数据库 GENERATED 列，自动维护，只读
  source_kind  : 来源性质（真题/教材/章节习题/...）—— 权威归位列
  source_label : 原始来源字符串去掉前缀后的展示标签，不再承载归类语义
  is_past_exam : = (source_kind = 'past_exam') 的 GENERATED 列，可直接建索引
"""

from __future__ import annotations

import datetime

from sqlalchemy import ( Boolean, Float, ForeignKey, Integer, REAL, SmallInteger, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import FetchedValue

from ..pg_types import JSONBList, JSONBObject, build_enum
from .base import Base, BigIntKey, BigIntPKMixin, DateTimeUTC, TimestampMixin


class QuizQuestion(BigIntPKMixin, TimestampMixin, Base):
    """题库主表。"""

    __tablename__ = "quiz_questions"

    # —— 题干与选项 —— #
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="题干正文，不含选项")
    options: Mapped[list | None] = mapped_column(
        JSONBList, comment='选项数组，规范格式 [{"key":"A","text":"..."}]，长度 2-10')
    images: Mapped[list | None] = mapped_column(
        JSONBList, comment='题目配图数组：[{url,page,bbox,kind}] 或路径字符串')
    #: 只读：PG GENERATED 列。FetchedValue 让 ORM 不把它写进 INSERT。
    option_count: Mapped[int | None] = mapped_column(
        SmallInteger, server_default=FetchedValue(), nullable=True,
        comment="选项数量派生列，数据库自动维护，只读")
    answer: Mapped[str | None] = mapped_column(
        Text, comment="正确答案；客观题存选项 key（多选如 AB），主观题存参考答案")
    analysis: Mapped[str | None] = mapped_column(Text, comment="解析")
    rubric: Mapped[str | None] = mapped_column(Text, comment="主观题评分细则")
    max_score: Mapped[float | None] = mapped_column(Float, comment="该题满分")

    # —— 题型与作答 —— #
    question_type: Mapped[str] = mapped_column(
        build_enum("question_type"), nullable=False, server_default="single",
        comment="题型枚举（实测取值 single/judge/fill/calc/essay/draw）")
    answer_type: Mapped[str] = mapped_column(
        build_enum("answer_type"), nullable=False, server_default="objective",
        comment="作答类型：objective 自动判分 / subjective 人工或 LLM 评分")
    difficulty: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="3", comment="难度 1-5")

    # —— 来源（正交双列，取代 "知识库:" / "真题:" 前缀）—— #
    source_kind: Mapped[str] = mapped_column(
        build_enum("source_kind"), nullable=False, server_default="external_import",
        comment="来源性质（权威归类列）：past_exam 真题 / textbook 教材 等")
    #: 只读：PG GENERATED 列，等价于 source_kind = 'past_exam'。
    is_past_exam: Mapped[bool | None] = mapped_column(
        Boolean, server_default=FetchedValue(), nullable=True,
        comment="是否真题派生列，等价于 source_kind=past_exam，只读")
    source_label: Mapped[str | None] = mapped_column(
        Text, comment="原始来源展示标签，不含归类前缀")
    origin_document_id: Mapped[int | None] = mapped_column( ForeignKey("documents.id", ondelete="SET NULL"), comment="来源文档 ID")
    origin_chunk_id: Mapped[int | None] = mapped_column( ForeignKey("knowledge_chunks.id", ondelete="SET NULL"), comment="来源分块 ID")

    # —— 真题属性 —— #
    year: Mapped[int | None] = mapped_column(Integer, comment="真题年份；真题时必填")
    paper: Mapped[str | None] = mapped_column(String(100), comment="试卷标识，如 2026全国卷")
    source_paper: Mapped[str | None] = mapped_column(String(200), comment="来源试卷名")
    source_page: Mapped[int | None] = mapped_column(Integer, comment="来源页码")
    question_no: Mapped[int | None] = mapped_column(Integer, comment="卷内题号")
    external_id: Mapped[str | None] = mapped_column(String(100), unique=True,
                                                    comment="外部题目唯一 ID")

    # —— 归属 —— #
    subject_id: Mapped[int | None] = mapped_column( ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID")
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    textbook_id: Mapped[int | None] = mapped_column( ForeignKey("textbooks.id", ondelete="SET NULL"), comment="权威教材 ID（五层知识树：学科→教材→章→节→知识点）")
    chapter_id: Mapped[int | None] = mapped_column( ForeignKey("subject_chapters.id", ondelete="SET NULL"), comment="权威章节 ID（章或节的父节点）")
    section_id: Mapped[int | None] = mapped_column( ForeignKey("subject_chapters.id", ondelete="SET NULL"), comment="权威小节 ID（章的子节点，五层结构第4层）")
    chapter: Mapped[str | None] = mapped_column(String(200), comment="兼容列：章节名")
    knowledge_point: Mapped[str | None] = mapped_column(
        String(200), comment="兼容列：知识点名（正式关联走 question_knowledge_links）")

    # —— 质量与治理 —— #
    confidence: Mapped[str] = mapped_column(
        build_enum("confidence_level"), nullable=False, server_default="medium",
        comment="入库置信度：high/medium/low")
    quality: Mapped[str | None] = mapped_column(
        build_enum("quality_grade"), comment="质量评级：A/B/C/incomplete")
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                               server_default="false",
                                               comment="答案解析是否 AI 生成")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           server_default="false",
                                           comment="AI 答案是否已人工或多角色校验")
    variant_group: Mapped[str | None] = mapped_column(String(50), comment="变式题组 ID")
    answer_source: Mapped[str | None] = mapped_column(
        build_enum("answer_source"), comment="答案来源")
    answer_confidence: Mapped[float | None] = mapped_column(
        Float, comment="答案置信度 0-1，低于 0.8 不参与自动判分")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                server_default="true", comment="是否可用")
    is_junk: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                          server_default="false",
                                          comment="是否 OCR 碎片或答案串")
    is_retest: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            server_default="false",
                                            comment="是否复试题（0 初试 / 1 复试）")
    figure_missing: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0",
        comment="识别图缺失标记：题干引用图表但库内无图")
    validation_status: Mapped[str] = mapped_column(
        build_enum("question_validation_status"), nullable=False,
        server_default="pending", comment="校验门结果：pending/pass/warn/fail")
    validation_errors: Mapped[list] = mapped_column(
        JSONBList, nullable=False, server_default="[]", comment="校验门错误明细")
    validated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTimeUTC, comment="最近一次过校验门的时间")

    knowledge_links: Mapped[list["QuestionKnowledgeLink"]] = relationship(
        "QuestionKnowledgeLink", back_populates="question")
    answer_candidates: Mapped[list["AnswerCandidate"]] = relationship(
        "AnswerCandidate", back_populates="question")


class QuestionKnowledgeLink(BigIntPKMixin, Base):
    """题目 ↔ 知识点 多对多关联（掌握度派生的路径）。"""

    __tablename__ = "question_knowledge_links"

    question_id: Mapped[int] = mapped_column( ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False,
        comment="题目 ID")
    knowledge_point_id: Mapped[int] = mapped_column( ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False,
        comment="知识点 ID")
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="primary",
                                      comment="关联角色：primary 主考点 / secondary 次考点")
    weight: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0",
                                          comment="关联权重 0-1")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                               server_default="false",
                                               comment="是否人工校验过该关联")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")

    question: Mapped["QuizQuestion | None"] = relationship(
        "QuizQuestion", back_populates="knowledge_links")
    knowledge_point: Mapped["KnowledgePoint | None"] = relationship(
        "KnowledgePoint", back_populates="question_links")


class Paper(BigIntPKMixin, TimestampMixin, Base):
    """试卷表：组卷结果与规则。"""

    __tablename__ = "papers"

    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="试卷标题")
    subject_id: Mapped[int | None] = mapped_column( ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID")
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    description: Mapped[str | None] = mapped_column(Text, comment="试卷描述")
    rules: Mapped[dict] = mapped_column(
        JSONBObject, nullable=False, server_default="{}", comment="组卷规则")
    total_score: Mapped[int] = mapped_column(Integer, nullable=False,
                                             server_default="100", comment="试卷总分")
    year: Mapped[int | None] = mapped_column(Integer, comment="真题年份（如 2024）")
    paper_type: Mapped[str | None] = mapped_column(String(50), comment="卷种标签（如 数学一/英语二）")
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false",
                                          comment="是否为模拟试卷（true=用户自建，false=真题套卷）")

    questions: Mapped[list["PaperQuestion"]] = relationship(
        "PaperQuestion", back_populates="paper")
    attempts: Mapped[list["PaperAttempt"]] = relationship(
        "PaperAttempt", back_populates="paper")


class PaperQuestion(BigIntPKMixin, Base):
    """试卷题目关联：快照题干与选项，题目下线不影响历史试卷。"""

    __tablename__ = "paper_questions"

    paper_id: Mapped[int] = mapped_column( ForeignKey("papers.id", ondelete="CASCADE"), nullable=False,
        comment="所属试卷 ID")
    question_id: Mapped[int | None] = mapped_column( ForeignKey("quiz_questions.id", ondelete="SET NULL"),
    comment="源题目 ID，题目删除时置空保留快照")
    seq: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0",
                                     comment="卷内序号")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="题干快照")
    options: Mapped[list | None] = mapped_column(JSONBList, comment="选项快照")
    answer: Mapped[str | None] = mapped_column(Text, comment="答案快照")
    analysis: Mapped[str | None] = mapped_column(Text, comment="解析快照")
    question_type: Mapped[str | None] = mapped_column(
        build_enum("question_type"), comment="题型快照")
    difficulty: Mapped[int | None] = mapped_column(SmallInteger, comment="难度快照")
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0",
                                       comment="该题分值")
    avg_score: Mapped[float | None] = mapped_column(REAL, comment="该题历史平均得分（用于难度分析）")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0",
                                               comment="该题被作答次数（用于热度统计）")

    paper: Mapped["Paper | None"] = relationship("Paper", back_populates="questions")


class PaperAttempt(BigIntPKMixin, Base):
    """试卷作答记录：记录用户对某份试卷的完整作答过程。"""

    __tablename__ = "paper_attempts"

    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False,
                                          comment="所属试卷 ID")
    user_id: Mapped[int | None] = mapped_column(BigIntKey, comment="用户 ID（预留多用户扩展）")
    started_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(),
                                                          nullable=False, comment="开始时间（UTC）")
    submitted_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="提交时间（UTC）")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ongoing",
                                        comment="作答状态：ongoing/submitted/expired")
    total_score: Mapped[float | None] = mapped_column(REAL, comment="实得总分")
    correct_count: Mapped[int | None] = mapped_column(Integer, comment="答对题数")
    duration_seconds: Mapped[int | None] = mapped_column(Integer, comment="作答时长（秒）")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(),
                                                          nullable=False, comment="创建时间（UTC）")

    paper: Mapped["Paper | None"] = relationship("Paper", back_populates="attempts")
    answers: Mapped[list["PaperAnswer"]] = relationship("PaperAnswer", back_populates="attempt")


class PaperAnswer(BigIntPKMixin, Base):
    """试卷逐题作答明细。"""

    __tablename__ = "paper_answers"

    attempt_id: Mapped[int] = mapped_column(ForeignKey("paper_attempts.id", ondelete="CASCADE"),
                                            nullable=False, comment="所属作答记录 ID")
    question_id: Mapped[int | None] = mapped_column(ForeignKey("quiz_questions.id", ondelete="SET NULL"),
                                                    comment="题目 ID")
    paper_question_seq: Mapped[int] = mapped_column(Integer, nullable=False,
                                                    comment="卷内题号（快照，避免题目重排后序号变化）")
    user_answer: Mapped[str | None] = mapped_column(Text, comment="用户作答")
    is_correct: Mapped[bool | None] = mapped_column(Boolean, comment="是否答对")
    score: Mapped[float | None] = mapped_column(REAL, comment="该题得分")
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer, comment="该题耗时（秒）")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(),
                                                          nullable=False, comment="创建时间（UTC）")

    attempt: Mapped["PaperAttempt | None"] = relationship("PaperAttempt", back_populates="answers")
