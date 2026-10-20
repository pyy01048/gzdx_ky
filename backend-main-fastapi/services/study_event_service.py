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
   本模块只做插入 / 聚合查询，不做 DDL。
3. **幂等无副作用**：埋点只新增流水行，不更新任何业务表，对已有功能
   无任何可观察副作用。同一份业务记录（如同一 ``answer_record_id``）重复
   调用只落一条——去重键存在 ``payload._dedupe_key``，命中即直接返回原行 id。
4. **批量友好**：一次答题提交可能包含多道题，提供 :func:`record_events`
   批量写入，避免 N 次 commit。

时间约定
--------
``occurred_at`` 使用本项目统一的 **naive UTC**（见 utils.timeutil.utcnow），
与 DB 中其余的 naive 时间列保持一致，避免 aware/naive 混用导致的比较异常。
DB 列本身是 ``timestamptz``，会话时区固定 UTC（core/db_session），语义一致。

统一口径
--------
:func:`learning_summary` 是「学习数据一览 / 热力图 / 连续天数」的读侧入口：
业务表（tasks / flashcards / words / error_records / answer_records）给"资产存量"，
``study_events`` 给"行为流水与真实耗时"。两边的用户过滤都用 ``user_id``，
不再出现"查了全库但页面按用户看"这种数不上的问题。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from models import StudyEvent
from utils.timeutil import (
    day_bucket_expr,
    local_today,
    local_window_for_day,
    utcnow,
)

logger = logging.getLogger(__name__)

__all__ = [
    "KNOWN_EVENT_TYPES",
    "record",
    "record_answer",
    "record_review",
    "record_focus",
    "record_event",
    "record_events",
    "resolve_knowledge_point_id",
    "learning_summary",
]

# 允许的事件类型白名单。这样做不是为了限制业务，而是给埋点一个"可枚举"
# 的语义边界，方便后续 BI 侧按类型聚合时不被脏数据干扰。
KNOWN_EVENT_TYPES = frozenset(
    {
        "answer",        # 答题（刷题提交）
        "review",        # 复习提交（知识点/错题/单词/卡片）
        "flashcard",     # 卡片复习
        "word",          # 单词背诵
        "focus",         # 专注计时（真实时长）
        "study",         # 通用学习动作
        "exam_submit",   # 模拟考提交
    }
)


# --------------------------------------------------------------------------- #
# 会话与参数清洗
# --------------------------------------------------------------------------- #
def _open_session(db: Optional[Session]):
    """返回 ``(session, owns_session)``。

    传入会话时直接复用（兼容既有调用点）；不传时自建一个短生命周期会话。
    自建会话的价值：埋点写失败只回滚自己，永远不会碰到请求主事务。
    """
    if db is not None:
        return db, False
    from database import SessionLocal

    return SessionLocal(), True


def _norm_duration(value: Any) -> Optional[int]:
    """耗时规整为非负整数秒；非法值按"未记录"处理（None）。"""
    if value is None:
        return None
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _check_chapter_id(db: Session, chapter_id: Optional[int]) -> Optional[int]:
    """校验 ``chapter_id`` 确实存在于 ``subject_chapters``。

    ``study_events.chapter_id`` 外键指向 ``subject_chapters(id)``，而历史上
    刷题侧曾把 ``knowledge_points.id`` 当成章节 id 传进来——两者 id 空间
    重叠时能写进去（脏关联），不重叠时整条埋点被外键打回、静默丢失。
    这里统一按权威章节表校验：不存在就落 NULL，绝不因为一个可选字段
    把整条事件丢掉。
    """
    if chapter_id is None:
        return None
    try:
        row = db.execute(
            text("SELECT 1 FROM subject_chapters WHERE id = :cid LIMIT 1"),
            {"cid": int(chapter_id)},
        ).first()
        return int(chapter_id) if row else None
    except Exception:  # pragma: no cover - 老库没有章节表时降级为 NULL
        return None


def _payload_with_key(
    payload: Optional[Dict[str, Any]], dedupe_key: Optional[str]
) -> Dict[str, Any]:
    """复制 payload 并写入去重键（不修改调用方传入的字典）。"""
    data: Dict[str, Any] = dict(payload or {})
    if dedupe_key:
        data["_dedupe_key"] = str(dedupe_key)
    return data


