"""北京时间日界工具的单测（P1-C1）。

这一层是「不动行为」的基础设施：本文件只锁 ``utils/timeutil`` 自身的语义，
不改任何调用点。要锁的三件事：

1. **边界**：UTC 16:00 == 北京次日零点，跨过这条线才算换天；
2. **宽限**：streak 的跨零点宽限移动的是「日的起点」，不改时间戳；
3. **两个后端同一个口径**：``day_bucket_expr`` 在 SQLite 与 PG 上必须给出
   与 Python 侧 :func:`local_date_of` 完全一致的分桶结果。

第 3 条是真凶。旧代码里 15 个调用点各自用 ``datetime.date.today()`` 或
``func.date(col)`` 切日，切的是本机日/UTC 日，而列里存的是 naive UTC ——
``tests/test_insight.py`` 在本机 00:05 跑会失败、``TZ=UTC`` 下通过，就是这个错位。
"""

import datetime as dt

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, Table, create_engine, func, select, text

from core.db_session import IS_POSTGRES, engine as app_engine
from utils import timeutil as tu

# 每个瞬间都标注它落在北京的哪一天，方便读失败信息。
INSTANTS = [
    dt.datetime(2026, 10, 16, 12, 0),  # 北京 20:00 → 10-16
    dt.datetime(2026, 10, 16, 15, 0),  # 北京 23:00 → 10-16（会话时区敏感点）
    dt.datetime(2026, 10, 16, 15, 59),  # 北京 23:59 → 10-16
    dt.datetime(2026, 10, 16, 16, 0),  # 北京次日 00:00 → 10-17
    dt.datetime(2026, 10, 16, 17, 59),  # 北京 01:59 → 10-17（grace=120 时回落 10-16）
    dt.datetime(2026, 10, 17, 1, 30),  # 北京 09:30 → 10-17
    dt.datetime(2026, 10, 17, 15, 59),  # 北京 23:59 → 10-17
    dt.datetime(2026, 10, 17, 16, 0),  # 北京次日 00:00 → 10-18
]

# 10-16 15:00 UTC 在北京是 23:00（10-16），在东京是次日 00:00（10-17）：
# 用它来证明分桶结果不随 PG 会话时区漂移。
assert tu.local_date_of(dt.datetime(2026, 10, 16, 15, 0)) == dt.date(2026, 10, 16)


def _probe_table(timezone_col: bool) -> tuple[MetaData, Table]:
    meta = MetaData()
    col_type = DateTime(timezone=timezone_col)
    tbl = Table(
        "day_bucket_probe",
        meta,
        Column("id", Integer, primary_key=True),
        Column("ts", col_type),
    )
    return meta, tbl


def _as_date(value):
    """分桶结果必须是 ``datetime.date``：SQLite 原生返回字符串，靠 ``day_bucket_expr``
    上挂的 ``Date`` 类型规整。这里断言而不是兼容，防止规整丢失后 12 个调用点各自踩坑。"""
    assert type(value) is dt.date, f"day_bucket_expr 未规整成 date，实际 {type(value)}"
    return value


def _buckets(*, driver: str, grace_minutes: int = 0, timezone_col: bool = True) -> dict:
    """在同一条时间序列上跑 SQL 分桶，返回 ``{naive UTC 瞬间: 日}``。"""
    if driver == "sqlite":
        eng = create_engine("sqlite://")
    else:
        eng = app_engine  # conftest 已把 PG_DATABASE 改写为 kaoyan_test
    meta, tbl = _probe_table(driver == "postgresql" and timezone_col)
    meta.drop_all(eng, tables=[tbl])
    meta.create_all(eng, tables=[tbl])
    try:
        # 写入用默认会话（connect args 把 timezone 钉在 UTC），naive 值即按 UTC 落库。
        with eng.begin() as conn:
            conn.execute(
                tbl.insert(),
                [{"id": i, "ts": value} for i, value in enumerate(INSTANTS)],
            )
        with eng.begin() as conn:
            if driver == "postgresql":
                # 读取前故意把会话时区改成 +09:00：正确的分桶不该受影响。
                conn.execute(text("SET LOCAL TIME ZONE 'Asia/Tokyo'"))
            rows = conn.execute(
                select(
                    tbl.c.ts,
                    tu.day_bucket_expr(tbl.c.ts, conn, grace_minutes=grace_minutes),
                )
            ).fetchall()
    finally:
        meta.drop_all(eng, tables=[tbl])
    return {tu.to_naive_utc(row[0]): _as_date(row[1]) for row in rows}


