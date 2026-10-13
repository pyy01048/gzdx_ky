# -*- coding: utf-8 -*-
"""学习行为事件埋点服务（M5-1）。

「学习科学」的唯一硬前置就是**有埋点数据**：没有事件流水，任何"遗忘曲线 /
薄弱点预测 / 学习时长分布"都是空谈。本模块是埋点的统一入口。

设计原则（务必遵守）
--------------------
1. **旁路、容错**：埋点是旁路逻辑，任何写入失败都**绝不能影响主流程**。
   所有写库动作都被 ``try/except`` 包住，失败只记 warning 日志并返回
   ``None``/``[]``，**不向上抛异常**。答题提交不会因为埋点挂了而失败。
2. **不改表结构**：``study_events`` 表已存在（见 models.StudyEvent），
   本模块只做插入，不做 DDL。
3. **幂等无副作用**：埋点只新增流水行，不更新任何业务表，对已有功能
   无任何可观察副作用。
4. **批量友好**：一次答题提交可能包含多道题，提供 :func:`record_events`
   批量写入，避免 N 次 commit。

时间约定
--------
``occurred_at`` 使用本项目统一的 **naive UTC**（见 utils.timeutil.utcnow），
与 DB 中其余的 naive 时间列保持一致，避免 aware/naive 混用导致的比较异常。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from models import StudyEvent
from utils.timeutil import utcnow

logger = logging.getLogger(__name__)

__all__ = [
    "record_event",
    "record_events",
    "resolve_knowledge_point_id",
]

# 允许的事件类型白名单。这样做不是为了限制业务，而是给埋点一个"可枚举"
# 的语义边界，方便后续 BI 侧按类型聚合时不被脏数据干扰。
KNOWN_EVENT_TYPES = frozenset(
    {
        "answer",        # 答题（刷题提交）
        "review",        # 复习提交（知识点/错题）
        "flashcard",     # 卡片复习
        "word",          # 单词背诵
        "study",         # 通用学习动作
        "exam_submit",   # 模拟考提交
    }
)


def resolve_knowledge_point_id(
    db: Session,
    question_id: Optional[int],
    *,
    prefer_primary: bool = True,
) -> Optional[int]:
    """经 ``question_knowledge_links`` 反查题目对应的主知识点 ID。

    优先取 ``role='primary'`` 的关联；若没有 primary，则退化为任意一条
    （按 id 升序取第一条，保证结果稳定、可复现）。查不到返回 ``None``。

    Args:
        db: SQLAlchemy 会话。
        question_id: 题目 ID；为 ``None`` 时直接返回 ``None``。
        prefer_primary: 是否优先匹配 ``role='primary'``，默认 ``True``。

    Returns:
        命中的 ``knowledge_point_id``，否则 ``None``。
    """
    if question_id is None:
        return None
    try:
        # 延迟导入避免潜在循环依赖（routers 侧已导入 models）。
        from models import QuestionKnowledgeLink

        q = db.query(QuestionKnowledgeLink).filter(
            QuestionKnowledgeLink.question_id == question_id
        )
        if prefer_primary:
            q = q.order_by(
                # primary 排在前面（'primary' < 'secondary' 字典序成立）
                QuestionKnowledgeLink.role.asc(),
                QuestionKnowledgeLink.id.asc(),
            )
        else:
            q = q.order_by(QuestionKnowledgeLink.id.asc())
        row = q.first()
        if row is not None:
            return row.knowledge_point_id
    except Exception as exc:  # pragma: no cover - 反查失败不应影响埋点
        logger.warning("study_events 反查知识点失败 question_id=%s: %s", question_id, exc)
    return None


def _build_event(
    event_type: str,
    *,
    subject: Optional[str] = None,
    question_id: Optional[int] = None,
    knowledge_point_id: Optional[int] = None,
    chapter_id: Optional[int] = None,
    is_correct: Optional[bool] = None,
    duration_seconds: Optional[int] = None,
    session_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[Any] = None,
) -> StudyEvent:
    """构造一个 ``StudyEvent`` ORM 对象（不落库）。

    抽出构造函数便于单测直接断言字段，也便于批量场景统一处理。
    """
    return StudyEvent(
        event_type=str(event_type),
        subject=subject,
        chapter_id=chapter_id,
        knowledge_point_id=knowledge_point_id,
        question_id=question_id,
        session_id=session_id,
        is_correct=is_correct,
        duration_seconds=duration_seconds,
        payload=payload,
        occurred_at=occurred_at or utcnow(),
    )


def record_event(
    db: Session,
    event_type: str,
    *,
    subject: Optional[str] = None,
    question_id: Optional[int] = None,
    knowledge_point_id: Optional[int] = None,
    chapter_id: Optional[int] = None,
    is_correct: Optional[bool] = None,
    duration_seconds: Optional[int] = None,
    session_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[Any] = None,
    commit: bool = True,
) -> Optional[int]:
    """记录单条学习行为事件（**容错，绝不抛异常**）。

    这是埋点的核心入口。任何异常都会被吞掉并记 warning，返回 ``None``，
    以保证调用方（如答题提交）的主流程永远不受埋点影响。

    Args:
        db: SQLAlchemy 会话。
        event_type: 事件类型，建议取 :data:`KNOWN_EVENT_TYPES` 之一。
        subject: 科目（已归一化更佳）。
        question_id: 题目 ID。
        knowledge_point_id: 知识点 ID。
        chapter_id: 章节 ID。
        is_correct: 是否答对（仅答题类事件有意义）。
        duration_seconds: 耗时（秒）。
        session_id: 会话/批次 ID。
        payload: 扩展载荷（任意可 JSON 序列化的字典）。
        occurred_at: 事件发生时间；缺省用当前 naive UTC。
        commit: 是否立即提交。批量场景应传 ``False`` 由调用方统一提交。

    Returns:
        成功时返回新行的 ``id``；失败（或被吞掉异常）时返回 ``None``。
    """
    try:
        event = _build_event(
            event_type,
            subject=subject,
            question_id=question_id,
            knowledge_point_id=knowledge_point_id,
            chapter_id=chapter_id,
            is_correct=is_correct,
            duration_seconds=duration_seconds,
            session_id=session_id,
            payload=payload,
            occurred_at=occurred_at,
        )
        db.add(event)
        if commit:
            db.commit()
            db.refresh(event)
        else:
            # 未提交时 flush 以拿到自增主键；失败由外层统一回滚
            db.flush()
        return event.id
    except Exception as exc:
        # 埋点失败绝不影响主流程：回滚本次埋点写入，记日志即可。
        logger.warning("study_events 埋点失败 event_type=%s: %s", event_type, exc)
        try:
            db.rollback()
        except Exception:  # pragma: no cover - 回滚失败也不再抛
            pass
        return None


def record_events(
    db: Session,
    events: Iterable[Dict[str, Any]],
    *,
    commit: bool = True,
) -> List[int]:
    """批量记录学习行为事件（**容错，绝不抛异常**）。

    一次答题提交若包含多题，调用本函数一次性写入，避免 N 次 commit 的开销。
    每条事件形如::

        {
            "event_type": "answer",
            "subject": "数学",
            "question_id": 123,
            "is_correct": True,
            "duration_seconds": 30,
            "knowledge_point_id": 82,
        }

    单条构造失败会被跳过，不影响其余事件，也不影响主流程。

    Args:
        db: SQLAlchemy 会话。
        events: 事件字典可迭代对象。
        commit: 是否在末尾统一提交。

    Returns:
        成功写入的行 id 列表（失败条目被静默跳过）。
    """
    written: List[int] = []
    try:
        pending: List[StudyEvent] = []
        for item in events:
            if not item:
                continue
            try:
                event_type = item.get("event_type")
                if not event_type:
                    # 无事件类型视为脏数据，跳过
                    continue
                pending.append(
                    _build_event(
                        event_type,
                        subject=item.get("subject"),
                        question_id=item.get("question_id"),
                        knowledge_point_id=item.get("knowledge_point_id"),
                        chapter_id=item.get("chapter_id"),
                        is_correct=item.get("is_correct"),
                        duration_seconds=item.get("duration_seconds"),
                        session_id=item.get("session_id"),
                        payload=item.get("payload"),
                        occurred_at=item.get("occurred_at"),
                    )
                )
            except Exception as exc:  # pragma: no cover - 单条脏数据跳过
                logger.warning("study_events 批量埋点单条构造失败，已跳过: %s", exc)
                continue

        if not pending:
            return written

        db.add_all(pending)
        if commit:
            db.commit()
            for ev in pending:
                written.append(ev.id)
        else:
            db.flush()
            for ev in pending:
                written.append(ev.id)
    except Exception as exc:
        logger.warning("study_events 批量埋点失败（共 %d 条）：%s", len(written) or -1, exc)
        try:
            db.rollback()
        except Exception:  # pragma: no cover
            pass
        return []
    return written
