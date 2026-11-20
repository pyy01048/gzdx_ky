"""院校与研招数据域模型。

对齐 core/sql/060_schools.sql。

命名说明：保留 kaoyan_ 前缀是为了与既有 37 个路由 / 80 个服务的查询保持兼容，
减少一次性重命名带来的迁移风险；语义收敛由 subjects/disciplines 负责。
"""

from __future__ import annotations

import datetime

from sqlalchemy import ( Boolean, Float, ForeignKey, Integer, REAL, SmallInteger, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import INET

from ..pg_types import JSONBList, JSONBObject, build_enum
from .base import Base, BigIntKey, BigIntPKMixin, DateTimeUTC, TimestampMixin


class KaoyanSchool(BigIntPKMixin, TimestampMixin, Base):
    """院校主数据。"""

    __tablename__ = "kaoyan_schools"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True,
                                      comment="院校名称，唯一")
    level: Mapped[str | None] = mapped_column(String(50),
                                               comment="院校层次：985 / 211 / 双一流 / 普通")
    province: Mapped[str | None] = mapped_column(String(50), comment="所在省份")
    city: Mapped[str | None] = mapped_column(String(50), comment="所在城市")
    logo_url: Mapped[str | None] = mapped_column(String(500), comment="校徽地址")
    intro: Mapped[str | None] = mapped_column(Text, comment="院校简介")
    tags: Mapped[list] = mapped_column(JSONBList, nullable=False,
                                        server_default="[]", comment="院校标签数组")
    official_url: Mapped[str | None] = mapped_column(String(500), comment="官网地址")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="数据采集来源")
    type: Mapped[str | None] = mapped_column(String(30), comment="院校类型：综合 / 理工 等")
    region: Mapped[str | None] = mapped_column(String(30), comment="所属地区")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true",
                                          comment="是否启用（禁用后前台不可见）")
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="软删除时间")


