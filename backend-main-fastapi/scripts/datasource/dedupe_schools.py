# -*- coding: utf-8 -*-
"""kaoyan_schools 重名去重（保留最早一条，迁移关联数据）。

背景（实测）: 真库存在 82 组重名、137 条重复，内容完全相同（同 official_url/province，
仅 created_at 微差），系历史批量导入重复插入所致。

做法:
  1. 按 name 分组，保留 id 最小者；
  2. 把被删项的**关联数据**（kaoyan_majors/admissions/scorelines/notices/colleges 等的
     school_id）改写到保留项，避免孤儿数据；
  3. 删除重复行。幂等：再跑无变化。

用法:
  python dedupe_schools.py            # 预览
  python dedupe_schools.py --apply    # 写库（自动备份）
"""
from __future__ import annotations

import shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

DB = r"D:\平台\database\kaoyan.db"
# 关联表（含 school_id 外键）
REL_TABLES = ["kaoyan_majors", "kaoyan_admissions", "kaoyan_scorelines",
              "kaoyan_notices", "kaoyan_colleges"]


def main():
    apply = "--apply" in sys.argv
    if apply:
        bak = f"{DB}.bak_dedupe_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(DB, bak)
        print(f"已备份 → {bak}")

    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    dup_names = [r[0] for r in cur.execute(
        "SELECT name FROM kaoyan_schools GROUP BY name HAVING COUNT(*)>1")]
    print(f"重名组数: {len(dup_names)}")

    total_del = 0
    plan = []
    for nm in dup_names:
        ids = [r[0] for r in cur.execute(
            "SELECT id FROM kaoyan_schools WHERE name=? ORDER BY id", (nm,))]
        keep, drops = ids[0], ids[1:]
        plan.append((nm, keep, drops))
        total_del += len(drops)

    print(f"将保留每个名称的最小 id，删除 {total_del} 条重复")
    print("样本:", [(p[0], p[1], len(p[2])) for p in plan[:5]])

    if not apply:
        print("\n[DRY-RUN] 未写库。加 --apply 执行。")
        con.close()
        return

    for nm, keep, drops in plan:
        for d in drops:
            for tbl in REL_TABLES:
                try:
                    cur.execute(f"UPDATE {tbl} SET school_id=? WHERE school_id=?", (keep, d))
                except sqlite3.OperationalError:
                    pass  # 表不存在或无该列
            cur.execute("DELETE FROM kaoyan_schools WHERE id=?", (d,))
    con.commit()
    total = cur.execute("SELECT COUNT(*) FROM kaoyan_schools").fetchone()[0]
    print(f"\n去重完成：删除 {total_del} 条；真库院校总数 {total}")
    con.close()


if __name__ == "__main__":
    main()
