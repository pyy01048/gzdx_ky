# --------------------------------------------------------------------------- #
# CHECK 约束生成器（供 core/models/* 定义行内约束时复用，避免各表手搓 SQL 文本）
# --------------------------------------------------------------------------- #
"""CHECK 约束生成器：把枚举 / 区间 / 非空 / JSON 数组结构检查转成 CheckConstraint。

从 core.pg_types 拆出，避免 pg_types 单文件超长；对外仍可通过
``from core.pg_types import range_check`` 使用（pg_types 已重导出）。

说明：题目表的主要结构校验在 core/sql/040_questions.sql 里以
``is_canonical_options()`` 等 PL/pgSQL 函数 + CHECK 落地，本模块用于
Python 侧声明式建表（SQLite 降级模式）时的等价约束。
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import CheckConstraint


def enum_check(column: str, values: Sequence[str], name: str) -> CheckConstraint:
    """生成枚举 CHECK：限定列取值。"""
    literal = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return CheckConstraint(f"{column} IN ({literal})", name=name)


def range_check(column: str, low: int, high: int, name: str) -> CheckConstraint:
    """生成闭区间 CHECK（如难度 1-5、掌握度 0-100）。"""
    return CheckConstraint(f"{column} BETWEEN {low} AND {high}", name=name)


def not_blank_check(column: str, name: str) -> CheckConstraint:
    """拒绝空串与纯空白（正文类字段的兜底门）。"""
    return CheckConstraint(f"char_length(btrim({column})) > 0", name=name)


def jsonb_array_check(
    column: str, name: str, min_len: int = 0, max_len: int = 64, elem: str = "object",
) -> CheckConstraint:
    """JSON 数组结构门：必须是数组、长度在界内、首元素类型正确。"""
    return CheckConstraint(
        f"{column} IS NULL OR ("
        f" jsonb_typeof({column}) = 'array'"
        f" AND jsonb_array_length({column}) BETWEEN {min_len} AND {max_len}"
        f" AND (jsonb_array_length({column}) = 0"
        f"      OR jsonb_typeof({column} -> 0) = '{elem}')"
        f")",
        name=name,
    )


def imply_check(condition: str, requirement: str, name: str) -> CheckConstraint:
    """蕴涵门：条件成立时要求必须满足（如"真题必须有年份"）。"""
    return CheckConstraint(f"NOT ({condition}) OR ({requirement})", name=name)


__all__ = [
    "enum_check",
    "range_check",
    "not_blank_check",
    "jsonb_array_check",
    "imply_check",
]
