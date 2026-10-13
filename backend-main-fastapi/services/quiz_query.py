# -*- coding: utf-8 -*-
"""题库查询口径统一（M1-1h，2026-10）。

背景：M1-1f 把 OCR 碎片题标记 `quiz_questions.is_junk=1`。刷题列表端点
`GET /api/quiz/questions` 已默认排除，但**其它统计端点**（考频/套卷索引/年份/
章节/科目题数）若不排除，会出现"各科目题数 9171 但可刷 8852"的口径漂移。

本模块提供**唯一**的"可见题目"过滤构造器，供列表与所有用户可见统计复用，
从根上避免口径再次漂移。

口径约定：
  * `is_junk = 1` 的题 = OCR 碎片/答案串，**默认不可见**；
  * `is_junk = NULL`（历史行、未标记）视为**非碎片**，可见（向后兼容）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_

from models import QuizQuestion


def visible_quiz_filter(query: Any, include_junk: bool = False) -> Any:
    """给任意 QuizQuestion 查询套上"可见题目"过滤（默认排除 is_junk=1）。

    Args:
        query: 一个以 `QuizQuestion` 为主表的 SQLAlchemy Query。
        include_junk: True 时不加过滤（查看/审计全量）。

    Returns:
        过滤后的 Query（可直接继续 filter/group_by/count）。

    用法：
        >>> base = visible_quiz_filter(db.query(QuizQuestion.subject, func.count(QuizQuestion.id)))
        >>> base.group_by(QuizQuestion.subject).all()
    """
    if include_junk:
        return query
    # NULL 视为未标记（非碎片）→ 保留；仅排除显式 is_junk=1
    return query.filter(
        or_(QuizQuestion.is_junk.is_(False), QuizQuestion.is_junk.is_(None))
    )
