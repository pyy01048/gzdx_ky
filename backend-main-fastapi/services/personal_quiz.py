# -*- coding: utf-8 -*-
"""个人题库资产口径与逐用户答题状态。"""

from __future__ import annotations

import datetime
import re
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from models import QuizQuestion, QuizQuestionSet, QuizQuestionSetItem, QuizQuestionState


def membership_ids(user_id: int):
    """本人题库中的题目 ID 子查询（不依赖题库名称或资源是否存在）。"""
    return (
        select(QuizQuestionSetItem.question_id)
        .join(QuizQuestionSet, QuizQuestionSet.id == QuizQuestionSetItem.set_id)
        .where(QuizQuestionSet.user_id == user_id)
    )


def personal_asset_expr(user_id: int):
    """全部题目=本人未软删自建题 ∪ 本人题库成员中的公共题，按主键自然去重。"""
    return or_(
        and_(
            QuizQuestion.owner_user_id == user_id,
            QuizQuestion.is_available.is_(True),
            QuizQuestion.is_junk.is_(False),
        ),
        and_(
            QuizQuestion.owner_user_id.is_(None),
            QuizQuestion.id.in_(membership_ids(user_id)),
            or_(QuizQuestion.is_junk.is_(False), QuizQuestion.is_junk.is_(None)),
        ),
    )


def asset_query(db: Session, user_id: int):
    """个人资产查询；关联唯一状态行，无记录时读取侧回落 unmastered。"""
    return (
        db.query(QuizQuestion, QuizQuestionState)
        .outerjoin(
            QuizQuestionState,
            and_(
                QuizQuestionState.user_id == user_id,
                QuizQuestionState.question_id == QuizQuestion.id,
            ),
        )
        .filter(personal_asset_expr(user_id))
    )


def mastery_expr(user_id: int):
    return func.coalesce(
        select(QuizQuestionState.mastery_state)
        .where(
            QuizQuestionState.user_id == user_id,
            QuizQuestionState.question_id == QuizQuestion.id,
        )
        .correlate(QuizQuestion)
        .scalar_subquery(),
        "unmastered",
    )


def mastery_summary(query, user_id: int) -> dict[str, int]:
    row = query.with_entities(
        func.count(QuizQuestion.id),
        func.sum(case((mastery_expr(user_id) == "mastered", 1), else_=0)),
    ).one()
    total = int(row[0] or 0)
    mastered = int(row[1] or 0)
    return {"total": total, "mastered": mastered, "unmastered": total - mastered}


def _insert_for(db: Session, model):
    return sqlite_insert(model) if db.get_bind().dialect.name == "sqlite" else pg_insert(model)


def add_membership(db: Session, bank_id: int, question_id: int) -> None:
    db.execute(
        _insert_for(db, QuizQuestionSetItem)
        .values(set_id=bank_id, question_id=question_id)
        .on_conflict_do_nothing(index_elements=["set_id", "question_id"])
    )


def get_or_create_state(db: Session, user_id: int, question_id: int) -> QuizQuestionState:
    db.execute(
        _insert_for(db, QuizQuestionState)
        .values(user_id=user_id, question_id=question_id, mastery_state="unmastered", attempts=0)
        .on_conflict_do_nothing(index_elements=["user_id", "question_id"])
    )
    return db.get(QuizQuestionState, (user_id, question_id))


def record_answer_state(
    db: Session,
    user_id: int | None,
    question: QuizQuestion,
    correct: bool | None,
    low_confidence: bool,
) -> None:
    """真实作答留痕；仅本人自建或本人题库成员可更新。

    未自评/低置信只增加流水，不改变掌握状态；手动切换不调用此函数。
    """
    if user_id is None:
        return
    is_asset = (
        db.query(QuizQuestion.id)
        .filter(
            QuizQuestion.id == question.id,
            personal_asset_expr(user_id),
        )
        .first()
    )
    if is_asset is None:
        return
    now = datetime.datetime.now(datetime.UTC)
    last_result = None if low_confidence else correct
    next_mastery = "mastered" if correct else "unmastered"
    db.execute(
        _insert_for(db, QuizQuestionState)
        .values(
            user_id=user_id,
            question_id=question.id,
            mastery_state=next_mastery if correct is not None else "unmastered",
            attempts=1,
            last_result=last_result,
            last_answered_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "question_id"],
            set_={
                "attempts": QuizQuestionState.attempts + 1,
                "last_result": last_result,
                "last_answered_at": now,
                "updated_at": now,
                "mastery_state": case(
                    (correct is not None, next_mastery),
                    else_=QuizQuestionState.mastery_state,
                ),
            },
        )
    )