def _expected(*, grace_minutes: int = 0) -> dict:
    return {value: tu.local_date_of(value, grace_minutes=grace_minutes) for value in INSTANTS}


# --------------------------------------------------------------------------- #
# 1. 边界与宽限
# --------------------------------------------------------------------------- #
def test_day_boundary_is_beijing_midnight():
    assert tu.local_date_of(dt.datetime(2026, 10, 16, 15, 59)) == dt.date(2026, 10, 16)
    assert tu.local_date_of(dt.datetime(2026, 10, 16, 16, 0)) == dt.date(2026, 10, 17)


def test_statistical_timezone_is_shanghai_without_dst():
    assert tu.tz_offset_minutes() == 480
    assert tu._has_dst(tu.local_tz()) is False


def test_grace_moves_the_day_start_not_the_timestamp():
    value = dt.datetime(2026, 10, 16, 17, 59)  # 北京 10-17 01:59
    assert tu.local_date_of(value) == dt.date(2026, 10, 17)
    # 2 小时宽限：北京 00:00~02:00 的行为记在前一天，日的起点也整体前移到北京 02:00
    assert tu.local_date_of(value, grace_minutes=120) == dt.date(2026, 10, 16)
    assert tu.local_day_start_utc(value) == dt.datetime(2026, 10, 16, 16, 0)
    assert tu.local_day_start_utc(value, grace_minutes=120) == dt.datetime(2026, 10, 15, 18, 0)
    day, start, end = tu.local_day_window(value, grace_minutes=120)
    assert (day, start, end) == (
        dt.date(2026, 10, 16),
        dt.datetime(2026, 10, 15, 18, 0),
        dt.datetime(2026, 10, 16, 18, 0),
    )
    assert start <= value < end, "宽限只移动窗口，不改变瞬间所属关系"


def test_streak_grace_is_one_hour_per_spec():
    """建设标准 01 §1.3.2 的口径：北京 00:00~01:00 的学习记在前一天（grace=60）。"""
    before_midnight = dt.datetime(2026, 10, 16, 15, 30)  # 北京 23:30
    after_midnight = dt.datetime(2026, 10, 16, 16, 30)  # 北京 00:30（次日）
    late_night = dt.datetime(2026, 10, 16, 17, 30)  # 北京 01:30（超出宽限）

    assert tu.local_date_of(before_midnight, grace_minutes=60) == dt.date(2026, 10, 16)
    assert tu.local_date_of(after_midnight, grace_minutes=60) == dt.date(2026, 10, 16)
    assert tu.local_date_of(late_night, grace_minutes=60) == dt.date(2026, 10, 17)


@pytest.mark.parametrize("value", INSTANTS)
def test_window_contains_exactly_its_own_day(value):
    day, start, end = tu.local_day_window(value)
    assert start <= value < end, "窗口必须右开且包含该瞬间"
    assert end - start == dt.timedelta(days=1)
    assert day == tu.local_date_of(value)
    # 窗口两端各自归属：起点算这天，终点算下一天
    assert tu.local_date_of(start) == day
    assert tu.local_date_of(end) == day + dt.timedelta(days=1)


