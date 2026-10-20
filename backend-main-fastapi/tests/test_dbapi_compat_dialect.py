"""跨方言改写层（services/dbapi_compat）纯函数单测。

为什么不放进集成测试
--------------------
``adapt_dml`` / ``adapt_sql`` 是**纯字符串改写**，不触碰数据库。把它们单列成
纯函数测试有两个好处：
  1. 数据库掉线时仍可验证（不需要连接）；
  2. 改写规则一旦被误删，这里立刻红，比"某个 PG 端点 500"好定位得多。

背景
----
项目是 SQLite / PostgreSQL **双底座**。存量代码里残留大量 SQLite 专有写法，
靠 ``wrap_conn`` 在**执行前**统一改写。下面这些规则每一条都对应一次真实故障：
  * ``INSERT OR IGNORE`` —— PG 无此语法；
  * ``IFNULL()`` —— PG 只有 ``COALESCE``；
  * ``datetime('now')`` —— PG 用 ``now()``；
  * ``IS ?``（可空参数判等）—— PG 只认 ``IS NULL`` / ``IS TRUE`` 这类固定右侧，
    ``IS $1`` 直接语法错误；实际踩在 ``notice_dedup.upsert_notice`` 的
    ``WHERE school_id IS ?`` 上。
"""
from __future__ import annotations

from services.dbapi_compat import adapt_dml, adapt_sql, convert_placeholders


class _FakePgConn:
    """PG 连接替身。``is_sqlite`` 对未知对象返回 False → 触发改写分支。"""

    __module__ = "psycopg"


_PG = _FakePgConn()


def _pg(sql: str) -> str:
    return adapt_sql(sql, _PG)


# --------------------------------------------------------------------------- #
# INSERT OR IGNORE → ON CONFLICT DO NOTHING
# --------------------------------------------------------------------------- #
def test_insert_or_ignore_becomes_on_conflict():
    out = _pg("INSERT OR IGNORE INTO kaoyan_notices (a, b) VALUES (?,?)")
    assert "OR IGNORE" not in out
    assert out.startswith("INSERT INTO")
    assert out.endswith("ON CONFLICT DO NOTHING")


def test_insert_or_ignore_with_trailing_semicolon():
    out = _pg("INSERT OR IGNORE INTO t (a) VALUES (?);")
    assert out.endswith("ON CONFLICT DO NOTHING;")


def test_existing_on_conflict_is_not_duplicated():
    out = _pg("INSERT INTO t (a) VALUES (?) ON CONFLICT (a) DO NOTHING")
    assert out.count("ON CONFLICT") == 1


# --------------------------------------------------------------------------- #
# 函数与字面量
# --------------------------------------------------------------------------- #
def test_ifnull_becomes_coalesce():
    assert "COALESCE(" in _pg("SELECT IFNULL(a, 1) FROM t")
    assert "IFNULL" not in _pg("SELECT ifnull(a, 1) FROM t")


def test_datetime_now_becomes_now():
    assert "now()" in _pg("UPDATE t SET dt = datetime('now')")
    assert "datetime(" not in _pg("UPDATE t SET dt = datetime('now', 'localtime')")


# --------------------------------------------------------------------------- #
# IS ? / IS NOT ?  →  IS [NOT] DISTINCT FROM
# --------------------------------------------------------------------------- #
def test_is_param_becomes_is_not_distinct_from():
    """SQLite 的 ``x IS ?`` 是 **NULL 安全相等**，等价 ``IS NOT DISTINCT FROM``。

    （旧断言写成 ``IS DISTINCT FROM``，方向反了：那是"不相等"，会让
    ``notice_dedup`` 的去重查询命中错误的行。实现侧 2026-10 已按语义修正。）
    """
    out = _pg("SELECT id FROM kaoyan_notices WHERE school_id IS ?")
    assert "IS NOT DISTINCT FROM" in out
    assert "%s" in out  # 占位符同时被改写


def test_is_not_param_becomes_is_distinct_from():
    out = _pg("SELECT id FROM t WHERE x IS NOT ?")
    assert "IS DISTINCT FROM" in out
    assert "IS NOT DISTINCT FROM" not in out


def test_is_null_is_untouched():
    """普通 ``IS NULL`` 不能被误伤 —— 两侧方言通用。"""
    out = _pg("SELECT 1 FROM t WHERE x IS NULL")
    assert out == "SELECT 1 FROM t WHERE x IS NULL"


# --------------------------------------------------------------------------- #
# 占位符与直通
# --------------------------------------------------------------------------- #
def test_placeholders_converted_only_on_pg():
    assert convert_placeholders("SELECT * FROM t WHERE a=? AND b=?") == \
        "SELECT * FROM t WHERE a=%s AND b=%s"
    # SQLite：adapt_sql 原样返回（conn=None 视为 SQLite）
    raw = "SELECT IFNULL(a,1) FROM t WHERE x IS ?"
    assert adapt_sql(raw) == raw


def test_adapt_sql_is_idempotent_for_placeholders():
    """改写后的 SQL 不应再次被占位符替换搞坏。"""
    once = _pg("SELECT 1 FROM t WHERE a=?")
    twice = adapt_sql(once, _PG)
    assert twice == once


def test_ddl_type_rewrite_still_works():
    """DDL 里的 DATETIME 类型仍要变成 TIMESTAMP。"""
    out = _pg("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, dt DATETIME)")
    assert "TIMESTAMP" in out
    assert "AUTOINCREMENT" not in out


def test_datetime_type_in_non_create_stmt_is_left_alone():
    """非 DDL 语句不做类型替换 —— 否则会把函数名 datetime 换成 TIMESTAMP。"""
    out = _pg("SELECT dt, created FROM t WHERE created >= ?")
    assert out == "SELECT dt, created FROM t WHERE created >= %s"


def test_adapt_dml_is_pure_string_transform():
    """adapt_dml 不依赖连接，可离线调用。"""
    assert adapt_dml("SELECT IFNULL(a,1)") == "SELECT COALESCE(a,1)"
