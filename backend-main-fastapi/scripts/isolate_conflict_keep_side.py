# -*- coding: utf-8 -*-
"""47 组裁决表 · 有正确侧的 40 条错误侧写库。

裁决（team-lead，2026-10-12 第二轮）：
  * 41 组「有正确侧」→ 正确侧保留原样（不改），错误侧 ``is_junk=1``。
  * O24（#6886 / #8390）**整组维持双 is_junk=1，不动**。勘误：O24 正确侧
    本身也是 junk，"正确性判定" 与 "启用判定" 是两件事，不得据前者推断后者。
  * 上一轮 6 组「两侧都错」已于 16:01 写库隔离，本脚本不再触碰。

红线：
  - 禁止 cp / shutil.copy2（WAL 模式会丢未合并事务），必须 backup() API
  - 禁止 DELETE，只 UPDATE is_junk

用法：
    python scripts/isolate_conflict_keep_side.py backup
    python scripts/isolate_conflict_keep_side.py diff
    python scripts/isolate_conflict_keep_side.py apply
    python scripts/isolate_conflict_keep_side.py verify
"""
from __future__ import annotations

import datetime
import os
import sqlite3
import sys

sys.path.insert(0, r"D:\平台\backend-main-fastapi\scripts")
from reconcile_47_groups import TABLE  # noqa: E402

DB_PATH = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\database\_backup"
PREFIX = "kaoyan_pre_keepside_"

#: team-lead 点名要逐条打出的 5 条（用户已可能刷到的错答案）
SPOTCHECK = (198, 270, 396, 6750, 8055)


def build_plan() -> tuple[list[int], list[int], list[int], list[tuple[str, int, int]]]:
    """返回 (待改错误侧 id, 正确侧 id, 已无需动作 id, [(组, 保留, 隔离)])。"""
    keep_ids, bad_ids, skip_ids, pairs = [], [], [], []
    for gid, a, b, keep, _note in TABLE:
        if keep is None:                     # 两侧都错，上一轮已隔离
            continue
        wrong = b if keep == a else a
        keep_ids.append(keep)
        pairs.append((gid, keep, wrong))
        (skip_ids if wrong == 6886 else bad_ids).append(wrong)  # O24 错误侧
    return bad_ids, keep_ids, skip_ids, pairs


def make_backup() -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_path = os.path.join(BACKUP_DIR, f"{PREFIX}{ts}.db")
    src = sqlite3.connect(DB_PATH, timeout=60)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
            check = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()
    print(f"[backup] path={dst_path}")
    print(f"[backup] size={round(os.path.getsize(dst_path)/1024/1024,1)} MB")
    print(f"[backup] integrity_check={check}")
    return dst_path


def latest_backup() -> str | None:
    if not os.path.isdir(BACKUP_DIR):
        return None
    names = [n for n in os.listdir(BACKUP_DIR)
             if n.startswith(PREFIX) and n.endswith(".db")]
    return os.path.join(BACKUP_DIR, sorted(names)[-1]) if names else None


def _marks(n: int) -> str:
    return ",".join("?" * n)


def dryrun() -> int:
    bad, keep, skip, pairs = build_plan()
    backup = latest_backup()
    if not backup:
        print("[diff] 无基线备份，请先 backup"); return 1
    conn = sqlite3.connect(DB_PATH, timeout=60)
    try:
        conn.execute("ATTACH DATABASE ? AS bak", (backup,))
        print(f"[diff] baseline={backup}")
        print(f"[diff] 待改 {len(bad)} 条 / 正确侧 {len(keep)} 条 / 无需动作 {len(skip)} 条 {skip}")
        print(f"\n{'组':<5}{'错误侧':<8}{'bak':<6}{'cur':<6}{'目标':<6}{'正确侧':<8}{'正确侧cur'}")
        print("-" * 60)
        for gid, k, w in pairs:
            if w in skip:
                print(f"{gid:<5}{w:<8}{'-':<6}{'-':<6}{'保持1':<6}{k:<8}(O24 整组不启用)")
                continue
            r = conn.execute(
                "SELECT b.is_junk, c.is_junk FROM bak.quiz_questions b "
                "JOIN main.quiz_questions c ON c.id=b.id WHERE b.id=?", (w,)).fetchone()
            rk = conn.execute("SELECT is_junk FROM main.quiz_questions WHERE id=?", (k,)).fetchone()
            print(f"{gid:<5}{w:<8}{r[0]:<6}{r[1]:<6}{1:<6}{k:<8}{rk[0]}")
        outside = [x[0] for x in conn.execute(
            "SELECT b.id FROM bak.quiz_questions b JOIN main.quiz_questions c "
            "ON c.id=b.id WHERE IFNULL(b.is_junk,-1)<>IFNULL(c.is_junk,-2)")]
        conn.execute("DETACH DATABASE bak")
    finally:
        conn.close()
    print(f"\n[diff] 越界 id 数量 = {len(outside)} {outside if outside else ''}")
    return len(outside)


def apply() -> None:
    bad, keep, skip, _p = build_plan()
    conn = sqlite3.connect(DB_PATH, timeout=60)
    try:
        conn.execute("BEGIN IMMEDIATE")
        before0 = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0").fetchone()[0]
        before1 = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=1").fetchone()[0]
        cur = conn.execute(
            f"UPDATE quiz_questions SET is_junk=1 "
            f"WHERE id IN ({_marks(len(bad))}) AND is_junk=0", bad)
        conn.commit()
        after0 = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0").fetchone()[0]
        after1 = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=1").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM quiz_questions").fetchone()[0]
        chk = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    print(f"[apply] UPDATE 影响行数={cur.rowcount}")
    print(f"[apply] is_junk=0 {before0} -> {after0}（Δ{after0-before0}）")
    print(f"[apply] is_junk=1 {before1} -> {after1}（Δ{after1-before1}）")
    print(f"[apply] 总行数={total}  integrity_check={chk}")


