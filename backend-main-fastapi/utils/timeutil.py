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

「日」的口径（2026-10-16 与用户确认：按北京时间切自然日）
--------------------------------------------------------
存储一律 UTC，但**统计口径的「今天」是北京的自然日**，不是 UTC 日。
两者相差 8 小时：UTC 16:00 才是北京的次日零点。凡是「今日/本周/连续打卡」
这类语义都必须走本模块的 ``local_*`` 出口，不要在调用点自己
``datetime.date.today()`` —— 那是本机时区，且与 naive UTC 列不同源，
本地 00:05 运行时就会把昨天的流水算进今天（实测：tests/test_insight.py
在 00:05 失败、TZ=UTC 下通过）。

对应关系（``KAOYAN_TZ=Asia/Shanghai``，偏移 +480 分钟）：

    北京 10-17 00:00  ==  UTC 10-16 16:00  ==  DB 里存的 naive 值 2026-10-16 16:00

``grace_minutes`` 是给连续打卡留的**跨零点宽限**（建设标准 01 §1.3.2：
北京 00:00~01:00 的学习记在前一天，所以调用点传 ``grace_minutes=60``）。
宽限改变的是**日的起点**，不是时间戳：``grace_minutes=60`` 表示一天从北京
01:00 开始算，边界前 1 小时内发生的行为仍归入前一天。
**当前打卡/连续天数一律不使用宽限**（grace=0，理由见 ``STREAK_GRACE_MINUTES``
上方注释与 ``services/study_calendar`` 的模块 docstring）；本模块保留该参数
是因为它对所有 ``local_*`` 出口都成立，单测也在两种取值下各跑一遍。