def _find_by_dedupe_key(
    db: Session, dedupe_key: str, user_id: Optional[int]
) -> Optional[int]:
    """在最近的事件里找相同去重键（命中返回原行 id）。

    不依赖 PG 的 ``jsonb ->>`` 运算符，改成取最近 N 行在 Python 侧比对：
    埋点量级小、去重窗口只需要覆盖"同一次提交的重试"，可移植性更好。
    """
    try:
        q = db.query(StudyEvent)
        if user_id is None:
            q = q.filter(StudyEvent.user_id.is_(None))
        else:
            q = q.filter(StudyEvent.user_id == user_id)
        for row in q.order_by(StudyEvent.id.desc()).limit(200).all():
            payload = row.payload or {}
            if isinstance(payload, dict) and str(payload.get("_dedupe_key")) == dedupe_key:
                return row.id
    except Exception:  # pragma: no cover - 去重失败不影响正常写入
        logger.debug("study_events 去重查询失败 key=%s", dedupe_key, exc_info=True)
    return None


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def record(
    event_type: str,
    *,
    subject: Optional[str] = None,
    chapter_id: Optional[int] = None,
    knowledge_point_id: Optional[int] = None,
    question_id: Optional[int] = None,
    session_id: Optional[int] = None,
    is_correct: Optional[bool] = None,
    duration_seconds: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
    occurred_at: Optional[Any] = None,
    dedupe_key: Optional[str] = None,
    db: Optional[Session] = None,
    commit: bool = True,
) -> Optional[int]:
    """记录单条学习行为事件（**容错，绝不抛异常**）。

    这是埋点的统一主入口。任何异常都会被吞掉并记 warning，返回 ``None``，
    以保证调用方（如答题提交）的主流程永远不受埋点影响。

    Args:
        event_type: 事件类型，建议取 :data:`KNOWN_EVENT_TYPES` 之一。
        subject: 科目（已归一化更佳）。
        chapter_id: 章节 ID（指向 ``subject_chapters``；不存在时自动落 NULL）。
        knowledge_point_id: 知识点 ID。
        question_id: 题目 ID。
        session_id: 会话/批次 ID。
        is_correct: 是否答对（仅答题类事件有意义；答案不可信时传 None）。
        duration_seconds: 耗时（秒），负数按未记录处理。
        payload: 扩展载荷（任意可 JSON 序列化的字典）。
        user_id: 事件归属用户 ID（行级隔离）；None 表示不归属具体用户。
        occurred_at: 事件发生时间；缺省用当前 naive UTC。
        dedupe_key: 幂等键。相同 ``user_id + dedupe_key`` 只落一条，重复调用
            返回已存在行的 id。
        db: 可选 SQLAlchemy 会话。不传则自建短会话并在结束后关闭。
        commit: 是否立即提交。批量场景传 ``False`` 由调用方统一提交
            （仅当传入了 ``db`` 时有效）。

    Returns:
        成功时返回新行的 ``id``；幂等命中返回原行 id；失败返回 ``None``。
    """
    session, owns = _open_session(db)
    try:
        key = str(dedupe_key) if dedupe_key else None
        if key:
            existing = _find_by_dedupe_key(session, key, user_id)
            if existing is not None:
                return existing

        event = StudyEvent(
            event_type=str(event_type),
            subject=subject,
            chapter_id=_check_chapter_id(session, chapter_id),
            knowledge_point_id=knowledge_point_id,
            question_id=question_id,
            session_id=session_id,
            is_correct=is_correct,
            duration_seconds=_norm_duration(duration_seconds),
            payload=_payload_with_key(payload, key),
            occurred_at=occurred_at or utcnow(),
            user_id=user_id,
        )
        session.add(event)
        if commit or owns:
            session.commit()
            session.refresh(event)
        else:
            session.flush()
        return event.id
    except Exception as exc:
        # 埋点失败绝不影响主流程：只回滚本次埋点写入，记日志即可。
        logger.warning("study_events 埋点失败 event_type=%s: %s", event_type, exc)
        try:
            session.rollback()
        except Exception:  # pragma: no cover - 回滚失败也不再抛
            pass
        return None
    finally:
        if owns:
            try:
                session.close()
            except Exception:  # pragma: no cover
                pass


