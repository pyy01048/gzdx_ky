"""#27 存量批量改名 —— **第一步：只出 dry-run CSV，不回写任何数据**。

命名规则不在这里，在 `services/doc_naming.py`（与上传/网盘/导入/知识库/目录监听
五条入库路径共用同一实现，避免两套规则漂移）。本脚本只负责：全库只读扫描、
逐条给出 `propose()` 的结论与依据、撞车交人判、并统计回写阶段需要写穿的
`knowledge_chunks.doc_name` 行数。

已批口径（2026-10-13）：先全库试算给人过，批准之后**只改 `documents.file_name`
显示名**，磁盘文件与 `file_path` 一律不动。

硬规矩：生产库 `mode=ro` 打开、脚本内没有 UPDATE；同名撞车只标注不动手；
绝不凭空造名（规则本身已保证名字逐字来自正文）。

用法：
    python scripts/rename_docs_dryrun.py                 # 全库试算 + 写 CSV
    python scripts/rename_docs_dryrun.py --limit 200     # 先小样本看口径
    python scripts/rename_docs_dryrun.py --out D:\\x.csv
"""
from __future__ import annotations

from pathlib import Path
import argparse
import csv
import os
import sqlite3
import sys
import time
from collections import Counter
from typing import Set

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 路径按本文件位置推导（P0-B2：拆除机器专属绝对路径绑定）
_REPO = Path(__file__).resolve().parents[2]
ROOT = str(_REPO)
BACKEND = os.path.join(ROOT, "backend-main-fastapi")
LIVE_DB = os.path.join(ROOT, "database", "kaoyan.db")
DEFAULT_OUT = os.path.join(ROOT, "docx", "_audit", "rename_dryrun_20261013.csv")

if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
from services.doc_naming import propose  # noqa: E402


def disk_hit(file_path: str) -> str:
    """#26 的原文可读性一并标出，人批时能判断「改名后还能不能预览」。"""
    if not file_path:
        return "no_path"
    for cand in (file_path, os.path.join(ROOT, file_path), os.path.join(BACKEND, file_path)):
        try:
            if os.path.exists(cand):
                return "yes"
        except OSError:
            return "unknown"
    return "missing"


def scan(docs, taken: Set[str], chunk_cnt):
    """逐篇定名。返回 (rows, stat)；撞车的行保留 proposed 但 reason 标注，交人判。"""
    rows, stat = [], Counter()
    for d in docs:
        name = d["file_name"] or ""
        got = propose(name, d["content"])
        base = {"id": d["id"], "subject": d["subject"] or "", "current": name,
                "proposed": "", "anchor": "", "basis": "", "verbatim": "",
                "chunks": chunk_cnt.get(d["id"], 0), "on_disk": disk_hit(d["file_path"])}
        reason = got.get("reason") or ""
        if reason:
            stat[reason[:40]] += 1
            if got.get("note"):
                reason += f"（首行={got['note']}）"
            rows.append({**base, "reason": reason})
            continue

        proposed = got["proposed"]
        if proposed.lower() in taken:
            stat["collision：库内已有同名"] += 1
            rows.append({**base, "proposed": proposed, "anchor": got["anchor"],
                         "basis": got["basis"], "verbatim": got["verbatim"],
                         "reason": "collision：库内已有同名，交人判定后再动"})
            continue
        taken.add(proposed.lower())
        stat["改名"] += 1
        rows.append({**base, "proposed": proposed, "anchor": got["anchor"],
                     "basis": got["basis"], "verbatim": got["verbatim"], "reason": ""})
    return rows, stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    sql = ("SELECT id, file_name, subject, file_path, COALESCE(content,'') AS content "
           "FROM documents")
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"
    t0 = time.time()
    docs = con.execute(sql).fetchall()
    taken = {str(r["file_name"]).lower()
             for r in con.execute("SELECT file_name FROM documents")}
    chunk_cnt = {r["document_id"]: r["n"] for r in con.execute(
        "SELECT document_id, COUNT(*) n FROM knowledge_chunks GROUP BY document_id")}
    rows, stat = scan(docs, taken, chunk_cnt)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "subject", "current", "proposed", "anchor",
                                           "basis", "verbatim", "chunks", "on_disk", "reason"])
        w.writeheader()
        w.writerows(rows)

    picks = [r for r in rows if r["proposed"] and not r["reason"]]
    drift = sum(r["chunks"] for r in picks)
    print(f"扫描文档 {len(docs)} 篇（用时 {time.time()-t0:.1f}s）→ 建议改名 {len(picks)} 篇")
    for k, v in stat.most_common():
        if k != "改名":
            print(f"  不改（{v}）：{k}")
    print(f"改名涉及 knowledge_chunks {drift} 行（回写阶段同事务写穿 doc_name）；"
          f"原文不在盘 {sum(1 for r in picks if r['on_disk'] != 'yes')} 篇")
    print(f"CSV：{args.out}")

    print("\n样例（前 20 条建议）：")
    for r in picks[:20]:
        print(f"  #{r['id']} [{r['subject']}] {r['current']}  →  {r['proposed']}")

    print("\n⚠ 本脚本只读，未回写任何数据；批准后再跑 scripts/rename_docs_apply.py --apply。")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
