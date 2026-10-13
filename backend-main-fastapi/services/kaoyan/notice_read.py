# -*- coding: utf-8 -*-
"""通知已读/加星状态层（幂等迁移 + 原生 SQL 读写）。

为什么是「加列」而不是「关联表」
--------------------------------
用户诉求原文：「每一个通知都要有一个已读标记，这样防止我错过消息」。
已读/加星是**用户对通知本身的属性标注**，不是独立实体：

1. 本项目**无用户体系**——真库 63 张表中没有 ``users``/``accounts`` 表，
   ``models.py`` 中亦无任何 User 模型、无 ``user_id`` 外键、无认证中间件
   （已 grep 全库核实）。因此不存在「这条已读记录属于谁」的问题，
   建 ``notice_reads(notice_id, user_id, ...)`` 关联表只会引入一个恒为 1 的
   ``user_id`` 列，纯属无收益的复杂度。故直接在 ``kaoyan_notices`` 上加列。

2. ``kaoyan_notices`` 本身是**原生 DDL 表**（见 ``spider_notices._DDL``，
   刻意绕开 ORM 基线以降低迁移风险），由 ``ensure_notices_schema`` 保证存在。
   本模块沿用同一模式：``ALTER TABLE ... ADD COLUMN`` 幂等补列，绝不重建表、
   不动既有 1504 行数据、不碰采集器写入路径（新增列全部带 DEFAULT，
   采集器 INSERT 不受影响）。

3. 加列而非重建，也保证**已读状态与通知同生命周期**：通知被
   ``UNIQUE(school_name, title, publish_date)`` 去重刷新时状态天然保留，
   而关联表需要额外的级联/孤儿清理。

存储语义
--------
- ``is_read``    0/1，默认 0（未读）。**新增通知默认未读** —— 这正是需求所在。
- ``is_starred`` 0/1，默认 0（未加星）。用户手动置顶关键通知（录取/调剂/复试）。
- ``read_at``    TEXT ISO 时间戳，标记已读时刻；未读为 NULL。用于「何时读的」
  追溯，也便于前端展示；不参与任何过滤逻辑。
- ``starred_at`` TEXT ISO 时间戳，加星时刻；未加星为 NULL。

为什么不用 ``priority`` 数值列：用户的心智是「加星 / 不加星」二值开关，
数值优先级会引入「多严重算严重」的产品决策且用户无法自主表达，
反而增加误标风险。

重要度口径（v2修正）
--------------------
本模块早期版本自己用 ``IMPORTANT_TYPES``（notice_type 白名单）派生``is_important``，
但 ``services/kaoyan/notice_alert.py`` 的规则引擎早已把打分结果落库到
``kaoyan_notices.importance_level``（urgent/important/normal）。两套口径实测冲突：

- 白名单口径命中 218 条，落库口径命中 411 条，交集仅 146 条；
- 白名单**漏掉** 94 条 ``notice_type='公告'`` 的urgent 通知，而它们恰恰是
  「XX大学 2027 年全国硕士研究生招生考试网上报名公告」这类最容易错过的节点；
- 白名单**误标** 72 条博士/学位类通知，而本平台用户是硕士考生。

因此权威口径是落库的 ``importance_level``，``IMPORTANT_TYPES`` 降级为
「老库缺少 importance_* 列时」的兜底，不再参与正常判定。

WAL 注意事项
------------
真库为 SQLite WAL 模式。本模块**不做任何文件级拷贝**，
备份必须用 ``sqlite3.Connection.backup()``（见 ``backup.py``），
否则会拿到撕裂的快照。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 新增列定义：(列名, DDL 类型, DEFAULT)。全部可空或有默认值，
# 保证既有 1504 行立即可用、且采集器 INSERT 语句无需修改。
_READ_COLUMNS = (
    ("is_read", "INTEGER NOT NULL DEFAULT 0"),
    ("is_starred", "INTEGER NOT NULL DEFAULT 0"),
    ("read_at", "TEXT"),
    ("starred_at", "TEXT"),
)

# 支撑「未读筛选 + 排序」与「按类型/院校统计未读」的索引。
_READ_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_notices_read ON kaoyan_notices(is_read, publish_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_notices_starred ON kaoyan_notices(is_starred)",
)

# 「重要」的判定分级（由重到轻）。``importance_level`` 列由
# services/kaoyan/notice_alert.py 分级回填，是**重要性的唯一权威口径**。
#
# 历史沿革（勿回退）：本模块最初用「notice_type IN (录取,调剂,复试)」派生
# is_important，实测在真库上劣于 importance_level：
#   - 旧口径 218 条中 73 条(33%)是纯博士通知，对硕士考生是噪音
#   - importance_level 口径 411 条中仅 3 条纯博士噪音
#   - 且 importance_level 完整覆盖旧口径的 145 条硕士关键通知（0 漏检），
#     多出的 263 条是「网上报名公告/推免预报名/招生简章/目录」等硕士同样必看的内容
# 故统一改用 importance_level，两套口径合并为一个数字。
IMPORTANT_LEVELS = ("urgent", "important")

# 兜底：importance_level 列不存在时（极旧库）退化为按类型派生，
# 保证本模块不因依赖他方列而崩溃。
IMPORTANT_TYPES = ("录取", "调剂", "复试")


def _has_importance_column(conn) -> bool:
    """importance_level 列是否已存在（notice-alert 分级任务落库）。"""
    return "importance_level" in _table_columns(conn)


def _table_columns(conn) -> set:
    """返回 kaoyan_notices 现有列名集合。

    ``conn`` 可以是原生连接、``_DictCursor`` 包装或任意 cursor。
    原生连接返回 tuple（下标 1 是列名），``_DictCursor`` 返回 dict（键是列名），
    故两种形状都兼容。
    """
    names = set()
    for row in conn.execute("PRAGMA table_info(kaoyan_notices)").fetchall():
        # sqlite3.Row 两种下标/键访问都支持，故用 isinstance 判断更稳
        if isinstance(row, dict):
            names.add(row.get("name"))
        else:
            names.add(row[1])
    return names


def ensure_notice_read_schema(db_session) -> None:
    """幂等补齐已读/加星列与索引。

    与 ``ensure_notices_schema`` 一样在每次访问前调用：
    ALTER TABLE ADD COLUMN 无 IF NOT EXISTS 语法，靠「查列→缺失才加」实现幂等。
    并发场景下重复 ADD 会抛 ``duplicate column name``，捕获后视为成功。
    """
    from services.kaoyan.spider_notices import ensure_notices_schema

    # 先确保基表存在（首次部署时 kaoyan_notices 可能还没建）
    ensure_notices_schema(db_session)

    conn = db_session.connection().connection
    existing = _table_columns(conn)
    if not existing:
        # 基表仍不存在（异常情况）→ 不做任何变更，交由上层报错，避免建空表
        logger.warning("kaoyan_notices 不存在，跳过已读状态迁移")
        return

    added = []
    for col_name, col_ddl in _READ_COLUMNS:
        if col_name in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE kaoyan_notices ADD COLUMN {col_name} {col_ddl}")
            added.append(col_name)
        except Exception as exc:  # 并发下另一请求已加，属正常
            if "duplicate column" not in str(exc).lower():
                raise
    for ddl in _READ_INDEXES:
        conn.execute(ddl)

    db_session.commit()
    if added:
        logger.info("kaoyan_notices 已读状态迁移完成，新增列: %s", added)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class _DictCursor:
    """把 ``cursor.fetchall()`` 的 tuple 结果按列名转成 dict 的薄包装。

    为什么需要它
    ------------
    ``db_session.connection().connection`` 返回的是 SQLAlchemy 连接池里的
    DBAPI 裸连接，``fetchall()`` 默认给 tuple（下标访问）。
    直接设 ``conn.row_factory = sqlite3.Row`` **不可靠**——连接归还池中后
    row_factory 会被 SQLAlchemy 重置，下一次拿到的又是 tuple（已实测踩坑）。

    故不改连接本身，而是包装 ``execute``：执行后依据 ``cursor.description``
    把每一行转成 dict。这样 ``row["col"]`` 无论池如何复用都稳定成立，
    且不影响底层连接的行为（写入、rowcount 均照常）。
    """

    __slots__ = ("_session",)

    def __init__(self, db_session):
        # 只持有 Session，不缓存底层连接——见下方 _live_conn 说明
        self._session = db_session

    def _live_conn(self):
        """每次执行前重新取得底层 DBAPI 连接。

        为什么不能缓存连接引用
        ----------------------
        ``session.connection()`` 返回的 ``_ConnectionFairy`` 是**惰性**的，
        而 ``db.commit()`` 会把底层连接归还连接池，此时旧 fairy 的
        ``dbapi_connection`` 被置为 ``None``。若把它缓存下来跨 commit 复用，
        后续 execute 会抛::
            AttributeError: 'NoneType' object has no attribute 'execute'
        （本问题由 notice-alert 在真库复现并报告，属同一类生命周期陷阱：
        与 row_factory 被重置同源——都源于连接池会复用/回收连接。）

        故每次 execute 都重新走 ``session.connection()``，让 SQLAlchemy 按需
        重新建立或从池中取出可用连接。代价是每次多一次轻量属性访问，
        相对查询本身可忽略，换来的是**跨 commit 安全**。
        """
        return self._session.connection().connection

    def execute(self, sql, params=None):
        """执行 SQL，返回带 ``.fetchall()/.fetchone()/.rowcount`` 的游标包装。"""
        conn = self._live_conn()
        cur = conn.execute(sql, params) if params is not None else conn.execute(sql)
        return _DictCursorResult(cur)

    def executescript(self, script):
        return self._live_conn().executescript(script)

    def __getattr__(self, item):
        # 其余属性（commit/rollback/close 等）透传给底层连接
        return getattr(self._live_conn(), item)


class _DictCursorResult:
    """游标结果包装：把 tuple 行按列名转 dict。"""

    __slots__ = ("_cur",)

    def __init__(self, cur):
        self._cur = cur

    @property
    def _cols(self):
        desc = self._cur.description or []
        return [d[0] for d in desc]

    def fetchall(self):
        cols = self._cols
        return [dict(zip(cols, row)) for row in self._cur.fetchall()]

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(zip(self._cols, row)) if row is not None else None

    @property
    def rowcount(self):
        return self._cur.rowcount


def row_conn(db_session):
    """取原生 sqlite3 连接，并包装为「行可按列名访问」的形式。

    返回的包装对象代理全部连接方法，仅把 ``execute`` 的结果行转为 dict，
    使上层可以统一使用 ``row["col"]`` 可读写法（见 ``_DictCursor`` docstring）。

    **可跨 commit 安全复用**：内部每次执行都重新取连接，不会因
    ``db.commit()`` 归还连接池而拿到已失效的引用。
    """
    return _DictCursor(db_session)


def _is_important_row(row) -> bool:
    """单条通知是否「重要」。

    优先用 ``importance_level``（权威口径，见 ``IMPORTANT_LEVELS`` 注释）；
    该列缺失时退化为按类型派生，保证旧库不崩。
    """
    level = row.get("importance_level")
    if level is not None:
        return level in IMPORTANT_LEVELS
    # 兜底：SELECT 未带 importance_level 列时 dict 取不到 key
    return row.get("notice_type") in IMPORTANT_TYPES


def _row_to_dict(row, unread_by_type: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """把查询行转成前端契约对象（显式列名，避免依赖 raw tuple 顺序）。

    ``row`` 需为 ``row_conn`` 包装后取出的 dict。``type_total`` 允许缺省
    （列表查询的 SELECT 未带 total 列），此时降级为 0，由调用方按需覆盖。
    """
    notice_type = row["notice_type"]
    total = int(row.get("total") or 0)
    unread = int(unread_by_type.get(notice_type, 0)) if unread_by_type else 0
    return {
        "id": row["id"],
        "school_id": row["school_id"],
        "school_name": row["school_name"],
        "title": row["title"],
        "notice_type": notice_type,
        "publish_date": row["publish_date"],
        "url": row["url"],
        "source": row["source"],
        "fetched_at": row["fetched_at"],
        # ---- 已读/加星状态（前端渲染必需）----
        "is_read": bool(row["is_read"]),
        "is_starred": bool(row["is_starred"]),
        "read_at": row["read_at"],
        "starred_at": row["starred_at"],
        # ---- 派生字段（非落库）----
        # 「重要」取自 importance_level 权威口径（见 IMPORTANT_LEVELS 注释）
        "is_important": _is_important_row(row),
        "importance_level": row.get("importance_level"),
        "importance_score": int(row.get("importance_score") or 0),
        "type_total": total,
        "type_unread": unread,
    }


def mark_read(
    db_session,
    notice_ids: Optional[List[int]] = None,
    is_read: bool = True,
    school_id: Optional[int] = None,
    notice_type: Optional[str] = None,
    all_notices: bool = False,
) -> Dict[str, Any]:
    """批量标记已读/未读。至少给出一个限定条件，否则拒绝执行。

    支持四种作用域：
      - ``notice_ids``：指定若干条
      - ``school_id``：某院校的全部通知
      - ``notice_type``：某类型的全部通知
      - ``all_notices=True``：全库（对应「全部已读」按钮）

    Returns: ``{updated, is_read, scope}``
    """
    ensure_notice_read_schema(db_session)
    conn = row_conn(db_session)

    if not (notice_ids or school_id or notice_type or all_notices):
        raise ValueError("必须提供 notice_ids / school_id / notice_type / all 之一")

    where: List[str] = []
    args: List[Any] = []
    if notice_ids:
        ids = [int(i) for i in notice_ids]
        where.append("id IN (%s)" % ",".join("?" * len(ids)))
        args += ids
        scope = "ids"
    elif school_id is not None:
        where.append("school_id = ?")
        args.append(int(school_id))
        scope = "school"
    elif notice_type:
        where.append("notice_type = ?")
        args.append(notice_type)
        scope = "type"
    else:
        scope = "all"

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    target = int(is_read)
    cur = conn.execute(
        f"UPDATE kaoyan_notices SET is_read = ?, read_at = ?{where_sql}",
        [target, _now_iso() if target else None] + args,
    )
    db_session.commit()
    return {"updated": int(cur.rowcount or 0), "is_read": target, "scope": scope}


def set_starred(
    db_session, notice_ids: List[int], is_starred: bool = True
) -> Dict[str, Any]:
    """批量置顶/取消置顶（加星）。"""
    ensure_notice_read_schema(db_session)
    conn = row_conn(db_session)
    ids = [int(i) for i in notice_ids]
    if not ids:
        raise ValueError("notice_ids 不能为空")
    target = int(is_starred)
    cur = conn.execute(
        "UPDATE kaoyan_notices SET is_starred = ?, starred_at = ?"
        " WHERE id IN (%s)" % ",".join("?" * len(ids)),
        [target, _now_iso() if target else None] + ids,
    )
    db_session.commit()
    return {"updated": int(cur.rowcount or 0), "is_starred": target}


def unread_stats(db_session) -> Dict[str, Any]:
    """未读统计：总数 + 按类型分组 + 按院校分组 + 加星数。

    前端全局角标只需要 ``total``，其余分组用于筛选器旁的计数提示。
    """
    ensure_notice_read_schema(db_session)
    conn = row_conn(db_session)

    # 标量聚合：给列起别名后按名取值（与下方 dict 行保持一致的可读写法）
    total_notices = int(
        conn.execute("SELECT COUNT(*) AS c FROM kaoyan_notices").fetchone()["c"]
    )
    total_unread = int(
        conn.execute(
            "SELECT COUNT(*) AS c FROM kaoyan_notices WHERE is_read = 0"
        ).fetchone()["c"]
    )
    total_starred = int(
        conn.execute(
            "SELECT COUNT(*) AS c FROM kaoyan_notices WHERE is_starred = 1"
        ).fetchone()["c"]
    )

    by_type_rows = conn.execute(
        "SELECT COALESCE(NULLIF(notice_type, ''), '公告') AS t,"
        " COUNT(*) AS total,"
        " SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) AS unread"
        " FROM kaoyan_notices GROUP BY t ORDER BY unread DESC, total DESC"
    ).fetchall()
    by_type = {
        r["t"]: {"total": int(r["total"]), "unread": int(r["unread"] or 0)} for r in by_type_rows
    }

    # 院校分组用 COALESCE 兜底：采集时可能 school_id 为空，退化为按校名分组
    by_school_rows = conn.execute(
        "SELECT COALESCE(CAST(school_id AS TEXT), 'n:' || COALESCE(school_name, '未知院校')) AS k,"
        " MAX(school_id) AS school_id, MAX(school_name) AS school_name,"
        " COUNT(*) AS total,"
        " SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) AS unread"
        " FROM kaoyan_notices GROUP BY k ORDER BY unread DESC, total DESC"
    ).fetchall()
    by_school = {
        r["k"]: {
            "school_id": r["school_id"],
            "school_name": r["school_name"],
            "total": int(r["total"]),
            "unread": int(r["unread"] or 0),
        }
        for r in by_school_rows
    }

    # 重要通知未读数：首页红色角标优先提示「你还漏了几条要紧的」。
    # 统一走 importance_level 权威口径（列缺失时退化为按类型统计）。
    if _has_importance_column(conn):
        important_unread = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM kaoyan_notices"
                " WHERE is_read = 0"
                "   AND importance_level IN (%s)" % ",".join("?" * len(IMPORTANT_LEVELS)),
                list(IMPORTANT_LEVELS),
            ).fetchone()["c"]
        )
        important_total = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM kaoyan_notices"
                " WHERE importance_level IN (%s)" % ",".join("?" * len(IMPORTANT_LEVELS)),
                list(IMPORTANT_LEVELS),
            ).fetchone()["c"]
        )
    else:
        important_unread = sum(
            v["unread"] for k, v in by_type.items() if k in IMPORTANT_TYPES
        )
        important_total = sum(
            v["total"] for k, v in by_type.items() if k in IMPORTANT_TYPES
        )
        urgent_unread = 0

    # 紧急未读：前端「仅紧急」筛选与概览条红色计数用。urgent 是
    # importance_level 的最高档（不看就会错过报名/复试/录取节点），
    # 与 important 分开统计，供前端做分级展示。
    if _has_importance_column(conn):
        urgent_unread = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM kaoyan_notices"
                " WHERE is_read = 0 AND importance_level = 'urgent'"
            ).fetchone()["c"]
        )

    return {
        "total": total_notices,
        "unread": total_unread,
        "read": total_notices - total_unread,
        "starred": total_starred,
        "important_unread": important_unread,
        "important_total": important_total,
        "urgent_unread": urgent_unread,
        "by_type": by_type,
        "by_school": by_school,
    }
