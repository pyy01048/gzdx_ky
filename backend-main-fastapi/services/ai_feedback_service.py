# -*- coding: utf-8 -*-
"""AI 答疑回答反馈服务（R4：有用 / 无用 / 纠错三键）。

存储用户对 AI 答疑回答的反馈记录，UNIQUE(answer_id, user_id) 防同一用户对同一
回答重复反馈。answer_id 为前端生成的 UUID/时间戳字符串，不做 FK，不依赖 answers
表存在（幂等存储反馈，answer_id 不存在不报错）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import AiAnswerFeedback

logger = logging.getLogger(__name__)

#: 允许的反馈类型枚举
FEEDBACK_TYPES = ("helpful", "unhelpful", "correction")


async def submit_feedback(
    db: Session,
    answer_id: str,
    user_id: int,
    feedback_type: str,
    correction_text: str | None,
) -> int:
    """提交反馈，返回新插入的 feedback_id。

    重复反馈（同 answer_id + user_id）由 UNIQUE 约束拒绝，抛 ValueError 供路由层
    转 409。feedback_type 不合法抛 ValueError 供路由层转 422。

    Args:
        db: SQLAlchemy 会话。
        answer_id: 前端生成的回答标识（UUID/时间戳字符串）。
        user_id: 提交反馈的用户 ID。
        feedback_type: 反馈类型，须为 ``helpful`` / ``unhelpful`` / ``correction``。
        correction_text: 纠错文本，仅当 ``feedback_type == "correction"`` 时保留。

    Returns:
        新插入的反馈记录 ID。

    Raises:
        ValueError: ``feedback_type`` 不合法，或同 (answer_id, user_id) 已存在反馈。
    """
    if feedback_type not in FEEDBACK_TYPES:
        raise ValueError(f"feedback_type 不合法：{feedback_type}")
    if feedback_type != "correction":
        # 仅纠错类型收集 correction_text，其余类型忽略该字段
        correction_text = None

    feedback = AiAnswerFeedback(
        answer_id=answer_id,
        user_id=user_id,
        feedback_type=feedback_type,
        correction_text=correction_text,
    )
    db.add(feedback)
    try:
        db.commit()
    except IntegrityError as exc:  # UNIQUE(answer_id, user_id) 冲突
        db.rollback()
        logger.warning("重复反馈被拒绝: answer_id=%s user_id=%s", answer_id, user_id)
        raise ValueError("已对该回答反馈过") from exc
    db.refresh(feedback)
    logger.info(
        "反馈已记录: id=%s answer_id=%s user_id=%s type=%s",
        feedback.id,
        answer_id,
        user_id,
        feedback_type,
    )
    return feedback.id


async def list_feedback(db: Session, answer_id: str) -> list[dict[str, Any]]:
    """查询某回答的反馈列表（管理员查看）。

    Args:
        db: SQLAlchemy 会话。
        answer_id: 回答标识。

    Returns:
        反馈记录字典列表，按创建时间倒序。
    """
    items = (
        db.query(AiAnswerFeedback)
        .filter(AiAnswerFeedback.answer_id == answer_id)
        .order_by(AiAnswerFeedback.created_at.desc())
        .all()
    )
    return [_serialize(item) for item in items]


def _serialize(item: AiAnswerFeedback) -> dict[str, Any]:
    """反馈记录序列化为可 JSON 序列化的字典。

    Args:
        item: ``AiAnswerFeedback`` ORM 实例。

    Returns:
        包含 id/answer_id/user_id/feedback_type/correction_text/created_at 的字典。
    """
    return {
        "id": item.id,
        "answer_id": item.answer_id,
        "user_id": item.user_id,
        "feedback_type": item.feedback_type,
        "correction_text": item.correction_text,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
