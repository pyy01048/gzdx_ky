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
import logging
from typing import Any

from models import ErrorKnowledgeLink, ErrorRecord, KnowledgePoint, ReviewRecord, ReviewSchedule, StudyEvent
from sqlalchemy import func
from sqlalchemy.orm import Session
from utils.timeutil import (  # 统一 naive UTC 时间规范（P0-4）
    local_today,
    local_window_for_day,
    utcnow,
)

from services import kp_mastery, taxonomy

# 复习结果 → 质量分（对应 SM-2 的 0-5）
RESULT_GRADE = {
    "forgotten": 1,  # 完全忘了
    "fuzzy": 3,  # 想起来了但模糊
    "mastered": 5,  # 熟练掌握
}

# 复习结果 → 掌握度变化
MASTERY_DELTA = {
    "forgotten": -15,
    "fuzzy": 5,
    "mastered": 12,
}

# 三档结果 → PG review_result ENUM 标签
# 历史坑：这里原来直接把 forgotten/fuzzy/mastered 写进 review_records.result，
# 而库里的 ENUM 只有 again/hard/good/easy —— PG 上每次复习提交都 500。
RESULT_ENUM = {
    "forgotten": "again",
    "fuzzy": "hard",
    "mastered": "good",
}

# 掌握度衰减：距上次复习每超过 N 天，掌握度按比例衰减
DECAY_PER_DAY = 1.2


def _now() -> datetime.datetime:
    """当前时间（naive UTC），与 DB 的 DateTime 列保持同语义。"""
    return utcnow()


