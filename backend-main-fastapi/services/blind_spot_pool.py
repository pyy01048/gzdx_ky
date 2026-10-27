# -*- coding: utf-8 -*-
"""
A4 知识盲区池（services/blind_spot_pool.py）
============================================
abstain/拒答结果沉淀为 pending_questions 记录，形成"资料缺口看板"，
并反哺组卷（weakest 模式薄弱点排序）。

表结构（module_a_schema.py 已建）：
  pending_questions(id, question, subject, have_basis, have_basis_ids JSON,
    gap, gap_type, suggestion, suggested_action, status, resolved_by,
    resolved_at, occurrence_count, last_occurred_at, asked_at, created_at)

gap_type 枚举：no_material | ocr_failed | no_answer | ambiguous | out_of_scope
"""
from __future__ import annotations

import json
from datetime import timedelta
from utils.timeutil import utcnow  # 写库时间统一 naive UTC（P1-C2）
from typing import Any, Dict, List, Optional
from services.dbapi_compat import wrap_conn  # noqa: E402  PG/SQLite 双底座连接适配

GAP_TYPES = ("no_material", "ocr_failed", "no_answer", "ambiguous", "out_of_scope", "not_understood")
STATUSES = ("open", "resolved", "ignored", "duplicate")

_ABSTAIN_REPLY_TEMPLATE = (
    "当前资料未覆盖【{gap}】，无法据此可靠回答。\n"
    "先给出可答部分：{partial}\n"
    "（引用：{citations}）\n"
    "该问题已列入待补充清单，建议补充【{suggestion}】。"
)


def _now_str() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# 沉淀
# --------------------------------------------------------------------------- #
def record_abstain(
    db,
    question: str,
    subject: Optional[str] = None,
    basis: str = "",
    basis_ids: Optional[List[int]] = None,
    gap_type: str = "no_material",
    suggestion: str = "",
    suggested_action: str = "import_file",
    user_id: Optional[int] = None,
) -> int:
    """拒答沉淀：同一问题再次出现时 occurrence_count +1 并刷新时间。返回记录 id。

    B4 行级隔离：``user_id`` 传入时，去重查询与新建行都按用户隔离；
    None=旧行为（不区分用户，兼容脚本 / 未接线调用方）。
    """
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = wrap_conn(db.connection().connection)
    if gap_type not in GAP_TYPES:
        gap_type = "no_material"

    dedup_sql = "SELECT id, occurrence_count FROM pending_questions WHERE question = ? AND subject IS ?"
    dedup_params: List[Any] = [question, subject]
    if user_id is not None:  # B4：去重也按用户隔离，避免跨用户合并 occurrence_count
        dedup_sql += " AND user_id = ?"
        dedup_params.append(int(user_id))
    existing = conn.execute(dedup_sql, dedup_params).fetchone()
    now = _now_str()
    if existing:
        conn.execute(
            "UPDATE pending_questions SET occurrence_count = occurrence_count + 1, "
            "last_occurred_at = ?, status = CASE WHEN status='resolved' THEN 'open' ELSE status END "
            "WHERE id = ?",
            (now, existing[0]),
        )
        db.commit()
        return int(existing[0])

    # B4：user_id 传入时写入归属列；None=旧行为（不写该列，落 NULL）
    user_col = ", user_id" if user_id is not None else ""
    user_val = ", ?" if user_id is not None else ""
    cur = conn.execute(
        f"""
        INSERT INTO pending_questions
        (question, subject, have_basis, have_basis_ids, gap, gap_type,
         suggestion, suggested_action, status, occurrence_count, last_occurred_at{user_col})
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', 1, ?{user_val})
        """,
        (
            question[:2000],
            subject,
            basis[:2000] or "",
            json.dumps(basis_ids or [], ensure_ascii=False),
            _gap_text(gap_type, suggestion),
            gap_type,
            suggestion[:500] or "",
            suggested_action,
            now,
            *([int(user_id)] if user_id is not None else []),
        ),
    )
    db.commit()
    # PG 迁移修正：psycopg 无 lastrowid，且旧 SQL 未带 RETURNING → 回查主键
    from services.dbapi_compat import is_sqlite
    conn2 = wrap_conn(db.connection().connection)
    if is_sqlite(conn2):
        return int(cur.lastrowid)
    row = conn2.execute(
        "SELECT id FROM pending_questions WHERE question = ? AND subject IS ?"
        + (" AND user_id = ?" if user_id is not None else "")
        + " ORDER BY id DESC LIMIT 1",
        [question[:2000], subject] + ([int(user_id)] if user_id is not None else []),
    ).fetchone()
    return int(row[0]) if row else 0