def record_event(
    db: Optional[Session],
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
    user_id: Optional[int] = None,
) -> Optional[int]:
    """兼容旧调用点的 ``db`` 前置签名，转发到 :func:`record`。"""
    return record(
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
        user_id=user_id,
        db=db,
        commit=commit,
    )


def record_events(
    db: Optional[Session],
    events: Iterable[Dict[str, Any]],
    *,
    commit: bool = True,
    user_id: Optional[int] = None,
) -> List[int]:
    """批量记录学习行为事件（**容错，绝不抛异常**）。

    每条事件形如::

        {
            "event_type": "answer",
            "subject": "数学",
            "question_id": 123,
            "is_correct": True,
            "duration_seconds": 30,
            "knowledge_point_id": 82,
            "dedupe_key": "answer:456",
        }

    单条构造失败会被跳过，不影响其余事件，也不影响主流程。
    """
    written: List[int] = []
    try:
        pending: List[StudyEvent] = []
        for item in events:
            if not item or not item.get("event_type"):
                continue
            try:
                pending.append(
                    StudyEvent(
                        event_type=str(item["event_type"]),
                        subject=item.get("subject"),
                        chapter_id=_check_chapter_id(db, item.get("chapter_id")) if db else None,
                        knowledge_point_id=item.get("knowledge_point_id"),
                        question_id=item.get("question_id"),
                        session_id=item.get("session_id"),
                        is_correct=item.get("is_correct"),
                        duration_seconds=_norm_duration(item.get("duration_seconds")),
                        payload=_payload_with_key(item.get("payload"), item.get("dedupe_key")),
                        occurred_at=item.get("occurred_at") or utcnow(),
                        user_id=user_id,
                    )
                )
            except Exception as exc:  # pragma: no cover - 单条脏数据跳过
                logger.warning("study_events 批量埋点单条构造失败，已跳过: %s", exc)
                continue

        if not pending:
            return written
        if db is None:
            # 批量场景必须有会话；没有就逐条走主入口，保证语义一致。
            return [
                rid
                for rid in (
                    record(
                        ev.event_type,
                        subject=ev.subject,
                        chapter_id=ev.chapter_id,
                        knowledge_point_id=ev.knowledge_point_id,
                        question_id=ev.question_id,
                        session_id=ev.session_id,
                        is_correct=ev.is_correct,
                        duration_seconds=ev.duration_seconds,
                        payload=ev.payload,
                        occurred_at=ev.occurred_at,
                        user_id=ev.user_id,
                    )
                    for ev in pending
                )
                if rid is not None
            ]

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
        logger.warning("study_events 批量埋点失败（已写 %d 条）：%s", len(written), exc)
        try:
            if db is not None:
                db.rollback()
        except Exception:  # pragma: no cover
            pass
        return []
    return written


# --------------------------------------------------------------------------- #
# 便捷入口（业务语义封装）
# --------------------------------------------------------------------------- #
def record_answer(
    *,
    question_id: int,
    is_correct: Optional[bool],
    duration_seconds: Optional[int] = None,
    subject: Optional[str] = None,
    knowledge_point_id: Optional[int] = None,
    chapter_id: Optional[int] = None,
    session_id: Optional[int] = None,
    user_id: Optional[int] = None,
    answer_record_id: Optional[int] = None,
    mode: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
    occurred_at: Optional[Any] = None,
) -> Optional[int]:
    """记录一次答题提交。

    ``answer_record_id`` 是幂等键：刷题提交先落 ``answer_records``，同一行
    只允许对应一条 ``study_events``（HTTP 重试 / 前端重复提交都不会写两条）。
    """
    extra: Dict[str, Any] = dict(payload or {})
    if mode:
        extra.setdefault("mode", mode)
    if answer_record_id is not None:
        extra.setdefault("answer_record_id", int(answer_record_id))
    return record(
        "answer",
        subject=subject,
        chapter_id=chapter_id,
        knowledge_point_id=knowledge_point_id,
        question_id=question_id,
        session_id=session_id,
        is_correct=is_correct,
        duration_seconds=duration_seconds,
        payload=extra,
        user_id=user_id,
        occurred_at=occurred_at,
        dedupe_key=f"answer:{answer_record_id}" if answer_record_id is not None else None,
        db=db,
    )


