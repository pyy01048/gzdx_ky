# -*- coding: utf-8 -*-
"""噪声标记写库（step-1：只落 importance_reason，绝不改 level/score/deadline）。

对应 team-lead 2026-10-12 裁定「噪声写库第 1 步」：
* 把 detect_notice_noise.py 识别出的噪声，用 ``噪声:<类别>`` 形式写进
  ``kaoyan_notices.importance_reason`` 一列，便于前端过滤 / 查询；
* **只标记 high 级**（节气 / 节日祝福 / 栏目名），review 级（赛事活动 /
  疑似人名）只记录、不写库（team-lead：review 26 条不自动动）；
* **不改** importance_level / importance_score / deadline_date，不跑 backfill_all；
* 幂等：已含该标记的跳过；backup 走 SQLite backup() API（禁 cp）。

用法
----
    python scripts/apply_noise_markers.py            # dry-run，报数 + 抽样
    python scripts/apply_noise_markers.py --apply    # 写库（先 backup()）
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect_notice_noise import (  # noqa: E402
    EXISTING_NOISE_REASONS,
    classify_noise,
)

DB = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\data\backups"


def backup_db(tag: str) -> str:
    """SQLite WAL 模式下必须用 backup() API；cp 会丢未合并的 WAL 数据。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_noisemarker_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def build_marker(kind: str) -> str:
    return f"噪声:{kind}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = ap.parse_args()

    conn = sqlite3.connect(DB if args.apply else f"file:{DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, school_id, school_name, title, notice_type, importance_reason "
            "FROM kaoyan_notices ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    total = len(rows)

    # ---- 扫描：只对未被现有规则覆盖的行跑新增判据 ----
    high_hits: list[tuple] = []   # (row, kind)   —— 写库
    review_hits: list[tuple] = []  # (row, kind)   —— 只记录
    already = 0
    for r in rows:
        reason = (r[5] or "")
        if any(k in reason for k in EXISTING_NOISE_REASONS):
            already += 1
            continue
        kind, conf = classify_noise(r[3])
        if not kind:
            continue
        if conf == "high":
            high_hits.append((r, kind))
        else:
            review_hits.append((r, kind))

    print("=" * 78)
    print("噪声标记写库（step-1：只落 importance_reason）")
    print("=" * 78)
    print(f"  全库通知总数        : {total}")
    print(f"  已被现有规则降级     : {already} 条")
    print(f"  high 级（将写库标记）: {len(high_hits)} 条")
    print(f"  review 级（仅记录）  : {len(review_hits)} 条")
    by_kind_high: dict[str, int] = {}
    by_kind_rev: dict[str, int] = {}
    for _r, k in high_hits:
        by_kind_high[k] = by_kind_high.get(k, 0) + 1
    for _r, k in review_hits:
        by_kind_rev[k] = by_kind_rev.get(k, 0) + 1
    print("  high 分两类:", dict(by_kind_high))
    print("  review 分两类:", dict(by_kind_rev))

    print()
    print("-" * 78)
    print("high 级待写库清单（逐条，供核对误杀）:")
    for r, kind in high_hits:
        print(f"  [噪声:{kind}] id={r[0]:<5} {str(r[2] or '')[:14]:16s} | {r[3][:42]}")

    print()
    print("-" * 78)
    print("review 级仅记录清单（不写库）:")
    for r, kind in review_hits:
        print(f"  [噪声:{kind}] id={r[0]:<5} {str(r[2] or '')[:14]:16s} | {r[3][:42]}")

    if not args.apply:
        print()
        print("[dry-run] 未写库。加 --apply 执行（先 backup）。")
        return 0

    # ---- 写库：仅 UPDATE importance_reason，仅 high 级 ----
    print()
    print("=" * 78)
    print("写库")
    print("=" * 78)
    print("已备份:", backup_db("real"))
    conn = sqlite3.connect(DB)
    try:
        n_write = 0
        skipped = 0
        for r, kind in high_hits:
            nid = r[0]
            old = (r[5] or "").strip()
            marker = build_marker(kind)
            if marker in old:
                skipped += 1
                continue
            new_reason = (old + "；" + marker) if old else marker
            # 幂等：仅按 id 更新；重跑时 high_hits 仍会命中，但上面 marker in old 已跳过
            cur = conn.execute(
                "UPDATE kaoyan_notices SET importance_reason = ? WHERE id = ?",
                (new_reason, nid),
            )
            n_write += cur.rowcount
        conn.commit()
        print(f"  已写入 importance_reason: {n_write} 条（high 级）")
        print(f"  跳过（已含标记）        : {skipped} 条")
        print(f"  review 级未动           : {len(review_hits)} 条")
        # 写后核验
        marked = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_notices "
            "WHERE importance_reason LIKE '%噪声:%'"
        ).fetchone()[0]
        print(f"  当前 importance_reason 含「噪声:」总数: {marked}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
