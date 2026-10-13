# -*- coding: utf-8 -*-
"""清理 documents 表里的重复文档行（同一文件被当成多份文档入库）。

背景
----
`smart_ingest` 早期版本无条件 `db.add(Document(...))`，而
`ingest_document(replace=True)` 只能清理「该 document_id 名下已有的分块」——
新建的 Document 根本没有旧块。于是每跑一次入库管线就多一份 documents 行
+ 一整套重复 knowledge_chunks。库里因此有 444 组同名 documents，
横跨 4 个日期批次（08-31 / 09-01 / 10-08 / 10-12 各跑了一遍全量）。

保留策略（按优先级）
--------------------
1. content 最长           → 自动排除 data/storage/documents/ 下被截断到 ~5000 字的副本
2. index_status='indexed' → 排除未成功索引的半成品
3. knowledge_point_count 最大 → 分块最多的是最完整的
4. id 最小               → 最后兜底，保证确定性

删除顺序（避免外键约束失败）
----------------------------
    documents → knowledge_chunks → knowledge_chunks_vec / fts / error_knowledge_links
先取 doc_ids，再删它们名下的块及其向量/FTS 关联。

安全策略
--------
1. **dry-run 默认开**，必须显式 `--apply` 才写库。
2. `--apply` 时强制用 SQLite `backup()` API 备份（禁止 copy2/cp，WAL 会丢数据）。
3. 只能删「file_name 相同」的组；不同名一律不动。
4. 每组至少保留 1 行，绝不整组删空。

用法
----
    python scripts/dedup_documents.py                  # dry-run
    python scripts/dedup_documents.py --show 20       # dry-run，看最严重的20组
    python scripts/dedup_documents.py --apply         # 真删（自动先备份）
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from services.delete_guard import require_physical_delete_enabled  # noqa: E402

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

DEP_TABLES = ("knowledge_chunks_vec", "knowledge_chunks_fts", "error_knowledge_links")

SQL_DUP_GROUPS = """
SELECT file_name, COUNT(*) n FROM documents
WHERE file_name IS NOT NULL AND TRIM(file_name) <> ''
GROUP BY file_name HAVING n > 1
ORDER BY n DESC, file_name
"""

# 保留优先级：content 长 > indexed > 分块多 > id 小
SQL_PICK_KEEP = """
SELECT id FROM documents WHERE file_name = ?
ORDER BY COALESCE(LENGTH(content), 0) DESC,
         CASE WHEN index_status = 'indexed' THEN 0 ELSE 1 END,
         COALESCE(knowledge_point_count, 0) DESC,
         id ASC
