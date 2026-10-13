# -*- coding: utf-8 -*-
"""复核：team-lead 追问的 41 组「有正确侧」冲突处置状态。

只读。不写库。
输出逐组对照表：组号 / 正确侧id / 错误侧id / 是否已执行 / 错误侧当前 is_junk。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

DB_PATH = r"D:\平台\database\kaoyan.db"

OCR_JUNK = re.compile(r"[\ufffd\ufffe\u001a-\u001f\ue000-\uf8ff]+")
BLANK = re.compile(r"[_＿﹍﹏]{2,}|[（(]\s*[）)]|…+|\.{3,}")
SIGN_STRIP = re.compile(r"[\s，。、；：？！“”‘’（）()【】\[\]{}<>《》·.,;:?!\"'/\\|~`@#$%^&*+=_\-－]+")


def canon(s: str) -> str:
    """与 verify_post_restore_dup.py 同口径的归一化。"""
    s = OCR_JUNK.sub("", s or "")
    s = BLANK.sub("　", s)
    return SIGN_STRIP.sub("", s).strip().lower()


def main() -> int:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content, answer, is_junk, source FROM quiz_questions"
    ).fetchall()

    # 建 stem -> [row]
    buckets: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        c = canon(r["content"])
        if len(c) < 8:      # 太短跳过，与我此前口径一致
            continue
        buckets.setdefault(c, []).append(r)

    conflict_groups: list[list[sqlite3.Row]] = []
    pure_groups: list[list[sqlite3.Row]] = []
    for c, g in buckets.items():
        if len(g) < 2:
            continue
        answers = {}
        for r in g:
            a = canon(r["answer"])
            if a:
                answers.setdefault(a, []).append(r["id"])
        if len(answers) >= 2:
            conflict_groups.append(g)     # 同题干多答案 -> 冲突
        else:
            pure_groups.append(g)         # 同题干答案一致（或都无答案）-> 纯重复
    conn.close()

    conflict_groups.sort(key=lambda g: min(r["id"] for r in g))
    pure_groups.sort(key=lambda g: min(r["id"] for r in g))
    print(f"同题干冲突组 = {len(conflict_groups)}  涉及 {sum(len(g) for g in conflict_groups)} 条")
    print(f"同题干纯重复组 = {len(pure_groups)}  涉及 {sum(len(g) for g in pure_groups)} 条")

    print("\n=== 冲突组逐组明细 ===")
    for i, g in enumerate(conflict_groups, 1):
        ids = [r["id"] for r in g]
        anss = []
        for r in g:
            anss.append(f"{r['id']}={canon(r['answer']) or '(空)'}j{r['is_junk']}")
        print(f"G{i:02d} {ids} | " + " | ".join(anss))

    out = {
        "conflict_groups": [
            [
                {"id": r["id"], "is_junk": r["is_junk"],
                 "answer": (r["answer"] or "")[:60], "source": r["source"]}
                for r in g
            ] for g in conflict_groups
        ],
        "pure_groups": [[r["id"] for r in g] for g in pure_groups],
    }
    path = r"D:\平台\backend-main-fastapi\data\diagnostics\conflict_47_recheck.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n[saved] {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
