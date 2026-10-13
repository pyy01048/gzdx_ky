# -*- coding: utf-8 -*-
"""S0b 反向抽题干跑探测（只读，绝不写库）。

对 S0 找出的「一篇题都没抽出」的答案版文档，直接调用
``services.qbank_builder.extract_questions`` 跑一遍，看能抽出多少题、
其中多少带答案。用于量化「反向缺口」的真实可回收量。
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
OUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "diagnostics"))

import sqlite3  # noqa: E402

from services.qbank_builder import extract_questions  # noqa: E402
from services import quiz_content_gate as G  # noqa: E402

DOC_ANSWER_NAME = re.compile(r"答案|解析|详解|答案版")
MIN_DOC_LEN = 500


def strip_source_prefix(source: str) -> str:
    if not source:
        return ""
    s = source.strip()
    for sep in (":", "："):
        if sep in s:
            head, tail = s.split(sep, 1)
            if 0 < len(head) <= 12 and "/" not in head and "\\" not in head:
                return tail.strip()
    return s


def main() -> None:
    limit_docs = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # 0 = 全量
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    docs = con.execute(
        "SELECT id, file_name, content, subject FROM documents "
        "WHERE file_name IS NOT NULL AND content IS NOT NULL AND length(content) >= ? "
        "ORDER BY length(content) DESC",
        (MIN_DOC_LEN,),
    ).fetchall()
    answer_docs = [d for d in docs if DOC_ANSWER_NAME.search(d["file_name"] or "")]

    used_names = set()
    for (src,) in con.execute("SELECT DISTINCT source FROM quiz_questions"):
        used_names.add(strip_source_prefix(src or ""))
    idle = [d for d in answer_docs if (d["file_name"] or "").strip() not in used_names]
    if limit_docs:
        idle = idle[:limit_docs]

    print(f"答案版文档 {len(answer_docs)} 份，其中未抽出题的 {len(idle)} 份，本次探测 {len(idle)} 份")

    rows = []
    tot = Counter()
    for idx, d in enumerate(idle, 1):
        try:
            qs = extract_questions(d["content"] or "", source_hint=f"真题:{d['file_name']}")
        except Exception as exc:  # noqa: BLE001
            rows.append({"doc_id": d["id"], "file_name": d["file_name"],
                         "doc_len": len(d["content"]), "error": repr(exc)[:200]})
            tot["error"] += 1
            continue
        n = len(qs)
        with_ans = sum(1 for q in qs if (q.get("answer") or "").strip())
        with_ana = sum(1 for q in qs if (q.get("analysis") or "").strip())
        tot["docs"] += 1
        tot["docs_with_q"] += 1 if n else 0
        tot["q"] += n
        tot["q_with_ans"] += with_ans
        tot["q_with_ana"] += with_ana
        rec = {
            "doc_id": d["id"],
            "file_name": d["file_name"],
            "subject": d["subject"],
            "doc_len": len(d["content"]),
            "n_questions": n,
            "n_with_answer": with_ans,
            "n_with_analysis": with_ana,
            "samples": [
                {"answer": q.get("answer"), "analysis": (q.get("analysis") or "")[:80],
                 "content": q.get("content", "")[:160]}
                for q in qs[:2]
            ] if n else [],
        }
        rows.append(rec)
        if idx % 25 == 0:
            print(f"  [{idx}/{len(idle)}] 累计题 {tot['q']}，带答案 {tot['q_with_ans']}")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "s0b_reverse_extract_probe.json"), "w", encoding="utf-8") as f:
        json.dump({"tot": dict(tot), "rows": rows}, f, ensure_ascii=False, indent=2)

    L = []
    L.append("=" * 78)
    L.append("S0b 反向抽题干跑探测（只读）")
    L.append("=" * 78)
    L.append(f"探测文档数: {tot['docs']}")
    L.append(f"  能抽出题的文档: {tot['docs_with_q']} ({tot['docs_with_q']*100.0/max(tot['docs'],1):.1f}%)")
    L.append(f"  抽出题目总数: {tot['q']}")
    L.append(f"  其中带答案: {tot['q_with_ans']}")
    L.append(f"  其中带解析: {tot['q_with_ana']}")
    L.append(f"  异常文档: {tot['error']}")
    L.append("")
    L.append("--- 每文档明细（按抽题数降序，Top 40） ---")
    ranked = sorted([r for r in rows if r.get("n_questions")], key=lambda r: -r["n_questions"])
    L.append(f"{'doc_id':>6} {'题数':>5} {'有答案':>6} {'有解析':>6} {'字数':>8}  file_name")
    for r in ranked[:40]:
        L.append(f"{r['doc_id']:>6} {r['n_questions']:>5} {r['n_with_answer']:>6} "
                 f"{r['n_with_analysis']:>6} {r['doc_len']:>8,}  {r['file_name']}")
    L.append("")
    L.append("--- 抽题样例（Top 8 文档，每份前 1 题） ---")
    for r in ranked[:8]:
        if not r["samples"]:
            continue
        s = r["samples"][0]
        L.append(f"[doc#{r['doc_id']}] {r['file_name']}  ({r['n_questions']}题/{r['n_with_answer']}有答案)")
        L.append(f"   题干: {s['content']}")
        L.append(f"   答案: {s['answer']}")
        L.append(f"   解析: {s['analysis']}")
        L.append("")
    zero = [r for r in rows if not r.get("n_questions")]
    L.append(f"--- 抽不出题的文档: {len(zero)} 份（Top 20 示意） ---")
    for r in sorted(zero, key=lambda r: -r["doc_len"])[:20]:
        L.append(f"  {r['doc_len']:>8,}  {r['file_name']}")

    text = "\n".join(L)
    with open(os.path.join(OUT_DIR, "s0b_reverse_extract_probe.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