def test_window_for_day_is_the_range_primitive():
    """「按日范围取数」的唯一出口：给定北京日，返回 DB 里可用的 naive UTC 区间。"""
    assert tu.local_window_for_day(dt.date(2026, 10, 17)) == (
        dt.datetime(2026, 10, 16, 16, 0),
        dt.datetime(2026, 10, 17, 16, 0),
    )
    start, end = tu.local_window_for_day(dt.date(2026, 10, 17), grace_minutes=60)
    assert (start, end) == (dt.datetime(2026, 10, 16, 17, 0), dt.datetime(2026, 10, 17, 17, 0))
    assert end - start == dt.timedelta(days=1)


def test_local_today_ignores_machine_timezone():
    """``local_today`` 必须等于「当前 UTC 瞬间按北京切日」，而不是 ``date.today()``。"""
    assert tu.local_today() == tu.local_date_of(tu.utcnow())


# --------------------------------------------------------------------------- #
# 2. SQL 分桶：两个后端与 Python 侧同口径
# --------------------------------------------------------------------------- #
def test_sqlite_day_bucket_matches_python():
    assert _buckets(driver="sqlite") == _expected()


def test_sqlite_day_bucket_matches_python_with_grace():
    assert _buckets(driver="sqlite", grace_minutes=120) == _expected(grace_minutes=120)


def test_zero_offset_timezone_is_not_mistaken_for_beijing(monkeypatch):
    """``timedelta(0)`` 是假值：``utcoffset() or 兜底`` 会把 UTC 静默变成 +08:00。"""
    monkeypatch.setattr(tu, "KAOYAN_TZ_NAME", "Etc/UTC")
    assert tu.tz_offset_minutes() == 0
    assert tu.local_date_of(dt.datetime(2026, 10, 16, 16, 0)) == dt.date(2026, 10, 16)


def test_zero_offset_does_not_render_null_modifier(monkeypatch):
    """偏移为 0（KAOYAN_TZ=UTC）时不能渲染出 ``date(col, NULL)`` —— 那会全表 NULL。"""
    monkeypatch.setattr(tu, "KAOYAN_TZ_NAME", "Etc/UTC")
    from sqlalchemy import column
    from sqlalchemy.dialects import sqlite

    sqlite_eng = create_engine("sqlite://")
    expr = tu.day_bucket_expr(column("ts"), sqlite_eng)
    rendered = str(expr.compile(dialect=sqlite.dialect()))
    assert rendered == "date(ts)", rendered
    assert "NULL" not in rendered

    # 行为侧同样确认一次：零偏移就是纯 UTC 日，且没有一行变成 None
    assert _buckets(driver="sqlite") == {v: v.date() for v in INSTANTS}


@pytest.mark.skipif(not IS_POSTGRES, reason="测试库不是 PostgreSQL")
def test_postgres_day_bucket_matches_python():
    assert _buckets(driver="postgresql") == _expected()


@pytest.mark.skipif(not IS_POSTGRES, reason="测试库不是 PostgreSQL")
def test_postgres_day_bucket_matches_python_with_grace():
    assert _buckets(driver="postgresql", grace_minutes=120) == _expected(grace_minutes=120)


@pytest.mark.skipif(not IS_POSTGRES, reason="测试库不是 PostgreSQL")
def test_postgres_and_sqlite_agree():
    """跨后端一致性：同一批瞬间，两种方言必须给出同一张「日」表。"""
    for grace in (0, 120):
        assert _buckets(driver="postgresql", grace_minutes=grace) == _buckets(
            driver="sqlite", grace_minutes=grace
        )


@pytest.mark.skipif(not IS_POSTGRES, reason="测试库不是 PostgreSQL")
def test_pg_time_columns_are_all_timestamptz():
    """``day_bucket_expr`` 的 PG 分支以 ``timestamptz`` 为前提（先拍成 naive UTC 再偏移）。

    若将来有人把时间列改成 ``timestamp without time zone``，那条表达式会重新
    依赖会话时区，分桶可能在某些时区下静默错一天。这里把隐式前提变成显式红线。
    """
    with app_engine.connect() as conn:
        bad = conn.execute(
            text(
                "select table_name, column_name from information_schema.columns "
                "where table_schema='public' and data_type='timestamp without time zone' "
                "order by 1, 2 limit 20"
            )
        ).fetchall()
    assert not bad, f"PG 侧出现 naive timestamp 列，day_bucket_expr 会依赖会话时区：{bad}"


