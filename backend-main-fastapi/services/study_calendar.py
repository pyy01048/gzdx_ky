"""「哪天学了多少」的唯一口径：日活台账（study calendar）。

## 为什么需要这个模块
打卡 / 热力图 / 趋势 / KPI 各自查询、各算一套时，同一个"连续天数"能有三个答案
（2026-10-16 收敛前的实测状态）：

- ``DashboardService.get_stats``：今日/近 7 天时长走 ``study_sessions.duration``（真实分钟）；
- ``services/learning_analytics_service.get_learning_traces``：**估算**时长
  （已完成任务 ×30 分钟 + 答题 ×5 分钟），据此算 streak —— 用户从没记录过专注，
  只要做过题就"连续打卡"，口径完全对不上；
- ``routers/growth``：按 ``study_events`` 埋点流自己 distinct 本地日 + 跨零点宽限，
  又是第三种过滤条件。

本模块把「按北京自然日聚合的学习活动」收敛成一份台账：一次构建（6 条聚合查询），
streak / 热力图 / 趋势 / KPI / 未来负荷全部从同一份 ``DayActivity`` 派生，
不再有任何一处自己 group by 日期。上面三处（含成长体系的 summary 与 timeline）
现在都已改为调用 ``day_ledger`` + ``streak_summary``。

## 口径（与产品标准 01-仪表盘 §2.7 一致）
- **日界**：北京自然日（``KAOYAN_TZ``，无夏令时），由 ``utils.timeutil`` 的
  ``day_bucket_expr`` / ``local_today`` 统一提供。标准文档里「跨零点 2 小时宽限」
  **故意不实现**：一套产品里不能同时存在两个日界，否则今日/昨日会随模块漂移。
- **有效学习日（打卡日）**：当日 ``focus_minutes >= 10`` 或 ``words_done >= 10``
  或 ``questions_done >= 5``。三档阈值是**判定门槛**，不是任何演示数据。
- **时长只认真实记录**：``focus_minutes`` 只来自 ``study_sessions.duration``。
  绝不再用"任务 ×30 + 题目 ×5"估算 —— 估算值一旦进指标卡就等于撒谎。
- **今日未学不算断签**：streak 从今天往前数，今天还没学时从昨天起算
  （``current_streak`` 保持不立即清零），避免白天任何时候打开首页都显示"断了"。
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlalchemy import Integer, func

from models import AnswerRecord, ErrorRecord, ReviewRecord, StudySession, Task
from utils.timeutil import (
    day_bucket_expr,
    local_today,
    local_window_for_day,
)

__all__ = [
    "EFFECTIVE_FOCUS_MINUTES",
    "EFFECTIVE_WORDS",
    "EFFECTIVE_QUESTIONS",
    "MAX_FOCUS_MINUTES_PER_SESSION",
    "MAX_FOCUS_MINUTES_PER_DAY",
    "FOCUS_SOURCES",
    "DayActivity",
    "day_ledger",
    "fill_series",
    "streak_summary",
    "effective_activity_days",
]

#: 有效学习日门槛（01-仪表盘 §2.7 埋点口径）
EFFECTIVE_FOCUS_MINUTES = 10
EFFECTIVE_WORDS = 10
EFFECTIVE_QUESTIONS = 5

#: 时长**写入口径**，与上面的读出口径同住一处：
#: 专注计时的 POST（``routers/dashboard.py``）拿它们做校验，
#: 而台账把它们读成 ``focus_minutes``。分开放就会出现「校验放宽了、
#: 热力图阈值没改」这类同一应用两个答案。
#: 单次上限 600 分钟：番茄钟常态是 25，长时段块 120~180 也合理，
#: 再往上就不是「一次专注」而是客户端跑飞了。
MAX_FOCUS_MINUTES_PER_SESSION = 600
#: 单日上限 = 一天的分钟数。超过它的记录必然不是真实专注，
#: 一旦落库会把当日热力图 / streak / 周趋势一起带歪。
MAX_FOCUS_MINUTES_PER_DAY = 1440

#: 一次专注的来源（01-仪表盘 §3.1 的 ``source`` ENUM）。
#: 落在既有的 ``study_sessions.task_type`` 列上 —— 为该 ENUM 新增列属于
#: #10 的模型层收敛范围，这里不越界改 schema。
FOCUS_SOURCES = ("pomodoro", "manual", "module")

#: 热力图默认回看周数（53 列 ×7 行，GitHub 风格一整屏）
HEATMAP_WEEKS = 53


@dataclass
class DayActivity:
    """一个北京自然日的学习产出。缺数据的日子字段全 0（``is_active`` 为 False）。"""

    date: datetime.date
    focus_minutes: int = 0
    words_done: int = 0
    cards_done: int = 0
    knowledge_done: int = 0
    errors_done: int = 0
    questions_done: int = 0
    questions_correct: int = 0
    exams_done: int = 0
    tasks_done: int = 0
    errors_added: int = 0

    @property
    def reviews_done(self) -> int:
        """当日复习行为总数（词 / 卡 / 知识点 / 错题）。"""
        return self.words_done + self.cards_done + self.knowledge_done + self.errors_done

    @property
    def correct_rate(self) -> Optional[float]:
        """当日正确率 %；没答题返回 None（**不返回 0**，0 是"全错"不是"没做"）。"""
        if not self.questions_done:
            return None
        return round(100.0 * self.questions_correct / self.questions_done, 1)

    @property
    def is_effective(self) -> bool:
        """是否算「有效学习日」（打卡日）。"""
        return (
            self.focus_minutes >= EFFECTIVE_FOCUS_MINUTES
            or self.words_done >= EFFECTIVE_WORDS
            or self.questions_done >= EFFECTIVE_QUESTIONS
        )

    @property
    def is_active(self) -> bool:
        """当日有任何学习痕迹（含未达打卡门槛的少量行为）。"""
        return bool(
            self.focus_minutes
            or self.reviews_done
            or self.questions_done
            or self.exams_done
            or self.tasks_done
            or self.errors_added
        )

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "focus_minutes": self.focus_minutes,
            "words_done": self.words_done,
            "cards_done": self.cards_done,
            "knowledge_done": self.knowledge_done,
            "errors_done": self.errors_done,
            "questions_done": self.questions_done,
            "questions_correct": self.questions_correct,
            "correct_rate": self.correct_rate,
            "exams_done": self.exams_done,
            "tasks_done": self.tasks_done,
            "errors_added": self.errors_added,
            "is_effective": self.is_effective,
            "is_active": self.is_active,
        }


def _blank(day: datetime.date) -> DayActivity:
    return DayActivity(date=day)


def day_ledger(
    db,
    *,
    start_day: Optional[datetime.date] = None,
    end_day: Optional[datetime.date] = None,
    user_id: Optional[int] = None,
) -> Dict[str, DayActivity]:
    """按北京自然日聚合学习行为，返回 ``{"2026-10-17": DayActivity}``。

    只返回**有活动**的日子（前端热力图自行补 0），因此默认全量历史也就几十~几百行。

    Args:
        db: SQLAlchemy Session。
        start_day / end_day: 闭区间；``start_day=None`` 表示不限下界（全量历史）。
        user_id: B4 行级隔离——传入时全部个人表（study_sessions / review_records /
            answer_records / tasks / error_records）都按该用户过滤；不传（默认
            None）保持旧行为（不过滤），兼容尚未接线的调用方。调用方（路由层）
            一律传 ``owner_id(user)``。注意：模考场次（core.models.exams.ExamSession）
            尚无 user_id 列，模考场次暂按全库计数。
    """
    end_day = end_day or local_today()
    # local_window_for_day 返回该本地日的 [起, 止)，取 [1] 才是**含 end_day** 的右开边界
    # （写成 local_range_utc(end_day, end_day+1)[0] 会得到 end_day 当天零点，最后一天整体漏掉）。
    upper = local_window_for_day(end_day)[1]
    lower = local_window_for_day(start_day)[0] if start_day else None

    ledger: Dict[str, DayActivity] = {}

    # B4 行级隔离：user_id 传入时，个人表查询统一追加归属过滤；
    # None（旧行为）不加任何条件，兼容未接线调用方。
    def _user_extra(model):
        if user_id is None:
            return ()
        return (model.user_id == user_id,)

    def _slot(day_str: str) -> DayActivity:
        act = ledger.get(day_str)
        if act is None:
            act = _blank(datetime.date.fromisoformat(day_str))
            ledger[day_str] = act
        return act

    def _count_by_day(col, id_col, *, extra=(), label_col=None):
        """一条 ``GROUP BY 本地日`` 的聚合，返回 ``[(日期串, 分类, 计数)]``。

        ``label_col`` 给定时按 ``(日, 分类)`` 两列分组（review_records 用它分 item_type）。
        边界传 **naive UTC** datetime：``core/db_session`` 把 PG 会话时区钉在 UTC
        （``-c timezone=UTC``），所以连 ``submitted_at`` 这类 TIMESTAMPTZ 列，
        naive 绑定值也按 UTC 解释，不会多算/少算 8 小时。
        """
        day = day_bucket_expr(col, db)
        if label_col is not None:
            rows = db.query(day, label_col, func.count(id_col)).filter(*extra)
            if lower is not None:
                rows = rows.filter(col >= lower)
            rows = rows.filter(col < upper).group_by(day, label_col).all()
            return [(str(d), lbl, int(n or 0)) for d, lbl, n in rows]
        q = db.query(day, func.count(id_col)).filter(*extra)
        if lower is not None:
            q = q.filter(col >= lower)
        q = q.filter(col < upper).group_by(day)
        return [(str(d), None, int(n or 0)) for d, n in q.all()]

    # 1. 专注时长（study_sessions.date 是 Date 列，本身就是本地日，不参与时区换算）
    q = db.query(StudySession.date, func.coalesce(func.sum(StudySession.duration), 0))
    if start_day:
        q = q.filter(StudySession.date >= start_day)
    q = q.filter(StudySession.date <= end_day)
    q = q.filter(*_user_extra(StudySession)).group_by(StudySession.date)
    for d, minutes in q.all():
        _slot(str(d)).focus_minutes = int(minutes or 0)

    # 2. 复习行为（review_records 按 item_type 分流：word/flashcard/knowledge/error）
    field_map = {"word": "words_done", "flashcard": "cards_done",
                 "knowledge": "knowledge_done", "error": "errors_done"}
    for d, item_type, n in _count_by_day(
        ReviewRecord.created_at,
        ReviewRecord.id,
        label_col=ReviewRecord.item_type,
        extra=_user_extra(ReviewRecord),
    ):
        attr = field_map.get(str(item_type))
        if attr:
            setattr(_slot(d), attr, n)

    # 3. 答题数 + 答对数（同一 GROUP BY 出两个口径，避免两条查询各算各的）
    day = day_bucket_expr(AnswerRecord.created_at, db)
    q = db.query(
        day,
        func.count(AnswerRecord.id),
        func.coalesce(func.sum(func.cast(AnswerRecord.is_correct, Integer)), 0),
    )
    if lower is not None:
        q = q.filter(AnswerRecord.created_at >= lower)
    q = q.filter(*_user_extra(AnswerRecord))
    q = q.filter(AnswerRecord.created_at < upper).group_by(day)
    for d, total, correct in q.all():
        act = _slot(str(d))
        act.questions_done = int(total or 0)
        act.questions_correct = int(correct or 0)

    # 4. 模考场次（真题模块）：表建在 core/sql/041，ORM 分片在 core.models.exams。
    #    B4 注：ExamSession 尚无 user_id 列，模考场次暂按全库计数（待 models 层加列后补过滤）。
    try:
        from core.models.exams import ExamSession

        for d, _lbl, n in _count_by_day(
            ExamSession.submitted_at,
            ExamSession.id,
            extra=(ExamSession.status == "submitted", ExamSession.submitted_at.isnot(None)),
        ):
            _slot(d).exams_done = n
    except Exception:  # noqa: BLE001 - 老库没跑 041 分片时，真题记 0，不能让整张仪表盘 500
        pass

    # 5. 任务完成（只认 completed_at；旧数据 status='done' 但没留完成时间的不参与，
    #    否则按 updated_at 会把"今天改过状态"算成"今天完成"）
    for d, _lbl, n in _count_by_day(
        Task.completed_at,
        Task.id,
        extra=(Task.status == "done", Task.completed_at.isnot(None), *_user_extra(Task)),
    ):
        _slot(d).tasks_done = n

    # 6. 错题新增（趋势副标用，不参与打卡判定）
    for d, _lbl, n in _count_by_day(
        ErrorRecord.created_at, ErrorRecord.id, extra=_user_extra(ErrorRecord)
    ):
        _slot(d).errors_added = n

    return ledger


def focus_minutes_on(db, day: datetime.date, user_id: Optional[int] = None) -> int:
    """某北京自然日已记录的专注分钟总数（``study_sessions.duration`` 单一来源）。

    写入口径用它在落库前挡掉「一天超过一天该有的分钟数」的脏数据。
    读侧走 :func:`day_ledger`，两边都只 ``sum(duration)`` 且都只认真实记录，
    所以「计时器说记了 25 分钟」和「KPI 卡显示 25 分钟」不可能是两个数。
    B4 行级隔离：``user_id`` 传入时只统计该用户的专注记录；不传保持旧行为。
    """
    q = db.query(func.coalesce(func.sum(StudySession.duration), 0)).filter(
        StudySession.date == day
    )
    if user_id is not None:
        q = q.filter(StudySession.user_id == user_id)
    return int(q.scalar() or 0)


def fill_series(
    ledger: Dict[str, DayActivity], start_day: datetime.date, end_day: datetime.date
) -> List[DayActivity]:
    """把台账补成 ``[start_day, end_day]`` 逐日连续序列（缺的日子补 0）。

    折线/热力图需要**每天都有一格**，否则空档会消失，用户看不出"这周只学了两天"。
    """
    out: List[DayActivity] = []
    d = start_day
    while d <= end_day:
        out.append(ledger.get(d.isoformat()) or _blank(d))
        d += datetime.timedelta(days=1)
    return out


def streak_summary(
    ledger: Dict[str, DayActivity], *, today: Optional[datetime.date] = None
) -> dict:
    """连续打卡：当前 / 历史最长 / 累计有效天数。

    与 ``day_ledger`` 同源：只看 ``is_effective``，不再各写一套过滤条件。
    ``current`` 从今天往前数，今天还没学时从昨天起算（见模块 docstring）。

    ``today`` 可注入（默认 ``local_today()``）：既是给测试用的确定性入口，
    也让跨零点/时区排查时可以显式指定"哪天算今天"，而不是靠改系统时钟。
    """
    days = sorted((datetime.date.fromisoformat(k) for k in ledger), reverse=True)
    effective = {d for d in days if ledger[d.isoformat()].is_effective}
    today = today or local_today()

    current = 0
    cursor = today if today in effective else today - datetime.timedelta(days=1)
    while cursor in effective:
        current += 1
        cursor -= datetime.timedelta(days=1)

    longest = 0
    run = 0
    prev: Optional[datetime.date] = None
    for d in sorted(effective):
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d

    first_day = min(days) if days else None
    return {
        "current": current,
        "longest": longest,
        "total_days": len(effective),
        "checked_today": today in effective,
        "first_day": first_day.isoformat() if first_day else None,
        "rule": f"当日专注 ≥{EFFECTIVE_FOCUS_MINUTES} 分钟，或复习单词 ≥{EFFECTIVE_WORDS} 个，或答题 ≥{EFFECTIVE_QUESTIONS} 道",
    }


def effective_activity_days(
    ledger: Dict[str, DayActivity],
    *,
    weeks: int = HEATMAP_WEEKS,
    today: Optional[datetime.date] = None,
) -> List[dict]:
    """近 ``weeks`` 周的逐日格子（含空日），前端渲染 53×7 热力图。

    起点对齐到**周一**，保证列数就是周数，不会出现半列错位。
    """
    today = today or local_today()
    start = today - datetime.timedelta(days=weeks * 7 - 1)
    start -= datetime.timedelta(days=start.weekday())  # 回到本周所在周的周一
    series = fill_series(ledger, start, today)
    return [a.to_dict() for a in series]
