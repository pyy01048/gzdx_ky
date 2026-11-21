"""文档与知识分块域模型。

对齐 core/sql/020_documents.sql。

三个关键约束在本层如何落地：
  1. 格式归一：只写 canonical_content（Markdown 中间态），content 为兼容列，
     由 PG 触发器双向同步，Python 侧不要把 content 当独立字段改。
  2. 全文检索：只写 search_tokens（jieba 分词结果，空格分隔），
     search_vector 是 GENERATED 列，数据库自动维护，Python 侧只读。
  3. 向量双方案：chunk_vectors.embedding(bytea) 与 embedding_f32(vector) 并存，
     **两列必须同时写**（HNSW 索引建在 embedding_f32 上，检索走它；
     embedding 是无 pgvector 时的退化路径）。方言分流看
     core.db_session.IS_POSTGRES —— 注意不是 VECTOR_BACKEND，
     该名字历史上写在本文档里但**并不存在**（文档漂移，已修）。
"""

from __future__ import annotations

from sqlalchemy import (
    REAL,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import FetchedValue

from ..pg_types import Float32Vector, MarkdownText, TSVector, build_enum
from .base import Base, BigIntKey, BigIntPKMixin, TimestampMixin


class Document(BigIntPKMixin, TimestampMixin, Base):
    """文档主表：原始资料 + 统一的 Markdown 中间态。"""

    __tablename__ = "documents"

    file_name: Mapped[str] = mapped_column(String(500), nullable=False, comment="原始文件名")
    file_path: Mapped[str | None] = mapped_column(String(1000), comment="服务器存储路径")
    size: Mapped[int | None] = mapped_column(BigIntKey, comment="文件字节数")
    content_hash: Mapped[str | None] = mapped_column(String(64), comment="内容 SHA-256，用于跨来源去重")

    # —— 格式归一：source_format 记原始格式，canonical_content 是唯一中间态 —— #
    source_format: Mapped[str] = mapped_column(
        build_enum("doc_format"),
        nullable=False,
        server_default="other",
        comment="原始文件格式（pdf/txt/doc/docx/md/image 等 11 种）",
    )
    canonical_content: Mapped[str | None] = mapped_column(
        MarkdownText, comment="统一 Markdown 中间态，下游检索与切片只认这一列"
    )
    canonical_engine: Mapped[str | None] = mapped_column(String(50), comment="解析器名，便于重解析")
    canonical_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", comment="中间态格式版本号"
    )
    content: Mapped[str | None] = mapped_column(
        MarkdownText, comment="兼容列（历史代码读写），由触发器与 canonical_content 同步"
    )

    # —— 归属 —— #
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID"
    )
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("subject_chapters.id", ondelete="SET NULL"), comment="权威章节 ID"
    )
    chapter: Mapped[str | None] = mapped_column(String(200), comment="兼容列：章节名")

    # —— 三个正交维度，互不复用 —— #
    doc_type: Mapped[str | None] = mapped_column(
        build_enum("doc_type"), comment="加工层级：raw 原始 / note 笔记 / index 索引"
    )
    content_category: Mapped[str | None] = mapped_column(
        build_enum("content_category"), comment="内容语义分类：textbook 教材 / example 例题 / exam 真题 / method 方法"
    )
    exam_stage: Mapped[str | None] = mapped_column(build_enum("exam_stage"), comment="考试阶段：初试 / 复试")
    structure_level: Mapped[str | None] = mapped_column(
        build_enum("structure_level"), comment="结构化程度：structured / flat / ocr"
    )

    # —— 解析状态 —— #
    index_status: Mapped[str] = mapped_column(
        build_enum("index_status"),
        nullable=False,
        server_default="pending",
        comment="索引状态：pending/indexing/indexed/failed/skipped",
    )
    parse_progress: Mapped[float] = mapped_column(Float, nullable=False, server_default="0", comment="解析进度 0-1")
    parse_error: Mapped[str | None] = mapped_column(Text, comment="解析失败原因")
    knowledge_point_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="已抽取知识点数"
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="已产生的分块数")
    ocr_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", comment="是否经 OCR 识别")

    # —— 溯源 —— #
    source_kind: Mapped[str] = mapped_column(
        build_enum("source_kind"), nullable=False, server_default="external_import", comment="来源性质（权威归类列）"
    )
    subject_source: Mapped[str | None] = mapped_column(String(50), comment="资料来源：ima 或空")
    ima_media_id: Mapped[str | None] = mapped_column(String(200), comment="IMA 侧条目 ID，正文按需拉取")
    folder_path: Mapped[str | None] = mapped_column(String(500), comment="IMA 内文件夹路径")
    content_type: Mapped[str | None] = mapped_column(String(20), comment="内容性质：知识 / 试题 / 单词")

    chunks: Mapped[list["KnowledgeChunk"]] = relationship("KnowledgeChunk", back_populates="document")


