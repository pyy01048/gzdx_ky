# -*- coding: utf-8 -*-
"""存量错题复习排程修复（V12 同族 bug 的数据侧收尾，2026-10）。

背景：
    错题侧曾与单词/记忆卡片同族——新内容因排程缺失/过激全部算作"今日到期"。
    单词/卡片侧已在查询层修复（due 队列排除新内容），错题侧的代码修复为：
    新错题首入库按掌握度排首次复习（services/review_scheduler.first_review_at，
    ≥1 天）；本脚本负责**存量数据**：历史入库时 next_review 为 NULL/空串的错题，
    按同一口径一次性补排，恢复"每条错题都有下次复习时间"的不变式。

    为什么必须补：get_due_errors / review/stats 等查询都要求 next_review IS NOT NULL，
    NULL 行永远不进复习队列——错题入库即"消失"，比当日到期更糟。

口径（与 first_review_at 完全一致，按掌握度 accuracy 分档）：
    accuracy 缺失或 < 0.5 → 1 天后
    0.5 ≤ accuracy < 0.8  → 2 天后
    accuracy ≥ 0.8       → 3 天后

铁律（红线）：
    1. 写库前必须经 services.backup_service.create_backup() 备份——
       其内部用 SQLite src.backup(dst) 在线备份（WAL 安全），
       **禁止** shutil.copy2/cp 文件级拷贝（WAL 下会丢未合并数据）。
    2. 备份失败直接中止，绝不带着"没有备份"的状态写真库。
    3. 目标库路径只从 backup_service.DB_PATH 取（与 ORM 同源），不二次推断。

用法：
    D:/Anaconda/python.exe scripts/fix_error_review_schedule.py            # dry-run，只报告
    D:/Anaconda/python.exe scripts/fix_error_review_schedule.py --apply    # 先备份后修复
"""
from __future__ import annotations

import argparse
import datetime
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from services.backup_service import create_backup, DB_PATH  # noqa: E402
from services.db_retry import exec_retry  # noqa: E402

#: 与 services/review_scheduler.ReviewScheduler.first_review_at 相同的分档口径
_FMT = "%Y-%m-%d %H:%M:%S"


def _first_interval_days(accuracy) -> int:
    """按掌握度给首次复习间隔（天）。"""
    try:
        acc = float(accuracy) if accuracy is not None else None
    except (TypeError, ValueError):
        acc = None
    if acc is None or acc < 0.5:
        return 1
    if acc < 0.8:
        return 2
    return 3


def _tier_label(days: int) -> str:
    return {1: "1 天后（未掌握/未评估）", 2: "2 天后（半会）", 3: "3 天后（眼会手错）"}[days]


def _collect(conn) -> list[dict]:
    """捞出所有 next_review 为 NULL/空串的错题行。"""
    rows = exec_retry(
        conn,
        """
        SELECT id, status, COALESCE(review_count, 0), accuracy, created_at
        FROM error_records
        WHERE next_review IS NULL OR TRIM(COALESCE(next_review, '')) = ''
        ORDER BY id
        """,
    ).fetchall()
    return [
        {
            "id": r[0],
            "status": r[1] or "(null)",
            "review_count": r[2],
            "accuracy": r[3],
            "created_at": r[4],
        }
        for r in rows
    ]


