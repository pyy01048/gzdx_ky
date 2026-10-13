"""#27 第二步：把 dry-run CSV 里**人批过的建议改名**回写到显示名。

只有用户看过 `docx/_audit/rename_dryrun_20261013.csv` 并明确批准之后才允许带
`--apply` 运行；默认 dry-run，只打印计划，不写任何数据。

改动范围（与已批口径一致）：
* `documents.file_name` —— 列表页显示名；
* `knowledge_chunks.doc_name` —— **同一事务**写穿，否则答疑引用标题
  （`services/ai_service.py` 用 `c.doc_name`）和分块列表继续显示旧名；
* **不动** `file_path` / 磁盘文件：#26 的 `/api/documents/{id}/raw|download`
  按 `file_path` 定位原文，动物理名会打断在盘映射；
* **不重建 FTS**：镜像列是 (chunk_id, document_id, subject, content)，不含 doc_name。

安全阀：
1. 回写前逐条核对 `documents.file_name` 仍等于 CSV 的 `current`，库在这期间变过
   就跳过并报告，绝不覆盖新状态；
2. 先把 `(id, old, new)` 落到 rollback CSV，出问题可逐条还原；
3. 单事务，任一条出错整体回滚。

逻辑拆成 `load_plan / stage_plan / write_rollback / apply_plan` 四个纯函数，
便于 `tests/test_doc_rename_write_through.py` 用临时库驱动（红线：测试绝不碰生产库）。

用法：
    python scripts/rename_docs_apply.py                      # 看计划
    python scripts/rename_docs_apply.py --apply              # 人批后才执行
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sqlite3
import sys
from datetime import datetime
from typing import List, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = r"D:\平台"
LIVE_DB = os.path.join(ROOT, "database", "kaoyan.db")
DEFAULT_CSV = os.path.join(ROOT, "docx", "_audit", "rename_dryrun_20261013.csv")
AUDIT_DIR = os.path.join(ROOT, "docx", "_audit")


def load_plan(path: str) -> List[dict]:
    """CSV 里「有拟改名且 reason 为空」的行才是被批的条目；collision 行 reason 非空。"""
    with io.open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [r for r in csv.DictReader(fh)
                if (r.get("proposed") or "").strip() and not (r.get("reason") or "").strip()]


def stage_plan(con: sqlite3.Connection, plan: List[dict]) -> Tuple[List[dict], List[Tuple[str, str]]]:
    """逐条核对库的当前状态，返回 (可执行清单, 跳过原因)。"""
    chunk_cnt = {r["document_id"]: r["n"] for r in con.execute(
        "SELECT document_id, COUNT(*) n FROM knowledge_chunks GROUP BY document_id")}
    staged, stale = [], []
    for r in plan:
        doc = con.execute("SELECT id, file_name FROM documents WHERE id=?",
                          (int(r["id"]),)).fetchone()
        if doc is None:
            stale.append((r["id"], "文档已不存在"))
            continue
        if doc["file_name"] == r["proposed"]:
            # 必须排在「现名已变」前面：同一份 CSV 重复跑 --apply 是幂等的，
            # 若先比 current 会把已成功回写报成库漂移，看着像出错。
            stale.append((r["id"], "已是目标名，无需写"))
            continue
        if doc["file_name"] != r["current"]:
            stale.append((r["id"], f"现名已变：{doc['file_name']}"))
            continue
        staged.append({"id": doc["id"], "old": doc["file_name"], "new": r["proposed"],
                       "chunks": chunk_cnt.get(doc["id"], 0)})
    return staged, stale


def write_rollback(path: str, staged: List[dict]) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "old_file_name", "new_file_name", "chunks"])
        w.writeheader()
        w.writerows(staged)


def apply_plan(con: sqlite3.Connection, staged: List[dict]) -> Tuple[int, int]:
    """单事务回写：documents.file_name + knowledge_chunks.doc_name 一起改。"""
    applied = rows = 0
    try:
        with con:
            for s in staged:
                con.execute("UPDATE documents SET file_name=? WHERE id=?", (s["new"], s["id"]))
                rows += con.execute(
                    "UPDATE knowledge_chunks SET doc_name=? WHERE document_id=?",
                    (s["new"], s["id"])).rowcount
                applied += 1
    except sqlite3.Error as e:
        print(f"\n✗ 回写失败，事务已回滚：{e}")
        raise
    return applied, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--apply", action="store_true", help="真正回写；不带则只打印计划")
    ap.add_argument("--rollback-out", default=os.path.join(
        AUDIT_DIR, f"rename_rollback_{datetime.now():%Y%m%d_%H%M%S}.csv"))
    args = ap.parse_args()

    plan = load_plan(args.csv)
    print(f"CSV {args.csv}\n待回写 {len(plan)} 篇（改名建议 + reason 为空）")
    if not plan:
        print("没有可回写的条目。")
        return 0

    mode = "rw" if args.apply else "ro"
    con = sqlite3.connect(f"file:{LIVE_DB}?mode={mode}", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    if args.apply:
        # :8000 的 uvicorn 常连着同一个库，拿不到写锁时等 10 秒而不是立刻报错
        con.execute("PRAGMA busy_timeout=10000")

    staged, stale = stage_plan(con, plan)
    drift = sum(s["chunks"] for s in staged)
    print(f"可执行 {len(staged)} 篇，涉及 knowledge_chunks 写穿 {drift} 行；跳过 {len(stale)} 篇")
    for sid, why in stale:
        print(f"  跳过 #{sid}：{why}")
    for s in staged[:10]:
        print(f"  #{s['id']} {s['old']}  →  {s['new']}   （chunk {s['chunks']} 行）")
    if len(staged) > 10:
        print(f"  …其余 {len(staged) - 10} 条")

    if not args.apply:
        print("\nDRY-RUN：未写任何数据。人批后加 --apply 才回写。")
        con.close()
        return 0

    write_rollback(args.rollback_out, staged)
    applied, rows = apply_plan(con, staged)
    print(f"\n✓ 已回写 documents.file_name {applied} 篇、knowledge_chunks.doc_name {rows} 行")
    print("  （file_path 未改动；FTS 镜像不含 doc_name，无需重建）")
    print(f"  还原清单：{args.rollback_out}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
