# -*- coding: utf-8 -*-
"""考研通知噪声「标记」（非破坏，不动 importance_level）。

设计（team-lead 两步走裁定：第 1 步只标记不降级）
------------------------------------------------
1. 新增列 ``is_noise``（INTEGER DEFAULT 0），幂等 ADD COLUMN。
2. 标记口径：
   - 已被现有规则降级（importance_reason 含党务/博士）→ is_noise=1；
   - 新增判据里置信度 ``high``（节气/节日祝福/栏目名）→ is_noise=1；
   - 新增判据里置信度 ``review``（赛事活动/疑似人名）→ is_noise=0，
     但导出 CSV 供人工复核，**不自动标记、不删除**。
3. 绝不修改 ``importance_level``（不降级），只补充一个便于前端过滤的标记位。

安全性
------
* 备份走 SQLite ``backup()`` API（WAL 安全）；
* 默认 dry-run，``--apply`` 才写库；
* 幂等：重复运行结果一致。

用法
----
    python scripts/mark_notice_noise.py            # dry-run 报数
    python scripts/mark_notice_noise.py --apply    # 备份 + 加列 + 标记 + 导 CSV
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from detect_notice_noise import classify_noise, EXISTING_NOISE_REASONS  # noqa: E402

BACKUP_DIR = r"D:\平台\data\backups"


def backup_db(tag: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_noisemark_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def is_existing_noise(reason: str) -> bool:
    return any(k in (reason or "") for k in EXISTING_NOISE_REASONS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True) if not args.apply else sqlite3.connect(DB)
    try:
        rows = conn.execute(
            "SELECT id, title, importance_reason FROM kaoyan_notices"
        ).fetchall()
        mark_ids: list[int] = []
        review_rows: list[tuple] = []
        for rid, title, reason in rows:
            if is_existing_noise(reason):
                mark_ids.append(rid)
                continue
            kind, conf = classify_noise(title)
            if conf == "high":
                mark_ids.append(rid)
            elif conf == "review":
                review_rows.append((rid, title, kind))

        total = len(rows)
        print("=" * 70)
        print("考研通知噪声标记（非破坏：只加 is_noise 标记，不改 importance_level）")
        print("=" * 70)
        print(f"  全库通知总数        : {total}")
        print(f"  将标记 is_noise=1   : {len(mark_ids)} 条")
        print(f"    ├─ 现有规则已降级  : {sum(1 for r in rows if is_existing_noise(r[2]))} 条")
        print(f"    └─ 新增 high 命中  : {len(mark_ids) - sum(1 for r in rows if is_existing_noise(r[2]))} 条")
        print(f"  review 待人工复核   : {len(review_rows)} 条（不标记，导 CSV）")

        if not args.apply:
            print()
            print("[dry-run] 未写库。加 --apply 执行。")
            return 0

        print()
        print("=" * 70)
        print("写库")
        print("=" * 70)
        print("已备份:", backup_db("real"))
        # 幂等加列
        conn.execute(
            "ALTER TABLE kaoyan_notices ADD COLUMN is_noise INTEGER DEFAULT 0"
        )
        conn.commit()
        # 标记
        conn.executemany(
            "UPDATE kaoyan_notices SET is_noise = 1 WHERE id = ?",
            [(i,) for i in mark_ids],
        )
        conn.commit()
        flagged = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_notices WHERE is_noise = 1"
        ).fetchone()[0]
        print(f"  已标记 is_noise=1 : {flagged} 条")
        # 复核 CSV
        audit = (os.path.dirname(DB)
                 + f"\\notice_noise_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        with open(audit, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["id", "title", "noise_kind"])
            for rid, title, kind in review_rows:
                w.writerow([rid, title, kind])
        print(f"  review 复核清单  → {audit}（{len(review_rows)} 条）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