def _gap_text(gap_type: str, suggestion: str) -> str:
    default_gap = {
        "no_material": "概念未收录",
        "ocr_failed": "公式识别失败",
        "no_answer": "无解析",
        "ambiguous": "答案存疑",
        "out_of_scope": "超出资料范围",
        "not_understood": "AI 讲题后仍未理解",
    }.get(gap_type, gap_type)
    return f"{default_gap}；建议补充：{suggestion}" if suggestion else default_gap


# --------------------------------------------------------------------------- #
# 看板
# --------------------------------------------------------------------------- #
def get_gaps(
    db,
    subject: Optional[str] = None,
    status: str = "open",
    limit: int = 100,
    order_by_occurrence: bool = True,
    user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """盲区看板查询。B4：``user_id`` 非空时只返回本人缺口；None=旧行为。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = wrap_conn(db.connection().connection)
    sql = "SELECT id, question, subject, have_basis, have_basis_ids, gap, gap_type, suggestion, suggested_action, status, resolved_by, resolved_at, occurrence_count, last_occurred_at, created_at FROM pending_questions WHERE 1=1"
    params: List[Any] = []
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
    if user_id is not None:  # B4：按用户隔离缺口
        sql += " AND user_id = ?"
        params.append(int(user_id))
    if order_by_occurrence:
        sql += " ORDER BY occurrence_count DESC, last_occurred_at DESC"
    else:
        sql += " ORDER BY last_occurred_at DESC"
    sql += " LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    cols = [
        "id", "question", "subject", "have_basis", "have_basis_ids", "gap", "gap_type",
        "suggestion", "suggested_action", "status", "resolved_by", "resolved_at",
        "occurrence_count", "last_occurred_at", "created_at",
    ]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        try:
            d["have_basis_ids"] = json.loads(d["have_basis_ids"] or "[]")
        except Exception:
            d["have_basis_ids"] = []
        out.append(d)
    return out


def top_gaps(db, subject: Optional[str] = None, limit: int = 20, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """高频缺口聚合（occurrence_count 排序）。"""
    return get_gaps(db, subject=subject, status="all", limit=limit, order_by_occurrence=True, user_id=user_id)


# --------------------------------------------------------------------------- #
# 处理
# --------------------------------------------------------------------------- #
def resolve_gap(db, gap_id: int, action: str = "resolved", user_id: Optional[int] = None) -> bool:
    """标记缺口已处理（resolved | ignored | duplicate）。

    B4：``user_id`` 非空时只允许处理本人缺口，越权=查不到→返回 False（路由转 404）。
    """
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    if action not in STATUSES:
        action = "resolved"
    conn = wrap_conn(db.connection().connection)
    from services.db_retry import exec_retry

    update_sql = "UPDATE pending_questions SET status = ?, resolved_by = ?, resolved_at = ? WHERE id = ?"
    update_params: List[Any] = [action, action, _now_str(), gap_id]
    if user_id is not None:  # B4：越权更新=查不到→False→路由 404
        update_sql += " AND user_id = ?"
        update_params.append(int(user_id))
    cur = exec_retry(conn, update_sql, update_params)
    db.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# 薄弱点反哺刷题（供组卷 weakest 模式）
# --------------------------------------------------------------------------- #
def get_weakest_subjects(db, limit: int = 10, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """按 gap_type 聚合科目薄弱度（未解决缺口数加权）。B4：user_id 非空时只统计本人。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = wrap_conn(db.connection().connection)
    user_filter = " AND user_id = ?" if user_id is not None else ""  # B4：按用户隔离薄弱度
    rows = conn.execute(
        f"""
        SELECT subject, COUNT(*) AS open_count, SUM(occurrence_count) AS total_occurrences
        FROM pending_questions
        WHERE status IN ('open','duplicate') AND subject IS NOT NULL{user_filter}
        GROUP BY subject
        ORDER BY total_occurrences DESC, open_count DESC
        LIMIT ?
        """,
        ((int(user_id), int(limit)) if user_id is not None else (int(limit),)),
    ).fetchall()
    return [
        {"subject": r[0], "open_count": int(r[1]), "total_occurrences": int(r[2] or 0)}
        for r in rows
    ]


def get_weakest_kps(db, limit: int = 20, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """依据 pending_questions 中 knowledge_point 建议/题面抽取的薄弱知识点。B4：user_id 非空时只取本人。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = wrap_conn(db.connection().connection)
    user_filter = " AND user_id = ?" if user_id is not None else ""  # B4：按用户隔离薄弱点
    rows = conn.execute(
        f"""
        SELECT question, subject, gap_type, occurrence_count, suggestion
        FROM pending_questions
        WHERE status IN ('open','duplicate'){user_filter}
        ORDER BY occurrence_count DESC, last_occurred_at DESC
        LIMIT ?
        """,
        ((int(user_id), int(limit)) if user_id is not None else (int(limit),)),
    ).fetchall()
    return [
        {
            "gap_question": r[0],
            "subject": r[1],
            "gap_type": r[2],
            "occurrence_count": int(r[3]),
            "suggestion": r[4] or "",
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# 周会议题聚合（多人计数视图）
# --------------------------------------------------------------------------- #
def weekly_topics(db, days: int = 7, limit: int = 20) -> List[Dict[str, Any]]:
    """周会议题聚合：跨小组成员统计近 ``days`` 天活跃的开放缺口。

    产品背景：5–6 人私域备考小组每周碰头，需要把"大家都卡在哪"汇聚成议题。
    ``pending_questions`` 已按 B4 带 ``user_id`` 归属，此处刻意做**聚合计数**：

    - 只返回 ``subject + gap_type`` 维度的计数（open 数 / 参与人数 / 出现总次数）；
    - **不返回任何他人的原始问题文本**（避免跨用户泄露具体内容）；
    - ``suggestion`` 取自该分组最近一条开放记录的补充建议（无个人敏感信息）。

    因此它在聚合层继续守住 B4 的"不暴露他人行级数据"精神，
    同时满足私域小组"看共同薄弱点"的需求。
    """
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = wrap_conn(db.connection().connection)
    cutoff = (utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """
        SELECT p1.subject, p1.gap_type,
               COUNT(*) FILTER (WHERE p1.status IN ('open','duplicate')) AS open_count,
               COUNT(DISTINCT p1.user_id) AS user_count,
               SUM(p1.occurrence_count) AS total_occurrences,
               MAX(p1.last_occurred_at) AS last_occurred_at,
               (SELECT p2.suggestion FROM pending_questions p2
                 WHERE p2.subject = p1.subject AND p2.gap_type = p1.gap_type
                   AND p2.status IN ('open','duplicate')
                 ORDER BY p2.last_occurred_at DESC LIMIT 1) AS suggestion
        FROM pending_questions p1
        WHERE p1.user_id IS NOT NULL AND p1.last_occurred_at >= ?
        GROUP BY p1.subject, p1.gap_type
        ORDER BY total_occurrences DESC, user_count DESC, last_occurred_at DESC
        LIMIT ?
        """,
        (cutoff, int(limit)),
    ).fetchall()
    return [
        {
            "subject": r[0],
            "gap_type": r[1],
            "open_count": int(r[2] or 0),
            "user_count": int(r[3] or 0),
            "total_occurrences": int(r[4] or 0),
            "last_occurred_at": r[5],
            "suggestion": r[6] or "",
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# 拒答话术
# --------------------------------------------------------------------------- #
def build_abstain_reply(
    question: str,
    *,
    partial: str = "",
    citations: Optional[List[str]] = None,
    gap: str = "相关资料缺失或不足",
    suggestion: str = "该知识点的教材/真题解析资料",
) -> str:
    """先给可答部分+引用，再说明缺口（比整句拒答体验好）。"""
    return _ABSTAIN_REPLY_TEMPLATE.format(
        gap=gap,
        partial=partial or "暂无可靠依据",
        citations="、".join(citations or ["（无引用）"]),
        suggestion=suggestion,
    )


if __name__ == "__main__":  # pragma: no cover
    print("GAP_TYPES:", GAP_TYPES)
