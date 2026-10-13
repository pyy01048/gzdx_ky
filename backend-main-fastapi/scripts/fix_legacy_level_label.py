# -*- coding: utf-8 -*-
"""
一次性修复：level='一本' 旧口径词汇统一为 '双非'。

背景
----
「一本」是 2000 年代高考录取批次的旧口径，与库内并存的
985/211/双一流/双非 体系不一致，且库内仅此1 条（北京工商大学id=493）。
《学位授予和人才培养学科目录》中无此分类 —— 北京工商大学既非 985/211
也非双一流建设高校，归入「双非」是唯一与全库口径自洽的写法。

同时扩展：本脚本做全库 level 取值白名单校验，防止旧口径词汇再次混入。

用法：
  python scripts/fix_legacy_level_label.py# dry-run
  python scripts/fix_legacy_level_label.py --apply --verify
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\data\backups"

# 全库允许的 level 取值白名单（NULL 允许，表示未分类）
ALLOWED = {"985", "211", "双一流", "双非", None, ""}

# 旧口径 → 现代口径
LEGACY_MAP = {
    "一本": "双非",
    "二本": "双非",
    "三本": "双非",
    "重点": "双非",      # 老「重点大学」已并入 211
    "普通一本": "双非",
}


def backup_db(tag: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_legacylevel_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)          # WAL 模式必须用 backup() API
    finally:
        out.close()
        src.close()
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    print("=" * 70)
    print("level 取值现状")
    print("=" * 70)
    for r in conn.execute(
            "SELECT COALESCE(level,'<NULL>') lv, COUNT(*) c FROM kaoyan_schools"
            " GROUP BY 1 ORDER BY c DESC"):
        flag = "" if (r["lv"] in ALLOWED or r["lv"] == "<NULL>") else "  <-- 旧口径/非法"
        print(f"    {r['lv']:<10s} {r['c']:>4d}{flag}")

    plan = []
    for r in conn.execute(
            "SELECT id, name, level FROM kaoyan_schools WHERE level IS NOT NULL"):
        lv = (r["level"] or "").strip()
        if lv in LEGACY_MAP:
            plan.append((r["id"], r["name"], lv, LEGACY_MAP[lv]))

    print(f"\n[修复计划] {len(plan)} 条")
    for sid, name, old, new in plan:
        print(f"    {sid:<5d} {name:<20s} {old:<6s} -> {new}")

    if not args.apply:
        print("\n>>> dry-run。加--apply 执行。")
        return

    bak = backup_db("legacylevel")
    print(f"\n已备份：{bak}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    for sid, _name, _old, new in plan:
        n += conn.execute(
            "UPDATE kaoyan_schools SET level=?, updated_at=? WHERE id=?",
            (new, now, sid)).rowcount
    conn.commit()
    print(f"实际写入 {n} 条")

    if args.verify:
        print("\n[修复后 level 分布]")
        for r in conn.execute(
                "SELECT COALESCE(level,'<NULL>') lv, COUNT(*) c"
                " FROM kaoyan_schools GROUP BY 1 ORDER BY c DESC"):
            print(f"    {r['lv']:<10s} {r['c']:>4d}")
        illegal = conn.execute(
            "SELECT COALESCE(level,'<NULL>') lv, COUNT(*) c FROM kaoyan_schools"
            " GROUP BY 1").fetchall()
        bad = [r["lv"] for r in illegal
               if r["lv"] != "<NULL>" and r["lv"] not in ALLOWED]
        print(f"\n    白名单外取值: {bad if bad else '无'}")
    conn.close()


if __name__ == "__main__":
    main()