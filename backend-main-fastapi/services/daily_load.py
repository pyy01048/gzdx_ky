# -*- coding: utf-8 -*-
"""「今日推荐量」唯一口径：按算法到期 + 目标配额 + 合理上限，替掉"整库总量当今日任务"。

## 要消除的真实缺陷（2026-11-23 用户逐页报告）

- 今日中枢主数字「今天该做 5700+ 项」：来自 ``/api/dashboard/summary`` 的
  ``future_load.due_today.total``。它是**截至今天 24:00 的累计到期量**，
  对刚导入整本内置词书（5712 词）的账号 ≈ 全库量，被前端当成了"今天要做的量"。
- 单词页「今日队列 11653 词」：来自前端把 ``words/stats`` 的
  ``new``（**词库未学总量**）与到期数相加（``frontend/src/api/hub.js:308``）。

两个数字本身都没算错 —— 错在**口径被当成任务量展示**。本模块给出真正的
"今天应该学多少"：

```
今日推荐量 = min(该轨道真实到期/可学量, 用户目标配额 或 系统建议量, 合理上限)
```

三个入参缺一不可：
- **真实到期量**（FSRS / SM-2 排程，``next_review`` / ``due_date`` 已到期）——
  没到期就不该出现，用户没导入词书就是 0（诚实空态，绝不拿模板量冒充）；
- **目标配额**（``goals.daily_new_words / daily_review_words / daily_questions /
  daily_focus_minutes``）—— 用户自己说的节奏，优先级最高；未设时退回
  ``study_limits`` 里的系统建议量，并在 ``basis`` 里写明是谁定的；
- **合理上限**（``study_limits``）—— 挡住历史脏值与"整库一坨"。

## 可追溯性

每个轨道都返回 ``{value, due, quota, cap, basis, over_quota}`` 与一句 ``note``，
整份结果带 ``rule`` / ``source`` / ``version``；``backlog`` 单独给出"今日之外的
复习债"及其按当前节奏的清完天数估计。前端要显示"今天 82 项 / 复习债 5735 项，
按每日 100 词约 57 天清完"时，不需要再自己拼第二份口径。

## 与 ``dashboard_service`` 的关系

到期口径的唯一实现 ``due_counts()`` 原先是 ``DashboardService._due_counts``。
本模块把它接过来（含**按用户所选科目去噪**），``DashboardService._due_counts``
退化成一层转调，因此 ``future_load``、``today_tasks.modules``、``today_plan``
三条链必然同源，不可能给出两个"今日到期"。
"""

from __future__ import annotations

import datetime
import math
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from utils.timeutil import KAOYAN_TZ_NAME, iso_utc_z, local_today, local_window_for_day

from models import ErrorRecord, Flashcard, Goal, KnowledgePoint, QuizQuestion, Task, Word
from services import study_limits

__all__ = ["due_counts", "today_plan", "plan_by_key", "PLAN_VERSION"]

#: 口径版本号：前端/排障时可以据此判断服务端是不是换了算法，
#: 而不是对着两个日期的截图猜"到底哪一版算的"。
PLAN_VERSION = "w1-daily-load-1"


def _subject_cond(column, subjects: Optional[Sequence[str]]):
    """科目过滤条件；``subjects`` 为空（未配置科目）时返回 ``None`` = 不过滤。

    未配置科目**不等于**"零科目"：新号还没去设置页填科目时，
    把他的到期错题全过滤掉，等于告诉他"你今天没欠复习" —— 那是另一种谎。
    所以只在真的配置过科目时才收窄，并把收窄范围写进返回的 ``subject_scope``。
    """
    if not subjects:
        return None
    return column.in_(list(subjects))


