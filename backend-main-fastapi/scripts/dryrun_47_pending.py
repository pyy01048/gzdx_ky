# -*- coding: utf-8 -*-
"""47 组裁决表 · 待执行错误侧的 ATTACH dry-run diff（只读，绝不写库）。

用途：team-lead 要求「先 ATTACH dry-run diff 给我看越界 id 数量，确认后再 UPDATE」。
本脚本只做 SELECT，输出：
  - 40 条待写库 id 的当前 is_junk 值（与备份对比）
  - 正确侧 id 的当前 is_junk 值（必须保持 0）
  - 越界 id 数量（备份与主库在目标 id 之外是否存在差异）
  - 受影响用户可见题（有答案 + is_junk=0）的数量

红线：不执行任何 UPDATE / DELETE。
"""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, r"D:\平台\backend-main-fastapi\scripts")
from reconcile_47_groups import TABLE  # noqa: E402

DB_PATH = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\database\_backup"
PREFIX = "kaoyan_pre_isolate_"


def latest_backup() -> str | None:
    if not os.path.isdir(BACKUP_DIR):
        return None
    names = [n for n in os.listdir(BACKUP_DIR)
             if n.startswith(PREFIX) and n.endswith(".db")]
    return os.path.join(BACKUP_DIR, sorted(names)[-1]) if names else None


def main() -> int:
    backup = latest_backup()
    if not backup:
        print("[diff] 找不到备份，请先执行 isolate_conflict_quiz.py backup")
        return 1

    # 正确侧 = 保留原样（不得改动）；错误侧 = 待标 is_junk=1
    keep_ids, bad_ids = [], []
    for gid, a, b, keep, _note in TABLE:
        if keep is None:          # 两侧都错，上一轮已执行，跳过
            continue
        keep_ids.append(keep)
        bad_ids.append(b if keep == a else a)
    # O24：#6886 早已 is_junk=1，无需再改
    already = []
    todo = []
    conn = sqlite3.connect(DB_PATH, timeout=60)
    marks = ",".join("?" * len(bad_ids))
    cur = {r[0]: r[1] for r in conn.execute(
        f"SELECT id, is_junk FROM quiz_questions WHERE id IN ({marks})", bad_ids)}
    conn.close()
    for i in bad_ids:
        (already if cur.get(i) == 1 else todo).append(i)

    print(f"[diff] backup={backup}")
    print(f"[diff] 裁决表 47 组 → 两侧都错(已执行) {sum(1 for t in TABLE if t[3] is None)} 组；"
          f"有正确侧 {len(keep_ids)} 组")
    print(f"[diff] 错误侧合计 {len(bad_ids)} 条：已是 is_junk=1 {len(already)} 条 / "
          f"本次待改 {len(todo)} 条")
    print(f"[diff] 已是 junk 的 id（无需动作）: {sorted(already)}")

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("ATTACH DATABASE ? AS bak", (backup,))
        print(f"\n{'组':<5}{'错误侧':<8}{'bak.junk':<10}{'cur.junk':<10}{'delta':<8}正确侧(junk须为0)")
        print("-" * 72)
        changed, outside, keep_bad = 0, [], []
        todo_set = set(todo)
        for gid, a, b, keep, _n in TABLE:
            if keep is None:
                continue
            wrong = b if keep == a else a
            r = conn.execute(
                "SELECT b.is_junk, c.is_junk FROM bak.quiz_questions b "
                "JOIN main.quiz_questions c ON c.id=b.id WHERE b.id=?", (wrong,)).fetchone()
            rk = conn.execute(
                "SELECT is_junk FROM main.quiz_questions WHERE id=?", (keep,)).fetchone()
            if r is None:
                print(f"{gid:<5}{wrong:<8}缺失"); continue
            bj, cj = int(r[0]), int(r[1])
            kj = int(rk[0]) if rk else -1
            d = cj - bj
            flag = "" if kj == 0 else f"  ⚠正确侧 junk={kj}"
            if kj != 0:
                keep_bad.append((gid, keep, kj))
            if wrong in todo_set:
                print(f"{gid:<5}{wrong:<8}{bj:<10}{cj:<10}{d:+d}{'':<7}{keep}{flag}")
            if d != 0:
                changed += 1

        q = ("SELECT b.id FROM bak.quiz_questions b JOIN main.quiz_questions c "
             "ON c.id=b.id WHERE IFNULL(b.is_junk,-1)<>IFNULL(c.is_junk,-2)")
        params: list = []
        if todo:
            q += f" AND b.id NOT IN ({','.join('?'*len(todo))})"
            params = list(todo)
        outside = [r[0] for r in conn.execute(q, params)]

        tm = ",".join("?" * len(todo))
        vis = conn.execute(
            f"SELECT COUNT(*) FROM main.quiz_questions WHERE id IN ({tm}) "
            "AND is_junk=0 AND answer IS NOT NULL AND TRIM(answer)<>''", todo).fetchone()[0]
        tot = conn.execute("SELECT COUNT(*) FROM main.quiz_questions").fetchone()[0]
        btot = conn.execute("SELECT COUNT(*) FROM bak.quiz_questions").fetchone()[0]
        j0 = conn.execute("SELECT COUNT(*) FROM main.quiz_questions WHERE is_junk=0").fetchone()[0]
        conn.execute("DETACH DATABASE bak")
    finally:
        conn.close()

    print(f"\n[diff] 待改 {len(todo)} 条；与备份存在差异的 id 数 = {changed}")
    print(f"[diff] 越界 id（目标之外的变化）= {len(outside)} {outside if outside else ''}")
    print(f"[diff] 正确侧中 junk≠0 的组 = {len(keep_bad)} {keep_bad if keep_bad else ''}")
    print(f"[diff] 本次将被移出刷题区的「有答案」题 = {vis} 条")
    print(f"[diff] 行数 main={tot} / bak={btot} {'OK' if tot==btot else '不一致!'}；当前 is_junk=0 = {j0}")
    print("\n[dry-run] 本脚本未执行任何写操作。等 team-lead 确认后再走 UPDATE。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
