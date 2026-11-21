"""ORM 基类与公共混入。

约定（与 core/pg_schema.sql 严格对齐）：
  - 主键统一 BIGINT（BigInteger + autoincrement），不依赖 SQLite 的隐式 rowid；
  - 时间统一 DateTime(timezone=True)，Python 侧一律 timezone-aware UTC；
  - PG 的 GENERATED 列（option_count / search_vector / is_past_exam）在本层声明为
    **只读列**（insert=False, update=False）：PG 由数据库自动维护，
    SQLite 降级模式下退化为普通可空列，两种后端都能建表。
"""

from __future__ import annotations

import datetime

from sqlalchemy import BigInteger, DateTime, Integer, MetaData, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: 主键 / 外键统一类型：
#:   PostgreSQL → BIGINT（BIGSERIAL）
#:   SQLite     → INTEGER
#: 必须降级的原因：SQLite 只在列声明类型**恰好**是 INTEGER 时才把它当作 rowid 别名，
#: 声明成 BIGINT 则不会，此时 INSERT 不带 id 会因 NOT NULL 约束直接失败。
BigIntKey = BigInteger().with_variant(Integer(), "sqlite")

#: 索引/约束命名约定：让 Alembic 或手工比对 diff 时名字稳定可预期
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime.datetime:
    """timezone-aware 当前 UTC 时间（替代已弃用的 datetime.utcnow）。"""
    return datetime.datetime.now(datetime.timezone.utc)


class DateTimeUTC(DateTime):
    """带时区的时间列；SQLite 下同样保持 ISO 字符串存储。"""

    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)


class Base(DeclarativeBase):
    """全库 DeclarativeBase：统一元数据与类型映射。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime.datetime: DateTimeUTC}


class BigIntPKMixin:
    """统一 BIGINT 自增主键。"""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    """created_at / updated_at 双时间列。

    PG 侧由 set_updated_at 触发器维护 updated_at；SQLite 侧由 onupdate 维护，
    保证不依赖数据库特性也能拿到正确值。
    """

    created_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTimeUTC, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TimestampedBigIntPKMixin(BigIntPKMixin, TimestampMixin):
    """BIGINT 主键 + 双时间列，绝大多数表的默认组合。"""


__all__ = [
    "Base",
    "BigIntKey",
    "BigIntPKMixin",
    "TimestampMixin",
    "TimestampedBigIntPKMixin",
    "DateTimeUTC",
    "NAMING_CONVENTION",
    "utcnow",
    "func",
    "text",
]
