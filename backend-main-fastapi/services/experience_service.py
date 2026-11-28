# -*- coding: utf-8 -*-
"""经验卡服务（已上岸校友分享 · R6）。

alumni 角色提交结构化经验卡（院校 / 专业 / 年份 / 分数 / 方法论 / 依据），
管理员审核通过后进 RAG 索引（source_type='experience'），供学弟学妹检索引用。

状态机：pending → approved / pending → rejected，不可逆。
幂等：approve_experience / reject_experience 对已处终态的卡重复调用为 no-op。
RAG 打标：审核通过时把经验卡内容写入 knowledge_chunks，doc_name 带
``[experience]#`` 前缀作为来源标记，检索侧可据此识别经验卡并展示引用溯源。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from utils.timeutil import utcnow

from models import ExperienceCard

logger = logging.getLogger(__name__)

#: 经验卡在 RAG 中的来源标记（写入 knowledge_chunks.doc_name 前缀）
RAG_SOURCE_TYPE = "experience"
#: 经验卡状态枚举
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class ExperienceCreate(BaseModel):
    """经验卡提交载荷（依据字段 ≥5 项由前端保证）。"""

    school_id: int
    major_id: int | None = None
    year: int
    score: int | None = None
    content: str
    methodology: str
    evidence: dict[str, Any] = {}


async def create_experience(db: Session, author_id: int, data: ExperienceCreate) -> ExperienceCard:
    """alumni 提交经验卡，初始状态 pending。

    重复提交同校同年由 UNIQUE(author_id, school_id, year) 约束拒绝，
    抛 ValueError 供路由层转 409。
    """
    card = ExperienceCard(
        author_id=author_id,
        school_id=data.school_id,
        major_id=data.major_id,
        year=data.year,
        score=data.score,
        content=data.content,
        methodology=data.methodology,
        evidence_json=data.evidence,
        status=STATUS_PENDING,
        created_at=utcnow(),
    )
    db.add(card)
    try:
        db.commit()
    except IntegrityError as exc:  # UNIQUE(author_id, school_id, year) 冲突
        db.rollback()
        raise ValueError("重复提交：同校同年已有经验卡") from exc
    db.refresh(card)
    return card


def _load_card_for_review(db: Session, card_id: int) -> ExperienceCard:
    """载入经验卡用于审核流程；不存在抛 LookupError。"""
    card = db.query(ExperienceCard).filter(ExperienceCard.id == card_id).first()
    if card is None:
        raise LookupError(f"经验卡 {card_id} 不存在")
    return card


async def approve_experience(db: Session, card_id: int, approver_id: int) -> ExperienceCard:
    """管理员审核通过：pending → approved，并触发 RAG 打标索引。

    幂等：已 approved 的卡重复调用为 no-op（不再重复写 RAG）。
    rejected 的卡不可再 approve（状态机不可逆），抛 ValueError。
    卡不存在抛 LookupError。
    """
    card = _load_card_for_review(db, card_id)
    if card.status == STATUS_APPROVED:
        return card  # 幂等 no-op
    if card.status == STATUS_REJECTED:
        raise ValueError("已驳回的经验卡不可再审核通过")

    card.status = STATUS_APPROVED
    card.approved_at = utcnow()
    card.approved_by = approver_id
    db.commit()
    db.refresh(card)

    _index_to_rag(db, card)
    return card


async def reject_experience(db: Session, card_id: int, approver_id: int) -> ExperienceCard:
    """管理员驳回：pending → rejected，不可逆。

    幂等：已 rejected 的卡重复调用为 no-op。
    approved 的卡不可再 reject，抛 ValueError。
    卡不存在抛 LookupError。
    """
    card = _load_card_for_review(db, card_id)
    if card.status == STATUS_REJECTED:
        return card  # 幂等 no-op
    if card.status == STATUS_APPROVED:
        raise ValueError("已通过的经验卡不可再驳回")

    card.status = STATUS_REJECTED
    card.approved_at = utcnow()
    card.approved_by = approver_id
    db.commit()
    db.refresh(card)
    return card


async def list_experiences(
    db: Session,
    school_id: int | None = None,
    status: str | None = None,
) -> list[ExperienceCard]:
    """经验卡列表查询。公开列表由路由层默认传 status='approved'。"""
    q = db.query(ExperienceCard)
    if school_id is not None:
        q = q.filter(ExperienceCard.school_id == school_id)
    if status is not None:
        q = q.filter(ExperienceCard.status == status)
    return q.order_by(ExperienceCard.created_at.desc()).all()


def _index_to_rag(db: Session, card: ExperienceCard) -> None:
    """把已审核经验卡写入 RAG 索引（knowledge_chunks），doc_name 带来源前缀。

    source_type='experience' 通过 doc_name 前缀 ``[experience]#`` 标记。
    失败旁路容错：RAG 索引失败不影响审核主链路（仅 log warning），
    与项目既有 kg_rag 等模块的旁路容错风格一致。
    """
    try:
        from services.kb_service import ingest_text

        doc_name = f"[{RAG_SOURCE_TYPE}]#{card.id} school={card.school_id} year={card.year}"
        text = f"{card.content}\n\n## 方法论\n{card.methodology}"
        ingest_text(
            db,
            doc_id=None,
            doc_name=doc_name,
            text=text,
            subject=RAG_SOURCE_TYPE,
            replace=True,
        )
    except Exception as exc:  # noqa: BLE001 - RAG 索引旁路容错，不阻断审核
        logger.warning("经验卡 %s 进 RAG 失败：%s", card.id, exc)
