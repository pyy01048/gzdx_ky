# -*- coding: utf-8 -*-
"""通知已读标记 API（用户诉求：每一个通知都要有已读标记，防止错过消息）。

设计依据
--------
P5（2026-10-19）：已读/加星为 per-user 状态，落 ``notice_user_states``
（UNIQUE(user_id, notice_id)，DDL 见 core/sql/108 第 5 节）；所有端点挂
``current_user``，按登录用户读写。``kaoyan_notices`` 上的 ``is_read`` /
``is_starred`` 共享列已废弃（仅 user_id=None 兼容路径使用）。详见
``services/kaoyan/notice_read.py`` 模块 docstring。

所有端点均为纯 SQLAlchemy/原生 SQL，**不涉及任何网络抓取**，
仅对本地已入库的 1504 条通知做状态标注与查询。

端点总览（前缀 /api/notices）
  GET  /unread-stats         未读统计（总数/按类型/按院校/加星）→ 前端角标
  GET  /list                 通知列表（未读过滤/类型/院校/关键词/分页）
  POST /{id}/read            单条标记已读 / 取消已读
  POST /batch-read           批量标记（ids / 某院校 / 某类型 / 全部）
  POST /{id}/star            单条加星 / 取消加星
  POST /batch-star           批量加星
  POST /backfill-important   将关键类型默认加星（一次性，可选）
"""
from __future__ import annotations
from utils.security import require_admin

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import User
from services.dbapi_compat import wrap_conn
from database import SessionLocal
from utils.timeutil import naive_utc_iso
from services.kaoyan.notice_read import (
    IMPORTANT_LEVELS,
    IMPORTANT_TYPES,
    _has_importance_column,
    _read_pred,
    _row_to_dict,
    _state_cols,
    _state_join,
    _starred_pred,
    _table_columns,
    ensure_notice_read_schema,
    mark_read,
    row_conn,
    set_starred,
    unread_stats,
)
from utils.scope import owner_id
from utils.security import current_user

