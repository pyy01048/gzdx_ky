"""统一时间规范工具（naive-UTC）。

背景
----
本项目数据库（SQLite）中的所有时间列都是 **naive**（`tzinfo is None`）的，
而代码里大量使用 `datetime.datetime.now(datetime.UTC)` 生成 **aware** 对象。
一旦两者相遇，就会抛出：

    TypeError: can't compare offset-naive and offset-aware datetimes

同时 `datetime` 这个名字极易被遮蔽：`from datetime import datetime` 之后，
`datetime.UTC` 会变成对**类**取属性，直接 `AttributeError`。

两种模式的适用场景
----------------
1) :func:`utcnow` —— **naive UTC**，本项目与数据库交互的**默认**选择。
   任何时候该值会被存进 DB，或与 DB 读回的列做比较（`<=` / `>=` / `sort`），
   都必须用它。DB 里的数据就是 naive UTC，两者才能对齐。

2) :func:`utcnow_aware` —— **aware UTC**，仅用于「纯展示」或「与外部系统
   （HTTP API、ISO8601 报文）交互」的场景：带时区的ISO 字符串能明确表达
   偏移量，前端 `new Date()` 解析也更可靠。**禁止**把它写入 DB 或用于比较。

历史遗留说明
------------
早期代码用 `datetime.datetime.now(datetime.UTC)` 的"意图"其实是 UTC 时间点，
但由于 DB 列是naive，实际存进去的是带 +00:00 偏移的 aware 值 —— SQLite
虽然接受，但读回来时 tzinfo 已丢失，退化成本地时间语义的 naive 值，
这正是"读回来的时间和刚写进去的不一样"的隐性bug 根源。本模块统一按 naive UTC 处理。
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

__all__ = [
    "utcnow",
    "utcnow_aware",
    "to_naive_utc",
    "to_aware_utc",
    "ensure_naive",
    "day_start_naive",
    "add_days",
]

UTC = timezone.utc


def utcnow() -> datetime:
    """返回当前 **naive UTC** 时间（tzinfo=None）。

    这是本项目所有与数据库时间列交互场景的**唯一正确入口**。

    Examples:
        >>> now = utcnow()
        >>> now.tzinfo is None
        True
        >>> db.query(X).filter(X.ts <= now).count()  # 不会抛 TypeError
    """
    return datetime.now(UTC).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """返回当前 **aware UTC** 时间。

    仅用于纯展示 / 与外部 ISO8601 接口交互。**不要**写入本项目的 DB，
    也不要用于与 DB 读回的列做比较。
    """
    return datetime.now(UTC)


def to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """把任意 datetime（含 aware）统一转成 naive UTC。

    - None 原样返回，方便链式处理可空的时间列。
    - naive 输入按"已经是 UTC"处理，只剥掉 tzinfo（不做时区换算）。
    - aware 输入先换算到 UTC 再剥掉 tzinfo。

    Examples:
        >>> from datetime import datetime, timezone, timedelta
        >>> to_naive_utc(datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=8))))
        datetime.datetime(2026, 1, 1, 4, 0)
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(tzinfo=None)


def to_aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    """把任意 datetime 统一转成 aware UTC（用于展示/外部接口）。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def ensure_naive(value: Optional[datetime]) -> Optional[datetime]:
    """确保返回值是 naive（便于写入 DB 或参与比较）。

    与 :func:`to_naive_utc` 语义一致，保留此别名是为了让调用点意图更直白。
    """
    return to_naive_utc(value)


def day_start_naive(value: Optional[datetime] = None) -> datetime:
    """返回当天 00:00:00 的 naive UTC 时间戳，用于「今日」类统计。

    Examples:
        >>> day_start_naive(datetime(2026, 3, 5, 13, 45)).isoformat()
        '2026-03-05T00:00:00'
    """
    base = to_naive_utc(value) if value is not None else utcnow()
    return base.replace(hour=0, minute=0, second=0, microsecond=0)


def add_days(value: datetime, days: float) -> datetime:
    """在naive/aware 皆可的 datetime 上加天数并保持 tzinfo 一致。

    典型用法：``next_review = add_days(utcnow(), 7)``
    """
    return value + timedelta(days=days)