def record_review(
    item_type: str = "knowledge",
    *,
    item_id: Optional[int] = None,
    subject: Optional[str] = None,
    knowledge_point_id: Optional[int] = None,
    is_correct: Optional[bool] = None,
    duration_seconds: Optional[int] = None,
    user_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
    dedupe_key: Optional[str] = None,
) -> Optional[int]:
    """记录一次复习动作（知识点 / 错题 / 单词 / 卡片）。"""
    extra: Dict[str, Any] = dict(payload or {})
    extra.setdefault("item_type", str(item_type))
    if item_id is not None:
        extra.setdefault("item_id", int(item_id))
    return record(
        "review",
        subject=subject,
        knowledge_point_id=knowledge_point_id,
        is_correct=is_correct,
        duration_seconds=duration_seconds,
        payload=extra,
        user_id=user_id,
        dedupe_key=dedupe_key,
        db=db,
    )


def record_focus(
    *,
    duration_seconds: int,
    subject: Optional[str] = None,
    session_id: Optional[int] = None,
    user_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
    occurred_at: Optional[Any] = None,
) -> Optional[int]:
    """记录一次专注计时（真实学习时长，秒）。

    时长是「今日学习分钟数 / 热力图 / 连续天数」的唯一真实来源；
    不做任何"任务数 × 30 分钟"的估算。
    """
    extra: Dict[str, Any] = dict(payload or {})
    extra.setdefault("kind", "focus")
    return record(
        "focus",
        subject=subject,
        session_id=session_id,
        duration_seconds=duration_seconds,
        payload=extra,
        user_id=user_id,
        occurred_at=occurred_at,
        db=db,
    )


# --------------------------------------------------------------------------- #
# 知识点反查
# --------------------------------------------------------------------------- #
def resolve_knowledge_point_id(
    db: Session,
    question_id: Optional[int],
    *,
    prefer_primary: bool = True,
) -> Optional[int]:
    """经 ``question_knowledge_links`` 反查题目对应的主知识点 ID。

    优先取 ``role='primary'`` 的关联；若没有 primary，则退化为任意一条
    （按 id 升序取第一条，保证结果稳定、可复现）。查不到返回 ``None``。
    """
    if question_id is None:
        return None
    try:
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


