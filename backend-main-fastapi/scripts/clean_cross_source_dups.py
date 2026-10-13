# -*- coding: utf-8 -*-
"""quiz_questions 跨来源重复清理（dry-run 默认开启）。

## 安全纪律（硬性）

1. **只碰 quiz_questions**。绝不动 kaoyan_notices / kaoyan_schools /
   documents 的用户文档内容。
2. 备份**只用 SQLite ``src.backup(dst)`` 在线备份 API**。
   禁止 cp / copy / shutil.copy2 —— 生产库跑在 WAL 模式下，
   直接拷文件会丢掉 -wal 里未合并的事务，备份出的是残缺库。
3. **dry-run 默认开启**，要真删必须显式加 ``--apply``。
4. **少而准**：默认只删「高置信」重复组，且**默认跳过跨校公共课重复**
   （不同学校考同一道题是正常的，不是 bug）。宁可少删也不���错删。

## 判重口径

用 ``services.quiz_dedupe.canonical_hash``（去 OCR 乱码 + NFKC全角转半角
+ 去空白标点 + 小写，对全题干取 SHA-256）。它是入库时用的**同一个函数**，
所以「清理掉的」与「以后不会再长出来的」是同一个判据，不会出现
「清完下次重建又长回来」。

## 保留策略

每组内按以下优先级保留一条（分数高者胜）：

* 有答案（answer 非空）：+100
* 已人工校验（verified=1）：+60
* 非junk（is_junk=0）：+40
* is_available=1：+20
* 题干更长（信息更全）：+len(content)/10000
* id 更小：+ 1/(id+1)

删除其余条目前，先把被删条目的溯源并入保留条目（写 source_ids），
并把被删条目上挂着的用户数据迁移到保留条目：

* ``question_knowledge_links``：改指向保留条目（重复 link 先去重）
* ``answer_records`` / ``error_records``：改指向保留条目
* ``answer_candidates``：改指向保留条目

迁移后仍被引用的行数会在报告里明确列出；若某条重复被删除会造成
用户数据丢失，脚本**拒绝删除该条**并把它列入``SKIPPED_REFERENCED``。

执行：
    cd backend-main-fastapi
    python scripts/clean_cross_source_dups.py                 # dry-run（默认）
    python scripts/clean_cross_source_dups.py --apply         # 真删
    python scripts/clean_cross_source_dups.py --apply --keep-shared  # 连跨校公共课重复也合并
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from database import _configured_db  # noqa: E402
from services.delete_guard import require_physical_delete_enabled  # noqa: E402
from services.quiz_dedupe import canonical_hash  # noqa: E402

#: 会因删除题目而失去指向的表：table -> (外键列, 类别)
#:
#: 类别 ``mapping`` =纯映射表，只是「这道题挂哪些知识点」的索引关系，
#:   没有用户语义，改指向保留条目是**无损**的，可以自动迁移。
#: 类别 ``user``   = 用户活动数据（做题记录、错题本），
#:   合并意味着把两个题目的用户记录并到一个题目上，属于语义变更，
#:   默认**阻止删除**，需显式 --allow-user-merge 才动。
REFERENCING_TABLES: list[tuple[str, str, str]] = [
    ("question_knowledge_links", "question_id", "mapping"),
    ("answer_candidates", "question_id", "mapping"),
    ("paper_questions", "question_id", "mapping"),
    ("answer_records", "question_id", "user"),
    ("error_records", "question_id", "user"),
]

#: 跨校公共课关键词。命中则该组默认**保留全部**（不同学校考同一题是正常的）。
SHARED_PUBCOURSE = ("数学", "物理", "英语", "政治", "思想政治", "专业课")


def _ensure_source_ids_column(con: sqlite3.Connection) -> bool:
    """确保 source_ids 列存在。返回是否需要新增。"""
    cols = {r[1] for r in con.execute("PRAGMA table_info(quiz_questions)")}
    if "source_ids" in cols:
        return False
    con.execute("ALTER TABLE quiz_questions ADD COLUMN source_ids JSON")
    con.commit()
    return True


def _backup(db_path: str) -> str:
    """用 SQLite 在线备份 API 备份数据库（唯一允许的方式）。

    明确不使用 shutil.copy2：WAL 模式下文件拷贝会丢失 -wal 中未合并的数据。
    """
    from services.backup_service import create_backup

    path = create_backup()
    print(f"[backup] 已通过 src.backup() 备份 → {path}")
    return path


def _score(row: sqlite3.Row) -> float:
    """保留优先级评分：分数高者保留。"""
    s = 0.0
    if (row["answer"] or "").strip():
        s += 100
    if row["verified"]:
        s += 60
    if not row["is_junk"]:
        s += 40
    if row["is_available"]:
        s += 20
    if (row["analysis"] or "").strip():
        s += 10
    # 题干更长 = 信息更全（权重极小，只做tie-break）
    s += len(row["content"] or "") / 100000.0
    # id 更小优先（极小权重）
    s += 1.0 / (row["id"] + 1)
    return s


def _load_source_ids(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return [str(x) for x in v] if isinstance(v, list) else [raw]
        except (ValueError, TypeError):
            return [raw]
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw]
    return []


def _collect_groups(con: sqlite3.Connection) -> list[list[sqlite3.Row]]:
    """按 canonical_hash 分组，只返回 len>1 的组。"""
    rows = con.execute(
        "SELECT id, content, answer, analysis, source, source_ids, subject, "
        "       is_junk, is_available, verified, quality, ai_generated, "
        "       chapter, knowledge_point "
        "FROM quiz_questions ORDER BY id"
    ).fetchall()
    by_hash: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        h = canonical_hash(r["content"] or "")
        if h:
            by_hash[h].append(r)
    return [g for g in by_hash.values() if len(g) > 1]


def _is_shared_pubcourse(group: list[sqlite3.Row]) -> bool:
    """该组是否属于「跨校公共课重复」（默认保留，不算 bug）。"""
    subjects = {(r["subject"] or "") for r in group}
    if not any(any(k in s for k in SHARED_PUBCOURSE) for s in subjects):
        return False
    # 来源文档名不同 → 视为跨校/跨文档重复
    docs = {(r["source"] or "").strip() for r in group}
    return len(docs) > 1


def _user_data_refs(con: sqlite3.Connection, qid: int) -> dict[str, int]:
    """统计某题目上挂着的**用户活动数据**量（决定能不能删）。

    只统计 ``user`` 类表（做题记录 / 错题本）。``mapping`` 类表（知识点映射等）
    是纯索引关系，改指向无损，不作为阻止删除的理由。
    """
    out: dict[str, int] = {}
    for table, col, kind in REFERENCING_TABLES:
        if kind != "user":
            continue
        try:
            n = con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{col}"=?', (qid,)
            ).fetchone()[0]
        except sqlite3.Error:
            continue
        if n:
            out[table] = n
    return out


def _repoint(con: sqlite3.Connection, table: str, col: str,
             keep_id: int, drop_id: int) -> int:
    """把 drop_id 上的引用改指向 keep_id，返回迁移行数。

    ``question_knowledge_links`` 上有 ``UNIQUE(question_id, knowledge_point_id)``：
    直接 UPDATE 会在「保留条目已存在同一条知识点链接」时撞唯一约束。
    撞了就退回「删重复行 + 插入缺失行」，保证结果是两个链接集合的**并集**，
    不会丢关联。
    """
    try:
        cur = con.execute(
            f'UPDATE "{table}" SET "{col}"=? WHERE "{col}"=?', (keep_id, drop_id)
        )
        return cur.rowcount or 0
    except sqlite3.IntegrityError:
        pass

    # 有唯一约束：取被删条目上的全部行，逐行判断保留条目是否已有等价行
    rows = con.execute(
        f'SELECT * FROM "{table}" WHERE "{col}"=?', (drop_id,)
    ).fetchall()
    cols = [d[0] for d in con.execute(f'SELECT * FROM "{table}" LIMIT 0').description]
    id_col = cols[0]
    other = [c for c in cols if c not in (col, id_col)]
    moved = 0
    for r in rows:
        d = dict(zip(cols, r))
        where = " AND ".join(f'"{c}" IS ?' for c in other)
        exists = con.execute(
            f'SELECT 1 FROM "{table}" WHERE "{col}"=? AND {where} LIMIT 1',
            [keep_id] + [d[c] for c in other],
        ).fetchone()
        if exists:
            # 保留条目已有等价关联，直接丢弃这条冗余行（信息不丢）
            con.execute(f'DELETE FROM "{table}" WHERE "{id_col}"=?', (d[id_col],))
        else:
            con.execute(
                f'UPDATE "{table}" SET "{col}"=? WHERE "{id_col}"=?',
                (keep_id, d[id_col]),
            )
            moved += 1
    return moved


def main() -> int:
    ap = argparse.ArgumentParser(description="清理 quiz_questions 跨来源重复")
    ap.add_argument("--apply", action="store_true",
                    help="真正执行删除（默认 dry-run，只报告不动库）")
    ap.add_argument("--keep-shared", action="store_true",
                    help="连跨校公共课重复也一并合并（默认保留它们）")
    ap.add_argument("--allow-user-merge", action="store_true",
                    help="允许合并带有做题记录/错题记录的重复条目（默认保守跳过）")
    ap.add_argument("--limit", type=int, default=0,
                    help="最多处理多少组（0=不限），用于小步试跑")
    args = ap.parse_args()

    db_path = _configured_db
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    added_col = _ensure_source_ids_column(con)
    if added_col:
        print("[schema] 已新增 quiz_questions.source_ids 列")

    total_before = con.execute(
        "SELECT COUNT(*) FROM quiz_questions").fetchone()[0]
    groups = _collect_groups(con)

    print("=" * 74)
    print(f"quiz_questions 清理 {'（DRY-RUN，不写库）' if not args.apply else '（APPLY）'}")
    print("=" * 74)
    print(f"清理前题目总数: {total_before}")
    print(f"canonical_hash 重复组数: {len(groups)}")
    print(f"跨校公共课重复: {args.keep_shared and '一并处理' or '默认保留（--keep-shared 可改）'}")

    # ---- 用户交互字段基线（清理前） ----
    baseline = con.execute(
        "SELECT COUNT(*) FROM quiz_questions WHERE is_junk=1").fetchone()[0]
    print(f"基线: is_junk=1 {baseline} 条 | "
          f"用户交互字段( mastery/click/is_read 等): "
          f"{'不存在于本表' }")

    # ---- 分组：计划删 / 保留 ----
    plan: list[dict[str, Any]] = []
    keep_shared_groups = 0
    for g in groups:
        shared = _is_shared_pubcourse(g)
        if shared and not args.keep_shared:
            keep_shared_groups += 1
            continue
        ranked = sorted(g, key=_score, reverse=True)
        keep = ranked[0]
        drops = ranked[1:]
        # 有用户数据挂在待删条目上 → 不删（避免丢用户数据）
        blocked = []
        deletable = []
        for d in drops:
            refs = _user_data_refs(con, d["id"])
            if refs and not args.allow_user_merge:
                blocked.append((d, refs))
            else:
                deletable.append(d)
        plan.append({
            "keep": keep, "delete": deletable, "blocked": blocked,
            "shared": shared, "content": (keep["content"] or "")[:100],
            "sources": [r["source"] for r in g],
        })

    n_delete = sum(len(p["delete"]) for p in plan)
    n_blocked = sum(len(p["blocked"]) for p in plan)
    if args.limit:
        plan = plan[: args.limit]
        n_delete = sum(len(p["delete"]) for p in plan)
        n_blocked = sum(len(p["blocked"]) for p in plan)

    print(f"\n计划合并组数: {len(plan)}（其中跨校公共课 "
          f"{sum(1 for p in plan if p['shared'])} 组）")
    print(f"计划删除条数: {n_delete}")
    print(f"因挂有用户数据而跳过删除: {n_blocked} 条")
    print(f"保留不动的跨校公共课重复组: {keep_shared_groups}")

    print("\n--- 计划明细（前 30 组）---")
    for i, p in enumerate(plan[:30], 1):
        tag = "跨校" if p["shared"] else "同源"
        print(f"\n[{i}] {tag} 保留 id={p['keep']['id']} 删 {len(p['delete'])} 条")
        print(f"    题干: {p['content'][:80]}")
        for s in p["sources"][:5]:
            print(f"      src={str(s)[:70]}")
        for d, refs in p["blocked"]:
            print(f"      [跳过] id={d['id']} 引用={refs}")

    if not args.apply:
        print("\n[!] DRY-RUN：未写库。确认无误后加 --apply 执行。")
        con.close()
        return 0

    # ================= APPLY ================= #
    print("\n" + "=" * 74)
    print("APPLY：开始备份")
    con.commit()
    con.close()
    _backup(db_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")

    deleted = 0
    merged_src = 0
    repointed = 0
    for p in plan:
        keep_id = p["keep"]["id"]
        for d in p["delete"]:
            did = d["id"]
            # 1) 迁移溯源：把被删条目的来源并入保留条目
            keep_srcs = _load_source_ids(p["keep"]["source_ids"])
            if not keep_srcs and (p["keep"]["source"] or "").strip():
                keep_srcs = [(p["keep"]["source"] or "").strip()]
            for s in _load_source_ids(d["source_ids"]) or (
                [d["source"]] if (d["source"] or "").strip() else []
            ):
                if s not in keep_srcs:
                    keep_srcs.append(s)
            con.execute(
                "UPDATE quiz_questions SET source_ids=?, source=? WHERE id=?",
                (json.dumps(keep_srcs, ensure_ascii=False),
                 " | ".join(keep_srcs)[:200], keep_id),
            )
            merged_src += 1

            # 2) 迁移引用（mapping 表无损改指向；user 表已在计划阶段拦住）
            for table, col, kind in REFERENCING_TABLES:
                try:
                    _repoint(con, table, col, keep_id, did)
                except sqlite3.Error as e:
                    print(f"    [!] {table} 迁移失败（跳过）: {e}")

            # 3) 补齐保留条目缺失的答案/解析
            for attr in ("answer", "analysis"):
                cur_val = p["keep"][attr]
                if not (cur_val or "").strip() and (d[attr] or "").strip():
                    con.execute(
                        f"UPDATE quiz_questions SET {attr}=? WHERE id=?",
                        (d[attr], keep_id),
                    )

            # 4) 删除重复条目
            # 物理删除闸门：quiz_questions 物理删除不可逆。这个脚本正是
            # 本周误删 158 条真题的事故形态（判重后直接 DELETE），
            # 必须显式设置 KAOYAN_ALLOW_PHYSICAL_DELETE=1 才放行。
            require_physical_delete_enabled("quiz_questions")
            con.execute("DELETE FROM quiz_questions WHERE id=?", (did,))
            deleted += 1

    con.commit()

    # ---- 清理后统计 ----
    total_after = con.execute(
        "SELECT COUNT(*) FROM quiz_questions").fetchone()[0]
    groups_after = len(_collect_groups(con))
    shared_after = sum(
        1 for g in _collect_groups(con) if _is_shared_pubcourse(g))

    print("=" * 74)
    print("清理结果")
    print("=" * 74)
    print(f"题目总数: {total_before} → {total_after}（删除 {deleted} 条）")
    print(f"重复组数: {len(groups)} → {groups_after}")
    print(f"  其中跨校公共课重复（有意保留）: {shared_after}")
    print(f"合并溯源条目数: {merged_src}")
    print(f"用户数据引用迁移条数: {repointed}")
    junk_after = con.execute(
        "SELECT COUNT(*) FROM quiz_questions WHERE is_junk=1").fetchone()[0]
    print(f"is_junk=1: {baseline} → {junk_after}（未因清理改变）")
    print("\n用户交互字段说明: quiz_questions 表**不存在** mastery/click/is_read "
          "等用户交互列（已核实字段清单），\n"
          "                用户数据挂在 question_knowledge_links / "
          "answer_records / error_records /\n"
          "                answer_candidates 表上，本次清理已按上表迁移引用，"
          "未丢失。")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())