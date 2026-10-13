# -*- coding: utf-8 -*-
"""知识库「空正文文档」清单与状态标记（docx/22 §3.2 E3 的文档侧 + E3 空题根因）。

背景（真库实测）
----------------
    documents.content 为空的文档   193 篇
      其中 index_status='indexed'  135 篇（**谎报已入库**：无正文却被标为已索引）
      其中 index_status='failed'    58 篇
    这些文档正文完全没进知识库 → AI 检索不到，也是「识别是空问题」的根因。

处置
----
1. 产出**全量清单**（id / 文件名 / 类型 / 体积 / 状态 / OCR / 分块数 / 本地路径）。
2. **状态标记**（不删除）：
   - 真·空（content 空且**无任何 knowledge_chunks**）且当前 ``index_status='indexed'``
     → 改判 ``index_status='failed'``（纠正「谎报已索引」，前端即可显示失败/待重解析）。
   - content 空但**有分块**（库内仍有可检索内容）→ 不动状态，清单里单列提示。
   - 已是 ``failed`` → 不动。
   ※ 本库 documents 表无 `status`/`quality` 列、kb_pipeline 的合法状态集为
     {pending,indexing,indexed,failed}，故复用 ``index_status`` 承载该语义
     （新增枚举值会被 kb_pipeline 判为 unknown_status 告警，故不新增）。

安全红线
--------
* dry-run 默认开，必须显式 ``--apply`` 才写库。
* ``--apply`` 前强制 ``services/backup_service.py::create_backup()``（SQLite backup API）。
* **不删除任何文档/分块**（只改状态）。

用法
----
    python scripts/clean_documents_empty.py                 # dry-run
    python scripts/clean_documents_empty.py --show-samples 8
    python scripts/clean_documents_empty.py --report-json ../docx/24-docs-empty.json
    python scripts/clean_documents_empty.py --apply         # 写库（自动先备份）
    python scripts/clean_documents_empty.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

#: 空正文判定：NULL 或 纯空白。
_EMPTY_SQL = "(content IS NULL OR TRIM(content)='')"


def classify(index_status: str | None, chunk_count: int, is_empty: bool) -> str:
    """给一篇文档分类（供清单与自检使用）。"""
    if not is_empty:
        return "ok"
    if chunk_count > 0:
        return "empty_with_chunks"      # 正文缺失但仍有可检索分块
    if index_status == "failed":
        return "empty_failed"           # 已经标失败，无需再动
    if index_status == "indexed":
        return "empty_mislabeled"       # 谎报已索引 → 应改判 failed
    return "empty_other"                # pending/其它


def _do_backup(db_path: str) -> str:
    from services.backup_service import DB_PATH as _REAL_DB, create_backup  # noqa

    if os.path.abspath(db_path) != os.path.abspath(_REAL_DB):
        raise RuntimeError(
            f"拒绝对非真库执行备份/写入：--db={db_path} != 真库 {_REAL_DB}"
        )
    return create_backup()


def scan(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """扫描空正文文档清单（只读）。"""
    rows = conn.execute(
        f"""
        SELECT d.id, d.file_name, d.file_type, d.size, d.index_status, d.ocr_used,
               d.subject, d.folder_path, d.file_path, d.parse_progress,
               (SELECT COUNT(*) FROM knowledge_chunks kc WHERE kc.document_id = d.id)
        FROM documents d
        WHERE {_EMPTY_SQL}
        ORDER BY d.id
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for (did, fname, ftype, size, status, ocr, subject, folder, fpath, prog, nchunk) in rows:
        out.append({
            "id": did,
            "file_name": fname,
            "file_type": ftype,
            "size": size,
            "index_status": status,
            "ocr_used": bool(ocr),
            "subject": subject,
            "folder_path": folder,
            "file_path": fpath,
            "parse_progress": prog,
            "chunk_count": nchunk,
            "class": classify(status, nchunk, True),
            "has_local_file": bool(fpath) and os.path.isfile(fpath),
        })
    return out


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    def one(sql: str) -> int:
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return -1

    return {
        "documents_total": one("SELECT COUNT(*) FROM documents"),
        "content_empty": one(f"SELECT COUNT(*) FROM documents WHERE {_EMPTY_SQL}"),
        "empty_indexed": one(f"SELECT COUNT(*) FROM documents WHERE {_EMPTY_SQL} AND index_status='indexed'"),
        "empty_failed": one(f"SELECT COUNT(*) FROM documents WHERE {_EMPTY_SQL} AND index_status='failed'"),
        "empty_pending": one(f"SELECT COUNT(*) FROM documents WHERE {_EMPTY_SQL} AND index_status='pending'"),
        "indexed_total": one("SELECT COUNT(*) FROM documents WHERE index_status='indexed'"),
        "failed_total": one("SELECT COUNT(*) FROM documents WHERE index_status='failed'"),
    }


