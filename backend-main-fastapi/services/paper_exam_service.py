# -*- coding: utf-8 -*-
"""
P2-M4 真题模块：papers 年份/卷种轴 + 整卷模考与报告

核心功能:
1. 按年份/卷种筛选试卷列表
2. 开始整卷模考(创建 paper_attempts)
3. 提交作答并判分
4. 生成模考报告(逐题分析+薄弱点诊断)
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.models.questions import Paper, PaperQuestion, PaperAttempt, PaperAnswer, QuizQuestion
from utils.timeutil import utcnow

logger = logging.getLogger(__name__)


def list_papers_by_year_type(
    db: Session,
    *,
    subject: Optional[str] = None,
    year: Optional[int] = None,
    paper_type: Optional[str] = None,
    is_mock: Optional[bool] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """按年份/卷种筛选试卷列表。

    Returns:
        试卷列表，每项包含 id/title/year/paper_type/total_score/question_count/created_at
    """
    q = db.query(Paper)
    if subject:
        q = q.filter(Paper.subject == subject)
    if year:
        q = q.filter(Paper.year == year)
    if paper_type:
        q = q.filter(Paper.paper_type == paper_type)
    if is_mock is not None:
        q = q.filter(Paper.is_mock == is_mock)

    rows = q.order_by(Paper.year.desc().nulls_last(), Paper.created_at.desc()).limit(limit).all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "subject": p.subject,
            "year": p.year,
            "paper_type": p.paper_type,
            "is_mock": p.is_mock,
            "total_score": p.total_score,
            "question_count": len(p.questions),
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


def get_available_years(db: Session, subject: str) -> List[int]:
    """获取某科目下所有可用的真题年份。"""
    rows = (
        db.query(Paper.year)
        .filter(Paper.subject == subject, Paper.year.isnot(None))
        .distinct()
        .order_by(Paper.year.desc())
        .all()
    )
    return [r[0] for r in rows]


def get_available_paper_types(db: Session, subject: str, year: Optional[int] = None) -> List[str]:
    """获取某科目(可选年份)下所有可用的卷种。"""
    q = db.query(Paper.paper_type).filter(
        Paper.subject == subject,
        Paper.paper_type.isnot(None),
    )
    if year:
        q = q.filter(Paper.year == year)
    rows = q.distinct().order_by(Paper.paper_type).all()
    return [r[0] for r in rows]


def start_paper_attempt(
    db: Session, paper_id: int, *, user_id: Optional[int] = None
) -> Dict[str, Any]:
    """开始一份试卷的模考作答。

    Args:
        paper_id: 试卷 ID
        user_id: 作答归属用户；不写就会变成「谁都能读的历史」
    Returns:
        {"attempt_id", "paper_id", "status": "ongoing", "started_at"}
    """
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise ValueError(f"试卷不存在: id={paper_id}")

    attempt = PaperAttempt(
        paper_id=paper_id,
        user_id=user_id,
        status="ongoing",
        started_at=utcnow(),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    # 返回试卷详情+作答记录
    questions = (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper_id)
        .order_by(PaperQuestion.seq)
        .all()
    )

    return {
        "attempt_id": attempt.id,
        "paper_id": paper_id,
        "title": paper.title,
        "subject": paper.subject,
        "year": paper.year,
        "paper_type": paper.paper_type,
        "total_score": paper.total_score,
        "status": "ongoing",
        "started_at": attempt.started_at.isoformat(),
        "questions": [
            {
                "seq": q.seq,
                "question_id": q.question_id,
                "content": q.content,
                "options": q.options,
                "question_type": q.question_type,
                "difficulty": q.difficulty,
                "score": q.score,
            }
            for q in questions
        ],
    }


def submit_paper_attempt(
    db: Session,
    attempt_id: int,
    answers: List[Dict[str, Any]],
    *,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """提交试卷作答并判分。

    Args:
        attempt_id: 作答记录 ID
        answers: 逐题作答列表 [{"seq": 1, "user_answer": "A", "time_spent_seconds": 60}, ...]
        user_id: 归属用户；传了就只允许提交本人的作答
    Returns:
        模考报告数据
    """
    q = db.query(PaperAttempt).filter(PaperAttempt.id == attempt_id)
    if user_id is not None:
        q = q.filter(PaperAttempt.user_id == user_id)
    attempt = q.first()
    if not attempt:
        raise ValueError(f"作答记录不存在: id={attempt_id}")
    if attempt.status != "ongoing":
        raise ValueError(f"作答状态异常: {attempt.status}")

    paper = db.query(Paper).filter(Paper.id == attempt.paper_id).first()
    if not paper:
        raise ValueError("关联试卷不存在")

    # 获取试卷题目快照
    paper_questions = (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper.id)
        .order_by(PaperQuestion.seq)
        .all()
    )
    pq_by_seq = {q.seq: q for q in paper_questions}

    # 判分并保存逐题作答
    total_score = 0.0
    correct_count = 0
    question_stats: Dict[int, Dict[str, Any]] = {}  # question_id -> {scores[], attempts}

    for ans_item in answers:
        seq = ans_item.get("seq")
        user_answer = ans_item.get("user_answer", "")
        time_spent = ans_item.get("time_spent_seconds")

        pq = pq_by_seq.get(seq)
        if not pq:
            continue

        # 客观题自动判分
        is_correct = None
        score = 0.0
        if pq.question_type in ("single", "multiple", "judge"):
            is_correct = (user_answer.strip().upper() == (pq.answer or "").strip().upper())
            score = pq.score if is_correct else 0.0
            if is_correct:
                correct_count += 1

        # 保存作答记录
        pa = PaperAnswer(
            attempt_id=attempt_id,
            question_id=pq.question_id,
            paper_question_seq=seq,
            user_answer=user_answer,
            is_correct=is_correct,
            score=score,
            time_spent_seconds=time_spent,
        )
        db.add(pa)
        total_score += score

        # 统计该题历史表现
        if pq.question_id:
            if pq.question_id not in question_stats:
                question_stats[pq.question_id] = {"scores": [], "attempts": 0}
            question_stats[pq.question_id]["scores"].append(score)
            question_stats[pq.question_id]["attempts"] += 1

    # 更新作答记录
    submitted_at = utcnow()
    duration = int((submitted_at - attempt.started_at).total_seconds())
    attempt.submitted_at = submitted_at
    attempt.status = "submitted"
    attempt.total_score = total_score
    attempt.correct_count = correct_count
    attempt.duration_seconds = duration
    db.commit()

    # 更新题目热度统计
    for qid, stats in question_stats.items():
        pq_obj = db.query(PaperQuestion).filter(
            PaperQuestion.question_id == qid,
            PaperQuestion.paper_id == paper.id,
        ).first()
        if pq_obj:
            old_avg = pq_obj.avg_score or 0.0
            old_count = pq_obj.attempt_count or 0
            new_scores = stats["scores"]
            new_total = old_avg * old_count + sum(new_scores)
            new_count = old_count + len(new_scores)
            pq_obj.avg_score = new_total / new_count if new_count > 0 else 0.0
            pq_obj.attempt_count = new_count
    db.commit()

    # 生成报告
    report = generate_paper_report(db, attempt_id, user_id=user_id)
    report["summary"] = {
        "attempt_id": attempt_id,
        "paper_id": paper.id,
        "title": paper.title,
        "total_score": total_score,
        "full_score": paper.total_score,
        "correct_count": correct_count,
        "total_questions": len(paper_questions),
        "accuracy": round(correct_count / len(paper_questions) * 100, 1) if paper_questions else 0.0,
        "duration_seconds": duration,
        "submitted_at": submitted_at.isoformat(),
    }
    return report


def generate_paper_report(
    db: Session, attempt_id: int, *, user_id: Optional[int] = None
) -> Dict[str, Any]:
    """生成试卷作答报告。

    Returns:
        {
            "summary": {...},
            "question_analysis": [...],  # 逐题分析
            "weak_points": [...],  # 薄弱知识点
            "time_analysis": {...},  # 时间分配分析
        }
    """
    q = db.query(PaperAttempt).filter(PaperAttempt.id == attempt_id)
    if user_id is not None:
        q = q.filter(PaperAttempt.user_id == user_id)
    attempt = q.first()
    if not attempt:
        raise ValueError(f"作答记录不存在: id={attempt_id}")

    paper = db.query(Paper).filter(Paper.id == attempt.paper_id).first()
    answers = (
        db.query(PaperAnswer)
        .filter(PaperAnswer.attempt_id == attempt_id)
        .order_by(PaperAnswer.paper_question_seq)
        .all()
    )

    # 逐题分析
    question_analysis = []
    weak_kps: Dict[str, int] = {}  # knowledge_point -> error_count

    for ans in answers:
        pq = (
            db.query(PaperQuestion)
            .filter(
                PaperQuestion.paper_id == paper.id,
                PaperQuestion.seq == ans.paper_question_seq,
            )
            .first()
        )
        if not pq:
            continue

        # 获取原题知识点
        kps = []
        if ans.question_id:
            from core.models.questions import QuestionKnowledgeLink
            links = (
                db.query(QuestionKnowledgeLink)
                .filter(QuestionKnowledgeLink.question_id == ans.question_id)
                .all()
            )
            kps = [link.knowledge_point_id for link in links]

        item = {
            "seq": ans.paper_question_seq,
            "question_id": ans.question_id,
            "content": pq.content[:50] + "..." if pq.content and len(pq.content) > 50 else pq.content,
            "question_type": pq.question_type,
            "difficulty": pq.difficulty,
            "score": ans.score,
            "full_score": pq.score,
            "is_correct": ans.is_correct,
            "user_answer": ans.user_answer,
            "correct_answer": pq.answer,
            "time_spent_seconds": ans.time_spent_seconds,
            "knowledge_points": kps,
        }
        question_analysis.append(item)

        # 统计薄弱知识点
        if ans.is_correct is False:
            for kp_id in kps:
                weak_kps[kp_id] = weak_kps.get(kp_id, 0) + 1

    # 薄弱知识点 TOP5
    from core.models.knowledge import KnowledgePoint
    weak_points = []
    for kp_id, error_count in sorted(weak_kps.items(), key=lambda x: -x[1])[:5]:
        kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
        if kp:
            weak_points.append({
                "id": kp.id,
                "name": kp.name,
                "subject": kp.subject,
                "chapter": kp.chapter,
                "error_count": error_count,
            })

    # 时间分配分析
    times = [ans.time_spent_seconds for ans in answers if ans.time_spent_seconds]
    time_analysis = {
        "total_seconds": sum(times) if times else 0,
        "avg_seconds_per_question": round(sum(times) / len(times)) if times else 0,
        "max_seconds": max(times) if times else 0,
        "min_seconds": min(times) if times else 0,
    }

    return {
        "question_analysis": question_analysis,
        "weak_points": weak_points,
        "time_analysis": time_analysis,
    }


def get_attempt_history(
    db: Session,
    paper_id: Optional[int] = None,
    limit: int = 20,
    *,
    user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """获取历史作答记录（传 user_id 时只返回本人的）。"""
    q = db.query(PaperAttempt).filter(PaperAttempt.status == "submitted")
    if paper_id:
        q = q.filter(PaperAttempt.paper_id == paper_id)
    if user_id is not None:
        q = q.filter(PaperAttempt.user_id == user_id)

    rows = q.order_by(PaperAttempt.submitted_at.desc()).limit(limit).all()
    return [
        {
            "attempt_id": a.id,
            "paper_id": a.paper_id,
            "total_score": a.total_score,
            "correct_count": a.correct_count,
            "duration_seconds": a.duration_seconds,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
        }
        for a in rows
    ]