def due_counts(
    db: Session,
    day: datetime.date,
    user_id: Optional[int] = None,
    *,
    subjects: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """某一北京自然日的**累计到期量**（含此前欠下的复习债），切点为该日 24:00。

    判定规则与 ``services.review_scheduler`` 一致（``next_review`` 非空且 <= 切点，
    错题另加 ``status='active'``，任务排除 ``done``），切点走
    ``local_window_for_day`` —— 不引入第二套日界。
    B4：传入 ``user_id`` 时只统计该用户的到期量。

    ``subjects``（W1 去噪）：给定用户所选科目时，错题 / 任务 / 卡片按科目收窄，
    被剔出的数量进 ``outside_scope``，让"去噪"这件事本身可追溯。

    返回 ``{words, flashcards, errors, tasks, total, due_all, total_all,
    outside_scope, subject_scope, cutoff}``。``total`` 是**到期量**
    （不是今日任务量）；今日任务量见 :func:`today_plan`。
    """
    cutoff = local_window_for_day(day)[1]

    def _u(model):
        return () if user_id is None else (model.user_id == user_id,)

    def _sched(model, extra=()):
        return int(
            db.query(func.count(model.id))
            .filter(model.next_review != None, model.next_review <= cutoff, *extra)  # noqa: E711
            .scalar()
            or 0
        )

    # 错题：科目可筛，所以"范围内 / 全量"各数一次，差值即被剔出的噪声
    err_base = (ErrorRecord.status == "active", ErrorRecord.next_review != None, *_u(ErrorRecord))  # noqa: E711
    errors_all = _sched(ErrorRecord, err_base)
    econd = _subject_cond(ErrorRecord.subject, subjects)
    errors = _sched(ErrorRecord, (*err_base, econd)) if econd is not None else errors_all

    # 任务：只数"未完成且已到期"。done 任务继续留在待办数里，
    # 会把"已经做完了"渲染成"还欠一堆"。
    task_base = (Task.next_review != None, Task.status != "done", *_u(Task))  # noqa: E711
    tasks_all = _sched(Task, task_base)
    tcond = _subject_cond(Task.subject, subjects)
    tasks = _sched(Task, (*task_base, tcond)) if tcond is not None else tasks_all

    # 卡片：科目要经 knowledge_points 关联；没挂知识点的卡**保留**
    # （无归属 ≠ 非学习科目，直接抹掉会让"卡片到期 0"变成假话）
    cards_all = _sched(Flashcard, _u(Flashcard))
    if subjects:
        cq = (
            db.query(func.count(Flashcard.id))
            .outerjoin(KnowledgePoint, Flashcard.knowledge_point_id == KnowledgePoint.id)
            .filter(
                Flashcard.next_review != None,  # noqa: E711
                Flashcard.next_review <= cutoff,
                or_(KnowledgePoint.subject.is_(None), KnowledgePoint.subject.in_(list(subjects))),
            )
        )
        if user_id is not None:
            cq = cq.filter(Flashcard.user_id == user_id)
        cards = int(cq.scalar() or 0)
    else:
        cards = cards_all

    # 单词走 due_date（date 列，无时间部分），因此直接和自然日比，不换算成 UTC。
    # 口径与 GET /api/words/due、words/stats 一致：只数已学过的（learning/reviewing），
    # 新词不是"待复习"。
    wq = db.query(func.count(Word.id)).filter(
        Word.due_date != None,  # noqa: E711
        Word.due_date <= day,
        Word.status.in_(["learning", "reviewing"]),
        *_u(Word),
    )
    words = int(wq.scalar() or 0)

    inside = {"words": words, "flashcards": cards, "errors": errors, "tasks": tasks}
    all_of = {"words": words, "flashcards": cards_all, "errors": errors_all, "tasks": tasks_all}
    out: Dict[str, Any] = dict(inside)
    out["total"] = sum(inside.values())
    out["due_all"] = all_of
    out["total_all"] = sum(all_of.values())
    out["outside_scope"] = max(0, out["total_all"] - out["total"])
    out["subject_scope"] = list(subjects) if subjects else None
    out["cutoff"] = iso_utc_z(cutoff)
    return out


def new_words_available(db: Session, user_id: Optional[int] = None, *, cap: int = 1000) -> int:
    """可学新词量（**库存**，不是今日任务）：本人词库内 ``not_mastered`` 词条数。

    只做上限截断，避免把 5712 这种整库量原样带进响应；
    返回值的上限足以表达"库存远多于今日配额"这个事实。
    """
    q = db.query(func.count(Word.id)).filter(Word.status == "not_mastered")
    if user_id is not None:
        q = q.filter(Word.user_id == user_id)
    return min(int(q.scalar() or 0), cap)


def questions_available(db: Session, subjects: Optional[Sequence[str]] = None, *, need: int = 200) -> int:
    """题库里**至少**有多少道可练题（上界截断到 ``need``）。

    题库没有排程字段（见 ``dashboard_service._DUE_NOTES``），所以不能用"到期量"。
    但也不能不看库存就推荐"今日 15 道" —— 空题库的新号该拿到 0。
    这里用 ``limit need`` 的有界取数代替 ``COUNT(*)``：大表上不随题库规模变慢，
    且对"今天只需十几道"的判断完全够用。
    """
    if need <= 0:
        return 0
    q = db.query(QuizQuestion.id).filter(QuizQuestion.is_available == True)  # noqa: E712
    cond = _subject_cond(QuizQuestion.subject, subjects)
    if cond is not None:
        q = q.filter(cond)
    return len(q.limit(need).all())


def _track(
    key: str,
    label: str,
    unit: str,
    *,
    available: int,
    quota: Optional[int],
    cap: int,
    default: int,
    countable: bool = True,
    extra_note: str = "",
) -> Dict[str, Any]:
    """一条轨道的推荐量与它的推导过程。

    ``basis`` 说明这个数字**是谁定的**：
    - ``goal``         —— 用户在目标里设了每日配额（最高优先级）；
    - ``goal_capped``  —— 目标值本身超出合理上限，按上限排并说明；
    - ``system_default`` —— 用户没设目标，用系统建议量（界面须标"建议"）；
    - ``stock_limited`` —— 库存/到期量比配额小，今日推荐 = 库存。
    ``over_quota`` 是"到期但没排进今天"的量，界面上要作为复习债单列，
    绝不能加回"今日该做"。
    """
    if quota is None:
        limit = min(default, cap)
        basis = "system_default"
    else:
        limit = min(quota, cap)
        basis = "goal" if quota <= cap else "goal_capped"
    value = min(available, limit)
    if available < limit:
        basis = "stock_limited"

    note: List[str] = []
    if basis == "goal":
        note.append(f"按你在目标里设的每日 {quota}{unit}")
    elif basis == "goal_capped":
        note.append(f"目标 {quota}{unit} 超出合理上限 {cap}{unit}，按 {limit}{unit} 排")
    elif basis == "stock_limited":
        note.append(f"可学/到期仅 {available}{unit}，不足每日配额，今日按 {value}{unit} 排")
    else:
        note.append(f"未设每日目标，按系统建议 {limit}{unit}")
    if available > value:
        note.append(f"另有 {available - value}{unit} 转入复习债，按每日节奏分摊")
    if extra_note:
        note.append(extra_note)
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "value": value,
        "available": available,
        "quota": quota,
        "cap": cap,
        "countable": countable,
        "basis": basis,
        "over_quota": max(0, available - value),
        "note": "；".join(note),
    }


