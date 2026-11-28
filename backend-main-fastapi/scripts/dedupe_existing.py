"""
清洗已入库的重复数据：
  1) knowledge_points：同 (subject, name, parent_id) 的重复节点 → 合并到规范行，迁移全部子关联后删除。
  2) quiz_questions：题干完全相同且不跨年/跨试卷的重复题 → 合并到规范行（保留更全答案/解析），迁移关联后删除。
默认 dry-run 只打印计划；加 --apply 才真正执行。所有 DML 在一个事务里，迁移用 SAVEPOINT 逐表隔离。
"""

from __future__ import annotations

import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from database import engine  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _exec(conn, sql, params=None):
    """单条语句包 SAVEPOINT，失败不污染外层事务。"""
    try:
        nested = conn.begin_nested()
        res = conn.execute(text(sql), params or {})
        nested.commit()
        return res
    except Exception:  # noqa: BLE001
        try:
            nested.rollback()  # type: ignore[name-defined]
        except Exception:  # noqa: BLE001
            pass
        raise


def reassign(conn, table, col, dup, canon, conflict_cols=None):
    """把 table.col=dup 的行改指到 canon；冲突行先删。返回 (updated, deleted)。"""
    updated = deleted = 0
    if conflict_cols:
        cols = ", ".join(conflict_cols)
        del_sql = (
            f"DELETE FROM {table} WHERE {col} = :dup AND ({cols}) IN (SELECT {cols} FROM {table} WHERE {col} = :canon)"
        )
        try:
            deleted += _exec(conn, del_sql, {"dup": dup, "canon": canon}).rowcount or 0
        except Exception:  # noqa: BLE001
            deleted = -1
    try:
        updated = (
            _exec(conn, f"UPDATE {table} SET {col} = :canon WHERE {col} = :dup", {"canon": canon, "dup": dup}).rowcount
            or 0
        )
    except Exception:  # noqa: BLE001 — 唯一冲突兜底：删掉 dup 的剩余子行
        try:
            deleted += _exec(conn, f"DELETE FROM {table} WHERE {col} = :dup", {"dup": dup}).rowcount or 0
        except Exception:  # noqa: BLE001
            pass
    return updated, deleted


# ---- 引用 knowledge_points.id 的子表 (table, col, conflict_cols) ----
KP_CHILDREN = [
    ("knowledge_points", "parent_id", None),
    ("question_knowledge_links", "knowledge_point_id", ["question_id"]),
    ("knowledge_point_relations", "source_kp_id", ["target_kp_id", "relation_type"]),
    ("knowledge_point_relations", "target_kp_id", ["source_kp_id", "relation_type"]),
    ("error_knowledge_links", "knowledge_point_id", ["error_id"]),
    ("misconceptions", "knowledge_point_id", None),
    ("error_records", "knowledge_point_id", None),
    ("flashcards", "knowledge_point_id", None),
    ("study_events", "knowledge_point_id", None),
    ("memory_facts", "knowledge_point_id", None),
]
# ---- 引用 quiz_questions.id 的子表 ----
Q_CHILDREN = [
    ("question_knowledge_links", "question_id", ["knowledge_point_id"]),
    ("answer_records", "question_id", None),
    ("paper_questions", "question_id", None),
    ("exam_answers", "question_id", None),
    ("error_records", "question_id", None),
    ("study_events", "question_id", None),
    ("misconceptions", "question_id", None),
    ("paper_answers", "question_id", None),
    ("memory_traces", "question_id", None),
    ("quiz_attempts", "question_id", None),
    ("answer_candidates", "question_id", None),
    ("question_images", "question_id", None),
]


def plan_kp(conn):
    rows = conn.execute(
        text(
            "SELECT id, coalesce(subject,''), name, parent_id, "
            "char_length(coalesce(description,'')) dl, (extract_source is not null)::int hs "
            "FROM knowledge_points WHERE name IS NOT NULL"
        )
    ).all()
    groups = {}
    for r in rows:
        key = (r[1], r[2], r[3])  # subject, name, parent_id
        groups.setdefault(key, []).append((r[0], r[4], r[5]))  # id, desc_len, has_source
    plan = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda m: (-m[1], -m[2], m[0]))  # 有描述 > 有来源 > 最小 id
        canon = members[0][0]
        dups = [m[0] for m in members[1:]]
        plan.append((key, canon, dups))
    return plan


def plan_questions(conn):
    rows = conn.execute(
        text(
            "SELECT id, content, coalesce(answer,''), coalesce(analysis,''), "
            "coalesce(year,0), coalesce(paper,'') FROM quiz_questions WHERE content IS NOT NULL"
        )
    ).all()
    groups = {}
    for r in rows:
        groups.setdefault(r[1], []).append((r[0], len(r[2]), len(r[3]), r[4], r[5]))
    plan = []
    for content, members in groups.items():
        if len(members) < 2:
            continue
        years = {m[3] for m in members}
        papers = {m[4] for m in members}
        if len(years) > 1 or len(papers) > 1:
            continue  # 跨年/跨卷的占位题（如英语写作）保留，不合并
        members.sort(key=lambda m: (-m[1], -m[2], m[0]))  # 有答案 > 有解析 > 最小 id
        canon = members[0][0]
        dups = [m[0] for m in members[1:]]
        plan.append((content[:40], canon, dups))
    return plan


def apply_kp(conn, plan):
    total_del = 0
    for _key, canon, dups in plan:
        for dup in dups:
            for table, col, ccols in KP_CHILDREN:
                reassign(conn, table, col, dup, canon, ccols)
            _exec(conn, "DELETE FROM knowledge_points WHERE id = :id", {"id": dup})
            total_del += 1
    return total_del


def apply_questions(conn, plan):
    total_del = 0
    for _, canon, dups in plan:
        for dup in dups:
            for table, col, ccols in Q_CHILDREN:
                reassign(conn, table, col, dup, canon, ccols)
            _exec(conn, "DELETE FROM quiz_questions WHERE id = :id", {"id": dup})
            total_del += 1
    return total_del


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--questions-only", action="store_true")
    ap.add_argument("--kp-only", action="store_true")
    args = ap.parse_args()

    with engine.connect() as conn:
        kp_plan = [] if args.questions_only else plan_kp(conn)
        q_plan = [] if args.kp_only else plan_questions(conn)

        kp_dup_rows = sum(len(d) for _, _, d in kp_plan)
        q_dup_rows = sum(len(d) for _, _, d in q_plan)
        print(f"[plan] KP 重复组={len(kp_plan)} 待删行={kp_dup_rows}")
        print(f"[plan] 题目重复组(排除跨年卷)={len(q_plan)} 待删行={q_dup_rows}")
        for key, canon, dups in kp_plan[:8]:
            print(
                f"   KP  {key[0]!r} / {key[1]!r} / parent={key[2]} → 保留 {canon} 删 {dups[:5]}{'...' if len(dups) > 5 else ''}"
            )
        for label, canon, dups in q_plan[:8]:
            print(f"   Q   {label!r} → 保留 {canon} 删 {dups[:5]}{'...' if len(dups) > 5 else ''}")

        if not args.apply:
            print("\n[dry-run] 未执行任何写入。加 --apply 执行。")
            return

        conn.rollback()  # 结束读事务，让写入走新事务
        try:
            kp_del = apply_kp(conn, kp_plan)
            q_del = apply_questions(conn, q_plan)
            conn.commit()
            print(f"\n[apply] 已删除重复 KP {kp_del} 行、重复题目 {q_del} 行（关联已迁移）。")
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            print(f"\n[apply] 失败已回滚: {e}")
            raise


if __name__ == "__main__":
    main()
