# -*- coding: utf-8 -*-
"""统一去重脚本 · PostgreSQL（6 类新去重 + 调用现有 dedupe_existing.py 处理 kp/quiz）。

覆盖 C-DEDUPE@1 契约（design.md §2.2）：
  words                    按 word 去重，保留 id 最小行，迁移 review_schedules(item_type='word')
  kaoyan_admission_details 按 (school_id, year, exam_no, name) 去重，保留 id 最小行
  kaoyan_scorelines        按 (school_id, year, major_code, line_type, depart_name, degree_type)
                           去重，保留 total_line 非空行
  kaoyan_majors            按 (school_id, code, name) 去重，保留 id 最小行，
                           迁移 kaoyan_major_subject_links(major_id)
  kaoyan_notices           按 url 去重（url 非空），保留 publish_date 最新行
  textbooks                按 title 去重，保留 id 最小行，迁移 textbook_documents(textbook_id)

安全：
  - 默认 dry-run 只打印计划；--apply 才写库
  - 6 类新去重在单事务 + SAVEPOINT 隔离子表迁移，失败回滚
  - 幂等：去重后重复组消失，重复执行 no-op
  - `all` 子命令顺序：words/textbooks/notices → majors/admissions/scorelines → dedupe_existing.py(kp/quiz)

用法::
    python scripts/governance/dedupe_all_pg.py words              # dry-run
    python scripts/governance/dedupe_all_pg.py all --apply        # 全部写库
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Any, Callable, Sequence

import psycopg

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from scripts._conn import pg_connect  # noqa: E402

# 去重计划项：(group_key, canon_id, [dup_id, ...])
DedupePlan = list[tuple[Any, int, list[int]]]


# --------------------------------------------------------------------------- #
# 子表迁移：把 child.child_col=dup 的行改指到 canon，唯一冲突行先删
# --------------------------------------------------------------------------- #
def reassign(
    conn: psycopg.Connection,
    table: str,
    child_col: str,
    dup: int,
    canon: int,
    conflict_cols: Sequence[str] | None = None,
    where_extra: str | None = None,
) -> tuple[int, int]:
    """单条 UPDATE/DELETE 包 SAVEPOINT，失败不污染外层事务。返回 (updated, deleted)。

    where_extra: 追加到 WHERE 的额外过滤（如 item_type='word'），用于多态外键。
    conflict_cols: 子表上可能与 canon 行冲突的列（如 user_id），冲突行先删再 UPDATE。
    """
    where_clause = f" AND {where_extra}" if where_extra else ""
    updated = deleted = 0

    if conflict_cols:
        cols = ", ".join(conflict_cols)
        with conn.transaction():
            cur = conn.execute(
                f"DELETE FROM {table} WHERE {child_col} = %s{where_clause} AND ({cols}) IN "
                f"(SELECT {cols} FROM {table} WHERE {child_col} = %s{where_clause})",
                (dup, canon),
            )
            deleted = cur.rowcount or 0

    try:
        with conn.transaction():
            cur = conn.execute(
                f"UPDATE {table} SET {child_col} = %s WHERE {child_col} = %s{where_clause}",
                (canon, dup),
            )
            updated = cur.rowcount or 0
    except Exception:  # noqa: BLE001 — 唯一冲突兜底：删掉 dup 的剩余子行
        with conn.transaction():
            cur = conn.execute(f"DELETE FROM {table} WHERE {child_col} = %s{where_clause}", (dup,))
            deleted += cur.rowcount or 0
    return updated, deleted


# --------------------------------------------------------------------------- #
# 通用 plan 构造：按 key 列分组，保留 id 最小行
# --------------------------------------------------------------------------- #
def _plan_by_key(
    conn: psycopg.Connection,
    sql: str,
    params: Sequence[Any] = (),
) -> DedupePlan:
    """执行 ``sql``（返回 id 在首列、分组键在后续列），按键分组保留 id 最小行。

    sql 必须按 id 升序返回，以保证 ``ids[0]`` 即为组内最小 id。
    """
    cur = conn.execute(sql, params)
    groups: dict[tuple, list[int]] = {}
    for row in cur.fetchall():
        rid, *key_parts = row
        key = tuple(key_parts) if len(key_parts) > 1 else key_parts[0]
        groups.setdefault(key, []).append(rid)
    return [(key, ids[0], ids[1:]) for key, ids in groups.items() if len(ids) > 1]


# --------------------------------------------------------------------------- #
# words：按 word 去重，保留 id 最小行，迁移 review_schedules(word)
# --------------------------------------------------------------------------- #
def plan_words(conn: psycopg.Connection) -> DedupePlan:
    return _plan_by_key(
        conn,
        "SELECT id, word FROM words WHERE word IS NOT NULL ORDER BY id",
    )


def apply_words(conn: psycopg.Connection, plan: DedupePlan) -> int:
    total = 0
    for _, canon, dups in plan:
        for dup in dups:
            reassign(
                conn,
                "review_schedules",
                "item_id",
                dup,
                canon,
                conflict_cols=["user_id"],
                where_extra="item_type='word'",
            )
            conn.execute("DELETE FROM words WHERE id = %s", (dup,))
            total += 1
    return total


# --------------------------------------------------------------------------- #
# kaoyan_admission_details：按 (school_id, year, exam_no, name) 去重，保留 id 最小行
# --------------------------------------------------------------------------- #
def plan_admissions(conn: psycopg.Connection) -> DedupePlan:
    return _plan_by_key(
        conn,
        "SELECT id, school_id, year, exam_no, name FROM kaoyan_admission_details ORDER BY id",
    )


def apply_admissions(conn: psycopg.Connection, plan: DedupePlan) -> int:
    return _delete_dups(conn, plan, "kaoyan_admission_details")


# --------------------------------------------------------------------------- #
# kaoyan_scorelines：按 (school_id, year, major_code, line_type, depart_name, degree_type)
# 去重，保留 total_line 非空行（score 代理）；同优先级保留 id 最小
# --------------------------------------------------------------------------- #
def plan_scorelines(conn: psycopg.Connection) -> DedupePlan:
    cur = conn.execute(
        "SELECT id, school_id, year, major_code, line_type, depart_name, degree_type, "
        "total_line IS NOT NULL AS has_score "
        "FROM kaoyan_scorelines ORDER BY id"
    )
    groups: dict[tuple, list[tuple[int, bool]]] = {}
    for rid, sid, yr, mcode, ltype, dname, dtype, has_score in cur.fetchall():
        key = (sid, yr, mcode, ltype, dname, dtype)
        groups.setdefault(key, []).append((rid, bool(has_score)))
    plan: DedupePlan = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # has_score=True 优先；同优先级 id 升序
        members.sort(key=lambda m: (not m[1], m[0]))
        canon = members[0][0]
        dups = [m[0] for m in members[1:]]
        plan.append((key, canon, dups))
    return plan


def apply_scorelines(conn: psycopg.Connection, plan: DedupePlan) -> int:
    return _delete_dups(conn, plan, "kaoyan_scorelines")


# --------------------------------------------------------------------------- #
# kaoyan_majors：按 (school_id, code, name) 去重，保留 id 最小行，
# 迁移 kaoyan_major_subject_links(major_id)
# --------------------------------------------------------------------------- #
def plan_majors(conn: psycopg.Connection) -> DedupePlan:
    return _plan_by_key(
        conn,
        "SELECT id, school_id, code, name FROM kaoyan_majors ORDER BY id",
    )


def apply_majors(conn: psycopg.Connection, plan: DedupePlan) -> int:
    total = 0
    for _, canon, dups in plan:
        for dup in dups:
            reassign(
                conn,
                "kaoyan_major_subject_links",
                "major_id",
                dup,
                canon,
                conflict_cols=["subject_id"],
            )
            conn.execute("DELETE FROM kaoyan_majors WHERE id = %s", (dup,))
            total += 1
    return total


# --------------------------------------------------------------------------- #
# kaoyan_notices：按 url 去重（url 非空），保留 publish_date 最新行；
# None 视为最旧；同日期保留 id 最小
# --------------------------------------------------------------------------- #
def plan_notices(conn: psycopg.Connection) -> DedupePlan:
    cur = conn.execute(
        "SELECT id, url, publish_date FROM kaoyan_notices WHERE url IS NOT NULL AND url <> '' ORDER BY id"
    )
    groups: dict[str, list[tuple[int, Any]]] = {}
    for rid, url, pdate in cur.fetchall():
        groups.setdefault(url, []).append((rid, pdate))
    plan: DedupePlan = []
    for url, members in groups.items():
        if len(members) < 2:
            continue
        # 保留 publish_date 最新；None 视为最旧；同日期保留 id 最小
        canon = max(
            members,
            key=lambda m: (
                m[1] is not None,  # 有日期优先
                m[1] or "",  # 日期大者优先
                -m[0],  # id 小者优先（-id 大）
            ),
        )[0]
        dups = [m[0] for m in members if m[0] != canon]
        plan.append((url, canon, dups))
    return plan


def apply_notices(conn: psycopg.Connection, plan: DedupePlan) -> int:
    return _delete_dups(conn, plan, "kaoyan_notices")


# --------------------------------------------------------------------------- #
# textbooks：按 title 去重（无 edition 列），保留 id 最小行，
# 迁移 textbook_documents(textbook_id)
# --------------------------------------------------------------------------- #
def plan_textbooks(conn: psycopg.Connection) -> DedupePlan:
    return _plan_by_key(
        conn,
        "SELECT id, title FROM textbooks WHERE title IS NOT NULL ORDER BY id",
    )


def apply_textbooks(conn: psycopg.Connection, plan: DedupePlan) -> int:
    total = 0
    for _, canon, dups in plan:
        for dup in dups:
            reassign(
                conn,
                "textbook_documents",
                "textbook_id",
                dup,
                canon,
                conflict_cols=["document_id"],
            )
            # 删除 textbook 前先把引用行的 resource_type 改为 'other'，
            # 避免外键 SET NULL 后违反 ck_major_subject_resource_textbook 约束
            conn.execute(
                "UPDATE kaoyan_major_subject_resources SET resource_type = 'other' "
                "WHERE textbook_id = %s AND resource_type = 'textbook'",
                (dup,),
            )
            conn.execute("DELETE FROM textbooks WHERE id = %s", (dup,))
            total += 1
    return total


def _delete_dups(conn: psycopg.Connection, plan: DedupePlan, table: str) -> int:
    """无子表迁移的简单去重：直接按 dup id 删除主表行。"""
    total = 0
    for _, _canon, dups in plan:
        for dup in dups:
            conn.execute(f"DELETE FROM {table} WHERE id = %s", (dup,))
            total += 1
    return total


# --------------------------------------------------------------------------- #
# 调度表 + 统一执行入口
# --------------------------------------------------------------------------- #
PLANNERS: dict[str, Callable[[psycopg.Connection], DedupePlan]] = {
    "words": plan_words,
    "admissions": plan_admissions,
    "scorelines": plan_scorelines,
    "majors": plan_majors,
    "notices": plan_notices,
    "textbooks": plan_textbooks,
}
APPLIERS: dict[str, Callable[[psycopg.Connection, DedupePlan], int]] = {
    "words": apply_words,
    "admissions": apply_admissions,
    "scorelines": apply_scorelines,
    "majors": apply_majors,
    "notices": apply_notices,
    "textbooks": apply_textbooks,
}
LABELS: dict[str, str] = {
    "words": "words",
    "admissions": "kaoyan_admission_details",
    "scorelines": "kaoyan_scorelines",
    "majors": "kaoyan_majors",
    "notices": "kaoyan_notices",
    "textbooks": "textbooks",
}
# all 顺序：先无外键依赖，再有子表依赖（design.md §2.3 Open decisions）
ALL_ORDER: list[str] = ["words", "textbooks", "notices", "majors", "admissions", "scorelines"]


def run_one(conn: psycopg.Connection, target: str, apply: bool) -> int:
    """执行单类去重：plan → 打印 → (apply 时) 写库。返回已删行数。"""
    plan = PLANNERS[target](conn)
    dup_rows = sum(len(d) for _, _, d in plan)
    label = LABELS[target]
    print(f"[plan] {label} 重复组={len(plan)} 待删行={dup_rows}")
    for key, canon, dups in plan[:8]:
        preview = dups[:5]
        suffix = "..." if len(dups) > 5 else ""
        print(f"   {label} key={key!r} → 保留 {canon} 删 {preview}{suffix}")
    if not apply or not plan:
        return 0
    deleted = APPLIERS[target](conn, plan)
    print(f"[apply] {label} 已删 {deleted} 行")
    return deleted


def run_dedupe_existing(apply: bool) -> bool:
    """调用现有 dedupe_existing.py 处理 kp/quiz 去重（独立事务）。返回是否成功。"""
    cmd = [sys.executable, "scripts/dedupe_existing.py"]
    if apply:
        cmd.append("--apply")
    print(f"\n[dedupe_existing] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=_BACKEND_ROOT)
    if result.returncode != 0:
        print(f"[dedupe_existing] 退出码 {result.returncode}")
    return result.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="统一去重脚本（C-DEDUPE@1）")
    ap.add_argument(
        "target",
        choices=["words", "admissions", "scorelines", "majors", "notices", "textbooks", "all"],
        help="去重目标",
    )
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = ap.parse_args()

    targets = ALL_ORDER if args.target == "all" else [args.target]

    conn = pg_connect()
    total_deleted = 0
    try:
        for t in targets:
            total_deleted += run_one(conn, t, args.apply)
        if args.apply:
            conn.commit()
            print(f"\n[apply] 6 类去重已提交，共删 {total_deleted} 行。")
        else:
            conn.rollback()
            print("\n[dry-run] 6 类去重未写库。加 --apply 执行。")
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        print(f"\n[失败] 6 类去重已回滚: {e}")
        raise
    finally:
        conn.close()

    # kp/quiz 去重交由现有脚本（独立事务），仅在 all 时调用
    if args.target == "all":
        run_dedupe_existing(args.apply)
    return 0


if __name__ == "__main__":
    main()
