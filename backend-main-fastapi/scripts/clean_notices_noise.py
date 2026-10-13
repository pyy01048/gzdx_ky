# -*- coding: utf-8 -*-
"""kaoyan_notices 噪声清洗 —— 删除「栏目名当标题」的无效记录。

判据（谨慎，只删明显噪声）：
  标题 ≤4 字（char length，含中英数字） 且 publish_date 为空。
  这类记录是列表页栏目导航（如「硕士」「录取信息」「复试信息」）被误当
  公告标题写入，无检索价值；有日期或标题较长的可疑记录一律保留。

安全性：
  - 幂等：删除过的行重跑无变化；
  - 默认 dry-run；--apply 才写库；
  - 备份用 sqlite3 backup API（WAL 安全）；
  - 删除前逐行输出样本供人工复核；审计 CSV 记录删除明细。

用法：
  python scripts/clean_notices_noise.py            # dry-run
  python scripts/clean_notices_noise.py --apply    # 备份+删除
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = r"D:\平台\database\kaoyan.db"

# 额外白名单防御：即使 ≤4 字，若标题含年份（如「2027简章」）或高价值词，保留
_KEEP_RE = __import__("re").compile(r"20\d{2}|章程|简章|大纲|目录")


def main() -> None:
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    rows = cur.execute(
        "SELECT id, school_name, title, url FROM kaoyan_notices "
        "WHERE length(title) <= 4 AND (publish_date IS NULL OR publish_date='') "
        "ORDER BY school_name, title"
    ).fetchall()

    # 二次防御过滤：含年份/高价值词的不删
    keep = [r for r in rows if _KEEP_RE.search(r[2] or "")]
    to_del = [r for r in rows if r not in keep]

    print(f"命中 ≤4 字且无日期: {len(rows)} 行")
    if keep:
        print(f"  其中防御保留(含年份/章程简章等): {len(keep)} 行 -> {[(r[1], r[2]) for r in keep[:6]]}")
    print(f"确认删除: {len(to_del)} 行")

    from collections import Counter
    by_school = Counter(r[1] for r in to_del)
    print("按校分布:", dict(by_school))

    print("\n删除样本(前 25):")
    for rid, sch, title, url in to_del[:25]:
        print(f"  [{rid}] {sch} | {title!r} | {url[:40]}")

    if not apply:
        print("\n[DRY-RUN] 未写库。加 --apply 执行（先 WAL 安全备份）。")
        con.close()
        return

    # WAL 安全备份
    dst = f"{DB}.bak_notices_clean_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    src = sqlite3.connect(DB)
    dst_con = sqlite3.connect(dst)
    with dst_con:
        src.backup(dst_con)
    dst_con.close()
    src.close()
    print(f"\n已备份(WAL-safe) → {dst}")

    # 审计 CSV
    audit = Path(DB).parent / f"notices_clean_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(audit, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "school_name", "title", "url"])
        for row in to_del:
            w.writerow(row)

    ids = [r[0] for r in to_del]
    cur.executemany("DELETE FROM kaoyan_notices WHERE id=?", [(i,) for i in ids])
    con.commit()

    total = cur.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
    schools = cur.execute("SELECT COUNT(DISTINCT school_name) FROM kaoyan_notices").fetchone()[0]
    print(f"完成。删除 {len(ids)} 行。notices 现总 {total} 行 / {schools} 校。")
    print(f"审计日志 → {audit}")
    con.close()


if __name__ == "__main__":
    main()
