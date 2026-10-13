# -*- coding: utf-8 -*-
"""导出 L2「疑似真矛盾」组的人工裁决材料（只读）。

口径与 diagnose_l2_similarity.py 完全一致（0.86），只额外导出：
  组号 / idA / idB / 题干(截断) / ansA / ansB / 长度差 / 学科 / 来源 / analysis

「疑似真矛盾」= L2 独有组（题干非精确相同）且组内答案**互不包含**。
输出 data/diagnostics/l2_adjudicate.json，供逐组人工裁决。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from difflib import SequenceMatcher

sys.path.insert(0, r"D:\平台\backend-main-fastapi")
from services.quiz_content_gate import (  # noqa: E402
    MAX_INDEX_STEM_LEN,
    MIN_CONFLICT_STEM_LEN,
    normalize_dedup,
    stem_signature,
)

DB_PATH = r"D:\平台\database\kaoyan.db"
TH = 0.86


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def main() -> int:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content, answer, analysis, is_junk, source, subject "
        "FROM quiz_questions"
    ).fetchall()
    conn.close()
    meta = {r["id"]: r for r in rows}

    cand = []
    for r in rows:
        if r["is_junk"]:
            continue
        a = normalize_dedup(r["answer"])
        s = stem_signature(r["content"])
        if not a or len(s) < MIN_CONFLICT_STEM_LEN or len(s) > MAX_INDEX_STEM_LEN:
            continue
        cand.append((r["id"], s, a))

    buckets: dict[int, list] = {}
    for qid, s, _a in cand:
        buckets.setdefault(len(s), []).append((qid, s))
    ans_of = {qid: a for qid, _s, a in cand}

    assigned: set[int] = set()
    groups = []
    for qid, s, a in cand:
        if qid in assigned:
            continue
        grp = [(qid, s, a)]
        assigned.add(qid)
        n = len(s)
        lo, hi = int(n * 0.6), int(n / 0.6) + 1
        for L in sorted(buckets):
            if L < lo:
                continue
            if L > hi:
                break
            for qid2, s2 in buckets[L]:
                if qid2 in assigned:
                    continue
                if sim(s, s2) >= TH:
                    grp.append((qid2, s2, ans_of[qid2]))
                    assigned.add(qid2)
        if len(grp) > 1:
            groups.append(grp)

    real = []
    for g in groups:
        answers = {a for _q, _s, a in g}
        if len(answers) < 2:
            continue
        if len({s for _q, s, _a in g}) < len(g):
            continue                      # L1 已覆盖
        if any(x in y or y in x for x in answers
               for y in answers if y != x):
            continue                      # 互为子串 → 详略差异
        real.append(g)

    print(f"[export] L2 疑似真矛盾组 = {len(real)}")
    out = []
    for i, g in enumerate(real, 1):
        g = sorted(g, key=lambda x: x[0])
        base = g[0]
        items = []
        for qid, s, a in g:
            m = meta[qid]
            items.append({
                "id": qid,
                "stem": (m["content"] or "")[:80],
                "ans": (m["answer"] or "")[:60],
                "ans_norm_len": len(a),
                "analysis": (m["analysis"] or "")[:100],
                "source": m["source"] or "",
                "subject": m["subject"] or "",
            })
        out.append({
            "组号": f"L{i:02d}",
            "idA": items[0]["id"],
            "idB": items[1]["id"] if len(items) > 1 else None,
            "全部id": [x["id"] for x in items],
            "题干": items[0]["stem"],
            "相似度": round(sim(g[0][1], g[1][1]), 4) if len(g) > 1 else None,
            "归一化题干长度": [len(x[1]) for x in g],
            "选项": items,
        })

    path = r"D:\平台\backend-main-fastapi\data\diagnostics\l2_adjudicate.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # 学科分布
    from collections import Counter
    subj = Counter()
    for grp in out:
        for it in grp["选项"]:
            subj[it["subject"] or "(空)"] += 1
    print(f"[export] 学科分布（按条）: {dict(subj.most_common())}")

    # 来源分布
    src = Counter()
    for grp in out:
        for it in grp["选项"]:
            s = it["source"]
            src["知识库" if s.startswith("知识库") else
                ("真题" if "真题" in s else ("课件/讲义" if any(
                    k in s for k in ("课件", "讲义", "教案")) else "其他"))] += 1
    print(f"[export] 来源分布（按条）: {dict(src.most_common())}")
    print(f"[saved] {path}")

    # 文本表格
    for grp in out:
        ids = "/".join(str(x) for x in grp["全部id"])
        print(f"\n### {grp['组号']}  ids={ids}  sim={grp['相似度']}  "
              f"题干长={grp['归一化题干长度']}")
        print(f"  题干: {grp['题干']}")
        for it in grp["选项"]:
            print(f"  #{it['id']} ans={it['ans']!r} subj={it['subject']!r} "
                  f"src={it['source']!r}")
            if it["analysis"]:
                print(f"        analysis: {it['analysis'][:90]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