LIMIT 1
"""


def backup_db(src_path: str, dst_path: str) -> str:
    """SQLite 官方 backup() API —— 唯一正确的备份方式（copy2/cp 会丢 WAL 数据）。"""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dst_path


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    def one(sql: str) -> int:
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return -1

    return {
        "documents": one("SELECT COUNT(*) FROM documents"),
        "knowledge_chunks": one("SELECT COUNT(*) FROM knowledge_chunks"),
        "vec": one("SELECT COUNT(*) FROM knowledge_chunks_vec"),
        "fts": one("SELECT COUNT(*) FROM knowledge_chunks_fts"),
        "ekl": one("SELECT COUNT(*) FROM error_knowledge_links"),
        "dup_groups": one("SELECT COUNT(*) FROM (SELECT file_name FROM documents "
                          "WHERE file_name IS NOT NULL GROUP BY file_name HAVING COUNT(*)>1)"),
        "orphan_chunks": one("SELECT COUNT(*) FROM knowledge_chunks k WHERE NOT EXISTS "
                             "(SELECT 1 FROM documents d WHERE d.id = k.document_id)"),
    }


def analyze(conn: sqlite3.Connection, show: int) -> dict:
    groups = conn.execute(SQL_DUP_GROUPS).fetchall()
    total_docs_to_delete = sum(n - 1 for _, n in groups)

    chunks_to_delete = 0
    details = []
    for fname, n in groups:
        keep_id = conn.execute(SQL_PICK_KEEP, (fname,)).fetchone()[0]
        del_ids = [r[0] for r in conn.execute(
            "SELECT id FROM documents WHERE file_name=? AND id<>?", (fname, keep_id)
        ).fetchall()]
        if not del_ids:
            continue
        ph = ",".join("?" * len(del_ids))
        nc = conn.execute(
            f"SELECT COUNT(*) FROM knowledge_chunks WHERE document_id IN ({ph})", del_ids
        ).fetchone()[0]
        chunks_to_delete += nc
        info = conn.execute(
            "SELECT LENGTH(content), index_status, knowledge_point_count FROM documents WHERE id=?",
            (keep_id,),
        ).fetchone()
        details.append((fname, n, keep_id, len(del_ids), nc, info))

    return {
        "groups": groups,
        "docs_to_delete": total_docs_to_delete,
        "chunks_to_delete": chunks_to_delete,
        "details": details[:show] if show else [],
        "total_groups": len(groups),
    }


def apply_dedup(conn: sqlite3.Connection) -> dict:
    """执行删除。顺序：documents → knowledge_chunks → 依赖表。"""
    groups = conn.execute(SQL_DUP_GROUPS).fetchall()
    all_del_doc_ids: list[int] = []

    for fname, _n in groups:
        keep_id = conn.execute(SQL_PICK_KEEP, (fname,)).fetchone()[0]
        all_del_doc_ids.extend(
            r[0] for r in conn.execute(
                "SELECT id FROM documents WHERE file_name=? AND id<>?", (fname, keep_id)
            ).fetchall()
        )

    if not all_del_doc_ids:
        return {"docs": 0, "chunks": 0, "dep": {}}

    # 1) 先收集要删的 chunk ids
    ph = ",".join("?" * len(all_del_doc_ids))
    chunk_ids = [r[0] for r in conn.execute(
        f"SELECT id FROM knowledge_chunks WHERE document_id IN ({ph})", all_del_doc_ids
    ).fetchall()]

    dep_done: dict[str, int] = {}
    if chunk_ids:
        cph = ",".join("?" * len(chunk_ids))
        for t in DEP_TABLES:
            try:
                dep_done[t] = conn.execute(
                    f"DELETE FROM {t} WHERE chunk_id IN ({cph})", chunk_ids
                ).rowcount
            except sqlite3.Error as e:
                dep_done[t] = f"SKIP({e})"

    # 2) 删 chunks
    chunks_deleted = 0
    if chunk_ids:
        # 物理删除闸门：knowledge_chunks 物理删除不可逆。判重是本周
        # 误删 158 条真题的根因所在，这个脚本必须显式放行才允许跑。
        require_physical_delete_enabled("knowledge_chunks")
        cph = ",".join("?" * len(chunk_ids))
        chunks_deleted = conn.execute(
            f"DELETE FROM knowledge_chunks WHERE id IN ({cph})", chunk_ids
        ).rowcount

    # 3) 最后删 documents
    docs_deleted = conn.execute(
        f"DELETE FROM documents WHERE id IN ({ph})", all_del_doc_ids
    ).rowcount
    conn.commit()
    return {"docs": docs_deleted, "chunks": chunks_deleted, "dep": dep_done}


def main() -> int:
    ap = argparse.ArgumentParser(description="清理 documents 重复行（dry-run 默认开）")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--apply", action="store_true", help="真正写库")
    ap.add_argument("--show", type=int, default=15, help="展示前 N 组细节")
    ap.add_argument("--backup", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f"数据库不存在: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    try:
        before = stats(conn)
        info = analyze(conn, args.show)

        print("=" * 72)
        print("documents 去重" + ("（DRY-RUN，不写库）" if not args.apply else "（APPLY）"))
        print("=" * 72)
        print("  保留优先级：content最长 > indexed > 分块最多 > id最小")
        print()
        print("  清理前：")
        for k, v in before.items():
            print(f"    {k:<20} {v}")
        print()
        print(f"  同名 documents 组 = {info['total_groups']}")
        print(f"  将删除 documents 行 = {info['docs_to_delete']}")
        print(f"  将连带删除 knowledge_chunks = {info['chunks_to_delete']}")
        print()
        if info["details"]:
            print(f"  前 {len(info['details'])} 组（保留 / 删除）：")
            for fname, n, keep_id, ndel, nc, kinfo in info["details"]:
                kl, kst, kc = kinfo if kinfo else (0, "", 0)
                print(f"    x{n} 保留id={keep_id} 删{ndel}份 连带删块{nc}")
                print(f"        {str(fname)[:58]}")
                print(f"        保留份: content={kl}字 status={kst} chunks={kc}")
        print()

        if not args.apply:
            print(">>> DRY-RUN 结束，未做任何改动。确认后加 --apply 执行。")
            return 0

        if info["docs_to_delete"] == 0:
            print(">>> 无重复 documents，无需清理。")
            return 0

        bk = args.backup or (args.db + ".docdup.bak")
        print(f">>> 备份中（SQLite backup() API）→ {bk}")
        backup_db(args.db, bk)
        print(f">>> 备份完成（{os.path.getsize(bk) / 1e6:.1f} MB）")

        res = apply_dedup(conn)
        print(f">>> 已删除 documents {res['docs']} 行")
        print(f">>> 已删除 knowledge_chunks {res['chunks']} 行")
        for t, v in res["dep"].items():
            print(f"    {t:<24} {v}")

        after = stats(conn)
        print()
        print("  清理前后对比：")
        for k in before:
            b, a = before[k], after[k]
            print(f"    {k:<20} {b:>7} → {a:>7}  (减少 {b - a})")
        print()
        print(f"  孤儿块复查：{before['orphan_chunks']} → {after['orphan_chunks']}"
              f"  {'✓' if after['orphan_chunks'] == 0 else '✗ 出现孤儿'}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())