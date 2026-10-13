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

from typing import Any, Optional

from sqlalchemy import and_, not_, or_

from models import QuizQuestion


# --------------------------------------------------------------------------- #
# 来源大类（真题 / 教材题 / 自建）——**唯一**派生口径（M0-103）。
#
# 库里没有 source_kind 列，来源大类由 `source` 字段前缀派生：
#   * `真题:<文档名>`    → exam（历年真题）
#   * `知识库:<文档名>`  → textbook（教材 / 讲义 / 知识库抽取题）
#   * 其余 / NULL        → custom（ai 变式题、手工录入等）
#
# 该规则被 routers/quiz.py（列表/统计口径）与 routers/ai_tutoring.py
# （真题/教材两种答疑模式）共同复用，**只此一份**，避免两处派生漂移。
# --------------------------------------------------------------------------- #
SOURCE_KIND_CHOICES = ("exam", "textbook", "custom")
EXAM_PREFIX = "真题:%"
TEXTBOOK_PREFIX = "知识库:%"


def source_kind_of(source: Optional[str]) -> str:
    """按 `source` 前缀派生来源大类，返回 exam / textbook / custom（永不返回 None）。"""
    s = (source or "").strip()
    if s.startswith("真题:"):
        return "exam"
    if s.startswith("知识库:"):
        return "textbook"
    return "custom"


def normalize_source_kind(source_kind: Optional[str]) -> Optional[str]:
    """归一 source_kind 入参：''/'all'/None → None；否则小写化（不校验合法性）。"""
    if source_kind is None:
        return None
    k = str(source_kind).strip().lower()
    if k in ("", "all"):
        return None
    return k


def source_kind_expr(source_kind: Optional[str], model: Any = QuizQuestion) -> Any:
    """返回 source_kind 对应的 SQLAlchemy 过滤表达式；''/'all'/None 返回 None。

    非法的 source_kind 不在此处抛错（由调用方决定如何失败），只返回 None 会掩盖错误，
    故对未知值直接抛 ValueError，调用方转 400。
    """
    kind = normalize_source_kind(source_kind)
    if kind is None:
        return None
    if kind not in SOURCE_KIND_CHOICES:
        raise ValueError(f"不支持的 source_kind：{source_kind}")
    if kind == "exam":
        return model.source.like(EXAM_PREFIX)
    if kind == "textbook":
        return model.source.like(TEXTBOOK_PREFIX)
    # custom：既非真题也非教材（含 source 为 NULL 的历史行），不丢数据。
    # 两个「非」之间必须是 AND——用 OR 会把 exam/textbook 行也放进来。
    return or_(
        model.source.is_(None),
        and_(
            not_(model.source.like(EXAM_PREFIX)),
            not_(model.source.like(TEXTBOOK_PREFIX)),
        ),
    )


def answerable_expr(model: Any = QuizQuestion) -> Any:
    """「可作答」判定表达式：is_available 为 True 或 NULL（NULL 视为可用，向后兼容）。"""
    return or_(model.is_available.is_(True), model.is_available.is_(None))


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
