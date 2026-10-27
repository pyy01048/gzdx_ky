"""考研「届数 / 初试日期」的唯一权威出口。

## 为什么需要这个模块
初试日期此前在三处各算各的，互相打架：

- ``services/dashboard_service.get_countdown``：Goal 没写 exam_date 时**写死 12/21**；
- ``routers/plan._exam_date``：按「(year-1) 年 12 月倒数第二个周六」推导；
- 前端 ``utils/exam.js``：读后端 / 本地设置，任一为空就显示"未配置"。

同一个应用因此能给出三个不同答案。真库实测：``goals.exam_date='2027-12-25'``，
但复习里程碑里的初试是 2026-12-19，两者差一年，用户根本不知道自己到底在数哪一天。

## 术语约定（这是本模块的核心）
「**届**」= 考研年份，即**入学年份**，用 ``exam_year`` 表示。2027 年入学 = 2027 届。
「**初试日**」= 该届的全国统考初试第一天，发生在**上一年 12 月的倒数第二个周六**。

已由教育部正式公布的届（``OFFICIAL_EXAM_DATES`` 是硬事实，不推导）：
- 2026 届：初试 2025-12-20
- 2027 届：初试 2026-12-19（教育部《2027 年全国硕士研究生招生工作管理规定》，
  报名 2026-10-15~10-24，初试 2026-12-19 至 12-20）
未公布的届走 :func:`estimate_exam_date` 的规则推导，并标 ``is_official=False``，
前端必须显示成「预估」，**不得**当成官方日期。

## 使用约定
**任何地方需要初试日期，都必须调本模块**，不允许再自行推导或写死月份日期。
"""
from __future__ import annotations

import calendar
import datetime
from typing import Optional, Tuple

from utils.timeutil import local_today

#: 已由教育部正式公布初试日期的届 -> 初试第一天（date 对象用 (年, 月, 日) 元组表达）
OFFICIAL_EXAM_DATES: dict[int, Tuple[int, int, int]] = {
    2025: (2024, 12, 21),
    2026: (2025, 12, 20),
    2027: (2026, 12, 19),
}

#: 可接受的届数范围（防止把 1999 或 2099 写进来）
MIN_EXAM_YEAR = 2000
MAX_EXAM_YEAR = 2100


class ExamYearError(ValueError):
    """届数非法（越界或非整数）。调用方应转成 HTTP 422。"""


def validate_exam_year(exam_year: int) -> int:
    """校验届数并返回。非法抛 :class:`ExamYearError`。"""
    try:
        y = int(exam_year)
    except (TypeError, ValueError):
        raise ExamYearError(f"届数必须是整数，收到 {exam_year!r}")
    if not (MIN_EXAM_YEAR <= y <= MAX_EXAM_YEAR):
        raise ExamYearError(f"届数需在 {MIN_EXAM_YEAR}~{MAX_EXAM_YEAR} 之间，收到 {y}")
    return y


def estimate_exam_date(exam_year: int) -> datetime.date:
    """推导某届的初试日：上一年 12 月的**倒数第二个周六**。

    这是考研的稳定规律（教育部通常选 12 月下旬的周末），用于尚未公布日期的届。
    注意这是**估算**，调用方应把 ``is_official`` 一并返回给前端。

    举例：2027 届 -> 2026-12 的周六为 5/12/19/26，倒数第二个是 19 -> 2026-12-19。
    """
    y = validate_exam_year(exam_year)
    cal = calendar.monthcalendar(y - 1, 12)
    saturdays = [w[5] for w in cal if w[5] != 0]
    if not saturdays:  # 极端兜底（理论上不可能）
        saturdays = [w[d] for w in cal for d in range(7) if w[d] != 0 and d == 5]
    return datetime.date(y - 1, 12, saturdays[-2])


def resolve_exam_date(exam_year: int) -> Tuple[datetime.date, bool]:
    """返回 ``(初试日, is_official)``。

    已公布的届直接取官方日期；未公布的按规律估算并标 ``is_official=False``。
    """
    y = validate_exam_year(exam_year)
    official = OFFICIAL_EXAM_DATES.get(y)
    if official:
        return datetime.date(*official), True
    return estimate_exam_date(y), False


def exam_year_of(exam_date: Optional[datetime.date]) -> Optional[int]:
    """由初试日反推届数：初试在上一年 12 月，所以届数 = 初试年 + 1。

    这是本模块最重要的一条纠错规则。库里那条 ``exam_date='2027-12-25'`` 若按此
    反推，届数是 2028——也就是说它记的其实是 2028 届，而不是备注里写的 2027 届目标。
    """
    if exam_date is None:
        return None
    return exam_date.year + 1


