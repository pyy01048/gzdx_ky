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
from datetime import datetime
from typing import Any, Dict, List, Optional

GAP_TYPES = ("no_material", "ocr_failed", "no_answer", "ambiguous", "out_of_scope")
STATUSES = ("open", "resolved", "ignored", "duplicate")

_ABSTAIN_REPLY_TEMPLATE = (
    "当前资料未覆盖【{gap}】，无法据此可靠回答。\n"
    "先给出可答部分：{partial}\n"
    "（引用：{citations}）\n"
    "该问题已列入待补充清单，建议补充【{suggestion}】。"
)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
) -> int:
    """拒答沉淀：同一问题再次出现时 occurrence_count +1 并刷新时间。返回记录 id。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection
    if gap_type not in GAP_TYPES:
        gap_type = "no_material"

    existing = conn.execute(
        "SELECT id, occurrence_count FROM pending_questions WHERE question = ? AND subject IS ?",
        (question, subject),
    ).fetchone()
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

    cur = conn.execute(
        """
        INSERT INTO pending_questions
        (question, subject, have_basis, have_basis_ids, gap, gap_type,
         suggestion, suggested_action, status, occurrence_count, last_occurred_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', 1, ?)
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
        ),
    )
    db.commit()
    return int(cur.lastrowid)


def _gap_text(gap_type: str, suggestion: str) -> str:
    default_gap = {
        "no_material": "概念未收录",
        "ocr_failed": "公式识别失败",
        "no_answer": "无解析",
        "ambiguous": "答案存疑",
        "out_of_scope": "超出资料范围",
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
) -> List[Dict[str, Any]]:
    """盲区看板查询。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection
    sql = "SELECT id, question, subject, have_basis, have_basis_ids, gap, gap_type, suggestion, suggested_action, status, resolved_by, resolved_at, occurrence_count, last_occurred_at, created_at FROM pending_questions WHERE 1=1"
    params: List[Any] = []
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    if status and status != "all":
        sql += " AND status = ?"
        params.append(status)
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


def top_gaps(db, subject: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """高频缺口聚合（occurrence_count 排序）。"""
    return get_gaps(db, subject=subject, status="all", limit=limit, order_by_occurrence=True)


# --------------------------------------------------------------------------- #
# 处理
# --------------------------------------------------------------------------- #
def resolve_gap(db, gap_id: int, action: str = "resolved") -> bool:
    """标记缺口已处理（resolved | ignored | duplicate）。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    if action not in STATUSES:
        action = "resolved"
    conn = db.connection().connection
    from services.db_retry import exec_retry

    cur = exec_retry(
        conn,
        "UPDATE pending_questions SET status = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
        (action, action, _now_str(), gap_id),
    )
    db.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# 薄弱点反哺刷题（供组卷 weakest 模式）
# --------------------------------------------------------------------------- #
def get_weakest_subjects(db, limit: int = 10) -> List[Dict[str, Any]]:
    """按 gap_type 聚合科目薄弱度（未解决缺口数加权）。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection
    rows = conn.execute(
        """
        SELECT subject, COUNT(*) AS open_count, SUM(occurrence_count) AS total_occurrences
        FROM pending_questions
        WHERE status IN ('open','duplicate') AND subject IS NOT NULL
        GROUP BY subject
        ORDER BY total_occurrences DESC, open_count DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [
        {"subject": r[0], "open_count": int(r[1]), "total_occurrences": int(r[2] or 0)}
        for r in rows
    ]


def get_weakest_kps(db, limit: int = 20) -> List[Dict[str, Any]]:
    """依据 pending_questions 中 knowledge_point 建议/题面抽取的薄弱知识点。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection
    rows = conn.execute(
        """
        SELECT question, subject, gap_type, occurrence_count, suggestion
        FROM pending_questions
        WHERE status IN ('open','duplicate')
        ORDER BY occurrence_count DESC, last_occurred_at DESC
        LIMIT ?
        """,
        (int(limit),),
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
