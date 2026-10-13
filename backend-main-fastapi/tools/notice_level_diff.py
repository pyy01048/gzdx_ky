# -*- coding: utf-8 -*-
"""规则改动前后 level 差异对比（只读，不写库）。

用途：notice_rules.yaml 改动后，验证「哪些行的importance_level 会变」，
避免把博士/学位/党务/占位脏数据误升为 urgent。

用法：
    python tools/notice_level_diff.py            # 对比当前规则 vs 库中已存 level
    python tools/notice_level_diff.py --dump     # 额外打印变化行明细
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.kaoyan.notice_alert import classify_importance, load_rules  # noqa: E402

DB = r"D:\平台\database\kaoyan.db"


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, title, notice_type, COALESCE(importance_level,'normal') "
        "FROM kaoyan_notices"
    ).fetchall()
    conn.close()

    rules = load_rules()
    changed = []
    new_counter: Counter = Counter()
    old_counter: Counter = Counter()

    for nid, title, ntype, old_level in rows:
        new = classify_importance(title or "", ntype, None, rules)["level"]
        new_counter[new] += 1
        old_counter[old_level] += 1
        if new != old_level:
            changed.append((nid, title or "", ntype, old_level, new))

    print("== 库中已存 level 分布 ==")
    for k, v in sorted(old_counter.items()):
        print(f"  {k:10s} {v}")
    print("== 当前规则重算 level 分布 ==")
    for k, v in sorted(new_counter.items()):
        print(f"  {k:10s} {v}")
    print(f"== 变化行数: {len(changed)} ==")

    if "--dump" in sys.argv:
        print("\n== 变化明细 ==")
        for nid, title, ntype, old, new in changed:
            print(f"  id={nid} [{old}->{new}] ({ntype}) {title[:70]}")
    else:
        print("（加 --dump 查看变化明细）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())