_OPTION_PREFIX = re.compile(r"^\s*(?:[-*]\s*)?\(?([A-Za-z])\)?\s*[.、．:：)]\s*(.*)$")


def normalize_personal_options(options: Any, question_type: str):
    """个人题选项统一为 A–H 单字符 key；拒绝重复 key，不静默重排对象 key。"""
    if options is None or options == []:
        if question_type in ("single", "multiple"):
            raise ValueError("选择题必须提供选项")
        if question_type == "judge":
            return [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
        return None
    if not isinstance(options, list):
        raise ValueError("选项格式不正确")

    canonical: list[dict[str, str]] = []
    explicit_keys: set[str] = set()
    for index, option in enumerate(options):
        key: str
        text: Any
        if isinstance(option, str):
            match = _OPTION_PREFIX.match(option)
            if match:
                key, text = match.group(1).upper(), match.group(2)
            else:
                key, text = chr(65 + index), option
        elif isinstance(option, dict):
            key = str(option.get("key") or "").strip().upper()
            text = option.get("text")
            if key:
                explicit_keys.add(key)
        else:
            raise ValueError("选项格式不正确")

        if key not in "ABCDEFGH" or len(key) != 1:
            raise ValueError("选项 key 必须为 A–H 的单字符")
        if key in explicit_keys and any(item["key"] == key for item in canonical):
            raise ValueError("选项 key 重复")
        # 字符串列表未显式编号时按顺序补 key；若与显式 key 冲突也必须拒绝。
        if any(item["key"] == key for item in canonical):
            raise ValueError("选项 key 重复")
        text_value = str(text).strip() if text is not None else ""
        if not text_value:
            raise ValueError("选项内容不能为空")
        canonical.append({"key": key, "text": text_value})

    if question_type in ("single", "multiple") and len(canonical) < 2:
        raise ValueError("选择题至少需要两个选项")
    if question_type not in ("single", "multiple", "judge"):
        if canonical:
            raise ValueError("主观题不能配置选项")
        return None
    if question_type == "judge":
        if {item["key"]: item["text"] for item in canonical} != {"A": "正确", "B": "错误"}:
            raise ValueError("判断题选项应为 A正确、B错误")
    return canonical


_JUDGE_ANSWERS = {
    "对": "A",
    "正确": "A",
    "√": "A",
    "T": "A",
    "TRUE": "A",
    "错": "B",
    "错误": "B",
    "×": "B",
    "F": "B",
    "FALSE": "B",
}


def normalize_choice_answer(answer: Any, question_type: str, option_keys=None, *, strict: bool = True) -> str:
    value = str(answer or "").strip().upper()
    keys = {str(key).upper() for key in (option_keys or [])}
    if question_type == "judge":
        normalized = _JUDGE_ANSWERS.get(value, value)
        if normalized not in ("A", "B"):
            if strict:
                raise ValueError("判断题答案应为正确或错误")
            return value
    elif question_type == "multiple":
        compact = re.sub(r"[\s,，、;；/]+", "", value)
        if not re.fullmatch(r"[A-H]+", compact):
            if strict:
                raise ValueError("多选答案格式不正确")
            return compact
        normalized = "".join(sorted(set(compact)))
    else:
        normalized = value
    if strict and keys:
        answer_keys = normalized if question_type == "multiple" else (normalized,)
        if any(key not in keys for key in answer_keys):
            raise ValueError("答案不在选项集合中")
    return normalized


def normalize_personal_answer(answer: Any, question_type: str, options) -> str:
    if question_type not in ("single", "multiple", "judge"):
        return str(answer).strip()
    keys = [item["key"] for item in (options or [])]
    return normalize_choice_answer(answer, question_type, keys)
