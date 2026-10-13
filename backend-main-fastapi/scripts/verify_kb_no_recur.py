# -*- coding: utf-8 -*-
"""验证 smart_ingest 的入库幂等性（防复发回归测试）。

背景
----
`services/smart_ingest.py` 早期无条件 `db.add(Document(...))`，而
`kb_service.ingest_document(replace=True)` 只能清理「该 document_id 名下已有的分块」——
新建的 Document 根本没有旧块。于是每跑一次入库管线就多一份 documents 行 +
一整套重复 knowledge_chunks。实测库里因此攒下 444 组同名 documents
（横跨 08-31 / 09-01 / 10-08 / 10-12 四个日期批次），
knowledge_chunks 75122 行里唯一 text 只有 68915。

这个脚本**用真实入库管线跑真实文件**，断言连续跑两次的增量必须为 0。
它跑在**临时副本库**上，不碰真库（真库是生产数据，不能拿来做写入测试）。

为什么用副本库
--------------
SQLite 单文件、且 `smart_ingest_file()` 需要写 documents / knowledge_chunks /
knowledge_chunks_fts / knowledge_chunks_vec 多张表。用真库做「跑两次看增量」的测试
会污染生产数据，而且没法回滚。副本库通过官方 `backup()` API 生成
（**禁止 shutil.copy2 / cp，WAL 里未 checkpoint 的事务会丢**）。

用法
----
    python scripts/verify_kb_no_recur.py                    # 自动挑 5 个样本文件
    python scripts/verify_kb_no_recur.py --files a.pdf b.pdf
    python scripts/verify_kb_no_recur.py --keep             # 跑完不删临时库
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

REAL_DB = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
KB_ROOT = r"D:\平台\knowledge_base"

# 只挑这些扩展名的小文件，测试要快
SAMPLE_EXTS = {".pdf", ".txt", ".md", ".docx", ".doc"}
MAX_SAMPLE_BYTES = 3 * 1024 * 1024  # 3MB 以内，跑得快


def backup_db(src: str, dst: str) -> str:
    """SQLite backup() API —— 唯一正确的复制方式。"""
    s = sqlite3.connect(src)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    return dst


def pick_samples(n: int) -> list[str]:
    """从 knowledge_base 挑 n 个体积适中的真实文件。"""
    out: list[str] = []
    for dirpath, dirs, files in os.walk(KB_ROOT):
        dirs[:] = [d for d in dirs if d not in {".git", "_trash", "documents", "chunks", "meta"}]
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext not in SAMPLE_EXTS:
                continue
            p = os.path.join(dirpath, f)
            try:
                if os.path.getsize(p) > MAX_SAMPLE_BYTES:
                    continue
            except OSError:
                continue
            out.append(p)
            if len(out) >= n:
                return out
    return out


def row_counts(db_path: str) -> dict[str, int]:
    """统计关键表行数。用裸 sqlite3 读，避免 ORM session 缓存干扰。"""
    con = sqlite3.connect(db_path)
    try:
        out = {}
        for t in ("documents", "knowledge_chunks", "knowledge_chunks_fts",
                  "knowledge_chunks_vec"):
            try:
                out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error as e:
                out[t] = f"ERR({e})"
        return out
    finally:
        con.close()


def run_ingest_once(db_path: str, files: list[str]) -> list[dict[str, Any]]:
    """对每个文件跑一次 smart_ingest_file（extract_kp=False 避免调用本地模型）。"""
    # 让 database 模块指向副本库（database.py 读的是 DATABASE_PATH 这个变量名）
    os.environ["DATABASE_PATH"] = db_path
    import importlib

    import database
    importlib.reload(database)
    import services.smart_ingest as si
    importlib.reload(si)

    results = []
    for p in files:
        db = database.SessionLocal()
        try:
            r = si.smart_ingest_file(
                db, p, dry_run=False, force=True, extract_kp=False
            )
            db.commit()
            results.append(r)
        except Exception as e:  # noqa: BLE001
            try:
                db.rollback()
            except Exception:
                pass
            results.append({"file": os.path.basename(p), "status": "error",
                            "reasons": [repr(e)]})
        finally:
            db.close()
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="验证入库幂等性（防复发）")
    ap.add_argument("--db", default=REAL_DB)
    ap.add_argument("--files", nargs="*", help="指定测试文件；不给则自动挑 5 个")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--keep", action="store_true", help="保留临时库（调试用）")
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f"真库不存在: {args.db}")
        return 1

    files = args.files or pick_samples(args.n)
    if not files:
        print(f"在 {KB_ROOT} 下没找到可用样本文件")
        return 1

    print("=" * 72)
    print("入库幂等性验证（防复发）")
    print("=" * 72)
    print(f"  真库（只读）: {args.db}")
    print(f"  样本文件 {len(files)} 个：")
    for p in files:
        print(f"    {os.path.basename(p)[:60]}  ({os.path.getsize(p) / 1024:.0f} KB)")
    print()

    # 1) 生成副本库
    tmpdir = tempfile.mkdtemp(prefix="idem_verify_")
    db2 = os.path.join(tmpdir, "test.db")
    print(">>> 用 SQLite backup() API 生成副本库（不污染真库）…")
    backup_db(args.db, db2)
    print(f">>> 副本库: {db2}")
    print()

    base = row_counts(db2)
    print("  基线行数：")
    for k, v in base.items():
        print(f"    {k:<24} {v}")
    print()

    # 2) 第一轮
    print(">>> 第 1 轮入库…")
    r1 = run_ingest_once(db2, files)
    for r in r1:
        print(f"    {r.get('status','?'):<10} {r.get('file','')[:46]}"
              f" doc={r.get('doc_id')} chunks={r.get('chunks')}"
              f" reused={r.get('dedup_reused', False)}")
    after1 = row_counts(db2)
    print()
    print("  第 1 轮后：")
    for k, v in after1.items():
        d = (v - base[k]) if isinstance(v, int) and isinstance(base.get(k), int) else "?"
        print(f"    {k:<24} {v:>7}   增量 {d:+}")
    print()

    # 3) 第二轮（关键：增量必须全为 0）
    print(">>> 第 2 轮入库（关键：增量必须全部为 0）…")
    r2 = run_ingest_once(db2, files)
    for r in r2:
        print(f"    {r.get('status','?'):<10} {r.get('file','')[:46]}"
              f" doc={r.get('doc_id')} chunks={r.get('chunks')}"
              f" reused={r.get('dedup_reused', False)}")
    after2 = row_counts(db2)
    print()
    print("  第 2 轮后：")
    deltas = {}
    for k, v in after2.items():
        if isinstance(v, int) and isinstance(after1.get(k), int):
            deltas[k] = v - after1[k]
        else:
            deltas[k] = None
        print(f"    {k:<24} {v:>7}   增量 {deltas[k] if deltas[k] is not None else '?'}")
    print()

    # 4) 断言
    reused2 = sum(1 for r in r2 if r.get("dedup_reused"))
    print("=" * 72)
    ok = True
    for t in ("documents", "knowledge_chunks", "knowledge_chunks_fts",
              "knowledge_chunks_vec"):
        d = deltas.get(t)
        if d is None:
            print(f"  [SKIP] {t} 无法统计")
            continue
        good = d == 0
        ok = ok and good
        print(f"  [{'PASS' if good else 'FAIL'}] {t} 第2轮增量 = {d:+}（应为 0）")

    print(f"  [{'PASS' if reused2 == len(r2) else 'WARN'}] "
          f"第2轮 {reused2}/{len(r2)} 个文件走了复用分支（dedup_reused=True）")
    print()
    print("  RESULT: " + ("PASS —— 幂等生效，重复跑不会膨胀" if ok else "FAIL —— 仍在膨胀"))
    print("=" * 72)

    if args.keep:
        print(f"\n临时库保留在: {db2}")
    else:
        try:
            os.remove(db2)
            os.rmdir(tmpdir)
            print("\n临时库已清理。")
        except OSError:
            print(f"\n临时库清理失败，可手动删: {db2}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())