历史遗留说明
------------
早期代码用 `datetime.datetime.now(datetime.UTC)` 的"意图"其实是 UTC 时间点，
但由于 DB 列是naive，实际存进去的是带 +00:00 偏移的 aware 值 —— SQLite
虽然接受，但读回来时 tzinfo 已丢失，退化成本地时间语义的 naive 值，
这正是"读回来的时间和刚写进去的不一样"的隐性bug 根源。本模块统一按 naive UTC 处理。
"""

import os
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Optional

__all__ = [
    "utcnow",
    "utcnow_aware",
    "naive_utc_iso",
    "to_naive_utc",
    "to_aware_utc",
    "iso_utc_z",
    "ensure_naive",
    "day_start_naive",
    "add_days",
    # 北京时间日界
    "KAOYAN_TZ_NAME",
    "STREAK_GRACE_MINUTES",
    "local_tz",
    "tz_offset_minutes",
    "local_now",
    "local_today",
    "local_date_of",
    "local_day_start_utc",
    "local_day_end_utc",
    "local_window_for_day",
    "local_range_utc",
    "local_day_window",
    "day_bucket_expr",
    "day_bucket_text_expr",
]

UTC = timezone.utc

#: 统计口径的时区名。可用 ``KAOYAN_TZ`` 覆盖（默认北京时间）。
KAOYAN_TZ_NAME = (os.environ.get("KAOYAN_TZ", "") or "Asia/Shanghai").strip()

#: 北京时间的固定偏移；``zoneinfo`` 数据缺失时用它兜底（中国无夏令时，值恒定）。
_CN_OFFSET = timedelta(hours=8)

#: 连续打卡的跨零点宽限（分钟）。建设标准 01 §1.3.2 的原文是「跨零点 2 小时宽限
#: （即 23:00~次日 01:00 的学习记在前一天）」—— 23:00~24:00 本来就属于前一天，
#: 真正越界的只有 00:00~01:00 这一小时，所以落地值是 60 而不是 120。
#:
#: **当前产品口径不使用它**（2026-10-16 决定，见 services/study_calendar 模块
#: docstring）：打卡一律按北京自然日，日界不给宽限。理由是「今日」只能有一个
#: 定义——台账按宽限切日、KPI/热力图按自然日切日的话，同一个屏幕上的今日专注
#: 分钟和连续打卡会互相矛盾。宽限机制本身保留（本模块与单测仍在），
#: 若将来要恢复 §1.3.2，必须连台账一起改，不许只在某个调用点加。
#: 任何调用点都不允许自己另写一个宽限分钟数。
STREAK_GRACE_MINUTES = 60


def utcnow() -> datetime:
    """返回当前 **naive UTC** 时间（tzinfo=None）。

    这是本项目所有与数据库时间列交互场景的**唯一正确入口**。

    Examples:
        >>> now = utcnow()
        >>> now.tzinfo is None
        True

    ``db.query(X).filter(X.ts <= now)`` 因此不会抛 TypeError。
    """
    return datetime.now(UTC).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """返回当前 **aware UTC** 时间。

    仅用于纯展示 / 与外部 ISO8601 接口交互。**不要**写入本项目的 DB，
    也不要用于与 DB 读回的列做比较。
    """
    return datetime.now(UTC)


def naive_utc_iso() -> str:
    """写进 **TEXT 时间列/字段** 的标准值：naive UTC、ISO「T」分隔、秒精度。

    为什么需要一个专用出口（而不是各调用点自己 ``strftime``）：
    1. ``utils/response.py`` 的 ``UtcZJSONResponse`` 只给形如
       ``2026-10-16T16:00:00`` 的串补 ``Z``；空格分隔的 ``2026-10-16 16:00:00``
       不匹配，前端 ``new Date()`` 会按**本地**时间解析。所以「存储格式」直接
       决定「出参有没有时区标记」，必须是带 ``T`` 的 ISO。
    2. 历史上这些列用的是 ``datetime.now()``（北京墙钟），既比 UTC 列早 8 小时，
       又因为无 ``T`` 而不会被补 ``Z``——两处口径同时错。
    3. 展示给用户的「今天/昨天」一律是北京时间，由前端按本地时区渲染，或由后端
       用 :func:`local_date_of` 归日；**不靠**写一个本地墙钟串进去。

    Examples:
        >>> s = naive_utc_iso()
        >>> len(s), s[10]
        (19, 'T')
    """
    return utcnow().isoformat(timespec="seconds")


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


def iso_utc_z(value: Optional[datetime]) -> Optional[str]:
    """把 datetime 序列化成 **带 Z 的 ISO 8601 UTC 串**，用于接口出参。
    为什么要有这个出口：库里是 naive UTC，FastAPI 默认编码出来是
    ``2026-10-16T16:00:00``（无偏移），JS ``Date`` 会按本地时间解析，北京用户
    看什么都早 8 小时。凡是自己 ``strftime`` 拼时间串塞进响应的地方，都必须走
    这里 —— 应用层默认响应类（utils/response.py:UtcZJSONResponse）只能兜住
    ORM/Pydantic 交出来的 datetime，兜不住已经是字符串的值。

    Examples:
        >>> from datetime import datetime, timezone, timedelta
        >>> iso_utc_z(datetime(2026, 10, 16, 16, 0))                      # naive = UTC
        '2026-10-16T16:00:00Z'
        >>> iso_utc_z(datetime(2026, 10, 17, 0, 0, tzinfo=timezone(timedelta(hours=8))))
        '2026-10-16T16:00:00Z'
    """
    if value is None:
        return None
    return to_aware_utc(value).isoformat().replace("+00:00", "Z")


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


# ---------------------------------------------------------------------------
# 北京时间日界（统计口径）
# ---------------------------------------------------------------------------


def _utc_offset(tz: tzinfo, when: datetime) -> timedelta:
    return when.astimezone(tz).utcoffset() or timedelta(0)


def _has_dst(tz: tzinfo) -> bool:
    """时区在一年内的偏移是否会变化（夏令时）。

    北京恒定 +08:00，所以本模块的「加上固定分钟数再截断到日」成立。若有人把
    ``KAOYAN_TZ`` 设成带夏令时的时区，固定偏移会在换季那天错一整天 —— 这种情况
    必须显式报错，而不是静默给出偏移一天的统计。
    """
    jan = _utc_offset(tz, datetime(2026, 1, 15, 12, tzinfo=UTC))
    jul = _utc_offset(tz, datetime(2026, 7, 15, 12, tzinfo=UTC))
    return jan != jul


def local_tz() -> tzinfo:
    """返回 ``KAOYAN_TZ`` 对应的 tzinfo。

    本机的 tzdata 是 pip 包（操作系统不提供 zoneinfo），``ZoneInfo`` 可能
    找不到 ``Asia/Shanghai``，此时退化为固定 +08:00。中国无夏令时，退化结果
    与真实时区等价，所以这里是安全的兜底而不是猜测。
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(KAOYAN_TZ_NAME)
    except Exception:  # zoneinfo 不可用 / tz 名写错：宁可退回固定偏移，也不要整站崩
        return timezone(_CN_OFFSET)