def verify() -> None:
    bad, keep, skip, pairs = build_plan()
    conn = sqlite3.connect(DB_PATH, timeout=60)
    try:
        conn.execute("ATTACH DATABASE ? AS bak", (latest_backup(),))
        print("=== 错误侧 40 条（必须全为 1）===")
        wrong_now = {r[0]: r[1] for r in conn.execute(
            f"SELECT id, is_junk FROM quiz_questions WHERE id IN ({_marks(len(bad))})", bad)}
        for gid, k, w in pairs:
            if w in skip:
                continue
            print(f"  {gid:<5} #{w:<6} is_junk={wrong_now.get(w)}  (正确侧 #{k})")
        badv = [i for i in bad if wrong_now.get(i) != 1]

        print("\n=== 正确侧 41 条（O24 的 8390 除外，必须全为 0）===")
        keep0 = [k for k in keep if k != 8390]
        keep_now = {r[0]: r[1] for r in conn.execute(
            f"SELECT id, is_junk FROM quiz_questions WHERE id IN ({_marks(len(keep0))})", keep0)}
        for gid, k, w in pairs:
            if k == 8390:
                continue
            print(f"  {gid:<5} #{k:<6} is_junk={keep_now.get(k)}  (错误侧 #{w})")
        keepv = [i for i in keep0 if keep_now.get(i) != 0]

        print("\n=== O24 勘误（整组维持双 junk，禁止启用 8390）===")
        for i in (6886, 8390):
            v = conn.execute("SELECT is_junk FROM quiz_questions WHERE id=?", (i,)).fetchone()[0]
            print(f"  #{i} is_junk={v}")
        o24 = conn.execute(
            "SELECT id,is_junk FROM quiz_questions WHERE id IN (6886,8390)").fetchall()
        o24v = [i for i, v in o24 if v != 1]

        # 越界定义：**目标 40 条之外**的任何 is_junk 变化才算越界。
        # （写库后 diff 对比写库前基线，必然出现这 40 条，那是预期内的动作本身。）
        q = ("SELECT b.id FROM bak.quiz_questions b JOIN main.quiz_questions c "
             "ON c.id=b.id WHERE IFNULL(b.is_junk,-1)<>IFNULL(c.is_junk,-2)")
        params: list = []
        if bad:
            q += f" AND b.id NOT IN ({_marks(len(bad))})"
            params = list(bad)
        outside = [x[0] for x in conn.execute(q, params)]
        # 同时记录"目标内实际发生变化的条数"，用于证明动作完整落地
        hit = [x[0] for x in conn.execute(
            "SELECT b.id FROM bak.quiz_questions b JOIN main.quiz_questions c "
            f"ON c.id=b.id WHERE IFNULL(b.is_junk,-1)<>IFNULL(c.is_junk,-2) "
            f"AND b.id IN ({_marks(len(bad))})", bad)]
        total = conn.execute("SELECT COUNT(*) FROM main.quiz_questions").fetchone()[0]
        j0 = conn.execute("SELECT COUNT(*) FROM main.quiz_questions WHERE is_junk=0").fetchone()[0]
        j1 = conn.execute("SELECT COUNT(*) FROM main.quiz_questions WHERE is_junk=1").fetchone()[0]
        vis = conn.execute(
            f"SELECT COUNT(*) FROM main.quiz_questions WHERE id IN ({_marks(len(bad))}) "
            "AND is_junk=0 AND answer IS NOT NULL AND TRIM(answer)<>''", bad).fetchone()[0]
        chk = conn.execute("PRAGMA integrity_check").fetchone()[0]
        conn.execute("DETACH DATABASE bak")
    finally:
        conn.close()

    print(f"\n=== team-lead 点名 5 条（必须 is_junk=1）===")
    for i in SPOTCHECK:
        print(f"  #{i} is_junk={wrong_now.get(i)}")
    spot_bad = [i for i in SPOTCHECK if wrong_now.get(i) != 1]

    print("\n=== 三项数字 + 复验汇总 ===")
    print(f"  总行数 = {total}（应 9095）")
    print(f"  is_junk=0 = {j0}")
    print(f"  is_junk=1 = {j1}")
    print(f"  integrity_check = {chk}")
    print(f"  越界 id 数量 = {len(outside)} {outside if outside else ''}")
    print(f"  目标内实际变化条数 = {len(hit)}（应 {len(bad)}）")
    print(f"  错误侧未变 1 的 = {len(badv)} {badv if badv else ''}")
    print(f"  正确侧被误改的 = {len(keepv)} {keepv if keepv else ''}")
    print(f"  O24 违规的 = {len(o24v)} {o24v if o24v else ''}")
    print(f"  点名 5 条未隔离的 = {len(spot_bad)} {spot_bad if spot_bad else ''}")
    print(f"  40 条中仍可见于刷题区 = {vis}")
    ok = not (badv or keepv or o24v or spot_bad or outside) and len(hit) == len(bad)
    print(f"\n[verify] {'全部通过 ✅' if ok else '存在异常 ❌'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "backup":
        make_backup()
    elif cmd == "diff":
        sys.exit(0 if dryrun() == 0 else 2)
    elif cmd == "apply":
        apply()
    elif cmd == "verify":
        verify()
    else:
        print(__doc__)
