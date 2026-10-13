"""kaoyan_notices 重复记录清理脚本.

按 (school_id, 归一化URL) 判重 —— URL 是通知的真实身份标识. 标题相同但 URL
不同的记录**保留**, 因为那可能是不同年份/不同栏目的真通知.

默认 dry-run, 必须显式传 --apply 才真正执行 DELETE.

保留策略优先级:
  1. is_read / is_starred 有标记（用户交互过的）
  2. fetched_at 最早（原始数据）
  3. id 最小
被删记录上的 is_read / is_starred / read_at / starred_at 会**迁移到保留记录**,
保证用户交互状态不丢失.

用法:
    python scripts/dedupe_notices.py                 # dry-run, 打印计划
    python scripts/dedupe_notices.py --apply         # 先备份再执行
    python scripts/dedupe_notices.py --apply --no-backup   # 跳过备份(不推荐)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.kaoyan.notice_dedup import (  # noqa: E402
    dedupe_table,
    normalize_notice_title,
    normalize_notice_url,
)

DEFAULT_DB = r"D:\平台\database\kaoyan.db"
TABLE = "kaoyan_notices"


def snapshot(conn: sqlite3.Connection) -> Dict[str, Any]:
    """抓取清理前/后的对比指标."""
    total = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    sum_read = conn.execute(f"SELECT COALESCE(SUM(is_read),0) FROM {TABLE}").fetchone()[0]
    sum_star = conn.execute(f"SELECT COALESCE(SUM(is_starred),0) FROM {TABLE}").fetchone()[0]
    unread = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE COALESCE(is_read,0)=0"
    ).fetchone()[0]
    by_school = {
        r[0]: r[1]
        for r in conn.execute(
            f"SELECT school_name, COUNT(*) FROM {TABLE} GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    }
    # 剩余重复组数（严格键）
    dup_groups = conn.execute(
        f"SELECT COUNT(*) FROM ("
        f"  SELECT school_id, lower(rtrim(COALESCE(url,''),'/')) AS u, COUNT(*) c"
        f"  FROM {TABLE} WHERE COALESCE(url,'')<>''"
        f"  GROUP BY school_id, u HAVING c>1)"
    ).fetchone()[0]
    # 标题重复组数（弱键，用于报告）
    title_dup_groups = conn.execute(
        f"SELECT COUNT(*) FROM ("
        f"  SELECT school_id, title, COUNT(*) c FROM {TABLE}"
        f"  GROUP BY school_id, title HAVING c>1)"
    ).fetchone()[0]
    return {
        "total": total,
        "sum_read": sum_read,
        "sum_star": sum_star,
        "unread": unread,
        "by_school": by_school,
        "dup_groups_strict": dup_groups,
        "dup_groups_title": title_dup_groups,
    }


def print_snapshot(label: str, snap: Dict[str, Any]) -> None:
    print("=" * 96)
    print(f"{label}")
    print("=" * 96)
    print(f"  总记录数        : {snap['total']}")
    print(f"  未读数(is_read=0): {snap['unread']}")
    print(f"  sum(is_read)    : {snap['sum_read']}")
    print(f"  sum(is_starred) : {snap['sum_star']}")
    print(f"  严格键重复组数  : {snap['dup_groups_strict']}")
    print(f"  标题重复组数    : {snap['dup_groups_title']}")
    print("  按学校 TOP10:")
    for i, (name, cnt) in enumerate(snap["by_school"].items(), 1):
        if i > 10:
            break
        print(f"      {i:>2}. {name:<24} {cnt}")
    print()


def migrate_user_state(
    conn: sqlite3.Connection, keep_id: int, drop_rows: List[sqlite3.Row]
) -> int:
    """把被删记录的用户交互状态迁移到保留记录.

    只有当保留记录尚未标记时, 才把被删记录的已读/星标状态搬过来, 避免用
    0 值覆盖已有的 1 值.
    """
    migrated = 0
    for row in drop_rows:
        if not (row["is_read"] or row["is_starred"]):
            continue
        cur = conn.execute(
            "UPDATE kaoyan_notices SET "
            "  is_read = CASE WHEN ?=1 THEN 1 ELSE is_read END, "
            "  read_at = COALESCE(read_at, ?), "
            "  is_starred = CASE WHEN ?=1 THEN 1 ELSE is_starred END, "
            "  starred_at = COALESCE(starred_at, ?) "
            "WHERE id = ?",
            (
                row["is_read"],
                row["read_at"],
                row["is_starred"],
                row["starred_at"],
                keep_id,
            ),
        )
        if cur.rowcount > 0:
            migrated += 1
    return migrated


def backup_database(db_path: str) -> str:
    """用 SQLite 原生备份 API 备份（WAL 模式下唯一安全的备份方式, 禁止 cp）。"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = f"{db_path}.bak_notice_dedupe_{stamp}"
    src = sqlite3.connect(db_path)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            src.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src.close()
    size = os.path.getsize(dst)
    print(f"[backup] 已用 SQLite backup API 备份 -> {dst}  ({size:,} bytes)")
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description="清理 kaoyan_notices 重复记录")
    ap.add_argument("--apply", action="store_true", help="真正执行 DELETE（默认仅 dry-run）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不推荐）")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--show", type=int, default=30, help="打印前 N 组明细, 0=不打印")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    before = snapshot(conn)
    print_snapshot("清理前快照", before)

    # ---- 预演：找出标题相同但 URL 不同的组（这些要保留）----
    title_groups: Dict[tuple, List[sqlite3.Row]] = defaultdict(list)
    for r in conn.execute(
        f"SELECT id, school_id, school_name, title, url, publish_date, fetched_at "
        f"FROM {TABLE} ORDER BY id"
    ).fetchall():
        title_groups[(r["school_id"], normalize_notice_title(r["title"]))].append(r)

    keep_multi_url = {
        k: v for k, v in title_groups.items() if len({normalize_notice_url(x["url"]) for x in v}) > 1
    }
    print("=" * 96)
    print("保留策略说明：以下标题相同但 URL 不同的组，按 URL 拆分后各自保留 1 条")
    print("（不同栏目/不同时间的真通知，绝不合并）")
    print("=" * 96)
    for key, members in sorted(keep_multi_url.items(), key=lambda kv: len(kv[1]), reverse=True):
        by_url: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        for m in members:
            by_url[normalize_notice_url(m["url"])].append(m)
        print(f"\n  {members[0]['school_name']} | {members[0]['title']}")
        for u, ms in by_url.items():
            print(f"      URL {u[:78]:<78} x{len(ms):<3} keep_id={ms[0]['id']} "
                  f"dates={sorted({str(x['publish_date'])[:10] for x in ms})}")
    print()

    plan = dedupe_table(conn)
    groups = sorted(plan["groups"], key=lambda g: len(g["drop_ids"]), reverse=True)
    print("=" * 96)
    print(f"清理计划：{len(groups)} 个重复组，将删除 {plan['redundant']} 条")
    print("=" * 96)
    for g in groups[: args.show]:
        row = conn.execute(
            f"SELECT school_name, title, url, publish_date FROM {TABLE} WHERE id=?",
            (g["keep_id"],),
        ).fetchone()
        print(f"  [{len(g['drop_ids'])+1}条] {row['school_name']} | {row['title'][:52]}")
        print(f"      url={str(row['url'])[:76]}")
        print(f"      keep_id={g['keep_id']}  drop_ids={g['drop_ids']}")
    if args.show and len(groups) > args.show:
        print(f"  ...(共{len(groups)}组, 用 --show 0 关闭明细)")
    print()

    # ---- 冗余记录的标题完全相同吗？（纯重复 vs 标题变体）----
    drop_all = [i for g in groups for i in g["drop_ids"]]
    same_url_title_diff = 0
    for g in groups:
        keep = conn.execute(
            f"SELECT title FROM {TABLE} WHERE id=?", (g["keep_id"],)
        ).fetchone()
        for did in g["drop_ids"]:
            d = conn.execute(
                f"SELECT title FROM {TABLE} WHERE id=?", (did,)
            ).fetchone()
            if normalize_notice_title(keep["title"]) != normalize_notice_title(d["title"]):
                same_url_title_diff += 1
    print(f"  冗余记录中归一化标题与保留记录不同的: {same_url_title_diff} 条")
    print()

    if not args.apply:
        print(">>> DRY-RUN 模式，未做任何修改。确认策略无误后加 --apply 执行。")
        conn.close()
        return 0

    # ---- 执行 ----
    if not args.no_backup:
        backup_database(args.db)

    print(f"[apply] 开始删除 {len(drop_all)} 条冗余记录 ...")
    migrated_total = 0
    conn.execute("BEGIN")
    try:
        for g in groups:
            placeholders = ",".join("?" * len(g["drop_ids"]))
            drop_rows = conn.execute(
                f"SELECT id, is_read, is_starred, read_at, starred_at "
                f"FROM {TABLE} WHERE id IN ({placeholders})",
                g["drop_ids"],
            ).fetchall()
            migrated_total += migrate_user_state(conn, g["keep_id"], drop_rows)
            conn.execute(
                f"DELETE FROM {TABLE} WHERE id IN ({placeholders})", g["drop_ids"]
            )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"[apply] 失败已回滚: {exc}")
        conn.close()
        return 1

    print(f"[apply] 删除完成，共删除 {len(drop_all)} 条，迁移用户状态 {migrated_total} 条")

    after = snapshot(conn)
    print_snapshot("清理后快照", after)

    print("=" * 96)
    print("验收对比")
    print("=" * 96)
    print(f"  总数      : {before['total']} -> {after['total']}  (删除 {before['total']-after['total']})")
    print(f"  未读数    : {before['unread']} -> {after['unread']}")
    print(f"  sum(is_read)    : {before['sum_read']} -> {after['sum_read']}")
    print(f"  sum(is_starred) : {before['sum_star']} -> {after['sum_star']}")
    print(f"  严格键重复组数  : {before['dup_groups_strict']} -> {after['dup_groups_strict']}")
    print(f"  标题重复组数    : {before['dup_groups_title']} -> {after['dup_groups_title']}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())