def _goal_row(db: Session, user_id: Optional[int]) -> Optional[Goal]:
    gq = db.query(Goal)
    if user_id is not None:
        gq = gq.filter(Goal.user_id == user_id)
    return gq.order_by(Goal.id.asc()).first()


#: 轨道表（声明式）：``key`` → 标签/单位/来源。
#: - ``quota_field``：goals 表里的每日配额列（``None`` = 没有用户目标列，走上限）
#: - ``source``：可用量的来源 —— ``due:<due_counts 键>`` / ``stock_new_words`` /
#:   ``question_bank`` / ``quota_only``（没有库存概念，纯粹按目标排）
#: - ``countable``：是否并入「今天该做 N 项」（专注是分钟，不能和项相加）
#:
#: 写成表而不是六段重复代码，是为了让"闸门常量 ↔ 推荐轨道"必须同步：
#: 新增一列每日目标却忘了登记轨道，这里一眼就能看出来。
TRACK_QUOTA_MAP: List[Dict[str, Any]] = [
    {
        "key": "new_words",
        "label": "今日新词",
        "unit": "词",
        "quota_field": "daily_new_words",
        "source": "stock_new_words",
        "countable": True,
    },
    {
        "key": "review_words",
        "label": "单词复习",
        "unit": "词",
        "quota_field": "daily_review_words",
        "source": "due:words",
        "countable": True,
    },
    {
        "key": "questions",
        "label": "刷题",
        "unit": "道",
        "quota_field": "daily_questions",
        "source": "question_bank",
        "countable": True,
    },
    {
        "key": "focus",
        "label": "专注时长",
        "unit": "分钟",
        "quota_field": "daily_focus_minutes",
        "source": "quota_only",
        "countable": False,
    },
    {
        "key": "cards",
        "label": "记忆卡片",
        "unit": "张",
        "quota_field": None,
        "source": "due:flashcards",
        "countable": True,
    },
    {
        "key": "errors",
        "label": "错题复习",
        "unit": "道",
        "quota_field": None,
        "source": "due:errors",
        "countable": True,
    },
    {"key": "tasks", "label": "今日待办", "unit": "项", "quota_field": None, "source": "due:tasks", "countable": True},
]


def _track_available(
    source: str,
    due: Dict[str, Any],
    *,
    db: Session,
    user_id: Optional[int],
    subjects: Optional[Sequence[str]],
    quota: Optional[int],
    cap: int,
) -> int:
    """按轨道来源取"今天最多能排多少"的真实上界（不拿库存/整库量冒充）。"""
    if source.startswith("due:"):
        return int(due.get(source[4:]) or 0)
    if source == "stock_new_words":
        return new_words_available(db, user_id, cap=cap)
    if source == "question_bank":
        # 题库没有排程字段：按"今日配额所需的量"去库存里有界取数，
        # 既不做 COUNT(*) 全表扫，也不把整库题量当今日任务。
        return questions_available(db, subjects, need=min(cap, quota or cap))
    return cap  # quota_only：没有库存概念（专注时长），上限即边界


