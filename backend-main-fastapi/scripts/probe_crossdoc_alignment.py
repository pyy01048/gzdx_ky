# -*- coding: utf-8 -*-
"""跨文档答案对齐可行性（只读）—— 回答「A/B 类无答案题里到底有多少能补上答案」。

### 为什么需要跨文档
A 类真题的 source 指向的是「无答案版」真题卷（如 `贵州大学电子技术基础真题16-21.txt`、
`0-（无答案版）25管综真题.pdf`），答案在**另一份**文档里
（如 `…真题及答案.pdf`、`2004年真题逐题细解.txt`、`…考试卷带解析….pdf`）。
只在本来源文档里找答案（A 类命中率仅 5/129）会严重低估可行性。

本脚本对 A/B 类每一道题：
  S1 本文档对齐（同源就近，答案与题目同页排版，如习题解答）
  S2 同学科跨文档对齐：在 documents.content 全库检索题干特征串，命中后再就近找答案
  S3 knowledge_chunks 对齐：同上，但检索面换成 chunks.text（含摘要/分块）
三路命中任一即算「可自动对齐补答案」，并给出命中路径与切出的答案原文。

判定沿用 scripts/classify_noanswer_abc.py 的三分类与 probe_align()，不重写。

用法：
    python scripts/probe_crossdoc_alignment.py --limit 0     # 全量 A+B 类
    python scripts/probe_crossdoc_alignment.py --limit 20    # 快速试跑
只读。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

from classify_noanswer_abc import (  # noqa: E402
    classify, norm, probe_align, extract_answer_after,
)

#: 归一化后长度 >= 该值的文档才参与跨文档检索（太短的文档命中率极低且拖慢速度）
MIN_DOC_LEN = 3000


def build_corpus(con):
    """构建归一化检索语料：documents.content + knowledge_chunks.text（按 doc_name 合并）。"""
    corpus = []          # [(label, 归一化正文)]
    t0 = time.time()
    for did, fn, body in con.execute(
        "SELECT id, file_name, content FROM documents "
        "WHERE content IS NOT NULL AND length(content) >= ?", (MIN_DOC_LEN,)
    ):
        corpus.append((f"doc:{fn}", norm(body)))
    # chunks 按 doc_name 聚合拼接（chunks 是文档正文的另一种切分，通常带更多答案信号）
    per_doc = defaultdict(list)
    for dn, tx in con.execute(
        "SELECT doc_name, text FROM knowledge_chunks WHERE text IS NOT NULL AND length(text)>200"
    ):
        per_doc[dn].append(tx)
    for dn, parts in per_doc.items():
        corpus.append((f"chunk:{dn}", norm("".join(parts))))
    print(f"语料条目: {len(corpus)}（docs+chunks 合并），构建耗时 {time.time()-t0:.1f}s")
    return corpus


def cross_search(qnorm: str, corpus, narrow: int, max_docs: int):
    """全库检索题干，找就近答案。返回 (命中来源标签, 答案) 或 (None, 原因)。"""
    if len(qnorm) < 8:
        return None, "题干过短"
    probes = [qnorm[:L] for L in (24, 18, 14, 10) if len(qnorm) >= L]
    checked = 0
    for label, body in corpus:
        if not body:
            continue
        checked += 1
        hit = False
        for p in probes:
            idx = body.find(p)
            if idx >= 0:
                hit_len = len(p)
                res = probe_align(qnorm[:hit_len], body[idx: idx + hit_len + narrow + 400], narrow)
                if res.get("why") == "strict-ok":
                    return label, res["answer"]
                hit = True
                break
        if checked >= max_docs:
            break
    return None, "全库未命中"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="A/B 每类处理条数上限，0=全量")
    ap.add_argument("--narrow", type=int, default=300)
    ap.add_argument("--max-docs", type=int, default=2616)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=600)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=600000")

    rows = con.execute(
        "SELECT id, content, options, answer, source, paper, question_type, subject, chapter "
        "FROM quiz_questions WHERE answer IS NULL OR trim(answer)=''"
    ).fetchall()

    # 三分类，复用脚本
    ab = {"A-真题缺答案": [], "B-习题缺答案": []}
    for r in rows:
        opts = r["options"]
        if isinstance(opts, str):
            try:
                opts = json.loads(opts)
            except Exception:
                opts = []
        cls, why, comp, cw = classify(
            (r["id"], r["content"], opts, r["answer"], r["source"], r["question_type"]))
        if cls in ab:
            ab[cls].append((dict(r), comp, cw))
    for k in ab:
        if args.limit:
            ab[k] = ab[k][: args.limit]
    print(f"A 类 {len(ab['A-真题缺答案'])} 条 / B 类 {len(ab['B-习题缺答案'])} 条待探测\n")

    corpus = build_corpus(con)

    stat = Counter()
    detail = []
    samples = defaultdict(list)

    for cls in ("A-真题缺答案", "B-习题缺答案"):
        for i, (r, comp, cw) in enumerate(ab[cls], 1):
            c = r["content"] or ""
            p1 = extract_answer_after(c)
            if p1["ok"]:
                stat[f"{cls}|S1题干内"] += 1
                detail.append({**r, "hit": "S1题干内", "answer": p1["answer"]})
                if len(samples[f"{cls}|S1"]) < 6:
                    samples[f"{cls}|S1"].append((r, "（题干内切分）", p1["answer"]))
                continue
            label, ans = cross_search(norm(c), corpus, args.narrow, args.max_docs)
            if ans and ans != "全库未命中":
                stat[f"{cls}|跨文档命中"] += 1
                detail.append({**r, "hit": label, "answer": ans})
                if len(samples[f"{cls}|跨文档"]) < 8:
                    samples[f"{cls}|跨文档"].append((r, label, ans))
            else:
                stat[f"{cls}|未找到"] += 1
            if i % 50 == 0:
                print(f"  [{cls}] 已探测 {i}/{len(ab[cls])} …")

    print("\n" + "=" * 76)
    print("跨文档对齐结果")
    print("=" * 76)
    for k, v in sorted(stat.items()):
        print(f"  {k}: {v}")

    total_hit = sum(v for k, v in stat.items() if "未找到" not in k)
    print(f"\n  合计可自动对齐补答案: {total_hit} / "
          f"{len(ab['A-真题缺答案']) + len(ab['B-习题缺答案'])}")

    print("\n命中来源分布:")
    src_stat = Counter(d["hit"] for d in detail)
    for k, v in src_stat.most_common(20):
        print(f"  {k}: {v}")

    print("\n抽样（题干 / 来源 / 切出的答案）:")
    for key, arr in samples.items():
        if not arr:
            continue
        print(f"\n=== {key} ===")
        for r, lab, ans in arr[:6]:
            print(f"\n[id={r['id']}] {r['subject']}/{r['question_type']} src={r['source']}")
            print(f"  命中: {lab}")
            print(f"  题干: {(r['content'] or '').replace(chr(10),' ')[:140]}")
            print(f"  ▶答案: {ans[:200]}")

    if args.json_out:
        out = os.path.join(BASE_DIR, args.json_out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"stat": dict(stat), "src_stat": dict(src_stat),
                       "detail": [{k: (str(v)[:600] if isinstance(v, str) else v)
                                   for k, v in d.items()} for d in detail]},
                      f, ensure_ascii=False, indent=2)
        print(f"\n[JSON] {out}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
