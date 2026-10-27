# -*- coding: utf-8 -*-
"""DBAPI 双底座兼容层（SQLite / PostgreSQL）。

背景（2026-10 全量迁移后实测）
------------------------------
项目有 30+ 个服务通过**原生 DBAPI 连接**执行 SQL：

    conn = db.connection().connection      # SQLAlchemy 底层裸连接
    conn.execute("... WHERE id = ?", (x,))
    conn.executescript(_SCHEMA_SQL)
    new_id = cur.lastrowid

在 SQLite 后端下这段代码成立；切到 PostgreSQL 后底层是 **psycopg**，
上述四处**全部失效**，实测报出的错误类型有：

  1. AUTOINCREMENT 语法错误（DDL 层）        → 见 ddl_compat.adapt_ddl
  2. `?` 占位符不识别（psycopg 只认 %s）      → 本模块 convert_placeholders
  3. `executescript` 不存在（psycopg 无此 API）→ 本模块 split_statements
  4. `lastrowid` 不存在/为 None              → 本模块 insert_returning_id
  5. `INSERT OR REPLACE/IGNORE` 语法错误      → 本模块 adapt_dml
  6. `IFNULL/IIF` 函数不存在                  → 本模块 adapt_dml
  7. `sqlite_master` 目录表不存在             → 本模块 table_exists / list_tables
  8. ENUM 列不能直接 LIKE                     → 本模块 见 docs 说明

设计原则
--------
* **按连接实测方言**，不看全局配置（避免"测试连 PG 但配置说 SQLite"的错配）。
* **SQLite 路径零成本直通**：所有函数在 SQLite 连接上原样返回，不引入行为变化。
* **不改业务 SQL 文本**：由本层在提交前改写，业务代码保持 SQLite 写法即可。

用法
----
    from services.dbapi_compat import (
        execute, executescript, insert_returning_id, table_exists, adapt_sql,
    )

    # 替代 conn.execute(sql, params)
    cur = execute(conn, "SELECT * FROM t WHERE id = ?", (1,))

    # 替代 conn.executescript(ddl)
    executescript(conn, _SCHEMA_SQL)

    # 替代 cur.lastrowid
    new_id = insert_returning_id(conn, "INSERT INTO t (a) VALUES (?)", ("x",))
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from services.ddl_compat import adapt_ddl, is_postgres, is_sqlite  # noqa: F401 复用方言判定

__all__ = [
    "is_sqlite",
    "is_postgres",
    "adapt_sql",
    "execute",
    "executescript",
    "insert_returning_id",
    "table_exists",
    "list_tables",
    "column_names",
    "add_column_if_missing",
    "wrap_conn",
]

# --------------------------------------------------------------------------- #
# 占位符转换：SQLite 的 ? / :name → psycopg 的 %s / %(name)s
# 关键难点：不能误伤字符串字面量里的 '?'，也不能把已存在的 %s 再转一遍。
# --------------------------------------------------------------------------- #
_QMARK = "?"


def _split_sql_segments(sql: str) -> list[tuple[str, bool]]:
    """把 SQL 切成 (片段, 是否字符串字面量) 序列，用于安全替换占位符。

    处理：单引号串（含 '' 转义）、双引号标识符、$tag$ 美元引用、-- 行注释、/* */ 块注释。
    """
    segs: list[tuple[str, bool]] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        # 单引号串
        if ch == "'":
            if buf:
                segs.append(("".join(buf), False)); buf = []
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2; continue
                    j += 1; break
                j += 1
            segs.append((sql[i:j], True)); i = j; continue
        # 双引号标识符
        if ch == '"':
            if buf:
                segs.append(("".join(buf), False)); buf = []
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2; continue
                    j += 1; break
                j += 1
            segs.append((sql[i:j], True)); i = j; continue
        # 行注释
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            if buf:
                segs.append(("".join(buf), False)); buf = []
            j = sql.find("\n", i)
            j = n if j < 0 else j
            segs.append((sql[i:j], True)); i = j; continue
        # 块注释
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            if buf:
                segs.append(("".join(buf), False)); buf = []
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            segs.append((sql[i:j], True)); i = j; continue
        buf.append(ch); i += 1
    if buf:
        segs.append(("".join(buf), False))
    return segs


def convert_placeholders(sql: str) -> str:
    """把 SQLite 风格的 ? 占位符转成 psycopg 的 %s。

    只替换代码片段中的 `?`，字符串字面量/注释里的 `?` 原样保留。
    `%` 需在 psycopg 里转义为 `%%`（仅当原 SQL 未使用 %s 风格时）。
    """
    out: list[str] = []
    for text, is_literal in _split_sql_segments(sql):
        if is_literal:
            out.append(text)
        else:
            # 已有 %s / %(name)s 的语句视为已是 PG 风格，不再转 ?
            if "%s" in text or re.search(r"%\([^)]+\)s", text):
                out.append(text)
            else:
                out.append(text.replace(_QMARK, "%s"))
    return "".join(out)


# --------------------------------------------------------------------------- #
# DML 改写：INSERT OR REPLACE / INSERT OR IGNORE / IFNULL / IIF
# --------------------------------------------------------------------------- #
_INSERT_OR_REPLACE = re.compile(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", re.I)
_INSERT_OR_IGNORE = re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.I)
_IFNULL = re.compile(r"\bIFNULL\s*\(", re.I)
_IIF = re.compile(r"\bIIF\s*\(", re.I)
_DATETIME_NOW = re.compile(r"\bdatetime\s*\(\s*'now'\s*(?:,\s*'localtime'\s*)?\)", re.I)
_STRFTIME = re.compile(r"\bstrftime\s*\(", re.I)
# SQLite 独有：``IS ?`` / ``IS NOT ?`` 用于可空参数判等（NULL 安全）。
# PostgreSQL 只认 ``IS NULL`` / ``IS TRUE`` 等固定右侧，`IS $1` 直接语法错误。
# 标准写法 ``IS NOT DISTINCT FROM`` 两侧方言都支持。
_IS_PARAM = re.compile(r"\bIS\s+(NOT\s+)?\?", re.I)

# SQLite 无原生 BOOLEAN，布尔列存 0/1，故 `WHERE enabled = 1` 是常规写法；
# PostgreSQL 是真正的 boolean 类型，与整数比较直接报
#   operator does not exist: boolean = integer
# 这是本项目**反复踩**的一类坑（completed=1 / enabled=1 / acked=0 / is_read=0 /
# is_active=1 / is_available=1 …… 前后修了十几处），故在适配层做兜底：
# 列名白名单 + 0/1 字面量 → FALSE/TRUE。白名单限定为已知布尔语义的列，
# 避免误伤普通整数列（如 `LIMIT 1`、`score = 0`）。
# ⚠️ 曾经的尝试与结论（勿重蹈）：
#
# 曾加过一条规则，把布尔列 `= 0/1` 自动改写成 `= FALSE/TRUE`，白名单包含
# is_available / is_active / enabled …… 结果**踩了大坑**：
#
#   同一列名在不同表里类型可以不同！
#     code_questions.is_available → INTEGER
#     quiz_questions.is_available → BOOLEAN
#   规则把 `code_questions WHERE is_available = 1` 改成了 `= TRUE`，
#   PG 直接报 `operator does not exist: integer = boolean`，
#   /api/codebank/* 四个端点全挂。
#
# **文本层适配拿不到表上下文，这类改写本质上不安全。**
# 正确做法：在源码里按表逐个写正确的字面量（SQLAlchemy 也不会帮你，
# 它的 bind 类型来自 ORM 定义，裸 SQL 完全靠自己）。
#
# 已核实类型（2026-10-16）：
#   boolean: kaoyan_alert_records.acked / phase_daily_reviews.completed /
#            kaoyan_subscriptions.enabled / watermark_lexicon.enabled /
#            exam_blueprints|milestones|subject_chapters|subjects|textbooks.is_active /
#            quiz_questions.is_available|is_junk / documents.is_junk /
#            kaoyan_notices.is_read|is_starred / answer_candidates.used_for_grading /
#            retrieval_gate_logs.would_abstain
#   integer: code_questions.is_available   ← 唯一的例外，务必用 = 1


def adapt_dml(sql: str) -> str:
    """把 SQLite 专有 DML 片段改写为 PostgreSQL 等价写法。

    可处理的改写：
      * `INSERT OR IGNORE INTO t ...` → `INSERT INTO t ... ON CONFLICT DO NOTHING`
        （需要 SQL 末尾已有分号或无尾随子句；带 ON CONFLICT 的复杂语句建议手工改）
      * `INSERT OR REPLACE INTO t ...` → 语义是 upsert，但缺冲突键信息，
        无法安全自动改写 —— **保留原样并记入告警**，由调用方补 ON CONFLICT。
      * `IFNULL(a, b)` → `COALESCE(a, b)`
      * `IIF(cond, a, b)` → 需要 CASE WHEN，形态复杂 —— 保留原样并告警。
      * `datetime('now')` → `now()`
      * `IS ?` / `IS NOT ?` → `IS [NOT] DISTINCT FROM ?`（SQLite 的可空参数判等写法，
        PG 只认 `IS NULL` / `IS TRUE` 这类固定右侧，`IS $1` 直接语法错误）
      * 布尔列 `= 0/1` → `= FALSE/TRUE`（列名白名单，防误伤普通整数列）
    """
    if _INSERT_OR_IGNORE.search(sql):
        sql = _INSERT_OR_IGNORE.sub("INSERT INTO", sql)
        # 追加 ON CONFLICT DO NOTHING（无现有 on conflict 时）
        if not re.search(r"\bON\s+CONFLICT\b", sql, re.I):
            if sql.rstrip().endswith(";"):
                sql = sql.rstrip()[:-1] + " ON CONFLICT DO NOTHING;"
            else:
                sql = sql + " ON CONFLICT DO NOTHING"
    sql = _IFNULL.sub("COALESCE(", sql)
    sql = _DATETIME_NOW.sub("now()", sql)
    if _IS_PARAM.search(sql):
        # SQLite ``x IS ?`` = NULL 安全相等（? 为 NULL 时等价 ``x IS NULL``）；
        # 正确 PG 改写为 ``IS NOT DISTINCT FROM``。注意方向：无 NOT 时补 NOT，
        # 有 NOT（``IS NOT ?``）时直接 ``IS DISTINCT FROM``。
        sql = _IS_PARAM.sub(
            lambda m: f"IS {'DISTINCT FROM' if m.group(1) else 'NOT DISTINCT FROM'} ?",
            sql,
        )
    return sql


_DDL_PREFIX = re.compile(
    r"^\s*(CREATE|ALTER|DROP|COMMENT|PRAGMA)\b", re.I
)
# 行注释 / 块注释前缀。DDL 脚本常以注释开头（本项目 notice_alert._DDL 就是），
# 而 ``split_statements`` 会把注释与紧随其后的 CREATE TABLE 切成同一条语句。
# 若直接用 ``^`` 判断前缀，这类语句会被误判成"不是 DDL"从而**跳过整个 DDL
# 改写** —— 症状是 AUTOINCREMENT / DATETIME 原样发到 PG，报
# ``syntax error at or near "AUTOINCREMENT"``（实测，整个通知告警模块
# 因此全端点 500）。判断前缀前必须先剥掉前导注释。
_LEADING_COMMENT = re.compile(
    r"^\s*(?:(?:--[^\n]*\n)|(?:/\*.*?\*/\s*))+",
    re.S,
)


def _looks_like_ddl(sql: str) -> bool:
    """语句是否像 DDL（剥掉前导注释后判断）。"""
    stripped = _LEADING_COMMENT.sub("", sql or "", count=1)
    return bool(_DDL_PREFIX.match(stripped))


def adapt_sql(sql: str, conn=None) -> str:
    """一站式适配：DDL + 占位符 + DML。SQLite 连接原样返回。"""
    if conn is None or is_sqlite(conn):
        return sql
    # DDL 改写只在像 DDL 的语句上跑。
    # 背景：本函数对**所有**语句生效（含 SELECT/UPDATE/INSERT），而 DDL 层的
    # 类型替换是无上下文文本替换（如 DATETIME → TIMESTAMP）。放任它跑在 DML 上
    # 会把函数调用 ``datetime('now')`` 里的函数名一并换掉，产出非法的
    # ``TIMESTAMP('now')``。真正的 DDL 调用方（CREATE 脚本）不受影响。
    # 注意：不能用裸 ``_DDL_PREFIX.match(sql)`` —— 带前导注释的 CREATE 语句
    # 会被漏判，从而跳过整段 DDL 改写（详见 _LEADING_COMMENT 的注释）。
    if _looks_like_ddl(sql):
        sql = adapt_ddl(sql, conn)
    sql = adapt_dml(sql)
    sql = convert_placeholders(sql)
    return sql


# --------------------------------------------------------------------------- #
# 执行封装
# --------------------------------------------------------------------------- #
def execute(conn, sql: str, params: Sequence[Any] | dict | None = None):
    """执行单条 SQL，自动适配方言与占位符。返回游标。"""
    cur = conn.cursor()
    cur.execute(adapt_sql(sql, conn), params)
    return cur


def split_statements(script: str) -> list[str]:
    """按分号切分脚本，跳过字符串字面量与注释内的分号。

    用于替代 psycopg 缺失的 executescript。
    """
    stmts: list[str] = []
    buf: list[str] = []
    for text, is_literal in _split_sql_segments(script):
        if is_literal:
            buf.append(text)
            continue
        # 代码片段里按 ; 切
        parts = text.split(";")
        for k, p in enumerate(parts):
            buf.append(p)
            if k < len(parts) - 1:
                stmt = "".join(buf).strip()
                if stmt:
                    stmts.append(stmt)
                buf = []
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def executescript(conn, script: str) -> int:
    """执行多语句脚本，兼容 psycopg（无 executescript）。

    Returns:
        成功执行的语句数。
    """
    if is_sqlite(conn) and hasattr(conn, "executescript"):
        conn.executescript(adapt_ddl(script, conn))
        return -1  # SQLite 不返回计数
    n = 0
    for stmt in split_statements(script):
        adapted = adapt_sql(stmt, conn)
        if not adapted.strip():
            continue
        cur = conn.cursor()
        cur.execute(adapted)
        n += 1
    return n


def insert_returning_id(conn, sql: str, params: Sequence[Any] | dict | None = None) -> int | None:
    """执行 INSERT 并返回新行主键，兼容 SQLite(lastrowid) 与 PG(RETURNING id)。

    PG 下若原 SQL 无 RETURNING，则自动追加 `RETURNING id`。
    """
    if is_sqlite(conn):
        cur = execute(conn, sql, params)
        return cur.lastrowid
    adapted = adapt_sql(sql, conn)
    if not re.search(r"\bRETURNING\b", adapted, re.I):
        adapted = adapted.rstrip().rstrip(";") + " RETURNING id"
    cur = conn.cursor()
    cur.execute(adapted, params)
    row = cur.fetchone()
    return int(row[0]) if row else None


# --------------------------------------------------------------------------- #
# 目录查询：sqlite_master → information_schema
# --------------------------------------------------------------------------- #
def table_exists(conn, table: str, schema: str = "public") -> bool:
    """表是否存在（跨方言）。"""
    if is_sqlite(conn):
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return bool(cur.fetchone()[0])
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema=%s AND table_name=%s",
        (schema, table),
    )
    return bool(cur.fetchone()[0])


def list_tables(conn, schema: str = "public") -> list[str]:
    """全部表名（跨方言）。"""
    if is_sqlite(conn):
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [r[0] for r in cur.fetchall()]
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name",
        (schema,),
    )
    return [r[0] for r in cur.fetchall()]


def column_names(conn, table: str, schema: str = "public") -> list[str]:
    """表列名（替代 PRAGMA table_info）。"""
    if is_sqlite(conn):
        cur = conn.cursor()
        cur.execute(f'PRAGMA table_info("{table}")')
        return [r[1] for r in cur.fetchall()]
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
        (schema, table),
    )
    return [r[0] for r in cur.fetchall()]


def count_tables(conn, schema: str = "public") -> int:
    """表数量（替代 SELECT COUNT(*) FROM sqlite_master）。"""
    if is_sqlite(conn):
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        return int(cur.fetchone()[0])
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema=%s AND table_type='BASE TABLE'",
        (schema,),
    )
    return int(cur.fetchone()[0])


def add_column_if_missing(conn, table: str, column: str, ddl_type: str,
                          schema: str = "public") -> bool:
    """幂等加列（替代"PRAGMA 探测 + ALTER"，避免 PG 事务 abort）。

    Returns:
        True 表示实际新增，False 表示列已存在。
    """
    if column in column_names(conn, table, schema):
        return False
    if is_sqlite(conn):
        sql = f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl_type}'
    else:
        sql = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {ddl_type}'
    cur = conn.cursor()
    cur.execute(sql)
    return True


# --------------------------------------------------------------------------- #
# 连接代理：让存量"原生 DBAPI 调用"零改动跨方言
#
# 适用面最广的一层。项目有 30+ 服务写成：
#     conn = db.connection().connection
#     conn.execute("... WHERE id = ?", (x,))
#     conn.executescript(_DDL)
#     new_id = cur.lastrowid
# 全部改成经 wrap_conn 包装后，上述写法在 PG 下也能跑，无需逐个改 SQL 文本。
# SQLite 连接**原样返回**，不引入任何行为变化。
# --------------------------------------------------------------------------- #
class _CursorProxy:
    """游标代理：补出 psycopg 缺失的 lastrowid。"""

    __slots__ = ("_cur", "_conn", "_lastrowid")

    def __init__(self, cur, conn):
        self._cur = cur
        self._conn = conn
        self._lastrowid = None

    def __getattr__(self, name):
        return getattr(self._cur, name)

    @property
    def lastrowid(self):
        """PG 侧由 execute() 时注入（RETURNING id）；取不到返回 None。"""
        return self._lastrowid

    def __iter__(self):
        return iter(self._cur)


class _ConnProxy:
    """连接代理：改写 SQL 后转发，透明适配 ? → %s、executescript、lastrowid。"""

    __slots__ = ("_conn",)

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    # ---- 核心：execute 改写 ----
    def execute(self, sql, params=None):
        raw = sql if isinstance(sql, str) else str(sql)
        adapted = adapt_sql(raw, self._conn)

        # 注意：这里**不做**参数层面的 bool → int 改写。
        # 曾加过「True/False 一律转 1/0」的兜底，结果把所有 boolean 列的写入打挂
        # （exam_blueprints.is_active 预置蓝图 INSERT 报
        #  ``column "is_active" is of type boolean but expression is of type smallint``，
        #  /api/exam/blueprints 等用例集体 ERROR）。与上方 adapt_dml 注释同一结论：
        # 不知道表上下文就不能改类型——psycopg 会把 Python bool 正确绑定为 boolean，
        # 少数 INTEGER 语义列（如 code_questions.is_available）由调用方传 int。
        cur = self._conn.cursor()
        cur.execute(adapted, params if params is not None else ())
        proxy = _CursorProxy(cur, self._conn)
        # 若是 INSERT 且未带 RETURNING，尝试补取主键（仅 PG）
        if is_postgres(self._conn):
            low = adapted.lstrip().lower()
            if low.startswith("insert") and "returning" not in low:
                try:
                    # 已在 execute 中执行完，用 cur.description 判断是否可 fetch
                    if cur.description:
                        row = cur.fetchone()
                        proxy._lastrowid = int(row[0]) if row else None
                except Exception:  # noqa: BLE001
                    pass
        return proxy

    def executemany(self, sql, seq):
        """批量执行（SQLite conn.executemany 语义，PG 侧改写 ? → %s 后转发 cursor）。"""
        raw = sql if isinstance(sql, str) else str(sql)
        adapted = adapt_sql(raw, self._conn)
        cur = self._conn.cursor()
        cur.executemany(adapted, seq)
        return _CursorProxy(cur, self._conn)

    def executescript(self, script: str):
        return executescript(self._conn, script)

    def cursor(self, *a, **kw):
        return _CursorProxy(self._conn.cursor(*a, **kw), self._conn)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()


def wrap_conn(conn):
    """把原生连接包成跨方言代理。SQLite 直通，PG 走适配。

    用法（存量代码零改 SQL，只改取连接那一行）：
        conn = wrap_conn(db.connection().connection)
    """
    if conn is None or is_sqlite(conn):
        return conn
    # 幂等：已包过代理的连接不再二次包装，否则 adapt_sql 会被连跑两遍
    # （例如 raw_conn 的返回值又被调用方 wrap 一次的场景）。
    if isinstance(conn, _ConnProxy):
        return conn
    return _ConnProxy(conn)