# --------------------------------------------------------------------------- #
# 2b. 聚合写法：SELECT 与 GROUP BY 各建一次表达式也要能对上
# --------------------------------------------------------------------------- #
def _expected_counts(*, grace_minutes: int = 0) -> dict:
    counts: dict = {}
    for value in INSTANTS:
        day = tu.local_date_of(value, grace_minutes=grace_minutes)
        counts[day] = counts.get(day, 0) + 1
    return counts


def _group_counts(*, driver: str) -> dict:
    eng = create_engine("sqlite://") if driver == "sqlite" else app_engine
    meta, tbl = _probe_table(driver == "postgresql")
    meta.drop_all(eng, tables=[tbl])
    meta.create_all(eng, tables=[tbl])
    try:
        with eng.begin() as conn:
            conn.execute(tbl.insert(), [{"id": i, "ts": v} for i, v in enumerate(INSTANTS)])
        with eng.begin() as conn:
            # 两处**各自**调用一次 day_bucket_expr：真实调用点就是这么写的
            # （learning_analytics_service 的 select + group_by）。
            sel = select(
                tu.day_bucket_expr(tbl.c.ts, conn).label("d"),
                func.count(tbl.c.id),
            ).group_by(tu.day_bucket_expr(tbl.c.ts, conn))
            rows = conn.execute(sel).fetchall()
    finally:
        meta.drop_all(eng, tables=[tbl])
    return {_as_date(row[0]): int(row[1]) for row in rows}


@pytest.mark.parametrize("driver", ["sqlite", "postgresql"])
def test_day_bucket_expr_group_by_matches_python(driver):
    if driver == "postgresql" and not IS_POSTGRES:
        pytest.skip("测试库不是 PostgreSQL")
    assert _group_counts(driver=driver) == _expected_counts()


def test_day_bucket_expr_shift_is_inlined_not_bound():
    """偏移量必须内联成 SQL 字面量。

    走绑定参数时，SELECT 与 GROUP BY 里的同一条表达式会拿到不同的 ``$n`` 序号，
    PG 判定「该列不在 GROUP BY 中」直接 500（实测 /api/analytics/traces）。
    """
    from sqlalchemy import column
    from sqlalchemy.dialects import postgresql, sqlite

    pg_eng = create_engine("postgresql+psycopg://u:p@127.0.0.1/none")  # 只建引擎，不连接
    pg = tu.day_bucket_expr(column("ts"), pg_eng).compile(dialect=postgresql.dialect())
    assert not pg.params, f"PG 分桶表达式仍在绑定参数：{pg.params}"
    assert "make_interval(0, 0, 0, 0, 0, 480, 0)" in str(pg), str(pg)

    lite = tu.day_bucket_expr(column("ts"), create_engine("sqlite://")).compile(
        dialect=sqlite.dialect()
    )
    assert not lite.params, f"SQLite 分桶表达式仍在绑定参数：{lite.params}"
    assert str(lite) == "date(ts, '+480 minutes')", str(lite)


# --------------------------------------------------------------------------- #
# 3. 带夏令时的时区必须显式拒绝，而不是静默错一天
# --------------------------------------------------------------------------- #
def test_dst_timezone_is_rejected_not_silently_wrong(monkeypatch):
    monkeypatch.setattr(tu, "KAOYAN_TZ_NAME", "America/New_York")
    from sqlalchemy import column

    with pytest.raises(NotImplementedError):
        tu.day_bucket_expr(column("ts"))