def tz_offset_minutes() -> int:
    """当前时区相对 UTC 的偏移分钟数（北京 = 480，UTC = 0）。

    注意 ``timedelta(0)`` 是**假值**，绝不能用 ``utcoffset() or 兜底`` —— 那样
    零偏移时区（UTC）会被静默当成 +08:00，整整错 8 小时（单测锁过这条）。
    """
    tz = local_tz()
    delta = datetime.now(UTC).astimezone(tz).utcoffset()
    if delta is None:  # 只有 naive tzinfo 才会给出 None，同样退回固定偏移
        delta = _CN_OFFSET
    return int(delta.total_seconds() // 60)


def _shift_delta(grace_minutes: int) -> timedelta:
    """把「偏移 + 宽限」折成单个 timedelta。

    日的边界 = 本地零点 + ``grace_minutes``。等价于给 UTC 值加上
    ``(tz_offset - grace)`` 分钟后截断到日 —— 见 :func:`day_bucket_expr`。
    """
    return timedelta(minutes=tz_offset_minutes() - int(grace_minutes))


def local_now(value: Optional[datetime] = None) -> datetime:
    """把 naive/aware UTC 时刻表示为本地 aware 时间（默认取当下）。"""
    base = to_aware_utc(value) if value is not None else utcnow_aware()
    return base.astimezone(local_tz())


def local_date_of(value: datetime, *, grace_minutes: int = 0) -> date:
    """DB 读回的 naive UTC 时刻属于哪个本地自然日。

    Examples:
        >>> from datetime import datetime
        >>> local_date_of(datetime(2026, 10, 16, 15, 59)).isoformat()
        '2026-10-16'
        >>> local_date_of(datetime(2026, 10, 16, 16, 0)).isoformat()
        '2026-10-17'
        >>> local_date_of(datetime(2026, 10, 16, 17, 59), grace_minutes=120).isoformat()
        '2026-10-16'
    """
    shift = to_naive_utc(value) + _shift_delta(grace_minutes)
    return shift.date()


def local_today(*, grace_minutes: int = 0) -> date:
    """「今天」——按 ``KAOYAN_TZ`` 的自然日，而不是本机时区或 UTC 日。

    这是替代 ``datetime.date.today()`` 的唯一入口。
    """
    return local_date_of(utcnow(), grace_minutes=grace_minutes)


def local_window_for_day(
    day: date, *, grace_minutes: int = 0
) -> tuple[datetime, datetime]:
    """给定一个本地自然日，返回它在 DB 里的 ``[起点, 终点)`` naive UTC 窗口。

    这是「按日范围取数」的最小原语：凡是要算「近 7 天」「上周」「本月第 N 天」
    这类**由日期推时间范围**的查询，都从这里出发，不要在调用点拼 ``combine``。

    Examples:
        >>> local_window_for_day(date(2026, 10, 17))[0].isoformat()
        '2026-10-16T16:00:00'
        >>> local_window_for_day(date(2026, 10, 17))[1].isoformat()
        '2026-10-17T16:00:00'
        >>> local_window_for_day(date(2026, 10, 17), grace_minutes=60)[0].isoformat()
        '2026-10-16T17:00:00'
    """
    boundary = datetime.combine(day, time.min, tzinfo=local_tz()) + timedelta(
        minutes=int(grace_minutes)
    )
    start = boundary.astimezone(UTC).replace(tzinfo=None)
    return start, start + timedelta(days=1)


def local_range_utc(
    day_from: date, day_to: date, *, grace_minutes: int = 0
) -> tuple[datetime, datetime]:
    """``[day_from, day_to)`` 若干本地日对应的 naive UTC 时间区间。

    ``day_to`` **不含**，所以正好配 ``col >= start, col < end``；同时它也是
    日期列（``Date`` 类型）的范围上界，两个口径同一个参数，不用再各算一遍。

    Examples:
        >>> local_range_utc(date(2026, 10, 11), date(2026, 10, 17))[0].isoformat()
        '2026-10-10T16:00:00'
        >>> local_range_utc(date(2026, 10, 11), date(2026, 10, 17))[1].isoformat()
        '2026-10-16T16:00:00'
    """
    return (
        local_window_for_day(day_from, grace_minutes=grace_minutes)[0],
        local_window_for_day(day_to, grace_minutes=grace_minutes)[0],
    )


def _day_of(value: Optional[datetime], *, grace_minutes: int) -> date:
    if value is None:
        return local_today(grace_minutes=grace_minutes)
    return local_date_of(value, grace_minutes=grace_minutes)


def local_day_start_utc(
    value: Optional[datetime] = None, *, grace_minutes: int = 0
) -> datetime:
    """返回 value 所在本地日的起点，表示为 **naive UTC**（可直接与 DB 列比较）。

    Examples:
        >>> # 北京 2026-10-17 这一天从 UTC 10-16 16:00 开始
        >>> local_day_start_utc(datetime(2026, 10, 17, 1, 30)).isoformat()
        '2026-10-16T16:00:00'
        >>> # 给 2 小时跨零点宽限时，起点推到北京 02:00 = UTC 18:00
        >>> local_day_start_utc(datetime(2026, 10, 17, 1, 30), grace_minutes=120).isoformat()
        '2026-10-16T18:00:00'
    """
    day = _day_of(value, grace_minutes=grace_minutes)
    return local_window_for_day(day, grace_minutes=grace_minutes)[0]


def local_day_end_utc(
    value: Optional[datetime] = None, *, grace_minutes: int = 0
) -> datetime:
    """本地日的**右开**边界（naive UTC）。配合 ``<`` 使用，避免跨日重复计数。"""
    day = _day_of(value, grace_minutes=grace_minutes)
    return local_window_for_day(day, grace_minutes=grace_minutes)[1]


def local_day_window(
    value: Optional[datetime] = None, *, grace_minutes: int = 0
) -> tuple[date, datetime, datetime]:
    """一次拿到 ``(日, 起点, 终点)``，写「今日」类查询的标准入口。

    返回的时间都是 naive UTC，可直接进 ``filter(col >= start, col < end)``。
    """
    day = _day_of(value, grace_minutes=grace_minutes)
    start, end = local_window_for_day(day, grace_minutes=grace_minutes)
    return day, start, end


def day_bucket_expr(column: Any, bind: Any = None, *, grace_minutes: int = 0) -> Any:
    """给 SQL 用的「按本地日分桶」表达式，两种后端各自实现，语义严格一致。

    做法是把列加上 ``(偏移-宽限)`` 分钟后截断到日：对 naive UTC 列而言，
    加 480 分钟就是北京时间的墙上时钟，截断即得北京自然日。

    之所以要分支：``AT TIME ZONE`` 只有 PG 支持，而 ``date(col, '+480 minutes')``
    只有 SQLite 支持，两边写死任一种都会在另一种后端静默给出错误日期。

    PG 分支刻意先 ``timezone('UTC', col)`` 把 ``timestamptz`` 拍成 naive UTC 再偏移，
    这样结果与 ``SET timezone`` 无关 —— 不依赖 ``core/db_session`` 恰好把会话时区
    钉在 UTC 这个隐式前提。``make_interval`` 的第 3 个参数是 **weeks**、第 6 个才是
    mins（写错一位就是几百小时，实测会把日期推后 20 天），所以这里必须传满 7 个位置。

    偏移量一律**内联成 SQL 字面量**（``text(...)``）而不是绑定参数：分桶表达式通常
    在 SELECT 和 GROUP BY 里各出现一次，参数化的话两处会拿到不同的 ``$n`` 序号，
    PG 判定「表达式不在 GROUP BY 中」直接报 ``GroupingError``（实测 /api/analytics/traces 500）。

    Args:
        column: 时间列（naive UTC 语义）。
        bind: Engine/Connection/Session，用于判定方言；省略时回落
            ``core.db_session.IS_POSTGRES``。

    返回值统一挂 ``Date`` 类型：SQLite 的 ``date()`` 原生给字符串、PG 给 ``date``
    对象，不规整的话 12 个分桶调用点要各自写一遍 ``fromisoformat``。
    规整只能用 ``type_coerce``（纯类型标注，不渲染 SQL）—— SQLite 里
    ``CAST('2026-10-17' AS DATE)`` 会被 affinity 规则截成整数 ``2026``，实测过。
    """
    from sqlalchemy import cast, func, text, type_coerce
    from sqlalchemy.types import Date

    tz = local_tz()
    if _has_dst(tz):
        raise NotImplementedError(
            f"day_bucket_expr 只支持固定偏移时区（当前 {KAOYAN_TZ_NAME} 含夏令时，"
            "按日分桶无法用单一偏移表达，请改用 local_day_window 逐日取数）"
        )
    minutes = int(_shift_delta(grace_minutes).total_seconds() // 60)

    if _is_postgres(bind):
        shifted = func.timezone(text("'UTC'"), column) + func.make_interval(
            *[text(str(v)) for v in (0, 0, 0, 0, 0, minutes, 0)]
        )
        return cast(shifted, Date)
    expr = (
        func.date(column, text(f"'{minutes:+d} minutes'"))
        if minutes
        else func.date(column)
    )
    return type_coerce(expr, Date)


def day_bucket_text_expr(column_sql: str, *, grace_minutes: int = 0) -> str:
    """给 **TEXT 时间列**（内容是 naive UTC 的 ISO 串）用的「按本地日归日」SQL 片段。

    与 :func:`day_bucket_expr` 同语义，区别只在输入：那条走 SQLAlchemy 表达式、
    面向 DB 里的 timestamp 列；本条返回**裸 SQL 片段**，面向 ``fetched_at`` 这类
    早期用 TEXT 存时间戳的列（``day_bucket_expr`` 在 PG 上会把 TEXT 隐式转成
    ``timestamptz`` 判定，直接报错）。

    两侧实现都先把串当 naive UTC 加上 ``(偏移-宽限)`` 分钟，再截断到日：

    * PG：``to_char((col::timestamp + interval 'N minutes')::date, 'YYYY-MM-DD')``
      —— 走 naive timestamp，不碰会话时区，也不依赖服务端装有 tzdata。
    * SQLite：``date(col, 'N minutes')`` —— 原生就认 ISO 串。

    返回统一是 ``'YYYY-MM-DD'`` 文本，可直接与 ``local_today().isoformat()``
    做字典序比较（字典序即时间序）。

    Args:
        column_sql: 列的 SQL 片段，**必须是代码内字面量**（本函数不做任何转义）。
    """
    tz = local_tz()
    if _has_dst(tz):
        raise NotImplementedError(
            f"day_bucket_text_expr 只支持固定偏移时区（当前 {KAOYAN_TZ_NAME} 含夏令时）"
        )
    minutes = int(_shift_delta(grace_minutes).total_seconds() // 60)

    if _is_postgres(None):
        shifted = (
            f"({column_sql})::timestamp"
            + (f" + interval '{minutes} minutes'" if minutes else "")
        )
        return f"to_char(({shifted})::date, 'YYYY-MM-DD')"
    modifier = f", '{minutes:+d} minutes'" if minutes else ""
    return f"date({column_sql}{modifier})"


def _is_postgres(bind: Any) -> bool:
    """判定当前应走 PG 分支：优先看传入对象的方言，其次看全局后端开关。"""
    dialect = getattr(bind, "dialect", None)
    name = getattr(dialect, "name", None)
    if name:
        return name == "postgresql"
    session_bind = getattr(bind, "get_bind", None)
    if callable(session_bind):
        try:
            return _is_postgres(session_bind())
        except Exception:
            pass
    from core.db_session import IS_POSTGRES

    return bool(IS_POSTGRES)