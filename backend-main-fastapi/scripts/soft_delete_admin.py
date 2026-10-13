# -*- coding: utf-8 -*-
"""软删查询 / 恢复工具。

配合 `scripts/add_soft_delete.py` 使用。提供三个能力：

1. ``list``    —— 列出最近删除的记录（按时间窗口 / 按批次）
2. ``restore`` —— 按 id / 按批次 / 按时间窗口批量恢复
3. ``purge``   —— 物化清理：把超过保留期的软删记录真正物理删除

**默认 dry-run**：所有写操作缺省只打印将要执行的语句，加 ``--apply`` 才落库。

红线沿用 `services/delete_guard.py`：
  * ``purge`` 是物理删除，必须 ``KAOYAN_ALLOW_PHYSICAL_DELETE=1``；
  * 任何物理删除前先走 SQLite backup API 备份，禁止 copy2。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 允许软删的表。与 add_soft_delete.py 的 TARGETS 保持一致。
SOFT_TABLES = ("quiz_questions", "knowledge_chunks")

#: 恢复时的级联清理目标（与 kb_service.replace 的清理口径对齐）。
#: knowledge_chunks 被软删时，其向量/FTS/错题关联仍留在依赖表里，
#: 恢复时若这些行已被物化清理，就要把它们补回来。
CHUNK_DEPENDENTS = {
    "vec": "knowledge_chunks_vec",
    "fts": "knowledge_chunks_fts",
    "links": "error_knowledge_links",
}


def resolve_db_path(explicit: Optional[str]) -> str:
    """解析目标库路径（与 add_soft_delete.py 同规则）。"""
    if explicit:
        path = os.path.abspath(explicit)
        if os.path.isfile(path):
            return path
        raise SystemExit(f"[soft_delete] 指定的库不存在: {path}")

    env = (os.environ.get("KAOYAN_DB_PATH") or "").strip()
    if env and os.path.isfile(env):
        return os.path.abspath(env)

    sys.path.insert(0, BASE_DIR)
    try:
        from database import SQLALCHEMY_DATABASE_URL  # type: ignore

        path = (SQLALCHEMY_DATABASE_URL or "").replace("sqlite+aiosqlite:///", "")
        path = path.replace("sqlite:///", "").lstrip("/")
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    except Exception:  # noqa: BLE001
        pass

    raise SystemExit("[soft_delete] 无法定位目标库，请用 --db 指定。")


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #
def cmd_list(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """列出最近删除的记录。"""
    has_log = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='soft_delete_log'"
    ).fetchone()

    if has_log:
        # 有流水表：能按时间窗口精确列出。
        where = "restored_at IS NULL"
        params: list = []
        if args.table:
            where += " AND table_name = ?"
            params.append(args.table)
        if args.batch:
            where += " AND batch_id = ?"
            params.append(args.batch)
        if args.minutes:
            where += " AND deleted_at >= ?"
            params.append(
                (datetime.now() - timedelta(minutes=args.minutes)).strftime("%Y-%m-%d %H:%M:%S")
            )
        params.append(args.limit)
        rows = conn.execute(
            f"SELECT id, table_name, row_id, deleted_at, deleted_by, reason, batch_id "
            f"FROM soft_delete_log WHERE {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        print(f"[soft_delete] soft_delete_log 中未恢复的删除记录 {len(rows)} 条")
        for r in rows:
            print(f"  log#{r[0]:<6} {r[1]:<18} id={r[2]:<8} at={r[3]} by={r[4]} "
                  f"batch={r[6]} reason={(r[5] or '')[:50]}")
        return 0

    # 无流水表（迁移时用了 --no-log-table）：只能按主表当前标记列出，
    # **无法区分删除时间**，因此不能做时间窗口恢复。
    print("[soft_delete] 提示：soft_delete_log 不存在，无法按时间列出/恢复。")
    print("[soft_delete]       仅能列出当前 is_deleted=1 的记录（无时间信息）。")
    for table in ([args.table] if args.table else SOFT_TABLES):
        try:
            rows = conn.execute(
                f"SELECT id FROM {table} WHERE COALESCE(is_deleted,0)=1 LIMIT ?",
                (args.limit,),
            ).fetchall()
        except sqlite3.OperationalError as e:
            print(f"  {table}: 查询失败（可能未迁移）: {e}")
            continue
        print(f"  {table}: {len(rows)} 条已软删  ids={[r[0] for r in rows[:20]]}")
    return 0


# --------------------------------------------------------------------------- #
# restore
# --------------------------------------------------------------------------- #
def _resolve_targets(conn: sqlite3.Connection, args: argparse.Namespace) -> list[tuple[str, int]]:
    """解析出要恢复的 (table, row_id) 列表。"""
    out: list[tuple[str, int]] = []

    if args.ids:
        table = args.table or "quiz_questions"
        for raw in args.ids.split(","):
            raw = raw.strip()
            if raw:
                out.append((table, int(raw)))
        return out

    if not args.batch and not args.minutes:
        raise SystemExit("[soft_delete] 请用 --ids / --batch / --minutes 至少指定一个恢复范围")

    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='soft_delete_log'"
    ).fetchone() is None:
        raise SystemExit(
            "[soft_delete] 按批次/时间恢复需要 soft_delete_log 表。"
            "该库未创建（迁移时用了 --no-log-table），只能按 --ids 恢复。"
        )

    where = "restored_at IS NULL"
    params: list = []
    if args.table:
        where += " AND table_name = ?"
        params.append(args.table)
    if args.batch:
        where += " AND batch_id = ?"
        params.append(args.batch)
    if args.minutes:
        where += " AND deleted_at >= ?"
        params.append(
            (datetime.now() - timedelta(minutes=args.minutes)).strftime("%Y-%m-%d %H:%M:%S")
        )
    params.append(args.limit)
    for table, row_id in conn.execute(
        f"SELECT table_name, row_id FROM soft_delete_log WHERE {where} ORDER BY id DESC LIMIT ?",
        params,
    ).fetchall():
        out.append((table, row_id))
    return out


def cmd_restore(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """批量恢复软删记录。"""
    targets = _resolve_targets(conn, args)
    if not targets:
        print("[soft_delete] 没有匹配到任何待恢复记录。")
        return 0

    print(f"[soft_delete] 将恢复 {len(targets)} 条记录"
          f"{'（dry-run，未写库）' if not args.apply else ''}")
    by_table: dict[str, list[int]] = {}
    for table, rid in targets:
        by_table.setdefault(table, []).append(rid)
    for table, ids in by_table.items():
        print(f"  {table}: {len(ids)} 条 → {ids[:20]}{' ...' if len(ids) > 20 else ''}")

    if not args.apply:
        print("\n确认无误后追加 --apply 执行。")
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for table, ids in by_table.items():
        placeholders = ",".join("?" * len(ids))
        # 先确认这些 id 确实存在且处于软删态，避免把别的行误"恢复"。
        alive = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE id IN ({placeholders}) "
            f"AND COALESCE(is_deleted,0)=1",
            ids,
        ).fetchone()[0]
        if alive != len(ids):
            print(f"[soft_delete] 警告: {table} 期望恢复 {len(ids)} 条，"
                  f"实际匹配 {alive} 条（部分 id 不存在或本就没被删），按实际执行")
        conn.execute(
            f"UPDATE {table} SET is_deleted=0 WHERE id IN ({placeholders})",
            ids,
        )
        print(f"[soft_delete] 已恢复 {table}: {alive} 条")

        # 流水表标记为已恢复（若存在）
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='soft_delete_log'"
        ).fetchone():
            conn.execute(
                f"UPDATE soft_delete_log SET restored_at=?, restored_by=?, restore_reason=? "
                f"WHERE table_name=? AND row_id IN ({placeholders}) AND restored_at IS NULL",
                [now, args.by, args.reason, table] + ids,
            )

    conn.commit()
    print("[soft_delete] 恢复完成，已提交。")
    print("[soft_delete] 提醒：若期间跑过 purge，knowledge_chunks 的向量/FTS 行可能已被物化清理，")
    print("[soft_delete]       需要重跑 embedding 与 FTS 重建脚本补回。")
    return 0


# --------------------------------------------------------------------------- #
# purge（物化清理）
# --------------------------------------------------------------------------- #
def cmd_purge(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    """物化清理：物理删除超过保留期的软删记录。"""
    # sys.path 修正：purge 复用 services.delete_guard 的闸门与备份逻辑。
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    from services.delete_guard import (  # 延迟导入，复用同一道闸门
        ENV_FLAG, backup_before_delete, require_physical_delete_enabled,
    )

    cutoff = (datetime.now() - timedelta(days=args.keep_days)).strftime("%Y-%m-%d %H:%M:%S")
    has_log = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='soft_delete_log'"
    ).fetchone()

    print(f"[soft_delete] 物化清理：删除 {args.table or '全部软删表'} 中早于 {cutoff} "
          f"（保留 {args.keep_days} 天）的软删记录")
    print(f"[soft_delete] 模式: {'dry-run' if not args.apply else 'APPLY'}")

    total = 0
    untracked = 0
    for table in ([args.table] if args.table else SOFT_TABLES):
        if not has_log:
            # 无流水表：拿不到删除时间，**拒绝**按窗口物化清理。
            # 宁可让人显式指定 --ids 也不盲目物理删除。
            n = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE COALESCE(is_deleted,0)=1"
            ).fetchone()[0]
            print(f"  {table}: {n} 条软删，但 soft_delete_log 不存在 —— "
                  f"无法判断删除时间，跳过（如需清理请用 --ids 显式指定）")
            continue

        # LEFT JOIN 而非 IN 子查询：把「有流水且已超期」与「无流水的孤儿软删」
        # 分开统计。孤儿软删没有删除时间，既不能自动清理也不能悄悄放过，
        # 必须显式报出来让人决策。
        expired, orphan = [], []
        for rid, log_at in conn.execute(
            f"SELECT t.id, l.deleted_at FROM {table} t "
            f"LEFT JOIN soft_delete_log l "
            f"  ON l.table_name = ? AND l.row_id = t.id AND l.restored_at IS NULL "
            f"WHERE COALESCE(t.is_deleted,0)=1",
            (table,),
        ).fetchall():
            if log_at is None:
                orphan.append(rid)
            elif log_at < cutoff:
                expired.append(rid)

        ids = expired
        untracked += len(orphan)
        print(f"  {table}: 超期可清理 {len(ids)} 条"
              + (f"；另有 {len(orphan)} 条无流水记录（删除时间未知，不自动清理）"
                 if orphan else ""))
        if orphan:
            print(f"    ⚠ 无流水 ids 样例: {orphan[:20]}")
        total += len(ids)
        if not ids or not args.apply:
            continue

        # 物理删除闸门 + 备份。与 delete_guard 完全同源，不另写一套。
        require_physical_delete_enabled(table)
        backup_before_delete(args._db_path)

        placeholders = ",".join("?" * len(ids))
        if table == "knowledge_chunks":
            # 先清依赖表：向量 / FTS / 错题关联
            for dep in CHUNK_DEPENDENTS.values():
                try:
                    conn.execute(f"DELETE FROM {dep} WHERE chunk_id IN ({placeholders})", ids)
                    print(f"    已清理依赖表 {dep}")
                except sqlite3.OperationalError as e:
                    print(f"    跳过 {dep}: {e}")
        conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", ids)
        if has_log:
            # 物理删除后把流水行标为「已物化」，保留审计痕迹。
            conn.execute(
                f"UPDATE soft_delete_log SET restore_reason = COALESCE(restore_reason,'purged') "
                f"WHERE table_name=? AND row_id IN ({placeholders}) AND restored_at IS NULL",
                [table] + ids,
            )
        print(f"    已物理删除 {table}: {len(ids)} 条")

    if args.apply:
        conn.commit()
        if args.vacuum:
            print("[soft_delete] 执行 VACUUM（会重建全库文件，需额外约等于库大小磁盘空间）")
            conn.isolation_level = None
            conn.execute("VACUUM")
        print(f"[soft_delete] 物化清理完成，共 {total} 条。")
    else:
        print(f"\n合计可清理 {total} 条"
              + (f"；{untracked} 条无流水记录需人工决策" if untracked else ""))
        print(f"确认无误后追加 --apply 执行（需先设 {ENV_FLAG}=1）。")
    return 0


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="软删记录查询 / 恢复 / 物化清理")
    parser.add_argument("--db", default=None, help="目标库路径")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出最近删除的记录")
    p_list.add_argument("--table", default=None, choices=SOFT_TABLES)
    p_list.add_argument("--batch", default=None, help="按批次 ID 过滤")
    p_list.add_argument("--minutes", type=int, default=None, help="最近 N 分钟")
    p_list.add_argument("--limit", type=int, default=50)

    p_res = sub.add_parser("restore", help="批量恢复软删记录")
    p_res.add_argument("--table", default=None, choices=SOFT_TABLES)
    p_res.add_argument("--ids", default=None, help="逗号分隔的行 id")
    p_res.add_argument("--batch", default=None, help="按批次 ID 恢复")
    p_res.add_argument("--minutes", type=int, default=None, help="恢复最近 N 分钟内的删除")
    p_res.add_argument("--limit", type=int, default=1000)
    p_res.add_argument("--by", default="cli", help="操作人")
    p_res.add_argument("--reason", default="误删回滚", help="恢复原因")
    p_res.add_argument("--apply", action="store_true", help="真正写库（缺省 dry-run）")

    p_purge = sub.add_parser("purge", help="物化清理：物理删除超期软删记录")
    p_purge.add_argument("--table", default=None, choices=SOFT_TABLES)
    p_purge.add_argument("--keep-days", type=int, default=90, help="软删保留天数")
    p_purge.add_argument("--vacuum", action="store_true", help="清理后执行 VACUUM")
    p_purge.add_argument("--apply", action="store_true", help="真正物理删除")

    args = parser.parse_args(argv)
    args._db_path = resolve_db_path(args.db)

    conn = sqlite3.connect(args._db_path)
    try:
        if args.cmd == "list":
            return cmd_list(conn, args)
        if args.cmd == "restore":
            return cmd_restore(conn, args)
        if args.cmd == "purge":
            return cmd_purge(conn, args)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())