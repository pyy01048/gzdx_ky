# -*- coding: utf-8 -*-
"""复核 2：相似度口径的同题干冲突组全量枚举（只读）。

为什么要有这个脚本：`recheck_conflict_groups.py` 用 canon() 精确归一化匹配，
实测 6 组已裁决组里有 5 组 canon 不相等（如 400 vs 8152 len 19/19 但字符串不同），
说明当初那 31 组是**相似度(0.86)** 口径判出来的，精确口径会严重漏检。

本脚本按长度分桶 + SequenceMatcher 做同题干聚类，再按答案是否冲突分组，
输出 team-lead 要求的逐组对照表。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher

sys.path.insert(0, r"D:\平台\backend-main-fastapi\scripts")
from recheck_conflict_groups import canon  # noqa: E402

DB_PATH = r"D:\平台\database\kaoyan.db"
SIM = 0.86
LEN_RATIO = 0.6

# team-lead 已明确裁决并写库的 6 组（两侧全隔离）
ADJUDICATED = {
    "G07": (288, 8063), "G15": (400, 8152), "O02": (64, 1532),
    "O15": (140, 1562), "O16": (142, 1564), "O19": (315, 8083),
}
ADJ_IDS = {i for p in ADJUDICATED.values() for i in p}


def group_similar(rows):
    """长度分桶 + 相似度聚类，返回互斥的题干组列表。"""
    buckets: dict[int, list] = {}
    for r in rows:
        c = canon(r["content"])
        if len(c) < 8:
            continue
        buckets.setdefault(len(c), []).append((r, c))
    used: set[int] = set()
    groups: list[list] = []
    keys = sorted(buckets)
    for i, L in enumerate(keys):
        window = []
        for L2 in keys:
            if L2 < L * LEN_RATIO:
                continue
            if L2 > L / LEN_RATIO + 1:
                break
            window.extend(buckets[L2])
        for r, c in buckets[L]:
            if r["id"] in used:
                continue
            grp = [r]
            used.add(r["id"])
            for r2, c2 in window:
                if r2["id"] in used:
                    continue
                if SequenceMatcher(None, c, c2).ratio() >= SIM:
                    grp.append(r2)
                    used.add(r2["id"])
            if len(grp) > 1:
                groups.append(grp)
    groups.sort(key=lambda g: min(r["id"] for r in g))
    return groups


def main() -> int:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content, answer, is_junk, source FROM quiz_questions "
        "WHERE is_junk IS NOT 1"
    ).fetchall()
    conn.close()
    print(f"参与判重范围（排除 is_junk=1）: {len(rows)} 条")

    groups = group_similar(rows)
    conflict, pure = [], []
    for g in groups:
        answers = {}
        for r in g:
            a = canon(r["answer"])
            if a:
                answers.setdefault(a, []).append(r["id"])
        (conflict if len(answers) >= 2 else pure).append((g, answers))

    print(f"同题干组 = {len(groups)}（冲突 {len(conflict)} / 纯重复 {len(pure)}）")
    print(f"冲突组涉及 {sum(len(g) for g,_ in conflict)} 条，"
          f"纯重复组涉及 {sum(len(g) for g,_ in pure)} 条\n")

    print("=== 冲突组逐组对照（is_junk=0 范围内）===")
    print(f"{'组号':<6}{'成员id':<22}{'各侧答案':<50}{'已裁决?'}")
    table = []
    for i, (g, answers) in enumerate(conflict, 1):
        ids = [r["id"] for r in g]
        desc = " | ".join(f"{r['id']}={canon(r['answer'])[:22]}" for r in g)
        tag = "是(team-lead已裁)" if set(ids) & ADJ_IDS else "否"
        print(f"G{i:02d}{'':<3}{str(ids):<22}{desc:<50}{tag}")
        table.append({
            "组号": f"G{i:02d}", "ids": ids,
            "答案": {str(r["id"]): (r["answer"] or "")[:60] for r in g},
            "已裁决": bool(set(ids) & ADJ_IDS),
        })

    print("\n=== 纯重复组（同题干、答案一致或均无答案）===")
    for i, (g, answers) in enumerate(pure, 1):
        ids = [r["id"] for r in g]
        has = "有答案" if answers else "全无答案"
        print(f"P{i:02d} {ids} ({has})")

    path = r"D:\平台\backend-main-fastapi\data\diagnostics\conflict_recheck_sim.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"conflict": table,
                   "pure": [[r["id"] for r in g] for g, _ in pure]}, f,
                  ensure_ascii=False, indent=1)
    print(f"\n[saved] {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
