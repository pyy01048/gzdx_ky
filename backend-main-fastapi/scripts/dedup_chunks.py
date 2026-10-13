# -*- coding: utf-8 -*-
"""清理 knowledge_chunks 重复块（dry-run 默认开）。

背景
----
`knowledge_chunks` 全表 75122 行，唯一 text 仅 68915，冗余 6207 行。
归因（见 report）：
    A 同 doc 内完全同 text 冗余 =  796 (12.8%)  —— 58 个 document_id
    B 跨 doc 同 text 冗余       = 5411 (87.2%)  —— 444 组同名 documents 重复入库
                                               （4 个日期批次 08-31/09-01/10-08/10-12）

安全策略
--------
1. **dry-run 默认开**，必须显式 `--apply` 才会写库。
2. 写库前强制用 SQLite `backup()` API 备份（**禁止 shutil.copy2/cp**，WAL 会丢数据）。
3. knowledge_chunks 上**没有** is_deleted / is_junk 软删除字段，因此默认硬删。
   若你后续加了软删字段，用 `--soft` 可切到标记模式（脚本会自动探测）。
4. 按依赖顺序清理，避免外键约束失败：
       knowledge_chunks_vec / knowledge_chunks_fts / error_knowledge_links
       → knowledge_chunks
5. 保留规则：同一 (document_id, text) 保留 `page_start` 最早、其次 `id` 最小的一条。
   这样保留下来的块带有正确的页码溯源。

用法
----
    python scripts/dedup_chunks.py                     # dry-run，只报告
    python scripts/dedup_chunks.py --limit-groups 20    # dry-run，看最严重的20组
    python scripts/dedup_chunks.py --apply             # 真删（自动先备份）
    python scripts/dedup_chunks.py --apply --soft      # 有软删字段时用标记代替硬删
    python scripts/dedup_chunks.py --apply --keep-doc latest  # 跨doc重复时保留最新文档的块
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services.delete_guard import require_physical_delete_enabled  # noqa: E402

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

# 依赖 knowledge_chunks.id 的表（含 chunk_id 列）
DEP_TABLES = ("knowledge_chunks_vec", "knowledge_chunks_fts", "error_knowledge_links")


# --------------------------------------------------------------------------- #
# 备份（SQLite backup API —— 唯一正确的备份方式）
# --------------------------------------------------------------------------- #
def backup_db(src_path: str, dst_path: str) -> str:
    """用 SQLite 官方 backup() API 备份，WAL 内容会被完整合并。

    禁止 shutil.copy2 / cp：那样只复制主库文件，-wal 里未 checkpoint 的事务会丢。
    """
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dst_path


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
SQL_SAME_DOC_GROUPS = """
SELECT document_id, COUNT(*) - COUNT(DISTINCT text) AS dup
FROM knowledge_chunks
GROUP BY document_id
HAVING dup > 0
ORDER BY dup DESC
"""

SQL_GLOBAL_TOTALS = """
SELECT COUNT(*) AS total,
       COUNT(DISTINCT text) AS uniq_text,
       SUM(CASE WHEN document_id IS NULL THEN 1 ELSE 0 END) AS null_doc,
       SUM(CASE WHEN text IS NULL OR TRIM(text) = '' THEN 1 ELSE 0 END) AS empty_text