def selftest() -> int:
    cases: list[tuple[str, str | None, int, bool, str]] = [
        ("谎报已索引(空且无分块)", "indexed", 0, True, "empty_mislabeled"),
        ("空但仍有分块", "indexed", 3, True, "empty_with_chunks"),
        ("已是 failed", "failed", 0, True, "empty_failed"),
        ("pending 空", "pending", 0, True, "empty_other"),
        ("正常有正文", "indexed", 12, False, "ok"),
    ]
    print("=" * 64)
    print("SELFTEST：空正文文档分类判据")
    print("=" * 64)
    failed = 0
    for desc, st, n, empty, expect in cases:
        got = classify(st, n, empty)
        ok = got == expect
        print(f"  [{'✓' if ok else '✗ FAIL'}] {desc}  期望={expect} 实际={got}")
        if not ok:
            failed += 1
    print(f"\n  通过 {len(cases) - failed}/{len(cases)} → "
          + ("PASS" if failed == 0 else f"FAIL ({failed})"))
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="空正文文档清单与状态标记（dry-run 默认）")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--apply", action="store_true", help="真正写库（自动先备份）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--show-samples", type=int, default=8)
    ap.add_argument("--report-json", default=None)
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not os.path.isfile(args.db):
        print(f"数据库不存在: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    try:
        before = stats(conn)
        docs = scan(conn)
        by_class: dict[str, int] = {}
        for d in docs:
            by_class[d["class"]] = by_class.get(d["class"], 0) + 1
        mark_ids = [d["id"] for d in docs if d["class"] == "empty_mislabeled"]

        print("=" * 78)
        print("空正文文档清单与状态标记" + ("（DRY-RUN，不写库）" if not args.apply else "（APPLY）"))
        print("=" * 78)
        print("  现状：")
        for k, v in before.items():
            print(f"    {k:<18} {v}")
        print()
        print(f"  空正文文档合计 = {len(docs)}")
        for cls, n in sorted(by_class.items()):
            print(f"    {cls:<20} {n}")
        print(f"  → 拟改判 index_status='failed'（谎报已索引且无分块）= {len(mark_ids)}")
        print()
        if args.show_samples:
            print(f"  样例（前 {args.show_samples} 条）：")
            for d in docs[:args.show_samples]:
                print(f"   · #{d['id']:<5} [{d['class']:<18}] {d['file_name'][:52]}"
                      f"  type={d['file_type']} size={d['size']} chunks={d['chunk_count']}")
            print()

        if args.report_json:
            rep = {
                "mode": "apply" if args.apply else "dry-run",
                "db": os.path.abspath(args.db),
                "before": before,
                "empty_total": len(docs),
                "by_class": by_class,
                "misslabeled_ids": mark_ids,
                "documents": docs,
            }
            os.makedirs(os.path.dirname(os.path.abspath(args.report_json)), exist_ok=True)
            with open(args.report_json, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, ensure_ascii=False, indent=2)
            print(f"  >>> 已写出 JSON 报告：{args.report_json}")

        if not args.apply:
            print(">>> DRY-RUN 结束，未做任何改动。确认无误后加 --apply（自动先备份）。")
            return 0

        if not mark_ids:
            print(">>> 无需标记。")
            return 0

        bk = _do_backup(args.db)
        print(f">>> 备份完成（create_backup）：{bk} ({os.path.getsize(bk) / 1e6:.1f} MB)")

        cur = conn.cursor()
        n = 0
        for did in mark_ids:
            n += cur.execute(
                "UPDATE documents SET index_status='failed' "
                "WHERE id=? AND index_status='indexed'",
                (did,),
            ).rowcount
        conn.commit()

        after = stats(conn)
        print(f">>> 改判 index_status='failed' 共 {n} 篇")
        print("\n  变更前后对比：")
        for k in before:
            b, a = before[k], after[k]
            print(f"    {k:<18} {b:>7} → {a:>7}")
        if args.report_json:
            with open(args.report_json, "r", encoding="utf-8") as fh:
                rep = json.load(fh)
            rep["after"] = after
            rep["applied"] = {"marked_failed": n, "backup": bk}
            with open(args.report_json, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, ensure_ascii=False, indent=2)
            print(f">>> JSON 已更新（含 after/applied）：{args.report_json}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
