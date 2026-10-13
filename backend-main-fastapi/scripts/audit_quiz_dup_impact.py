# -*- coding: utf-8 -*-
"""去重收益量化（只读）—— 基于 dup_audit.json 统计"去重后能多出多少有效题"。"""

from __future__ import annotations

import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
OUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "diagnostics"))


def main() -> None:
    with open(os.path.join(OUT_DIR, "dup_audit.json"), encoding="utf-8") as f:
        d = json.load(f)
    groups = d["groups_detail"]

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    def q(ids: list[int]) -> dict[int, sqlite3.Row]:
        if not ids:
            return {}
        qm = ",".join("?" * len(ids))
        return {r["id"]: r for r in con.execute(
            f"SELECT id, answer, is_junk, is_available, source, content FROM quiz_questions "
            f"WHERE id IN ({qm})", ids)}

    need = [g for g in groups if 0 in g["is_junk"]]
    noop = [g for g in groups if all(i == 1 for i in g["is_junk"])]

    print(f"重复组总数            : {len(groups)}")
    print(f"  需动作（组内有 is_junk=0）: {len(need)}  冗余 {sum(len(g['drop_ids']) for g in need)} 条")
    print(f"  无需动作（整组已 junk=1）: {len(noop)}  冗余 {sum(len(g['drop_ids']) for g in noop)} 条")

    # 关键收益：丢弃的冗余条里，有多少是「is_junk=0 且 answer 非空」—— 这些是
    # 用户现在能刷到的重复题，去重会直接减少"看起来可选但内容重复"的题量。
    drop_all = [i for g in need for i in g["drop_ids"]]
    drop_rows = q(drop_all)
    ans_ok = [i for i in drop_all if (drop_rows[i]["answer"] or "").strip()]
    junk0 = [i for i in drop_all if not int(drop_rows[i]["is_junk"] or 0)]
    both = [i for i in drop_all
            if not int(drop_rows[i]["is_junk"] or 0) and (drop_rows[i]["answer"] or "").strip()]
    print()
    print("--- 冗余条构成（需动作组内，共 %d 条）---" % len(drop_all))
    print(f"  answer 非空（用户可刷）      : {len(ans_ok)}")
    print(f"  is_junk=0（未被隔离）        : {len(junk0)}")
    print(f"  两者都满足（刷题区重复题）  : {len(both)}")

    base_junk0 = con.execute(
        "SELECT count(*) FROM quiz_questions WHERE is_junk=0").fetchone()[0]
    base_ans = con.execute(
        "SELECT count(*) FROM quiz_questions WHERE is_junk=0 AND answer IS NOT NULL "
        "AND trim(answer)<>''").fetchone()[0]
    print()
    print(f"当前 is_junk=0                : {base_junk0}")
    print(f"当前 is_junk=0 且有答案        : {base_ans}")
    print(f"去重后 is_junk=0 会减少        : {len(junk0)}")
    print(f"去重后 有答案题 会减少        : {len(both)}")
    print(f"→ 用户视角「能刷的题」净变化   : -{len(both)}（这些是重复内容，不是新增）")
    print("   价值不在于减少题数，而在于：同一道题只出现一次，答题正确率统计不失真")

    with open(os.path.join(OUT_DIR, "dup_impact.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(f"{k}: {v}" for k, v in [
            ("需动作组", len(need)), ("无需动作组", len(noop)),
            ("冗余条", len(drop_all)), ("冗余中answer非空", len(ans_ok)),
            ("冗余中is_junk=0", len(junk0)), ("冗余中两者都满足", len(both)),
            ("当前is_junk=0", base_junk0), ("当前可刷题", base_ans),
        ]))
    print("\n→ data/diagnostics/dup_impact.txt")


if __name__ == "__main__":
    main()