def today_plan(
    db: Session,
    *,
    user_id: Optional[int] = None,
    day: Optional[datetime.date] = None,
    goal: Optional[Goal] = None,
    due: Optional[Dict[str, Any]] = None,
    subjects: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """今日推荐学习量（供数层唯一出口）。

    入参 ``goal`` / ``due`` / ``subjects`` 允许调用方复用已有查询结果
    （``DashboardService.get_summary`` 会传）；缺省时就地取，
    单独调用 ``GET /api/dashboard/today-plan`` 也自洽。

    返回 ``{date, timezone, version, source, tracks, items_total,
    focus_minutes, subject_scope, backlog, rule}``。
    """
    day = day or local_today()
    if goal is None:
        goal = _goal_row(db, user_id)
    if subjects is None:
        from services import subject_config

        subjects = subject_config.active_subjects(db, user_id=user_id) or None
    if due is None:
        due = due_counts(db, day, user_id, subjects=subjects)

    L = study_limits.DAILY_QUOTA_LIMITS
    T = study_limits.TODAY_TRACK_CAPS

    def g(name):
        return getattr(goal, name, None) if goal else None

    tracks: List[Dict[str, Any]] = []
    for spec in TRACK_QUOTA_MAP:
        key = spec["key"]
        qf = spec["quota_field"]
        limits = L.get(qf) if qf else T.get(key)
        cap = limits["max"]
        default = limits["default"] if "default" in limits else cap
        quota = g(qf) if qf else None
        available = _track_available(
            spec["source"], due, db=db, user_id=user_id, subjects=subjects, quota=quota, cap=cap
        )
        tracks.append(
            _track(
                key,
                spec["label"],
                spec["unit"],
                available=available,
                quota=quota,
                cap=cap,
                default=default,
                countable=spec["countable"],
                extra_note=(
                    "题库无排程字段，按每日目标从可练库存里排，不引用整库题量"
                    if key == "questions"
                    else "只数未完成且已到期的任务"
                    if key == "tasks"
                    else ""
                ),
            )
        )
    by = {t["key"]: t for t in tracks}

    items_total = sum(t["value"] for t in tracks if t["countable"])
    due_total = int(due["total_all"])
    planned_due = int(due["words"]) + int(due["flashcards"]) + int(due["errors"]) + int(due["tasks"])
    # 每日"消化能力" = 今日排进的复习类轨道之和（新词不算还债）
    capacity = max(1, by["review_words"]["value"] + by["cards"]["value"] + by["errors"]["value"])
    # 范围外（非所选科目被去噪剔除）的到期量
    outside_scope = max(0, due_total - planned_due)
    # 范围内、但因每日配额没排进今天的到期量（"今天排 50 / 还欠 750"的那 750）。
    # 复习债 = 两者之和：只算去噪差额会漏掉最大的那块 —— 配额/上限挡下的到期欠账，
    # 而 backlog 的存在意义正是"债要说清，但不能加回今天该做"。
    due_over = sum(int(by[k]["over_quota"]) for k in ("review_words", "cards", "errors", "tasks") if by.get(k))

    return {
        "date": day.isoformat(),
        "timezone": KAOYAN_TZ_NAME,
        "version": PLAN_VERSION,
        "source": "services.daily_load.today_plan",
        "tracks": tracks,
        "items_total": items_total,
        "focus_minutes": by["focus"]["value"],
        "subject_scope": due.get("subject_scope"),
        "backlog": {
            "due_total": due_total,
            "outside_today": outside_scope + due_over,
            "outside_scope": outside_scope,
            "deferred_by_quota": due_over,
            "capacity_per_day": capacity,
            "clear_days": math.ceil((outside_scope + due_over) / capacity) if (outside_scope + due_over) else 0,
            "rule": "到期总量含此前欠账；今日未排入（配额挡下 + 科目去噪）的部分按每日节奏分摊，不计入「今天该做」",
        },
        "rule": "今日推荐量 = min(真实到期/可学量, 目标配额或系统建议量, 合理上限)；"
        "单位不同的轨道（专注分钟）不并入项数",
    }


def plan_by_key(plan: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """把 ``today_plan`` 的 tracks 转成 ``{key: track}``，供调用方按轨道取名。"""
    if not plan:
        return {}
    return {t["key"]: t for t in plan.get("tracks") or [] if isinstance(t, dict) and t.get("key")}
