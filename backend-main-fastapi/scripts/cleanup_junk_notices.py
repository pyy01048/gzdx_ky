# -*- coding: utf-8 -*-
"""清理 `kaoyan_notices` 的空锚点伪通知（url='#'）。

背景
----
采集器把网页里的 ``<a href="#">`` 空锚点当成了通知条目。这类行的特征是
**URL 归一化后为空**：`normalize_notice_url('#')` 先剥协议、再按 `#` 切分，
得到空串，于是 `notice_dedup.notice_dedup_key` 退化成按标题判重；而两条
空锚点的**锚点文本不同**（一条是菜单项「博士专业学位授权类别」，另一条就是
字面量 `#`），标题判重也匹配不上，于是同一处空锚点被写成了两行。

实测全库 1004 条通知中，`url='#'` 的只有 2 行，且没有任何其它表通过
``notice_id`` 引用它们（``kaoyan_alert_records`` 中 0 条关联），因此清理
不会产生孤儿引用。

用法
----
    python scripts/cleanup_junk_notices.py                  # dry-run，只报告
    python scripts/cleanup_junk_notices.py --apply          # 物理删除（需放行环境变量）
    python scripts/cleanup_junk_notices.py --apply --soft   # 软标记 is_junk（备选方案）

红线
----
* 物理删除必须先走 ``services.delete_guard.require_physical_delete_enabled``
  闸门（环境变量 ``KAOYAN_ALLOW_PHYSICAL_DELETE`` 严格等于 ``"1"``），
  并且用 ``backup_before_delete()`` 完成 SQLite backup API 备份。
* **禁止 cp / copy2**：本库是 WAL 模式，文件级拷贝会丢未合并的 -wal 数据。
* **禁止 rm 任何文件**。
* 目标集合必须**精确等于** ``EXPECTED_IDS``，否则直接中止——
  这是防止"多删了别的行"的最后一道闸。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DB = r"D:\平台\database\kaoyan.db"

#: 预期清理目标。实测确认只有这 2 行；若实际命中集合与此不符，脚本中止。
EXPECTED_IDS = {419, 945}

#: 空锚点判据：URL 归一化后为空（'#' / '' / 'javascript:void(0)' 等）。
JUNK_URL_SQL = "TRIM(IFNULL(url, '')) = '#'"


def junk_rows(conn: sqlite3.Connection) -> list[tuple]:
    """取全部空锚点伪通知行。"""
    return conn.execute(
        f"SELECT id, school_id, school_name, title, notice_type, publish_date, "
        f"url, fetched_at, is_read, is_starred FROM kaoyan_notices WHERE {JUNK_URL_SQL} "
        f"ORDER BY id"
    ).fetchall()


def url_anomaly_scan(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """扫描全库 URL 异常行数量（只报数，本轮不处理）。"""
    checks = [
        ("url IS NULL", "url IS NULL"),
        ("url 空串", "TRIM(IFNULL(url,'')) = ''"),
        ("url = '#'（空锚点）", JUNK_URL_SQL),
        ("url 长度 < 8", "url IS NOT NULL AND LENGTH(TRIM(url)) < 8"),
        ("url 不以 http 开头且非空",
         "url IS NOT NULL AND TRIM(url) <> '' AND url NOT LIKE 'http%'"),
    ]
    out = []
    for label, cond in checks:
        n = conn.execute(f"SELECT COUNT(*) FROM kaoyan_notices WHERE {cond}").fetchone()[0]
        out.append((label, n))
    return out


def referrer_scan(conn: sqlite3.Connection, ids: set[int]) -> list[tuple[str, int]]:
    """扫全库其它表是否通过 notice_id 引用待删行。"""
    hits = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    for t in tables:
        if t == "kaoyan_notices":
            continue
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        if "notice_id" not in cols:
            continue
        marks = ",".join("?" * len(ids))
        n = conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE notice_id IN ({marks})", tuple(ids)
        ).fetchone()[0]
        if n:
            hits.append((t, n))
    return hits


def physical_delete(conn: sqlite3.Connection, ids: set[int]) -> int:
    """走 delete_guard 闸门的物理删除。"""
    from services.delete_guard import (  # noqa: PLC0415 —— 仅在写库路径导入
        PhysicalDeleteBlocked,
        backup_before_delete,
        require_physical_delete_enabled,
    )

    # 1) 闸门：未显式放行则抛异常
    require_physical_delete_enabled("kaoyan_notices")

    # 2) 前置备份（SQLite backup API，WAL 安全）
    backup_path = backup_before_delete(DB)
    print(f"[backup] {backup_path}")

    # 3) 执行删除
    marks = ",".join("?" * len(ids))
    cur = conn.execute(f"DELETE FROM kaoyan_notices WHERE id IN ({marks})", tuple(ids))
    conn.commit()
    print(f"[delete] 物理删除 {cur.rowcount} 行")
    return cur.rowcount


def soft_mark(conn: sqlite3.Connection, ids: set[int]) -> int:
    """备选方案：加 is_junk 列并软标记。

    对齐题库既有约定（``quiz_questions.is_junk`` + 列表默认排除 +
    ``include_junk`` 逃生开关）。注意：这只改数据不改读路径，
    因此软标记后这几行**仍会出现在现有接口里**，要真正生效还需要改读路径。
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(kaoyan_notices)")]
    if "is_junk" not in cols:
        conn.execute("ALTER TABLE kaoyan_notices ADD COLUMN is_junk INTEGER NOT NULL DEFAULT 0")
        print("[soft] 已新增列 kaoyan_notices.is_junk")
    marks = ",".join("?" * len(ids))
    cur = conn.execute(f"UPDATE kaoyan_notices SET is_junk = 1 WHERE id IN ({marks})", tuple(ids))
    conn.commit()
    print(f"[soft] 软标记 {cur.rowcount} 行（注意：读路径未改，仍会在接口出现）")
    return cur.rowcount


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    ap.add_argument("--soft", action="store_true", help="用 is_junk 软标记代替物理删除")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True) if not args.apply else sqlite3.connect(DB)
    try:
        print("=" * 72)
        print("1) 待清理行（url = '#' 空锚点）")
        print("=" * 72)
        rows = junk_rows(conn)
        for r in rows:
            print(f"  id={r[0]:<5} school_id={r[1]:<5} {r[2]}")
            print(f"        title={r[3]!r}  type={r[4]}  date={r[5]}")
            print(f"        url={r[6]!r}  fetched_at={r[7]}  is_read={r[8]} is_starred={r[9]}")

        ids = {r[0] for r in rows}
        print()
        print("=" * 72)
        print("2) 安全断言")
        print("=" * 72)
        ok = True
        if ids != EXPECTED_IDS:
            print(f"  [FAIL] 目标集合 {sorted(ids)} != 预期 {sorted(EXPECTED_IDS)}，中止")
            ok = False
        else:
            print(f"  [OK] 目标集合精确等于预期 {sorted(EXPECTED_IDS)}")
        refs = referrer_scan(conn, ids)
        if refs:
            print(f"  [FAIL] 存在外键引用: {refs}，中止")
            ok = False
        else:
            print("  [OK] 无任何其它表通过 notice_id 引用这些行")
        unread = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_notices WHERE id IN (%s) AND is_read = 1"
            % ",".join("?" * len(ids)), tuple(ids)
        ).fetchone()[0]
        starred = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_notices WHERE id IN (%s) AND is_starred = 1"
            % ",".join("?" * len(ids)), tuple(ids)
        ).fetchone()[0]
        if unread or starred:
            print(f"  [FAIL] 存在用户状态: 已读 {unread} / 已收藏 {starred}，中止")
            ok = False
        else:
            print("  [OK] 两行均未被用户标记已读/收藏，删除不损失用户状态")

        print()
        print("=" * 72)
        print("3) 全库 URL 异常扫描（只报数，本轮不处理）")
        print("=" * 72)
        for label, n in url_anomaly_scan(conn):
            print(f"  {label:32s} {n}")

        if not ok:
            print()
            print("[中止] 安全断言未全部通过，不执行任何写操作。")
            return 1

        if not args.apply:
            print()
            print("[dry-run] 未写库。加 --apply 执行（物理删除需 KAOYAN_ALLOW_PHYSICAL_DELETE=1）。")
            return 0

        print()
        print("=" * 72)
        print("4) 写库")
        print("=" * 72)
        before = conn.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
        if args.soft:
            soft_mark(conn, ids)
        else:
            physical_delete(conn, ids)
        after = conn.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
        print(f"  kaoyan_notices: {before} -> {after}")
        left = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_notices WHERE " + JUNK_URL_SQL).fetchone()[0]
        print(f"  残留 url='#' 行: {left}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