class SchoolAlias(BigIntPKMixin, Base):
    """院校别名，用于公告匹配与模糊院校名解析。"""

    __tablename__ = "school_aliases"

    alias: Mapped[str] = mapped_column(String(100), nullable=False, unique=True,
                                       comment="院校别名，唯一")
    school_id: Mapped[int] = mapped_column( ForeignKey("kaoyan_schools.id", ondelete="CASCADE"), nullable=False,
        comment="指向的院校 ID")
    school_name: Mapped[str | None] = mapped_column(String(200), comment="院校正式名")
    alias_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="common",
        comment="别名类型：common 俗称 / abbrev 缩写 / former 曾用名")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class KaoyanCollege(BigIntPKMixin, Base):
    """院校下属学院。"""

    __tablename__ = "kaoyan_colleges"

    school_id: Mapped[int] = mapped_column( ForeignKey("kaoyan_schools.id", ondelete="CASCADE"), nullable=False,
        comment="所属院校 ID")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="学院名称")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true",
                                          comment="是否启用")
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="软删除时间")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class KaoyanMajor(BigIntPKMixin, Base):
    """招生专业。"""

    __tablename__ = "kaoyan_majors"

    school_id: Mapped[int] = mapped_column( ForeignKey("kaoyan_schools.id", ondelete="CASCADE"), nullable=False,
        comment="所属院校 ID")
    college_id: Mapped[int | None] = mapped_column( ForeignKey("kaoyan_colleges.id", ondelete="SET NULL"), comment="所属学院 ID")
    code: Mapped[str | None] = mapped_column(String(20), comment="专业代码")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="专业名称")
    research_direction: Mapped[str | None] = mapped_column(String(300), comment="研究方向")
    subject_code: Mapped[str | None] = mapped_column(String(20), comment="所属学科代码")
    exam_subjects: Mapped[list] = mapped_column(
        JSONBList, nullable=False, server_default="[]", comment="初试科目数组")
    reference_books: Mapped[list] = mapped_column(
        JSONBList, nullable=False, server_default="[]", comment="参考书目数组")
    degree_type: Mapped[str] = mapped_column(
        build_enum("degree_type"), nullable=False,
        server_default="unknown", comment="学位类型：academic/professional/unknown")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true",
                                          comment="是否启用")
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="软删除时间")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class KaoyanAdmission(Base):
    """招生录取数据。"""

    __tablename__ = "kaoyan_admissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    school_id: Mapped[int] = mapped_column( ForeignKey("kaoyan_schools.id", ondelete="CASCADE"), nullable=False,
        comment="院校 ID")
    major_id: Mapped[int | None] = mapped_column( ForeignKey("kaoyan_majors.id", ondelete="CASCADE"), comment="专业 ID")
    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="招生年份")
    enroll_count: Mapped[int | None] = mapped_column(Integer, comment="计划招生人数")
    retest_count: Mapped[int | None] = mapped_column(Integer, comment="进入复试人数")
    admit_count: Mapped[int | None] = mapped_column(Integer, comment="实际录取人数")
    admit_avg_score: Mapped[float | None] = mapped_column(REAL, comment="录取平均分")
    major_avg_score: Mapped[float | None] = mapped_column(REAL, comment="专业课平均分")
    retest_ratio: Mapped[float | None] = mapped_column(REAL, comment="复录比")
    data_source: Mapped[str | None] = mapped_column(String(50), comment="采集来源")
    source: Mapped[str | None] = mapped_column(String(50), comment="采集批次标识")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true",
                                          comment="是否启用")
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="软删除时间")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class KaoyanScoreline(BigIntPKMixin, Base):
    """分数线。"""

    __tablename__ = "kaoyan_scorelines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    school_id: Mapped[int] = mapped_column( ForeignKey("kaoyan_schools.id", ondelete="CASCADE"), nullable=False,
        comment="院校 ID")
    major_id: Mapped[int | None] = mapped_column( ForeignKey("kaoyan_majors.id", ondelete="CASCADE"), comment="专业 ID")
    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="年份")
    total_line: Mapped[int | None] = mapped_column(Integer, comment="总分线")
    politics_line: Mapped[int | None] = mapped_column(Integer, comment="政治单科线")
    english_line: Mapped[int | None] = mapped_column(Integer, comment="英语单科线")
    math_line: Mapped[int | None] = mapped_column(Integer, comment="数学单科线")
    major_line: Mapped[int | None] = mapped_column(Integer, comment="专业课单科线")
    national_line: Mapped[int | None] = mapped_column(Integer, comment="当年国家线")
    retest_line: Mapped[int | None] = mapped_column(Integer, comment="复试线")
    line_type: Mapped[str | None] = mapped_column(
        String(20), comment="线类型：national/school/college/retest")
    source: Mapped[str | None] = mapped_column(String(50), comment="采集批次标识")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true",
                                          comment="是否启用")
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="软删除时间")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


class KaoyanSubject(BigIntPKMixin, Base):
    """择校数据中心·学科分类。"""

    __tablename__ = "kaoyan_subjects"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True,
                                      comment="学科代码")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="学科名称")
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="门类")
    parent_code: Mapped[str | None] = mapped_column(String(20), nullable=True,
                                                    comment="上级学科代码")
    exam_overlap: Mapped[str | None] = mapped_column(String(300), nullable=True,
                                                     comment="考试科目交叉")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="学科简介")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间（UTC）")


__all__ = ["KaoyanSchool", "SchoolAlias", "KaoyanCollege", "KaoyanMajor", "KaoyanAdmission", "KaoyanScoreline", "KaoyanSubject", "AuditLog"]


class AuditLog(Base):
    """审计日志：记录所有写操作，不可修改不可删除"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="表名")
    record_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="记录ID")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="操作类型：INSERT/UPDATE/DELETE/ENABLE/DISABLE")
    operator_id: Mapped[int | None] = mapped_column(Integer, comment="操作用户ID（NULL表示系统）")
    operator_ip: Mapped[str | None] = mapped_column(INET, comment="操作者IP（库列是 inet，写 String 会被 PG 拒）")
    before_data: Mapped[dict | None] = mapped_column(JSONBObject, comment="变更前快照")
    after_data: Mapped[dict | None] = mapped_column(JSONBObject, comment="变更后快照")
    change_summary: Mapped[str | None] = mapped_column(Text, comment="变更摘要")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(), nullable=False, comment="创建时间")