def _report(rows: list[dict], now: datetime.datetime) -> None:
    """dry-run / apply 共用的影响面报告。"""
    print(f"目标库: {DB_PATH}")
    print(f"基准时间(now, naive UTC): {now.strftime(_FMT)}")
    print(f"待修复行数（next_review 为 NULL/空串）: {len(rows)}")
    if not rows:
        print("无需修复：所有错题均已有排程。")
        return
    by_status: dict[str, int] = {}
    by_tier: dict[int, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_tier[_first_interval_days(r["accuracy"])] = by_tier.get(_first_interval_days(r["accuracy"]), 0) + 1

    print("按 status 分布: " + ", ".join(f"{k}={v}" for k, v in sorted(by_status.items())))
    print("按首间隔分档: " + ", ".join(f"{_tier_label(k)}: {v} 条" for k, v in sorted(by_tier.items())))
    print("样例（前 10 行，含将写入的 next_review）:")
    for r in rows[:10]:
        nxt = now + datetime.timedelta(days=_first_interval_days(r["accuracy"]))
        print(
            f"  id={r['id']:<6} status={r['status']:<10} review_count={r['review_count']:<3} "
            f"accuracy={r['accuracy']!r:<6} created_at={r['created_at']} "
            f"→ next_review={nxt.strftime(_FMT)}（{_tier_label(_first_interval_days(r['accuracy']))}）"
        )
    if len(rows) > 10:
        print(f"  …… 其余 {len(rows) - 10} 行从略")


def _report_legacy(conn, now: datetime.datetime) -> None:
    """附带发现（只报告、不在本脚本修复范围）：

    旧代码给新错题排的是"入册后 20 分钟"，这些错题若从未被复习
    （review_count=0），其 next_review 早已过去 → 今天起一直显示逾期。
    本脚本只补 NULL 行；这类行的排期是"当时合法"的，是否前移应由用户决定。
    """
    n = exec_retry(
        conn,
        "SELECT COUNT(*) FROM error_records "
        "WHERE status = 'active' AND COALESCE(review_count, 0) = 0 "
        "AND next_review IS NOT NULL AND next_review <= ?",
        (now.strftime(_FMT),),
    ).fetchone()[0]
    if n:
        print(f"\n附带发现（仅报告，不修改）: {n} 条 active 错题从未复习但已到期/逾期"
              f"（旧『入册 +20 分钟』首排程的产物，代码修复后新错题不再如此）。")


def main() -> int:
    ap = argparse.ArgumentParser(description="存量错题 next_review 缺失一次性修复（默认 dry-run）")
    ap.add_argument("--apply", action="store_true",
                    help="实际执行修复（先经 src.backup() API 备份真库）；不加则只做 dry-run 报告")
    args = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)  # naive UTC，与 DB 列同语义

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        rows = _collect(conn)

        if not args.apply:
            print("=== DRY-RUN（不写库）===")
            _report(rows, now)
            _report_legacy(conn, now)
            print("\n确认无误后加 --apply 执行；apply 前会先自动备份真库。")
            return 0

        print("=== APPLY ===")
        _report(rows, now)
        _report_legacy(conn, now)
        if not rows:
            return 0

        # —— 铁律：写库前必须经 src.backup() API 备份（禁 cp/copy2）；失败即中止 ——
        print("\n[1/2] 备份真库（SQLite src.backup，WAL 安全）…")
        try:
            backup_path = create_backup()
        except Exception as e:  # noqa: BLE001
            print(f"备份失败，已中止，未写入任何数据: {e}")
            return 2
        print(f"备份完成: {backup_path}")

        # —— 逐行补排（与 first_review_at 同口径）——
        print("[2/2] 写入 next_review …")
        updated = 0
        for r in rows:
            nxt = (now + datetime.timedelta(days=_first_interval_days(r["accuracy"]))).strftime(_FMT)
            cur = exec_retry(
                conn,
                "UPDATE error_records SET next_review = ?, updated_at = ? "
                "WHERE id = ? AND (next_review IS NULL OR TRIM(COALESCE(next_review, '')) = '')",
                (nxt, nxt, r["id"]),
            )
            updated += cur.rowcount or 0
        conn.commit()

        # 校验后置条件：不应再有 NULL/空串
        left = _collect(conn)
        print(f"完成: 更新 {updated} 行；复查剩余缺失行 = {len(left)}")
        if left:
            print(f"警告: 仍有 {len(left)} 行为空（并发写入?），建议重跑。")
            return 3
        print("不变式恢复: error_records.next_review 全部非空。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