# --------------------------------------------------------------------------- #
# 读侧：学习数据一览（统计唯一口径）
# --------------------------------------------------------------------------- #
def _streak_from_days(days: Iterable[date], *, today: Optional[date] = None) -> int:
    """连续学习天数：从今天（今天没学则从昨天）向前数连续出现的自然日。"""
    day_set = set(days)
    if not day_set:
        return 0
    cursor = today or local_today()
    if cursor not in day_set:
        # 今天还没学不算断签，从昨天起算
        cursor = cursor - timedelta(days=1)
    streak = 0
    while cursor in day_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def learning_summary(
    db: Session,
    *,
    user_id: Optional[int] = None,
    days: Optional[int] = None,
) -> Dict[str, Any]:
    """学习数据一览：业务表资产存量 + ``study_events`` 行为流水。

    这是设置页「学习数据一览」、仪表盘 KPI、热力图共用的读侧口径：

    - **资产存量**（tasks/flashcards/words/error_records/answer_records）——
      回答"我一共有多少东西"；
    - **行为流水**（study_events）——回答"我实际学了多少、学了几天"。

    两边都按 ``user_id`` 过滤（传 None 时保持全库口径，兼容脚本 / 未接线
    调用方）。时长只认 ``duration_seconds``，不做任何估算。

    Args:
        db: SQLAlchemy 会话。
        user_id: 归属用户 ID；None 表示不过滤。
        days: 只统计最近 N 天的事件（None = 全量历史）。业务表存量不受其影响。
    """
    from models import AnswerRecord, ErrorRecord, Flashcard, Task, Word

    today = local_today()
    since = None
    if days is not None and days > 0:
        since = local_window_for_day(today - timedelta(days=days - 1))[0]
    today_start = local_window_for_day(today)[0]

    def _u(model):
        return () if user_id is None else (model.user_id == user_id,)

    def _event_q(*cols):
        q = db.query(*cols)
        if user_id is not None:
            q = q.filter(StudyEvent.user_id == user_id)
        if since is not None:
            q = q.filter(StudyEvent.occurred_at >= since)
        return q

    # —— 行为流水 —— #
    events_total = int(_event_q(func.count(StudyEvent.id)).scalar() or 0)
    answer_events = int(
        _event_q(func.count(StudyEvent.id))
        .filter(StudyEvent.event_type == "answer")
        .scalar()
        or 0
    )
    review_events = int(
        _event_q(func.count(StudyEvent.id))
        .filter(StudyEvent.event_type.in_(("review", "flashcard", "word")))
        .scalar()
        or 0
    )
    focus_events = int(
        _event_q(func.count(StudyEvent.id))
        .filter(StudyEvent.event_type == "focus")
        .scalar()
        or 0
    )
    study_seconds = int(
        _event_q(func.coalesce(func.sum(StudyEvent.duration_seconds), 0)).scalar() or 0
    )
    today_seconds = int(
        _event_q(func.coalesce(func.sum(StudyEvent.duration_seconds), 0))
        .filter(StudyEvent.occurred_at >= today_start)
        .scalar()
        or 0
    )
    today_answers = int(
        _event_q(func.count(StudyEvent.id))
        .filter(StudyEvent.event_type == "answer", StudyEvent.occurred_at >= today_start)
        .scalar()
        or 0
    )
    correct_events = int(
        _event_q(func.count(StudyEvent.id))
        .filter(StudyEvent.event_type == "answer", StudyEvent.is_correct.is_(True))
        .scalar()
        or 0
    )

    # 活跃日：按北京自然日分桶，逐日去重
    day_expr = day_bucket_expr(StudyEvent.occurred_at, db)
    day_rows = _event_q(day_expr).group_by(day_expr).all()
    active_days = sorted(
        {
            d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
            for (d,) in day_rows
            if d is not None
        }
    )

    # —— 资产存量（业务表） —— #
    tasks_total = int(db.query(func.count(Task.id)).filter(*_u(Task)).scalar() or 0)
    tasks_pending = int(
        db.query(func.count(Task.id))
        .filter(Task.status != "done", *_u(Task))
        .scalar()
        or 0
    )
    flashcards_total = int(
        db.query(func.count(Flashcard.id)).filter(*_u(Flashcard)).scalar() or 0
    )
    words_total = int(db.query(func.count(Word.id)).filter(*_u(Word)).scalar() or 0)
    errors_total = int(
        db.query(func.count(ErrorRecord.id)).filter(*_u(ErrorRecord)).scalar() or 0
    )
    errors_active = int(
        db.query(func.count(ErrorRecord.id))
        .filter(ErrorRecord.status == "active", *_u(ErrorRecord))
        .scalar()
        or 0
    )
    answer_records_total = int(
        db.query(func.count(AnswerRecord.id)).filter(*_u(AnswerRecord)).scalar() or 0
    )

    return {
        "user_id": user_id,
        "days": days,
        "date_range": {
            "start": (today - timedelta(days=days - 1)).isoformat() if days else None,
            "end": today.isoformat(),
        },
        # 行为流水
        "study_events_total": events_total,
        "answer_events_total": answer_events,
        "review_events_total": review_events,
        "focus_events_total": focus_events,
        "correct_events_total": correct_events,
        "study_minutes": round(study_seconds / 60),          # 真实累计时长
        "today_study_minutes": round(today_seconds / 60),    # 今日真实时长
        "today_answers": today_answers,
        "active_days": len(active_days),
        "current_streak": _streak_from_days(active_days, today=today),
        "last_active_day": active_days[-1].isoformat() if active_days else None,
        # 资产存量
        "tasks_total": tasks_total,
        "tasks_pending": tasks_pending,
        "flashcards_total": flashcards_total,
        "words_total": words_total,
        "errors_total": errors_total,
        "errors_active": errors_active,
        "answer_records_total": answer_records_total,
        "caliber": {
            "study_minutes": "study_events.duration_seconds 求和 / 60（真实记录，不估算）",
            "current_streak": "study_events 按北京自然日去重后的连续天数（今天没学从昨天起算）",
            "assets": "tasks/flashcards/words/error_records/answer_records 按 user_id 计数",
        },
    }