def _naive_utc(dt: datetime.datetime | None) -> datetime.datetime | None:
    """review_schedules 的物理列是 TIMESTAMPTZ（050/102 分片），psycopg 读回
    aware datetime；本模块内部统一 naive UTC 口径，混算会抛
    TypeError: can't subtract offset-naive and offset-aware datetimes。"""
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


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
    user_id: int | None = None,
) -> dict[str, Any]:
    """记录一次复习并回写掌握度 / 调度。

    支持 item_type：knowledge（知识点）/ error（错题）。

    B4 行级隔离：``user_id`` 传入时——
    - error：校验错题归属（他人错题按不存在处理），镜像只写本人错题行；
    - knowledge：个人排程权威在 review_schedules 用户行，**不再回写全局
      KnowledgePoint 的任何调度/掌握度字段**（那是内容元数据，不许被个人
      复习改写）；SM-2 兼容状态从本人调度行读，掌握度从本人复习留痕推。
    不传（默认 None）保持旧的全局口径，兼容尚未接线的调用方。
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

        if user_id is not None:
            # —— 用户口径：读本人调度行 + 本人留痕，全局 KP 只读不写 ——
            sched = (
                db.query(ReviewSchedule)
                .filter(
                    ReviewSchedule.user_id == user_id,
                    ReviewSchedule.item_type == "knowledge_point",
                    ReviewSchedule.item_id == item_id,
                )
                .first()
            )
            last_rec = (
                db.query(ReviewRecord)
                .filter(
                    ReviewRecord.user_id == user_id,
                    ReviewRecord.item_type == "knowledge",
                    ReviewRecord.item_id == item_id,
                )
                .order_by(ReviewRecord.created_at.desc())
                .first()
            )
            before = int(last_rec.mastery_after or 0) if last_rec else 0
            after = before + MASTERY_DELTA[result]
            last_dt = _naive_utc(sched.last_reviewed_at if sched else None) or (
                _naive_utc(last_rec.created_at) if last_rec else None
            )
            if last_dt:
                days = (now - last_dt).days
                if days > 1:
                    after -= int(days * DECAY_PER_DAY)
            after = max(0, min(100, after))

            interval, ef, nxt = next_review_at(
                review_count=(sched.repetitions if sched else 0) or 0,
                ease_factor=(sched.ease_factor if sched else 2.5) or 2.5,
                interval=(sched.interval_days if sched else 0) or 0,
                result=result,
            )
            payload.update(
                {
                    "name": kp.name,
                    "subject": kp.subject,
                    "chapter": kp.chapter,
                    "mastery_before": before,
                    "mastery_after": after,
                    "interval": interval,
                    "_next_review_dt": nxt,
                }
            )
        else:
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

            payload.update(
                {
                    "name": kp.name,
                    "subject": kp.subject,
                    "chapter": kp.chapter,
                    "mastery_before": before,
                    "mastery_after": after,
                    "interval": interval,
                    "_next_review_dt": nxt,
                }
            )

    else:  # error
        err = db.query(ErrorRecord).filter(ErrorRecord.id == item_id).first()
        # 他人错题按不存在处理（404 而非 403，避免泄露他人数据存在性）
        if not err or (user_id is not None and err.user_id != user_id):
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

        payload.update(
            {
                "subject": err.subject,
                "mastery_before": before,
                "mastery_after": after,
                "interval": interval,
                "_next_review_dt": nxt,
            }
        )

    next_dt: datetime.datetime = payload.pop("_next_review_dt")

    rec = ReviewRecord(
        item_type=item_type,
        item_id=item_id,
        subject=payload.get("subject"),
        chapter=payload.get("chapter"),
        result=RESULT_ENUM[result],
        grade=RESULT_GRADE[result],
        mastery_before=payload.get("mastery_before", 0),
        mastery_after=payload.get("mastery_after", 0),
        duration=duration or 0,
        interval_after=payload.get("interval", 0),
        next_review=next_dt,
        note=note,
        user_id=user_id,
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
            user_id=user_id,
        )
    except Exception as _exc:  # noqa: BLE001
        # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
        # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
        logging.getLogger(__name__).warning("%s 处异常已忽略（不阻塞主流程）: %s", __name__, str(_exc)[:200])

    # 掌握度重算（2026-10-16 修复链路缺口）：
    # mastery 是派生列，只在 knowledge_points 被 UPDATE 时才由触发器刷新。
    # 只写 review_records 不会刷 —— 用户复习完看到掌握度不动就是这个原因。
    # 注意 seq：必须在 commit 之后、且用 SQL 自赋值触发（ORM 赋同值不发 UPDATE）。
    # 用户口径下不触发：touch 会按全库答题/复习记录重算全局 mastery，
    # 个人复习不得改写全局内容元数据（B4 隔离铁律）。
    if item_type == "knowledge" and user_id is None:
        try:
            kp_mastery.touch_mastery(db, [item_id])
        except Exception as _exc:  # noqa: BLE001
            # 不静默：刷新失败会让"掌握度不动"复现，且极难定位
            logging.getLogger(__name__).warning("复习后掌握度重算失败 kp=%s: %s", item_id, str(_exc)[:160])

    payload["review_id"] = rec.id
    payload["next_review"] = next_dt.isoformat()
    return payload


def due_items(
    db: Session,
    *,
    subject: str | None = None,
    limit: int = 50,
    include_new: bool = True,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """今天该复习的队列。

    用户口径（user_id 传入时，B4 隔离）：
      队列 = 本人 review_schedules 行（knowledge_point / error_record）中
      next_review_at 已到期或未排期的，join 内容表取展示字段；
      include_new=True 时补充「新知识点」——只限**本人接触过**（本人
      study_events 或本人错题关联）且尚无调度行的知识点。零数据新用户
      必须得到空队列，绝不能把全库知识点当"新"塞进来。
      item 新增 item_type 字段（knowledge/error），其余键保持旧形状。

    旧全局口径（user_id=None，兼容未接线调用方）："到期"包含三类：
      1. next_review 已过期
      2. 从未排期（next_review is null）
      3. 从未复习过（review_count == 0）—— 新建知识点首次排期在明天，
         但它今天就该进队列，否则新库建成后队列会一直显示 0 条。
    """
    from sqlalchemy import or_

    now = _now()
    norm_subject = taxonomy.normalize_subject(subject) if subject else None

    if user_id is not None:
        return _due_items_user(
            db, now=now, user_id=user_id, norm_subject=norm_subject, limit=limit, include_new=include_new
        )

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
        out.append(
            {
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
            }
        )
    return out


def _due_items_user(
    db: Session,
    *,
    now: datetime.datetime,
    user_id: int,
    norm_subject: str | None,
    limit: int,
    include_new: bool,
) -> list[dict[str, Any]]:
    """用户口径到期队列（见 due_items 文档）。"""
    from sqlalchemy import or_

    sched_rows = (
        db.query(ReviewSchedule)
        .filter(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.item_type.in_(["knowledge_point", "error_record"]),
            or_(ReviewSchedule.next_review_at.is_(None), ReviewSchedule.next_review_at <= now),
        )
        .all()
    )
    kp_ids = [r.item_id for r in sched_rows if r.item_type == "knowledge_point"]
    err_ids = [r.item_id for r in sched_rows if r.item_type == "error_record"]
    kps = {k.id: k for k in db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(kp_ids)).all()} if kp_ids else {}
    errs = {e.id: e for e in db.query(ErrorRecord).filter(ErrorRecord.id.in_(err_ids)).all()} if err_ids else {}

    entries: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for r in sched_rows:
        nr = _naive_utc(r.next_review_at)
        last_dt = _naive_utc(r.last_reviewed_at)
        days_late = (now - nr).days if nr else 0
        if r.item_type == "knowledge_point":
            kp = kps.get(r.item_id)
            if not kp or (norm_subject and taxonomy.normalize_subject(kp.subject) != norm_subject):
                continue
            mastery = int(kp.mastery or 0)
            entries.append(
                (
                    (-days_late, mastery),
                    {
                        "id": kp.id,
                        "item_type": "knowledge",
                        "name": kp.name,
                        "subject": kp.subject,
                        "chapter": kp.chapter,
                        "question_types": kp.question_types or taxonomy.question_types_of(kp.subject),
                        "mastery": mastery,
                        "exam_frequency": kp.exam_frequency or 0,
                        "review_count": r.repetitions or 0,
                        "last_review": last_dt.isoformat() if last_dt else None,
                        "next_review": nr.isoformat() if nr else None,
                        "is_new": False,
                    },
                )
            )
        else:
            err = errs.get(r.item_id)
            if not err or (norm_subject and taxonomy.normalize_subject(err.subject) != norm_subject):
                continue
            # 错题掌握度口径与错题本一致：accuracy(0~1) 折算百分制
            mastery = int(round(float(err.accuracy or 0) * 100))
            entries.append(
                (
                    (-days_late, mastery),
                    {
                        "id": err.id,
                        "item_type": "error",
                        "name": (err.content or "")[:80],
                        "subject": err.subject,
                        "chapter": None,
                        "question_types": taxonomy.question_types_of(err.subject),
                        "mastery": mastery,
                        "exam_frequency": 0,
                        "review_count": err.review_count or 0,
                        "last_review": err.last_review.isoformat() if err.last_review else None,
                        "next_review": nr.isoformat() if nr else None,
                        "is_new": False,
                    },
                )
            )

    if include_new:
        # 「新」只限本人接触过的 KP；已有调度行（哪怕未到期）的不算新
        touched = {
            kid
            for (kid,) in db.query(StudyEvent.knowledge_point_id)
            .filter(StudyEvent.user_id == user_id, StudyEvent.knowledge_point_id.isnot(None))
            .distinct()
            .all()
        }
        touched |= {
            kid
            for (kid,) in db.query(ErrorKnowledgeLink.knowledge_point_id)
            .join(ErrorRecord, ErrorRecord.id == ErrorKnowledgeLink.error_id)
            .filter(ErrorRecord.user_id == user_id, ErrorKnowledgeLink.knowledge_point_id.isnot(None))
            .distinct()
            .all()
        }
        scheduled_kp_ids = {
            sid
            for (sid,) in db.query(ReviewSchedule.item_id)
            .filter(ReviewSchedule.user_id == user_id, ReviewSchedule.item_type == "knowledge_point")
            .all()
        }
        new_ids = touched - scheduled_kp_ids
        if new_ids:
            q = db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(new_ids))
            if norm_subject:
                q = q.filter(KnowledgePoint.subject == norm_subject)
            for kp in q.all():
                mastery = int(kp.mastery or 0)
                entries.append(
                    (
                        (-10000, mastery),
                        {
                            "id": kp.id,
                            "item_type": "knowledge",
                            "name": kp.name,
                            "subject": kp.subject,
                            "chapter": kp.chapter,
                            "question_types": kp.question_types or taxonomy.question_types_of(kp.subject),
                            "mastery": mastery,
                            "exam_frequency": kp.exam_frequency or 0,
                            "review_count": 0,
                            "last_review": None,
                            "next_review": None,
                            "is_new": True,
                        },
                    )
                )

    entries.sort(key=lambda e: e[0])
    return [item for _, item in entries[:limit]]


def progress_overview(db: Session, *, subject: str | None = None, user_id: int | None = None) -> dict[str, Any]:
    """复习进度总览：整体掌握率、分科目、分章节、薄弱 TOP。

    掌握度三态口径（见 services/kp_mastery.py）：
      未学（无任何学习记录）不计入薄弱 —— 它们"还没开始"，不是"薄弱"。

    用户口径（user_id 传入时）：已学集合/已复习/到期/复习量全部取自
    本人行（review_schedules / review_records / 本人学习留痕）；未学
    知识点掌握度按 0 计（全局 mastery 是别人的成果，不许算进我的均值）。
    返回 JSON 形状与旧口径完全一致（前端 KbMap/QuizReview 消费）。
    """
    now = _now()
    q = db.query(KnowledgePoint)
    if subject:
        q = q.filter(KnowledgePoint.subject == taxonomy.normalize_subject(subject))
    rows = q.all()
    learned = kp_mastery.learned_kp_ids(db, user_id=user_id)

    def mastery_of(k: KnowledgePoint) -> int:
        m = int(k.mastery or 0)
        if user_id is not None and k.id not in learned:
            return 0
        return m

    total = len(rows)
    # 与 kp_mastery.tally 同口径，但均值用 mastery_of（用户口径下未学记 0）
    counts = {
        "total": 0,
        "unlearned": 0,
        "learning": 0,
        "weak": 0,
        "mastered": 0,
        "mastery_sum": 0,
        "learned_mastery_sum": 0,
    }
    for k in rows:
        m = mastery_of(k)
        state = kp_mastery.classify_state(int(k.mastery or 0), k.id in learned)
        counts["total"] += 1
        counts["mastery_sum"] += m
        counts[state] += 1
        if state != kp_mastery.STATE_UNLEARNED:
            counts["learned_mastery_sum"] += m
    unlearned = counts["unlearned"]
    learning = counts.get("learning", 0)
    weak = counts["weak"]
    mastered = counts["mastered"]

    sched_map: dict[int, ReviewSchedule] = {}
    if user_id is not None:
        sched_map = {
            r.item_id: r
            for r in db.query(ReviewSchedule)
            .filter(ReviewSchedule.user_id == user_id, ReviewSchedule.item_type == "knowledge_point")
            .all()
        }
        rec_counts = dict(
            db.query(ReviewRecord.item_id, func.count(ReviewRecord.id))
            .filter(
                ReviewRecord.user_id == user_id,
                ReviewRecord.item_type.in_(["knowledge", "knowledge_point"]),
            )
            .group_by(ReviewRecord.item_id)
            .all()
        )
        reviewed_ids = {kid for kid, s in sched_map.items() if s.last_reviewed_at} | set(rec_counts)
        reviewed = sum(1 for k in rows if k.id in reviewed_ids)
        due = sum(
            1
            for k in rows
            if k.id in reviewed_ids
            and sched_map.get(k.id) is not None
            and _naive_utc(sched_map[k.id].next_review_at) is not None
            and _naive_utc(sched_map[k.id].next_review_at) <= now
        )
    else:
        reviewed = sum(1 for k in rows if (k.review_count or 0) > 0)
        # due_count 只统计"已排期且逾期"的，不把新知识点算进来 ——
        # 否则新库建成时 due_count == total，"到期"这个指标就没意义了。
        due = sum(1 for k in rows if k.review_count and k.next_review is not None and k.next_review <= now)
    new_count = total - reviewed
    avg = round(counts["mastery_sum"] / total, 1) if total else 0.0
    # 已学平均掌握度：未学知识点不拉低均值（它们还没开始，谈不上掌握度）
    learned_n = total - unlearned
    learned_avg = round(counts["learned_mastery_sum"] / learned_n, 1) if learned_n else 0.0

    # 分科目
    by_subject: dict[str, dict[str, Any]] = {}
    for k in rows:
        s = taxonomy.normalize_subject(k.subject)
        d = by_subject.setdefault(
            s,
            {
                "subject": s,
                "total": 0,
                "mastery_sum": 0,
                "mastered": 0,
                "learning": 0,
                "weak": 0,
                "unlearned": 0,
                "learned_mastery_sum": 0,
            },
        )
        mastery = mastery_of(k)
        state = kp_mastery.classify_state(int(k.mastery or 0), k.id in learned)
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
            "learned_avg_mastery": round(d["learned_mastery_sum"] / (d["total"] - d["unlearned"]), 1)
            if d["total"] - d["unlearned"]
            else 0.0,
            "mastered": d["mastered"],
            "learning": d.get("learning", 0),
            "weak": d["weak"],
            "unlearned": d["unlearned"],
            "is_core": taxonomy.is_core(d["subject"]),
        }
        for d in sorted(by_subject.values(), key=lambda x: -x["total"])
    ]

    # 分章节（仅主线，章节多的科目才有意义）
    # 用户口径下只统计本人已学章节 —— 没碰过的章节不该出现在"我的薄弱章节"里
    by_chapter: dict[str, dict[str, Any]] = {}
    for k in rows:
        if not k.chapter:
            continue
        if user_id is not None and k.id not in learned:
            continue
        key = f"{taxonomy.normalize_subject(k.subject)}|{k.chapter}"
        d = by_chapter.setdefault(
            key,
            {
                "subject": taxonomy.normalize_subject(k.subject),
                "chapter": k.chapter,
                "total": 0,
                "mastery_sum": 0,
            },
        )
        d["total"] += 1
        d["mastery_sum"] += mastery_of(k)
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

    # 近 7 天复习量：按**北京自然日**切（含今天共 7 天），与 dashboard/growth 同源。
    # 用 now-7*24h 的滚动窗会把「昨天北京 00:30」和「今天 00:30」算成不同天数。
    week_ago = local_window_for_day(local_today() - datetime.timedelta(days=6))[0]
    recent_q = db.query(func.count(ReviewRecord.id)).filter(ReviewRecord.created_at >= week_ago)
    if user_id is not None:
        recent_q = recent_q.filter(ReviewRecord.user_id == user_id)
    recent_reviews = recent_q.scalar() or 0

    return {
        "total_knowledge_points": total,
        "reviewed_count": reviewed,
        "new_count": new_count,
        "due_count": due,
        "mastered_count": mastered,
        "learning_count": learning,
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
                # 用户口径下复习次数/失误次数取本人调度行，不取全局镜像
                "review_count": (sched_map[k.id].repetitions or 0)
                if user_id is not None and k.id in sched_map
                else (k.review_count or 0),
                "lapses": (sched_map[k.id].lapses or 0)
                if user_id is not None and k.id in sched_map
                else (k.lapses or 0),
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
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """复习留痕查询（用于"复习进度追踪"时间线）。"""
    since = _now() - datetime.timedelta(days=max(1, days))
    q = db.query(ReviewRecord).filter(ReviewRecord.created_at >= since)
    if user_id is not None:
        q = q.filter(ReviewRecord.user_id == user_id)
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