FROM knowledge_chunks
"""

SQL_SAME_DOC_IDS = """
SELECT id FROM knowledge_chunks k
WHERE k.document_id = ? AND k.id NOT IN (
    SELECT id FROM knowledge_chunks k2
    WHERE k2.document_id = ? AND k2.text = k.text
    ORDER BY COALESCE(k2.page_start, 1 << 30), k2.id
    LIMIT 1
)
"""


def pick_dup_ids_same_doc(conn: sqlite3.Connection, limit_groups: int | None) -> list[int]:
    """挑出「同 document_id 内 text 完全重复」的冗余行 id（保留最优一条）。"""
    groups = conn.execute(SQL_SAME_DOC_GROUPS).fetchall()
    if limit_groups:
        groups = groups[:limit_groups]
    dup_ids: list[int] = []
    for doc_id, _dup in groups:
        rows = conn.execute(SQL_SAME_DOC_IDS, (doc_id, doc_id)).fetchall()
        dup_ids.extend(r[0] for r in rows)
    return dup_ids


def analyze(conn: sqlite3.Connection, limit_groups: int | None) -> dict[str, Any]:
    """dry-run 报告：只读，不改任何数据。"""
    total, uniq, null_doc, empty = conn.execute(SQL_GLOBAL_TOTALS).fetchone()
    dup_ids = pick_dup_ids_same_doc(conn, limit_groups)
    per_doc = conn.execute(SQL_SAME_DOC_GROUPS).fetchall()

    # 被删块会牵连到的向量/FTS 行数
    dep_impact: dict[str, int] = {}
    if dup_ids:
        ph = ",".join("?" * len(dup_ids))
        for t in DEP_TABLES:
            try:
                n = conn.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE chunk_id IN ({ph})", dup_ids
                ).fetchone()[0]
            except sqlite3.Error:
                n = -1  # 表不存在或无该列
            dep_impact[t] = n

    samples = []
    if dup_ids:
        ph = ",".join("?" * len(dup_ids[:200]))
        for r in conn.execute(
            f"""SELECT k.id, k.document_id, k.doc_name, length(k.text),
                       substr(k.text, 1, 60)
                FROM knowledge_chunks k WHERE k.id IN ({ph})
                ORDER BY k.document_id, k.id LIMIT 15""",
            dup_ids[:200],
        ):
            samples.append(r)

    return {
        "total": total,
        "uniq_text": uniq,
        "null_doc": null_doc,
        "empty_text": empty,
        "dup_groups": len(per_doc),
        "dup_groups_rows": sum(d for _, d in per_doc),
        "dup_ids": dup_ids,
        "dep_impact": dep_impact,
        "samples": samples,
        "per_doc_top": per_doc[:20],
    }


# --------------------------------------------------------------------------- #
# 执行删除
# --------------------------------------------------------------------------- #
def apply_dedup(conn: sqlite3.Connection, dup_ids: list[int], *, soft: bool) -> dict[str, Any]:
    """按依赖顺序删除冗余块。soft=True 时标记而非删除（需库里有软删字段）。"""
    if not dup_ids:
        return {"deleted": 0, "dep_deleted": {}}

    ph = ",".join("?" * len(dup_ids))
    dep_done: dict[str, int] = {}

    if soft:
        col = None
        for cand in ("is_deleted", "is_junk", "deleted_at"):
            cols = {r[1] for r in conn.execute("PRAGMA table_info(knowledge_chunks)")}
            if cand in cols:
                col = cand
                break
        if col is None:
            raise SystemExit(
                "--soft 需要 knowledge_chunks 上存在 is_deleted/is_junk/deleted_at 字段，"
                "当前表没有这些字段，请改用硬删（不加 --soft）"
            )
        cur = conn.execute(
            f"UPDATE knowledge_chunks SET {col}=1 WHERE id IN ({ph})", dup_ids
        )
        return {"deleted": cur.rowcount, "dep_deleted": {}, "soft_col": col}

    # 物理删除闸门：硬删 knowledge_chunks 不可逆。判重逻辑正是本周
    # 误删 158 条真题的根因，此处必须显式放行。
    # 提示：加 --soft 可走上面的软删分支，无需本闸门。
    require_physical_delete_enabled("knowledge_chunks")
    for t in DEP_TABLES:
        try:
            cur = conn.execute(f"DELETE FROM {t} WHERE chunk_id IN ({ph})", dup_ids)
            dep_done[t] = cur.rowcount
        except sqlite3.Error as e:
            dep_done[t] = f"SKIP({e})"
    cur = conn.execute(f"DELETE FROM knowledge_chunks WHERE id IN ({ph})", dup_ids)
    deleted = cur.rowcount
    conn.commit()
    return {"deleted": deleted, "dep_deleted": dep_done}


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="清理 knowledge_chunks 重复块")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--soft", action="store_true", help="标记而非硬删（需软删字段）")
    ap.add_argument("--limit-groups", type=int, default=None,
                    help="只处理冗余最严重的 N 个 document_id")
    ap.add_argument("--backup", default=None, help="备份目标路径（默认 <db>.dedup.bak）")
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f"数据库不存在: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        info = analyze(conn, args.limit_groups)
        dup_n = len(info["dup_ids"])

        print("=" * 68)
        print("knowledge_chunks 去重报告" + ("（DRY-RUN，不写库）" if not args.apply else "（APPLY）"))
        print("=" * 68)
        print(f"  全表行数            = {info['total']}")
        print(f"  唯一 text           = {info['uniq_text']}")
        print(f"  全表口径冗余        = {info['total'] - info['uniq_text']}")
        print(f"  document_id 为 NULL = {info['null_doc']}")
        print(f"  text 为空           = {info['empty_text']}")
        print()
        print(f"  同doc内重复的 document_id 组 = {info['dup_groups']}")
        print(f"  这些组的冗余行合计           = {info['dup_groups_rows']}")
        print(f"  本次将删除的行数             = {dup_n}")
        print()
        print("  删除将牵连的依赖表行数：")
        for t, n in info["dep_impact"].items():
            print(f"    {t:<28} {n}")
        print()
        if info["per_doc_top"]:
            print("  冗余最严重的 document_id：")
            for doc_id, d in info["per_doc_top"]:
                name = conn.execute(
                    "SELECT file_name FROM documents WHERE id=?", (doc_id,)
                ).fetchone()
                nm = (name[0][:44] if name else "(文档已不存在)")
                print(f"    doc={doc_id:<6} 冗余={d:<5} {nm}")
        print()
        if info["samples"]:
            print("  待删样本：")
            for r in info["samples"]:
                print(f"    id={r[0]:<7} doc={r[1]:<6} len={r[3]:<6} {r[4]!r}")
        print()

        if not args.apply:
            print(">>> DRY-RUN 结束，未做任何改动。确认无误后加 --apply 执行。")
            print(">>> 注意：跨 document_id 的同名重复（444 组 documents）**本脚本不处理**，")
            print("    那属于 documents 层面的重复入库，需要单独决策保留哪一份。")
            return 0

        if dup_n == 0:
            print(">>> 无需清理。")
            return 0

        bk = args.backup or (args.db + ".dedup.bak")
        print(f">>> 备份中（SQLite backup() API）→ {bk}")
        backup_db(args.db, bk)
        print(f">>> 备份完成（{os.path.getsize(bk) / 1e6:.1f} MB）")

        res = apply_dedup(conn, info["dup_ids"], soft=args.soft)
        print(f">>> 已删除 knowledge_chunks {res['deleted']} 行")
        for t, n in res["dep_deleted"].items():
            print(f"    {t:<28} {n}")

        after = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        print(f">>> 清理后总行数 = {after}（清理前 {info['total']}，减少 {info['total'] - after}）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())