class KnowledgeChunk(BigIntPKMixin, TimestampMixin, Base):
    """知识分块：RAG 检索基本单元。

    search_vector 由数据库从 search_tokens 自动生成，Python 侧只读；
    写入路径统一走 core.services 层的分词函数（jieba cut_for_search）。
    """

    __tablename__ = "knowledge_chunks"

    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), comment="来源文档 ID"
    )
    doc_name: Mapped[str | None] = mapped_column(String(500), comment="来源文档名（冗余）")
    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="篇内分块序号，从 0 开始"
    )

    text: Mapped[str | None] = mapped_column(Text, comment="分块正文，禁止空串")
    search_tokens: Mapped[str | None] = mapped_column(
        Text, comment="jieba 预分词结果（空格分隔），写入后自动生成 tsvector"
    )
    #: 只读：PG GENERATED 列。FetchedValue 让 ORM 不把它写进 INSERT。
    search_vector: Mapped[str | None] = mapped_column(
        TSVector, server_default=FetchedValue(), nullable=True, comment="全文检索向量，GENERATED 列自动维护，只读"
    )
    summary: Mapped[str | None] = mapped_column(Text, comment="分块摘要")

    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), comment="权威科目 ID"
    )
    subject: Mapped[str | None] = mapped_column(String(50), comment="兼容列：科目中文名")
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("subject_chapters.id", ondelete="SET NULL"), comment="权威章节 ID"
    )

    page_start: Mapped[int | None] = mapped_column(Integer, comment="起始页码")
    page_end: Mapped[int | None] = mapped_column(Integer, comment="结束页码")

    l2_chapter: Mapped[str | None] = mapped_column(String(200), comment="L2 章节/模块")
    l3_content_type: Mapped[str | None] = mapped_column(build_enum("l3_content_type"), comment="L3 内容语义类型")
    classify_confidence: Mapped[float | None] = mapped_column(REAL, comment="分类置信度 0-1")
    classify_source: Mapped[str | None] = mapped_column(build_enum("classify_source"), comment="分类判定来源")
    token_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="估算 token 数，控制召回拼装长度"
    )

    document: Mapped["Document | None"] = relationship("Document", back_populates="chunks")
    vector: Mapped["ChunkVector | None"] = relationship("ChunkVector", back_populates="chunk", uselist=False)


class ChunkVector(BigIntPKMixin, TimestampMixin, Base):
    """分块向量：pgvector 与 Python 退化方案共用。

    - VECTOR_BACKEND=pgvector → 写 embedding_f32，SQL 侧用 <=> 做余弦检索；
    - VECTOR_BACKEND=python   → 写 embedding(bytea)，Python 侧 numpy 余弦检索。
    """

    __tablename__ = "chunk_vectors"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="关联分块 ID，一对一",
    )
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), comment="冗余文档 ID"
    )
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), comment="冗余科目 ID"
    )
    engine: Mapped[str] = mapped_column(
        build_enum("vector_engine"), nullable=False, server_default="unknown", comment="向量引擎"
    )
    dim: Mapped[int] = mapped_column(Integer, nullable=False, comment="向量维度")
    #: 退化方案存储：float32 小端字节数组
    embedding: Mapped[bytes | None] = mapped_column(Float32Vector, comment="退化方案：float32 小端字节数组")
    model_version: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="bge-small-zh-v1.5", comment="模型版本"
    )

    chunk: Mapped["KnowledgeChunk | None"] = relationship("KnowledgeChunk", back_populates="vector")


__all__ = ["Document", "KnowledgeChunk", "ChunkVector"]