router = APIRouter(prefix="/api/notices", tags=["通知已读"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 请求体
# --------------------------------------------------------------------------- #
class ReadBody(BaseModel):
    """单条/批量已读请求体。``is_read=false`` 即取消已读。"""

    is_read: bool = Field(True, description="true=标记已读，false=取消已读")


class BatchReadBody(BaseModel):
    """批量标记已读。四种作用域任选其一；都不传则后端拒绝（防误操作全库）。"""

    notice_ids: Optional[List[int]] = Field(None, description="指定若干条 id")
    school_id: Optional[int] = Field(None, description="某院校全部通知")
    notice_type: Optional[str] = Field(None, description="某类型全部通知（如「录取」）")
    all: bool = Field(False, description="全库标记（前端「全部已读」按钮）")
    is_read: bool = Field(True, description="true=标记已读，false=取消已读")


class StarBody(BaseModel):
    is_starred: bool = Field(True, description="true=加星置顶，false=取消加星")


class BatchStarBody(BaseModel):
    notice_ids: List[int] = Field(..., description="要加星/取消加星的 id 列表")
    is_starred: bool = Field(True)


# --------------------------------------------------------------------------- #
# 未读统计（前端角标数据源）
# --------------------------------------------------------------------------- #
@router.get("/unread-stats")
def get_unread_stats(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """未读统计。

    Returns::

        {
          "total": 1504, "unread": 1504, "read": 0, "starred": 0,
          "important_unread": 218,          # 录取+调剂+复试 未读合计
          "by_type": {"公告": {"total":1085,"unread":1085}, ...},
          "by_school": {"3": {"school_id":3,"school_name":"...","total":9,"unread":9}, ...}
        }
    """
    return unread_stats(db, user_id=owner_id(user))


@router.get("/stats")
def notice_stats(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """通知中心统计卡（2026-10-19 信息架构精简时前端先行，本端点补后端半边；
    此前页面调本路径一直 404，统计卡静默不渲染）。


    Returns::


        {
          "total": 714, "unread": 714, "starred": 3, "schools_covered": 47,
          "by_type": [ {"type": "公告", "total": 410, "unread": 409}, ... ]  # 按数量倒序
        }
    """
    base = unread_stats(db, user_id=owner_id(user))
    by_type = [
        {"type": t, "total": int(v.get("total", 0)), "unread": int(v.get("unread", 0))}
        for t, v in (base.get("by_type") or {}).items()
    ]
    by_type.sort(key=lambda x: x["total"], reverse=True)
    return {
        "total": base.get("total", 0),
        "unread": base.get("unread", 0),
        "starred": base.get("starred", 0),
        "schools_covered": len(base.get("by_school") or {}),
        "by_type": by_type,
    }


# --------------------------------------------------------------------------- #
# 通知列表（支持未读过滤 + 分页）
# --------------------------------------------------------------------------- #
@router.get("/list")
def list_notices(
    unread_only: bool = Query(False, description="只看未读"),
    starred_only: bool = Query(False, description="只看加星"),
    notice_type: Optional[str] = Query(None, description="按类型过滤：公告/简章/复试/调剂/录取/目录/大纲"),
    urgent_only: bool = Query(False, description="只看紧急（importance_level=urgent）"),
    important_only: bool = Query(False, description="只看重要（urgent+important）"),
    school_id: Optional[int] = Query(None, description="按院校过滤"),
    keyword: Optional[str] = Query(None, description="标题关键词（模糊匹配）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """通知列表（含 is_read / is_starred 字段，按当前用户计，P5）。

    排序：加星优先 → publish_date 倒序 → id 倒序，
    保证置顶通知永远在顶部（用户「防止错过」的核心诉求）。

    Returns: ``{items, total, page, page_size, unread}``
    其中 ``unread`` 为当前过滤条件下的未读数（便于前端分页时保持角标）。
    """
    ensure_notice_read_schema(db)
    conn = row_conn(db)
    user_id = owner_id(user)
    from_sql, join_args = _state_join(user_id)
    read_pred = _read_pred(user_id)
    starred_pred = _starred_pred(user_id)

    where: List[str] = []
    args: List[object] = []
    if unread_only:
        where.append(read_pred)
    if starred_only:
        where.append(starred_pred)
    if notice_type:
        where.append("COALESCE(NULLIF(CAST(notice_type AS TEXT), ''), '公告') = ?")
        args.append(notice_type)
    # 重要度筛选：urgent_only / important_only / important（urgent+important）。
    # 走 SQL 而非前端本地过滤，否则分页语义会退化成「仅过滤当前页」，
    # 用户会误以为全库只有这些。前端「仅紧急/仅重要」筛选依赖本参数。
    if urgent_only:
        where.append("importance_level = 'urgent'")
    elif important_only:
        where.append(
            "importance_level IN (%s)" % ",".join("?" * len(IMPORTANT_LEVELS))
        )
        args += list(IMPORTANT_LEVELS)
    if school_id is not None:
        where.append("school_id = ?")
        args.append(int(school_id))
    if keyword:
        where.append("title LIKE ?")
        args.append(f"%{keyword}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    # 总数 + 当前条件下的未读数（一次查询取两个标量，避免额外往返；
    # 未读按当前用户计——per-user LEFT JOIN notice_user_states，见 _state_join）
    stats_row = conn.execute(
        "SELECT COUNT(*) AS total,"
        f" SUM(CASE WHEN {read_pred} THEN 1 ELSE 0 END) AS unread{from_sql}{where_sql}",
        join_args + args,
    ).fetchone()
    total = int(stats_row["total"] or 0)
    unread = int(stats_row["unread"] or 0)

    # 各类型总数与未读数（供列表内类型筛选器显示计数），两次 GROUP BY 一次取回
    type_rows = conn.execute(
        "SELECT COALESCE(NULLIF(CAST(n.notice_type AS TEXT), ''), '公告') AS t,"
        " COUNT(*) AS total,"
        f" SUM(CASE WHEN {read_pred} THEN 1 ELSE 0 END) AS unread"
        f"{from_sql} GROUP BY t",
        join_args,
    ).fetchall()
    by_type_total = {r["t"]: int(r["total"] or 0) for r in type_rows}
    unread_by_type = {r["t"]: int(r["unread"] or 0) for r in type_rows}

    offset = (page - 1) * page_size

    # ---- 明细列表 ----
    # 带上 importance_level / importance_score：is_important 以importance_level
    # 为权威口径（见 notice_read.IMPORTANT_LEVELS）。逐列探测，极旧库缺列时用
    # NULL 占位，保证 SELECT 列表形状恒定、row.get() 恒有 key。
    cols = _table_columns(conn)
    lv_col = ", importance_level" if "importance_level" in cols else ", NULL AS importance_level"
    sc_col = ", importance_score" if "importance_score" in cols else ", NULL AS importance_score"
    rows = conn.execute(
        "SELECT n.id, n.school_id, n.school_name, n.title, n.notice_type, n.publish_date, n.url, n.source,"
        f" n.fetched_at, {_state_cols(user_id)}{lv_col}{sc_col}"
        f"{from_sql}{where_sql}"
        f" ORDER BY ({starred_pred}) DESC, COALESCE(NULLIF(n.publish_date, ''), n.fetched_at) DESC, n.id DESC"
        " LIMIT ? OFFSET ?",
        join_args + args + [page_size, offset],
    ).fetchall()

    # 逐条转前端契约对象；type_total 用上方 GROUP BY 得到的类型总数回填
    # （列表 SELECT 不含 total 列，故在此注入，避免每行再查一次）
    items = []
    for r in rows:
        d = _row_to_dict(r, unread_by_type)
        d["type_total"] = by_type_total.get(d["notice_type"], 0)
        items.append(d)

    return {
        "items": items,
        "total": total,
        "unread": unread,
        "page": page,
        "page_size": page_size,
        "by_type_total": by_type_total,
    }


# --------------------------------------------------------------------------- #
# 单条 / 批量标记已读
# --------------------------------------------------------------------------- #
@router.post("/{notice_id}/read")
def mark_notice_read(
    notice_id: int, body: ReadBody, db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """单条标记已读 / 取消已读（前端点击通知即调用）。"""
    exists = wrap_conn(db.connection().connection).execute(
        "SELECT 1 FROM kaoyan_notices WHERE id = ?", [notice_id]
    ).fetchone()
    if not exists:
        raise HTTPException(404, f"通知不存在: {notice_id}")
    result = mark_read(db, notice_ids=[notice_id], is_read=body.is_read, user_id=owner_id(user))
    return {"success": True, "notice_id": notice_id, **result}


@router.post("/batch-read")
def batch_mark_read(
    body: BatchReadBody, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """批量标记已读。

    示例：某院校全部已读 → ``{"school_id": 3}``
          某类型全部已读 → ``{"notice_type": "录取"}``
          全部已读     → ``{"all": true}``
    """
    try:
        result = mark_read(
            db,
            notice_ids=body.notice_ids,
            is_read=body.is_read,
            school_id=body.school_id,
            notice_type=body.notice_type,
            all_notices=body.all,
            user_id=owner_id(user),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"success": True, **result}


# --------------------------------------------------------------------------- #
# 加星（关键通知置顶）
# --------------------------------------------------------------------------- #
@router.post("/{notice_id}/star")
def star_notice(
    notice_id: int, body: StarBody, db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """单条加星 / 取消加星（落当前用户 notice_user_states）。"""
    exists = wrap_conn(db.connection().connection).execute(
        "SELECT 1 FROM kaoyan_notices WHERE id = ?", [notice_id]
    ).fetchone()
    if not exists:
        raise HTTPException(404, f"通知不存在: {notice_id}")
    result = set_starred(db, [notice_id], is_starred=body.is_starred, user_id=owner_id(user))
    return {"success": True, "notice_id": notice_id, **result}


@router.post("/batch-star")
def batch_star(
    body: BatchStarBody, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """批量加星 / 取消加星。"""
    try:
        result = set_starred(db, body.notice_ids, is_starred=body.is_starred, user_id=owner_id(user))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"success": True, **result}


@router.post("/backfill-important", dependencies=[Depends(require_admin)])
def backfill_important_stars(
    db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """把「重要」通知默认加星，一次性操作（幂等，可重复调用）。

    重要判定与列表/统计**完全同源**：优先 ``importance_level IN
    (urgent, important)``；该列不存在时退化为按类型（录取/调剂/复试）。
    口径统一，避免「角标说重要但加星没反应」这类不一致。

    加星是用户「手动表达」的语义，故默认不自动加星，仅在此显式端点提供。
    已读状态 **不受影响**。P5 起写当前用户 ``notice_user_states``，
    已加星的行跳过，rowcount 即本次实际变更数。
    """
    ensure_notice_read_schema(db)
    conn = row_conn(db)
    now = naive_utc_iso()
    user_id = owner_id(user)

    if _has_importance_column(conn):
        imp_where = "importance_level IN (%s)" % ",".join("?" * len(IMPORTANT_LEVELS))
        imp_args: list = list(IMPORTANT_LEVELS)
        basis = "importance_level"
    else:
        imp_where = (
            "COALESCE(NULLIF(CAST(notice_type AS TEXT), ''), '公告') IN (%s)"
            % ",".join("?" * len(IMPORTANT_TYPES))
        )
        imp_args = list(IMPORTANT_TYPES)
        basis = "notice_type"

    if user_id is None:
        # 旧行为（共享单租户列）
        cur = conn.execute(
            "UPDATE kaoyan_notices SET is_starred = TRUE, starred_at = ?"
            f" WHERE is_starred = FALSE AND {imp_where}",
            [now] + imp_args,
        )
    else:
        # per-user（P5）：无状态行则插入加星，已有未加星行翻转为加星；
        # 已加星的行被 DO UPDATE 的 WHERE 跳过，不重复计数
        cur = conn.execute(
            "INSERT INTO notice_user_states (user_id, notice_id, is_starred, updated_at)"
            f" SELECT ?, id, TRUE, CURRENT_TIMESTAMP FROM kaoyan_notices WHERE {imp_where}"
            " ON CONFLICT (user_id, notice_id) DO UPDATE"
            " SET is_starred = TRUE, updated_at = EXCLUDED.updated_at"
            " WHERE notice_user_states.is_starred = FALSE",
            [user_id] + imp_args,
        )
    db.commit()
    return {
        "success": True,
        "starred": int(cur.rowcount or 0),
        "basis": basis,
        "note": "加星不影响 is_read；未读数不变",
    }