def default_exam_year(today: Optional[datetime.date] = None) -> int:
    """推断"用户当前最可能考的届"：**下一场还没举行的初试**。

    规则按**日期**判定，不按月份。旧写法是「7~12 月就默认报明年那一届」，
    实测在 2026-10-17 会给出 2028 届（初试 2027-12-18，还有 427 天），
    而教育部公告的 2027 届初试就是 **2026-12-19（还有 63 天，报名 10-15~10-24 正在进行）** ——
    空库新用户一打开首页，倒计时数的是"根本没报名的那一届"，方向就错了。

    现在：从「初试年 = 今年」这一届起逐届往后找，取**第一个初试日 >= 今天**的届。
    - 2026-10-17 → 2027 届（2026-12-19，63 天）
    - 2026-12-25 → 2028 届（初试已过，自动滚到下一届）
    仅用于**未配置 Goal 时的兜底**，前端必须标成「预估」。
    """
    t = today or local_today()
    for year in (t.year, t.year + 1, t.year + 2):
        exam_date, _official = resolve_exam_date(year)
        if exam_date >= t:
            return year
    return t.year + 2


def describe(exam_year: int) -> dict:
    """给前端用的完整描述（初试日 + 届 + 是否官方 + 关键时间节点）。"""
    y = validate_exam_year(exam_year)
    exam_date, official = resolve_exam_date(y)
    today = local_today()
    return {
        "exam_year": y,
        "exam_date": exam_date.isoformat(),
        "is_official": official,
        "days_left": (exam_date - today).days,
        # 报名窗口：官方通知为「初试前一年 10 月中下旬」，仅作提醒用，不参与任何计算
        "signup_hint": f"{exam_date.year} 年 10 月中下旬（以研招网公告为准）",
        "source": "教育部已公布" if official else "按 12 月倒数第二个周六规律估算",
    }


def phase_of(days_left: int) -> str:
    """倒计时阶段（01-仪表盘 §2.3.1：最后 30 天警示、最后 7 天冲刺）。

    阶段判定**只有这一处**：前端按返回的 phase 上颜色/文案，不再自己 `days <= 30`
    分支，否则同一个数字会在两个页面给出两种语气。
    """
    if days_left < 0:
        return "passed"        # 初试已过（等下一届或复试）
    if days_left <= 7:
        return "sprint"        # 冲刺：最后 7 天
    if days_left <= 30:
        return "warning"       # 警示：最后 30 天
    if days_left <= 90:
        return "intensify"     # 考前 90 天：强化期
    return "base"


def resolve_for_db(goal) -> dict:
    """从 Goal 行推导对外统一的届数 / 初试日描述。

    优先级（这是纠错的核心逻辑）：
    1. Goal 有 ``exam_date``  -> 用它，并**按"上一年 12 月"规则反推届数**；
       这样即使库里存的是一个明显写错的日期（如同一条记录里混了 2028 届的日期），
       届数与初试日也永远自洽，不会出现"备注写 2027 届、倒计时按 2028 届数"的分裂。
    2. Goal 没有 ``exam_date`` -> 用 :func:`default_exam_year` 兜底，标 ``is_estimated``。

    Args:
        goal: ``models.Goal`` 实例或 None。
    Returns:
        含 ``exam_year / exam_date / is_official / is_estimated / days_left`` 等字段的 dict。
    """
    today = local_today()

    if goal is not None and getattr(goal, "exam_date", None) is not None:
        stored = goal.exam_date
        if isinstance(stored, datetime.datetime):
            stored = stored.date()
        # 以存量日期为准，届数按规则反推 —— 保证两者自洽
        year = exam_year_of(stored)
        official = year in OFFICIAL_EXAM_DATES and OFFICIAL_EXAM_DATES[year] == (
            stored.year, stored.month, stored.day,
        )
        return {
            "exam_year": year,
            "exam_date": stored.isoformat(),
            "is_official": official,
            # 存量日期存在，但它与"今天该不该考这一届"未必一致，故标 estimated=False 之外的提示
            "is_estimated": False,
            "days_left": (stored - today).days,
            "source": "用户配置" if official else "用户配置（该日期与教育部公布值不一致，请核对）",
            "official_date": datetime.date(*OFFICIAL_EXAM_DATES[year]).isoformat() if year in OFFICIAL_EXAM_DATES else None,
            "signup_hint": f"{stored.year} 年 10 月中下旬（以研招网公告为准）",
        }

    year = default_exam_year(today)
    exam_date, official = resolve_exam_date(year)
    return {
        "exam_year": year,
        "exam_date": exam_date.isoformat(),
        "is_official": official,
        "is_estimated": True,
        "days_left": (exam_date - today).days,
        "source": "未配置，按当前时间推断" + ("（官方已公布）" if official else "（估算）"),
        "official_date": datetime.date(*OFFICIAL_EXAM_DATES[year]).isoformat() if year in OFFICIAL_EXAM_DATES else None,
        "signup_hint": f"{exam_date.year} 年 10 月中下旬（以研招网公告为准）",
    }