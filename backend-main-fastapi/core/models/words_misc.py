"""单词域与辅助域模型：单词本 / 单词 / 网盘 / 标注 / 评测。

对齐 core/sql/070_words_misc.sql。
"""

from __future__ import annotations

import datetime

from sqlalchemy import REAL, Boolean, Date, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..pg_types import JSONBList, JSONBObject, build_enum
from .base import Base, BigIntKey, BigIntPKMixin, DateTimeUTC, TimestampMixin


class WordDeck(BigIntPKMixin, Base):
    """单词本。"""

    __tablename__ = "word_decks"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, comment="单词本名称，唯一")
    description: Mapped[str | None] = mapped_column(String(500), comment="单词本描述")
    source: Mapped[str | None] = mapped_column(String(100), comment="来源：考研大纲 / 真题词频 / 自定义")
    word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="单词总数（冗余，触发器维护）"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )

    words: Mapped[list["Word"]] = relationship("Word", back_populates="deck")


class Word(BigIntPKMixin, TimestampMixin, Base):
    """单词：SM-2 调度与复习历史。"""

    __tablename__ = "words"

    deck_id: Mapped[int | None] = mapped_column(
        ForeignKey("word_decks.id", ondelete="CASCADE"), comment="所属单词本 ID"
    )
    word: Mapped[str] = mapped_column(String(100), nullable=False, comment="单词")
    phonetic: Mapped[str | None] = mapped_column(String(100), comment="音标")
    pos: Mapped[str | None] = mapped_column(String(50), comment="词性")
    meaning: Mapped[str] = mapped_column(Text, nullable=False, comment="释义")
    root: Mapped[str | None] = mapped_column(String(300), comment="词根词缀")
    example: Mapped[str | None] = mapped_column(Text, comment="英文例句")
    example_cn: Mapped[str | None] = mapped_column(Text, comment="例句翻译")
    tag: Mapped[str | None] = mapped_column(String(50), comment="标签：高频 / 熟词僻义 / 词组")
    status: Mapped[str] = mapped_column(
        build_enum("mastery_level"),
        nullable=False,
        server_default="not_mastered",
        comment="掌握状态（复用 mastery_level 枚举）",
    )
    ease_factor: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="2.5", comment="SM-2 难度因子 1.3-3.5"
    )
    interval_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="当前复习间隔（天）"
    )
    reps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="复习次数")
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="遗忘次数")
    due_date: Mapped[datetime.date | None] = mapped_column(Date, comment="下次到期日期")
    last_review: Mapped[datetime.date | None] = mapped_column(Date, comment="上次复习日期")
    review_history: Mapped[list] = mapped_column(JSONBList, nullable=False, server_default="[]", comment="复习历史数组")

    deck: Mapped["WordDeck | None"] = relationship("WordDeck", back_populates="words")


class NetdiskFile(BigIntPKMixin, TimestampMixin, Base):
    """网盘文件索引：视频 / 讲义等学习资源。"""

    __tablename__ = "netdisk_files"

    file_name: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件名")
    path: Mapped[str | None] = mapped_column(String(1000), comment="路径")
    file_type: Mapped[str | None] = mapped_column(String(50), comment="类型：video / pdf / doc / audio")
    size: Mapped[int | None] = mapped_column(BigIntKey, comment="字节数")
    category: Mapped[str | None] = mapped_column(String(100), comment="分类")
    download_link: Mapped[str | None] = mapped_column(String(1000), comment="下载链接")
    play_progress: Mapped[float] = mapped_column(Float, nullable=False, server_default="0", comment="播放进度 0-1")
    fs_id: Mapped[str | None] = mapped_column(String(100), comment="网盘侧文件 ID")


class AnnotationSample(BigIntPKMixin, Base):
    """人工标注样本：用于训练与评估分块分类器。"""

    __tablename__ = "annotation_samples"

    chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="SET NULL"), comment="被标注的分块 ID"
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False, comment="标注时的分块正文快照")
    label_l1: Mapped[str | None] = mapped_column(String(50), comment="一级标签")
    label_l2: Mapped[str | None] = mapped_column(String(200), comment="二级标签")
    label_l3: Mapped[str | None] = mapped_column(build_enum("l3_content_type"), comment="三级标签")
    annotate_user: Mapped[str | None] = mapped_column(String(50), comment="标注人")
    source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual", comment="样本来源")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class SftExample(BigIntPKMixin, Base):
    """微调样例：system / user / assistant 三段式。"""

    __tablename__ = "sft_examples"

    split: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="train", comment="数据划分：train / valid / test"
    )
    system: Mapped[str | None] = mapped_column(Text, comment="系统提示词")
    user: Mapped[str | None] = mapped_column(Text, comment="用户输入")
    assistant: Mapped[str | None] = mapped_column(Text, comment="期望回复")
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID"
    )
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class EvalRun(BigIntPKMixin, Base):
    """评测运行记录：对比不同策略（arm）的效果。"""

    __tablename__ = "eval_runs"

    kind: Mapped[str] = mapped_column(String(24), nullable=False, comment="评测类型：retrieval / generation / grading")
    arm: Mapped[str | None] = mapped_column(String(120), comment="对比臂名称")
    dataset_fingerprint: Mapped[str | None] = mapped_column(String(64), comment="评测集指纹")
    n_samples: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="样本数")
    primary_metric: Mapped[float | None] = mapped_column(REAL, comment="主指标数值")
    metrics: Mapped[dict] = mapped_column(JSONBObject, nullable=False, server_default="{}", comment="全部指标")
    report_path: Mapped[str | None] = mapped_column(String(300), comment="报告文件路径")
    notes: Mapped[str | None] = mapped_column(Text, comment="备注")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class RetrievalGateLog(BigIntPKMixin, Base):
    """检索门决策日志：记录每次检索是否放行、拒答及其依据。"""

    __tablename__ = "retrieval_gate_logs"

    query: Mapped[str] = mapped_column(Text, nullable=False, comment="用户查询原文")
    is_complex: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", comment="是否被判为复杂查询"
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False, comment="门决策：answer / abstain / clarify")
    reason_codes: Mapped[str | None] = mapped_column(Text, comment="决策理由码（逗号分隔）")
    top1_score: Mapped[float | None] = mapped_column(REAL, comment="最高相似度")
    topk_mean: Mapped[float | None] = mapped_column(REAL, comment="TopK 平均相似度")
    top1_margin: Mapped[float | None] = mapped_column(REAL, comment="Top1 与第二名分差")
    distinct_doc_count: Mapped[int | None] = mapped_column(Integer, comment="命中覆盖文档数")
    gate_mode: Mapped[str | None] = mapped_column(String(30), comment="门模式：off / soft / strict")
    would_abstain: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", comment="对照模式下是否会拒答"
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, comment="检索耗时（毫秒）")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


__all__ = [
    "WordDeck",
    "Word",
    "NetdiskFile",
    "AnnotationSample",
    "SftExample",
    "EvalRun",
    "RetrievalGateLog",
]
