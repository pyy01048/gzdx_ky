# -*- coding: utf-8 -*-
"""复习进度追踪服务。

回答三个问题：
  1. 今天该复习哪些知识点？        → due_items()
  2. 复习一次后掌握度怎么变？      → apply_review()（SM-2 变体 + 掌握度衰减）
  3. 我复习到哪了 / 哪里最弱？     → progress_overview()

与既有模块的分工：
  - `services/review_scheduler.py` 是**只读查询**（到期卡片/错题/任务），
    不改任何数据；本模块负责**写**：留痕 review_records、回写 mastery。
  - `knowledge_points.mastery` 此前是"有字段、无写入路径"的死字段，
    本模块是它唯一的写入方。
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import KnowledgePoint, ErrorRecord, ReviewRecord
from services import kp_mastery, taxonomy
from utils.timeutil import utcnow  # 统一 naive UTC 时间规范（P0-4）


# 复习结果 → 质量分（对应 SM-2 的 0-5）
RESULT_GRADE = {
    "forgotten": 1,   # 完全忘了
    "fuzzy": 3,       # 想起来了但模糊
    "mastered": 5,    # 熟练掌握
}

# 复习结果 → 掌握度变化
MASTERY_DELTA = {
    "forgotten": -15,
    "fuzzy": 5,
    "mastered": 12,
}

# 掌握度衰减：距上次复习每超过 N 天，掌握度按比例衰减
DECAY_PER_DAY = 1.2


def _now() -> datetime.datetime:
    """当前时间（naive UTC），与 DB 的 DateTime 列保持同语义。"""
    return utcnow()


def next_review_at(
    *,
    review_count: int,
    ease_factor: float,
    interval: int,
    result: str,
) -> tuple[int, float, datetime.datetime]:
    """SM-2 变体调度。

    返回 (新间隔天数, 新 ease_factor, 下次复习时间)
    """
    grade = RESULT_GRADE.get(result, 3)
    ef = float(ease_factor or 2.5)
    interval = int(interval or 0)
    review_count = int(review_count or 0)

    # 更新 ease factor（SM-2 标准公式，下限 1.3）
    ef = ef + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    ef = max(1.3, round(ef, 2))

    if grade < 3:
        # 忘了：重置间隔
        new_interval = 1
    elif review_count == 0:
        new_interval = 1
    elif review_count == 1:
        new_interval = 3
    else:
        new_interval = max(1, int(round(interval * ef)))

    # 间隔上限：考研复习周期不超过 60 天
    new_interval = min(new_interval, 60)
    nxt = _now() + datetime.timedelta(days=new_interval)
    return new_interval, ef, nxt


def apply_review(
    db: Session,
    *,
    item_type: str,
    item_id: int,
    result: str,
    duration: int = 0,
    note: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """记录一次复习并回写掌握度 / 调度。

    支持 item_type：knowledge（知识点）/ error（错题）。
    """
    if item_type not in ("knowledge", "error"):
        raise ValueError(f"暂不支持的复习对象类型: {item_type}")
    if result not in RESULT_GRADE:
        raise ValueError(f"复习结果必须是 {list(RESULT_GRADE)} 之一")

    now = _now()
    payload: dict[str, Any] = {"item_type": item_type, "item_id": item_id, "result": result}

    if item_type == "knowledge":
        kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == item_id).first()
        if not kp:
            raise LookupError("知识点不存在")

        before = int(kp.mastery or 0)
        after = before + MASTERY_DELTA[result]
        # 先施加时间衰减
        if kp.last_review:
            days = (now - kp.last_review).days
            if days > 1:
                after -= int(days * DECAY_PER_DAY)
        after = max(0, min(100, after))

        interval, ef, nxt = next_review_at(
            review_count=kp.review_count or 0,
            ease_factor=kp.ease_factor or 2.5,
            interval=kp.interval or 0,
            result=result,
        )

        kp.mastery = after
        kp.review_count = (kp.review_count or 0) + 1
        kp.last_review = now
        kp.next_review = nxt
        kp.interval = interval
        kp.ease_factor = ef
        if result == "forgotten":
            kp.lapses = (kp.lapses or 0) + 1

        payload.update({
            "name": kp.name,
            "subject": kp.subject,
            "chapter": kp.chapter,
            "mastery_before": before,
            "mastery_after": after,
            "interval": interval,
            "_next_review_dt": nxt,
        })

    else:  # error
        err = db.query(ErrorRecord).filter(ErrorRecord.id == item_id).first()
        if not err:
            raise LookupError("错题不存在")

        # accuracy 在 ErrorRecord 里是 0-1 的小数（见 orchestrator 写入口径）
        before = int(round(float(err.accuracy or 0) * 100))
        after = 100 if result == "mastered" else (60 if result == "fuzzy" else 20)

        interval, ef, nxt = next_review_at(
            review_count=err.review_count or 0,
            ease_factor=2.5,
            interval=0,
            result=result,
        )
        err.review_count = (err.review_count or 0) + 1
        err.last_review = now
        err.next_review = nxt
        err.accuracy = round(after / 100, 2)

        payload.update({
            "subject": err.subject,
            "mastery_before": before,
            "mastery_after": after,
            "interval": interval,
            "_next_review_dt": nxt,
        })

    next_dt: datetime.datetime = payload.pop("_next_review_dt")

    rec = ReviewRecord(
        item_type=item_type,
        item_id=item_id,
        subject=payload.get("subject"),
        chapter=payload.get("chapter"),
        result=result,
        grade=RESULT_GRADE[result],
        mastery_before=payload.get("mastery_before", 0),
        mastery_after=payload.get("mastery_after", 0),
        duration=duration or 0,
        interval_after=payload.get("interval", 0),
        next_review=next_dt,
        note=note,
    )
    db.add(rec)

    if commit:
        db.commit()
        db.refresh(rec)

    # 学习行为埋点（2026-10）：复习提交此前完全不产事件，
    # 导致「复习」这一高频动作在学习科学/成长体系里没有流水。
    try:
        from services.study_event_service import record_event

        record_event(
            db,
            "review",
            subject=payload.get("subject"),
            knowledge_point_id=item_id if item_type == "knowledge" else None,
            payload={
                "item_type": item_type,
                "item_id": item_id,
                "result": result,
                "mastery_before": payload.get("mastery_before", 0),
                "mastery_after": payload.get("mastery_after", 0),
            },
        )
    except Exception:
        pass

    payload["review_id"] = rec.id
    payload["next_review"] = next_dt.isoformat()
    return payload


def due_items(
    db: Session,
    *,
    subject: str | None = None,
    limit: int = 50,
    include_new: bool = True,
) -> list[dict[str, Any]]:
    """今天该复习的知识点队列。

    "到期"包含三类：
      1. next_review 已过期
      2. 从未排期（next_review is null）
      3. 从未复习过（review_count == 0）—— 新建知识点首次排期在明天，
         但它今天就该进队列，否则新库建成后队列会一直显示 0 条。
    """
    from sqlalchemy import or_

    now = _now()
    q = db.query(KnowledgePoint)
    if subject:
        q = q.filter(KnowledgePoint.subject == taxonomy.normalize_subject(subject))

    conditions = [KnowledgePoint.next_review.is_(None), KnowledgePoint.next_review <= now]
    if include_new:
        # 新建但还没复习过的，无论排期在哪天都算"今日可复习"
        conditions.append(KnowledgePoint.review_count == 0)
        conditions.append(KnowledgePoint.review_count.is_(None))
    q = q.filter(or_(*conditions))

    rows = q.all()

    def sort_key(kp: KnowledgePoint):
        nr = kp.next_review
        # 从未复习的排最前（它们是"还没开始"的主体），其余按逾期天数
        if nr is None or not kp.review_count:
            return (-10000, int(kp.mastery or 0))
        days_late = (now - nr).days
        return (-days_late, int(kp.mastery or 0))

    rows.sort(key=sort_key)
    out = []
    for kp in rows[:limit]:
        out.append({
            "id": kp.id,
            "name": kp.name,
            "subject": kp.subject,
            "chapter": kp.chapter,
            "question_types": kp.question_types or taxonomy.question_types_of(kp.subject),
            "mastery": int(kp.mastery or 0),
            "exam_frequency": kp.exam_frequency or 0,
            "review_count": kp.review_count or 0,
            "last_review": kp.last_review.isoformat() if kp.last_review else None,
            "next_review": kp.next_review.isoformat() if kp.next_review else None,
            "is_new": kp.next_review is None or (kp.review_count or 0) == 0,
        })
    return out


def progress_overview(db: Session, *, subject: str | None = None) -> dict[str, Any]:
    """复习进度总览：整体掌握率、分科目、分章节、薄弱 TOP。

    掌握度三态口径（见 services/kp_mastery.py）：
      未学（无任何学习记录）不计入薄弱 —— 它们"还没开始"，不是"薄弱"。
    """
    now = _now()
    q = db.query(KnowledgePoint)
    if subject:
        q = q.filter(KnowledgePoint.subject == taxonomy.normalize_subject(subject))
    rows = q.all()
    learned = kp_mastery.learned_kp_ids(db)

    total = len(rows)
    counts = kp_mastery.tally(rows, learned)
    unlearned = counts["unlearned"]
    weak = counts["weak"]
    mastered = counts["mastered"]
    reviewed = sum(1 for k in rows if (k.review_count or 0) > 0)
    new_count = total - reviewed
    # due_count 只统计"已排期且逾期"的，不把新知识点算进来 ——
    # 否则新库建成时 due_count == total，"到期"这个指标就没意义了。
    due = sum(
        1 for k in rows
        if k.review_count and k.next_review is not None and k.next_review <= now
    )
    avg = round(counts["mastery_sum"] / total, 1) if total else 0.0
    # 已学平均掌握度：未学知识点不拉低均值（它们还没开始，谈不上掌握度）
    learned_n = total - unlearned
    learned_avg = round(counts["learned_mastery_sum"] / learned_n, 1) if learned_n else 0.0

    # 分科目
    by_subject: dict[str, dict[str, Any]] = {}
    for k in rows:
        s = taxonomy.normalize_subject(k.subject)
        d = by_subject.setdefault(s, {
            "subject": s, "total": 0, "mastery_sum": 0, "mastered": 0,
            "weak": 0, "unlearned": 0, "learned_mastery_sum": 0,
        })
        mastery = int(k.mastery or 0)
        state = kp_mastery.classify_state(mastery, k.id in learned)
        d["total"] += 1
        d["mastery_sum"] += mastery
        d[state] += 1
        if state != kp_mastery.STATE_UNLEARNED:
            d["learned_mastery_sum"] += mastery
    subject_stats = [
        {
            "subject": d["subject"],
            "total": d["total"],
            "avg_mastery": round(d["mastery_sum"] / d["total"], 1) if d["total"] else 0.0,
            "learned_avg_mastery": round(
                d["learned_mastery_sum"] / (d["total"] - d["unlearned"]), 1
            ) if d["total"] - d["unlearned"] else 0.0,
            "mastered": d["mastered"],
            "weak": d["weak"],
            "unlearned": d["unlearned"],
            "is_core": taxonomy.is_core(d["subject"]),
        }
        for d in sorted(by_subject.values(), key=lambda x: -x["total"])
    ]

    # 分章节（仅主线，章节多的科目才有意义）
    by_chapter: dict[str, dict[str, Any]] = {}
    for k in rows:
        if not k.chapter:
            continue
        key = f"{taxonomy.normalize_subject(k.subject)}|{k.chapter}"
        d = by_chapter.setdefault(key, {
            "subject": taxonomy.normalize_subject(k.subject),
            "chapter": k.chapter, "total": 0, "mastery_sum": 0,
        })
        d["total"] += 1
        d["mastery_sum"] += int(k.mastery or 0)
    chapter_stats = [
        {
            "subject": d["subject"],
            "chapter": d["chapter"],
            "total": d["total"],
            "avg_mastery": round(d["mastery_sum"] / d["total"], 1) if d["total"] else 0.0,
        }
        for d in by_chapter.values()
    ]
    chapter_stats.sort(key=lambda x: x["avg_mastery"])

    # 薄弱知识点 TOP10：只从**已学**知识点里挑 —— 未学的不算薄弱
    weak_top = sorted(
        (k for k in rows if k.id in learned),
        key=lambda k: (int(k.mastery or 0), -(k.exam_frequency or 0)),
    )[:10]

    # 近 7 天复习量
    week_ago = now - datetime.timedelta(days=7)
    recent_reviews = db.query(func.count(ReviewRecord.id)).filter(
        ReviewRecord.created_at >= week_ago
    ).scalar() or 0

    return {
        "total_knowledge_points": total,
        "reviewed_count": reviewed,
        "new_count": new_count,
        "due_count": due,
        "mastered_count": mastered,
        "weak_count": weak,
        "unlearned_count": unlearned,
        "avg_mastery": avg,
        "learned_avg_mastery": learned_avg,
        "completion_rate": round(reviewed / total * 100, 1) if total else 0.0,
        "mastered_rate": round(mastered / total * 100, 1) if total else 0.0,
        "reviews_last_7_days": recent_reviews,
        "by_subject": subject_stats,
        "weak_chapters": chapter_stats[:15],
        "weak_points": [
            {
                "id": k.id,
                "name": k.name,
                "subject": k.subject,
                "chapter": k.chapter,
                "mastery": int(k.mastery or 0),
                "exam_frequency": k.exam_frequency or 0,
                "review_count": k.review_count or 0,
                "lapses": k.lapses or 0,
                "state": kp_mastery.classify_state(k.mastery, k.id in learned),
            }
            for k in weak_top
        ],
    }


def review_history(
    db: Session,
    *,
    item_type: str | None = None,
    item_id: int | None = None,
    days: int = 30,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """复习留痕查询（用于"复习进度追踪"时间线）。"""
    since = _now() - datetime.timedelta(days=max(1, days))
    q = db.query(ReviewRecord).filter(ReviewRecord.created_at >= since)
    if item_type:
        q = q.filter(ReviewRecord.item_type == item_type)
    if item_id:
        q = q.filter(ReviewRecord.item_id == item_id)
    rows = q.order_by(ReviewRecord.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "item_type": r.item_type,
            "item_id": r.item_id,
            "subject": r.subject,
            "chapter": r.chapter,
            "result": r.result,
            "grade": r.grade,
            "mastery_before": r.mastery_before,
            "mastery_after": r.mastery_after,
            "interval_after": r.interval_after,
            "duration": r.duration,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
