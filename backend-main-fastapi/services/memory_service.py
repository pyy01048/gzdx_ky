# -*- coding: utf-8 -*-
"""三层可审计记忆服务（55 号方案 P0-1，DeepTutor DPM/Trace Forest 借鉴）。

设计：
  L1 ``memory_traces``     原始轨迹（append-only 事件快照）
  L2 ``memory_facts``      摘要事实（LLM 定期蒸馏，带 evidence 溯源）
  L3 ``memory_synthesis``  跨场景综合画像

核心原则：
  1. **埋点旁路容错**：写轨迹失败只记 warning，绝不抛异常影响主流程
     （与 study_event_service 同一纪律）。
  2. **可溯源**：L2 的 evidence 数组永远携带 trace_id，前端可点击回看原始
     上下文快照。
  3. **可纠错**：L2/L3 均保留 original_* 快照，用户纠正后权威值用
     corrected_* 字段。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import MemoryFact, MemorySynthesis, MemoryTrace
from utils.timeutil import utcnow

logger = logging.getLogger(__name__)

__all__ = [
    "TRACE_TYPES",
    "record_trace",
    "record_qa_trace",
    "record_grading_trace",
    "list_traces",
    "get_trace",
    "list_facts",
    "list_synthesis",
    "correct_fact",
    "correct_synthesis",
    "distill_facts",
    "build_profile",
    "evidence_from_trace",
]

#: 合法轨迹类型
TRACE_TYPES = frozenset({"qa", "tutoring", "grading", "study", "document", "feedback"})


def _now() -> Any:
    return utcnow()


def _open_session(db: Optional[Session]):
    """返回 ``(session, owns_session)``：复用传入会话或自建短生命周期会话。"""
    if db is not None:
        return db, False
    from database import SessionLocal

    return SessionLocal(), True


# --------------------------------------------------------------------------- #
# L1：原始轨迹写入
# --------------------------------------------------------------------------- #
def record_trace(
    *,
    user_id: Optional[int],
    trace_type: str,
    title: str,
    payload: Optional[Dict[str, Any]] = None,
    subject: Optional[str] = None,
    question_id: Optional[int] = None,
    document_id: Optional[int] = None,
    session_id: Optional[int] = None,
    occurred_at: Optional[Any] = None,
    db: Optional[Session] = None,
) -> Optional[int]:
    """写一条 L1 原始轨迹。任何失败都只记日志，不影响主流程。

    Returns:
        成功返回新轨迹 id；失败返回 ``None``（旁路容错）。
    """
    if trace_type not in TRACE_TYPES:
        trace_type = "qa"
    try:
        sess, owns = _open_session(db)
        try:
            tr = MemoryTrace(
                user_id=int(user_id) if user_id is not None else None,
                trace_type=trace_type,
                subject=subject,
                question_id=int(question_id) if question_id is not None else None,
                document_id=int(document_id) if document_id is not None else None,
                session_id=int(session_id) if session_id is not None else None,
                title=(title or "")[:200],
                payload=payload or {},
                occurred_at=occurred_at or _now(),
            )
            sess.add(tr)
            sess.commit()
            sess.refresh(tr)
            return tr.id
        finally:
            if owns:
                sess.close()
    except Exception as exc:  # noqa: BLE001 - 埋点旁路，不向上抛
        logger.warning("记忆轨迹写入失败（已旁路）: %s", exc)
        return None


def record_qa_trace(
    *,
    user_id: Optional[int],
    question: str,
    answer: str,
    citations: Optional[List[Dict[str, Any]]] = None,
    subject: Optional[str] = None,
    question_id: Optional[int] = None,
    session_id: Optional[int] = None,
    db: Optional[Session] = None,
) -> Optional[int]:
    """记录一次 AI 答疑/讲题为 L1 轨迹。"""
    payload = {
        "kind": "qa",
        "user_question": (question or "")[:2000],
        "ai_answer": (answer or "")[:4000],
        "citations": citations or [],
        "has_question_id": bool(question_id),
    }
    title = (question or "")[:80] or "AI 答疑"
    return record_trace(
        user_id=user_id,
        trace_type="qa",
        title=title,
        payload=payload,
        subject=subject,
        question_id=question_id,
        session_id=session_id,
        db=db,
    )


def record_grading_trace(
    *,
    user_id: Optional[int],
    question_id: Optional[int],
    subject: Optional[str],
    question_content: str,
    my_answer: str,
    score: Optional[float],
    evaluation: str,
    max_score: Optional[float] = None,
    db: Optional[Session] = None,
) -> Optional[int]:
    """记录一次主观题批改为 L1 轨迹（供 L2 蒸馏「薄弱点」）。"""
    payload = {
        "kind": "grading",
        "question_content": (question_content or "")[:1500],
        "my_answer": (my_answer or "")[:1500],
        "score": score,
        "max_score": max_score,
        "evaluation": (evaluation or "")[:1000],
    }
    title = f"主观题批改（{subject or '未知科目'}）"
    return record_trace(
        user_id=user_id,
        trace_type="grading",
        title=title,
        payload=payload,
        subject=subject,
        question_id=question_id,
        db=db,
    )


# --------------------------------------------------------------------------- #
# L1：查询
# --------------------------------------------------------------------------- #
def list_traces(
    db: Session,
    *,
    user_id: int,
    trace_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """列出用户的 L1 轨迹（按时间倒序）。"""
    q = db.query(MemoryTrace).filter(MemoryTrace.user_id == user_id)
    if trace_type:
        q = q.filter(MemoryTrace.trace_type == trace_type)
    rows = (
        q.order_by(MemoryTrace.occurred_at.desc(), MemoryTrace.id.desc())
        .limit(min(int(limit), 200))
        .offset(int(offset))
        .all()
    )
    return [_trace_dict(r) for r in rows]


def get_trace(db: Session, trace_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """按 id 取一条轨迹；user_id 非空时做归属校验。"""
    q = db.query(MemoryTrace).filter(MemoryTrace.id == int(trace_id))
    if user_id is not None:
        q = q.filter(MemoryTrace.user_id == int(user_id))
    r = q.first()
    return _trace_dict(r) if r else None


def _trace_dict(r: MemoryTrace) -> Dict[str, Any]:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "trace_type": r.trace_type,
        "subject": r.subject,
        "question_id": r.question_id,
        "document_id": r.document_id,
        "session_id": r.session_id,
        "title": r.title,
        "payload": r.payload or {},
        "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# --------------------------------------------------------------------------- #
# L2：摘要事实
# --------------------------------------------------------------------------- #
def evidence_from_trace(trace: Dict[str, Any], kind: str = "trace") -> Dict[str, Any]:
    """从轨迹 dict 构造 evidence 条目。"""
    return {
        "trace_id": trace["id"],
        "kind": kind,
        "snippet": (trace.get("title") or "")[:200],
        "occurred_at": trace.get("occurred_at"),
    }


def _facts_from_rows(rows: List[MemoryFact]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "user_id": r.user_id,
            "fact_type": r.fact_type,
            "subject": r.subject,
            "knowledge_point_id": r.knowledge_point_id,
            "kp_name": r.kp_name,
            "claim": r.claim,
            "confidence": r.confidence,
            "evidence": r.evidence or [],
            "source_layer": r.source_layer,
            "user_corrected": bool(r.user_corrected),
            "corrected_claim": r.corrected_claim,
            "corrected_at": r.corrected_at.isoformat() if r.corrected_at else None,
            "original_claim": r.original_claim,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return out


def list_facts(
    db: Session,
    *,
    user_id: int,
    fact_type: Optional[str] = None,
    subject: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """列出用户的 L2 摘要事实。"""
    q = db.query(MemoryFact).filter(MemoryFact.user_id == int(user_id))
    if fact_type:
        q = q.filter(MemoryFact.fact_type == fact_type)
    if subject:
        q = q.filter(MemoryFact.subject == subject)
    rows = (
        q.order_by(MemoryFact.updated_at.desc(), MemoryFact.id.desc())
        .limit(min(int(limit), 500))
        .offset(int(offset))
        .all()
    )
    return _facts_from_rows(rows)


def correct_fact(
    db: Session,
    *,
    user_id: int,
    fact_id: int,
    corrected_claim: str,
) -> Optional[Dict[str, Any]]:
    """用户纠正一条 L2 事实。保留原值快照，返回更新后的 dict。"""
    fact = (
        db.query(MemoryFact)
        .filter(MemoryFact.id == int(fact_id), MemoryFact.user_id == int(user_id))
        .first()
    )
    if not fact:
        return None
    if not fact.user_corrected:
        fact.original_claim = fact.claim  # 仅首次纠正保存原值
    fact.claim = corrected_claim.strip()
    fact.corrected_claim = corrected_claim.strip()
    fact.user_corrected = True
    fact.corrected_at = _now()
    fact.updated_at = _now()
    db.commit()
    db.refresh(fact)
    return _facts_from_rows([fact])[0]


# --------------------------------------------------------------------------- #
# L3：综合画像
# --------------------------------------------------------------------------- #
def _synth_from_rows(rows: List[MemorySynthesis]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "user_id": r.user_id,
            "synth_type": r.synth_type,
            "title": r.title,
            "summary": r.summary,
            "detail": r.detail or {},
            "fact_ids": r.fact_ids or [],
            "source_layer": r.source_layer,
            "user_corrected": bool(r.user_corrected),
            "corrected_summary": r.corrected_summary,
            "corrected_at": r.corrected_at.isoformat() if r.corrected_at else None,
            "original_summary": r.original_summary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return out


def list_synthesis(
    db: Session,
    *,
    user_id: int,
    synth_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """列出用户的 L3 综合画像。"""
    q = db.query(MemorySynthesis).filter(MemorySynthesis.user_id == int(user_id))
    if synth_type:
        q = q.filter(MemorySynthesis.synth_type == synth_type)
    rows = (
        q.order_by(MemorySynthesis.updated_at.desc(), MemorySynthesis.id.desc())
        .limit(min(int(limit), 200))
        .offset(int(offset))
        .all()
    )
    return _synth_from_rows(rows)


def correct_synthesis(
    db: Session,
    *,
    user_id: int,
    synthesis_id: int,
    corrected_summary: str,
) -> Optional[Dict[str, Any]]:
    """用户纠正一条 L3 综合结论。保留原值快照。"""
    syn = (
        db.query(MemorySynthesis)
        .filter(MemorySynthesis.id == int(synthesis_id), MemorySynthesis.user_id == int(user_id))
        .first()
    )
    if not syn:
        return None
    if not syn.user_corrected:
        syn.original_summary = syn.summary
    syn.summary = corrected_summary.strip()
    syn.corrected_summary = corrected_summary.strip()
    syn.user_corrected = True
    syn.corrected_at = _now()
    syn.updated_at = _now()
    db.commit()
    db.refresh(syn)
    return _synth_from_rows([syn])[0]


# --------------------------------------------------------------------------- #
# L2 蒸馏：从 L1 轨迹提取摘要事实（规则版，不依赖 LLM，保证离线可用）
# --------------------------------------------------------------------------- #
# 蒸馏规则（确定性，不调 LLM，避免幻觉与成本）：
#   * grading 轨迹且 score/max_score < 0.6 -> 薄弱点（subject 维度）
#   * qa 轨迹且 question 命中「为什么/不会/不懂/错」-> 疑问点（subject 维度）
#   * study/document 轨迹 -> 学习轨迹事实
# 每条事实带 evidence trace_id 溯源。
_DISTILL_WEAK_THRESHOLD = 0.6
_QUESTION_MARKERS = ("为什么", "怎么", "不会", "不懂", "错", "区别", "原理", "如何")


def distill_facts(
    db: Session,
    *,
    user_id: int,
    limit_traces: int = 200,
    min_confidence: float = 0.3,
) -> Dict[str, Any]:
    """从最近 ``limit_traces`` 条 L1 轨迹蒸馏 L2 事实（规则版）。

    Returns:
        ``{"created": n, "skipped": m, "facts": [...]}``
    """
    traces = (
        db.query(MemoryTrace)
        .filter(MemoryTrace.user_id == int(user_id))
        .order_by(MemoryTrace.occurred_at.desc(), MemoryTrace.id.desc())
        .limit(min(int(limit_traces), 500))
        .all()
    )
    created = 0
    skipped = 0
    new_facts: List[Dict[str, Any]] = []

    # 按 subject 聚合 grading 低分
    grading_by_subject: Dict[str, List[MemoryTrace]] = {}
    for tr in traces:
        if tr.trace_type == "grading":
            grading_by_subject.setdefault(tr.subject or "未知", []).append(tr)

    for subject, trs in grading_by_subject.items():
        low_scores = []
        for tr in trs:
            payload = tr.payload or {}
            score = payload.get("score")
            max_score = payload.get("max_score")
            try:
                ratio = float(score) / float(max_score) if max_score else None
            except (TypeError, ValueError):
                ratio = None
            if ratio is not None and ratio < _DISTILL_WEAK_THRESHOLD:
                low_scores.append((tr, ratio))
        if not low_scores:
            continue
        # 避免重复：同一 subject 已有 weakness 事实则跳过
        existing = (
            db.query(MemoryFact)
            .filter(
                MemoryFact.user_id == int(user_id),
                MemoryFact.fact_type == "weakness",
                MemoryFact.subject == subject,
            )
            .count()
        )
        if existing:
            skipped += 1
            continue
        worst = min(low_scores, key=lambda x: x[1])
        tr, ratio = worst
        evidence = [evidence_from_trace(_trace_dict(tr), kind="grading")]
        claim = (
            f"在「{subject}」的主观题作答中，近期批改得分率 {ratio:.0%}（低于 60%），"
            f"建议针对该科目加强答题规范与知识点梳理。"
        )
        fact = MemoryFact(
            user_id=int(user_id),
            fact_type="weakness",
            subject=subject,
            kp_name=None,
            claim=claim,
            confidence=round(max(min_confidence, 1 - ratio), 2),
            evidence=evidence,
            source_layer="l2_fact",
        )
        db.add(fact)
        created += 1
        new_facts.append({
            "fact_type": "weakness", "subject": subject, "claim": claim, "evidence": evidence,
        })

    # qa 疑问点蒸馏
    qa_subjects: Dict[str, List[MemoryTrace]] = {}
    for tr in traces:
        if tr.trace_type in ("qa", "tutoring"):
            qa_subjects.setdefault(tr.subject or "综合", []).append(tr)
    for subject, trs in qa_subjects.items():
        existing = (
            db.query(MemoryFact)
            .filter(
                MemoryFact.user_id == int(user_id),
                MemoryFact.fact_type == "weakness",
                MemoryFact.subject == subject,
            )
            .count()
        )
        if existing:
            skipped += 1
            continue
        marker_hits = []
        for tr in trs:
            payload = tr.payload or {}
            question = payload.get("user_question") or ""
            if any(m in question for m in _QUESTION_MARKERS):
                marker_hits.append(tr)
        if not marker_hits:
            continue
        tr = marker_hits[0]
        evidence = [evidence_from_trace(_trace_dict(tr), kind="qa")]
        claim = f"在「{subject}」答疑中多次出现理解性提问，可能对该科目概念存在薄弱环节。"
        fact = MemoryFact(
            user_id=int(user_id),
            fact_type="weakness",
            subject=subject,
            kp_name=None,
            claim=claim,
            confidence=0.4,
            evidence=evidence,
            source_layer="l2_fact",
        )
        db.add(fact)
        created += 1
        new_facts.append({
            "fact_type": "weakness", "subject": subject, "claim": claim, "evidence": evidence,
        })

    db.commit()
    return {"created": created, "skipped": skipped, "facts": new_facts}


# --------------------------------------------------------------------------- #
# L3：综合画像（规则版，从 L2 事实聚合）
# --------------------------------------------------------------------------- #
def build_profile(
    db: Session,
    *,
    user_id: int,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """生成/更新 L3 综合画像。

    规则版：聚合用户的 L2 事实，生成「薄弱点地图」画像。
    若已存在 profile 且 ``force=False``，直接返回现有画像。
    """
    existing = (
        db.query(MemorySynthesis)
        .filter(
            MemorySynthesis.user_id == int(user_id),
            MemorySynthesis.synth_type == "profile",
        )
        .order_by(MemorySynthesis.updated_at.desc())
        .first()
    )
    if existing and not force:
        return _synth_from_rows([existing])[0]

    facts = list_facts(db, user_id=int(user_id), limit=500)
    weaknesses = [f for f in facts if f["fact_type"] == "weakness"]
    strengths = [f for f in facts if f["fact_type"] == "strength"]

    detail = {
        "weakness_count": len(weaknesses),
        "strength_count": len(strengths),
        "weakness_subjects": sorted({f["subject"] for f in weaknesses if f.get("subject")}),
        "strength_subjects": sorted({f["subject"] for f in strengths if f.get("subject")}),
    }
    if weaknesses:
        summary = (
            "综合近期学习轨迹，你的薄弱环节集中在："
            + "、".join(detail["weakness_subjects"][:5])
            + "。建议优先安排针对性专项练习。"
        )
    else:
        summary = "暂无足够的 L2 事实生成综合画像，持续学习后将自动生成。"
    title = "学习者综合画像（薄弱点地图）"
    fact_ids = [f["id"] for f in weaknesses[:50]]

    if existing and force:
        existing.summary = summary
        existing.detail = detail
        existing.fact_ids = fact_ids
        existing.updated_at = _now()
        db.commit()
        db.refresh(existing)
        return _synth_from_rows([existing])[0]

    syn = MemorySynthesis(
        user_id=int(user_id),
        synth_type="profile",
        title=title,
        summary=summary,
        detail=detail,
        fact_ids=fact_ids,
        source_layer="l3_synthesis",
    )
    db.add(syn)
    db.commit()
    db.refresh(syn)
    return _synth_from_rows([syn])[0]


# --------------------------------------------------------------------------- #
# 统计（供前端记忆图谱面板）
# --------------------------------------------------------------------------- #
def memory_overview(db: Session, *, user_id: int) -> Dict[str, Any]:
    """记忆图谱总览：各层数量。"""
    trace_count = (
        db.query(MemoryTrace).filter(MemoryTrace.user_id == int(user_id)).count()
    )
    fact_count = (
        db.query(MemoryFact).filter(MemoryFact.user_id == int(user_id)).count()
    )
    synth_count = (
        db.query(MemorySynthesis).filter(MemorySynthesis.user_id == int(user_id)).count()
    )
    corrected_count = (
        db.query(MemoryFact)
        .filter(MemoryFact.user_id == int(user_id), MemoryFact.user_corrected.is_(True))
        .count()
    )
    return {
        "trace_count": trace_count,
        "fact_count": fact_count,
        "synthesis_count": synth_count,
        "corrected_count": corrected_count,
        "layers": {
            "l1_traces": trace_count,
            "l2_facts": fact_count,
            "l3_synthesis": synth_count,
        },
    }