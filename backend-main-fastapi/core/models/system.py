"""系统配置域模型：科目权威源 / 章节 / 科目配置 / 平台配置 / AI 供应商。

对齐 core/sql/010_system_config.sql。
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from utils.secret_codec import EncryptedText

from ..pg_types import Float32Vector, JSONBList, JSONBObject, build_enum
from .base import Base, BigIntPKMixin, DateTimeUTC, TimestampMixin


class Subject(BigIntPKMixin, TimestampMixin, Base):
    """备考科目：全项目唯一权威源。

    取代旧 subject_prototypes 与 subject_config 两套口径。代码里一律用 code
    引用科目，禁止再写中文科目字面量；历史写法落在 subject_aliases 里做映射。
    """

    __tablename__ = "subjects"

    code: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, comment="权威科目代码，如 politics/english/math/circuit"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="科目中文名")
    short_name: Mapped[str | None] = mapped_column(String(50), comment="科目简称")
    category: Mapped[str] = mapped_column(
        build_enum("subject_category"),
        nullable=False,
        server_default="professional",
        comment="科目分类：public 公共课 / professional 专业课 / retest 复试科目",
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"), comment="父科目 ID")
    exam_overlap: Mapped[str | None] = mapped_column(Text, comment="考纲重叠说明")
    description: Mapped[str | None] = mapped_column(Text, comment="科目说明")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="展示排序权重，升序")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", comment="是否启用")
    is_custom: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", comment="是否用户自定义科目"
    )
    legacy_names: Mapped[list] = mapped_column(
        JSONBList, nullable=False, server_default="[]", comment="历史中文名数组，供 ETL 归档"
    )

    parent: Mapped["Subject | None"] = relationship("Subject", back_populates="children", remote_side="Subject.id")
    children: Mapped[list["Subject"]] = relationship("Subject", back_populates="parent")


class Discipline(BigIntPKMixin, TimestampMixin, Base):
    """招生学科：研招口径的学科代码（原 kaoyan_subjects 更名对齐）。

    与 Subject（备考科目）是两套不同概念，靠 subject_discipline_links 建立映射，
    不要合并成一张表。
    """

    __tablename__ = "disciplines"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, comment="学科代码，如 0812")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="学科名称")
    category: Mapped[str | None] = mapped_column(String(50), comment="学科门类（如 工学）")
    parent_code: Mapped[str | None] = mapped_column(String(20), comment="上级学科代码")
    exam_overlap: Mapped[str | None] = mapped_column(Text, comment="考纲重叠说明")
    description: Mapped[str | None] = mapped_column(Text, comment="学科说明")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="展示排序权重，升序")


class SubjectDisciplineLink(BigIntPKMixin, Base):
    """备考科目 ↔ 招生学科 的多对多映射。"""

    __tablename__ = "subject_discipline_links"

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, comment="备考科目 ID"
    )
    discipline_id: Mapped[int] = mapped_column(
        ForeignKey("disciplines.id", ondelete="CASCADE"), nullable=False, comment="招生学科 ID"
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", comment="是否为主映射（一科对多科时用于默认归类）"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class SubjectAlias(BigIntPKMixin, Base):
    """科目别名：收敛散落在代码里的硬编码科目字符串。"""

    __tablename__ = "subject_aliases"

    alias: Mapped[str] = mapped_column(String(100), nullable=False, comment="别名原字符串")
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, comment="指向的权威科目 ID"
    )
    alias_source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="legacy_code", comment="别名来源：legacy_code / import / user"
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", comment="一个别名命中多行时，本行是否为首选解析结果"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


class SubjectChapter(BigIntPKMixin, TimestampMixin, Base):
    """科目章节：把 subject_config.chapters 的 JSON 升级为可关联实体。"""

    __tablename__ = "subject_chapters"

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, comment="所属科目 ID"
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="章节代码")
    title: Mapped[str] = mapped_column(String(300), nullable=False, comment="章节标题")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("subject_chapters.id", ondelete="SET NULL"), comment="父章节 ID"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="章节内排序权重，升序")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", comment="是否启用")


class SubjectConfig(BigIntPKMixin, TimestampMixin, Base):
    """科目配置：科目默认题型与扩展配置。"""

    __tablename__ = "subject_configs"

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, unique=True, comment="所属科目 ID，一对一"
    )
    question_types: Mapped[list] = mapped_column(
        JSONBList, nullable=False, server_default="[]", comment="支持的题型数组"
    )
    is_custom: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", comment="是否用户自定义配置"
    )
    extra: Mapped[dict] = mapped_column(JSONBObject, nullable=False, server_default="{}", comment="扩展配置项")


class SubjectPrototype(BigIntPKMixin, Base):
    """科目原型向量：分块学科分类用的聚类中心（实测 bge 512 维）。"""

    __tablename__ = "subject_prototypes"

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, comment="所属科目 ID"
    )
    engine: Mapped[str] = mapped_column(
        build_enum("vector_engine"), nullable=False, server_default="unknown", comment="向量引擎"
    )
    dim: Mapped[int] = mapped_column(Integer, nullable=False, comment="向量维度")
    prototype: Mapped[bytes] = mapped_column(Float32Vector, nullable=False, comment="原型向量的 float32 小端字节数组")
    n_samples: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="构建样本数")
    built_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="构建时间（UTC）"
    )


class PlatformConfig(BigIntPKMixin, TimestampMixin, Base):
    """第三方平台对接配置。"""

    __tablename__ = "platform_configs"

    platform_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="平台名称，唯一")
    token: Mapped[str | None] = mapped_column(EncryptedText, comment="访问令牌（密文落库）")
    app_key: Mapped[str | None] = mapped_column(EncryptedText, comment="应用标识（密文落库）")
    secret_key: Mapped[str | None] = mapped_column(EncryptedText, comment="应用密钥（密文落库）")
    sync_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", comment="是否启用自动同步"
    )
    sync_frequency: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="manual", comment="同步频率：manual/hourly/daily/weekly"
    )
    last_sync: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="上次同步时间")
    extra: Mapped[dict] = mapped_column(JSONBObject, nullable=False, server_default="{}", comment="平台专属扩展配置")


class AIProvider(BigIntPKMixin, TimestampMixin, Base):
    """大模型供应商配置，按 fallback_priority 升序降级。"""

    __tablename__ = "ai_providers"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="配置名，唯一")
    provider_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="openai_compatible", comment="接入协议类型"
    )
    api_key: Mapped[str | None] = mapped_column(EncryptedText, comment="API 密钥（密文落库）")
    base_url: Mapped[str | None] = mapped_column(String(500), comment="接口基地址")
    model_name: Mapped[str | None] = mapped_column(String(200), comment="默认模型名")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.7", comment="采样温度 0-2")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", comment="是否默认供应商")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", comment="是否启用")
    fallback_priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="100", comment="降级优先级，越小越优先"
    )


class CustomLink(BigIntPKMixin, Base):
    """用户自定义快捷链接。"""

    __tablename__ = "custom_links"

    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="链接显示名")
    url: Mapped[str] = mapped_column(String(1000), nullable=False, comment="链接地址")
    category: Mapped[str] = mapped_column(String(100), nullable=False, server_default="general", comment="分组分类")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="组内排序权重，升序")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）"
    )


__all__ = [
    "Subject",
    "Discipline",
    "SubjectDisciplineLink",
    "SubjectAlias",
    "SubjectChapter",
    "SubjectConfig",
    "SubjectPrototype",
    "PlatformConfig",
    "AIProvider",
    "CustomLink",
]
