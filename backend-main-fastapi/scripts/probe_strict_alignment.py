# -*- coding: utf-8 -*-
"""P2-严格：来源文档「就近答案」对齐可行性探测（只读）。

问题：probe_answer_recoverability.py 的 P2 用了 1600 字窗口，会把「后面几道题的答案」
误当作本题答案（串题）。本脚本改为**就近对齐**：
    题干在文档中的结束位置 → 向后仅看 NARROW 字（默认 300）→
    必须出现【答案】/答案:/解: 等信号，且答案段在遇到下一个题号/下一个答案信号前终止。

三种命中形态（可靠性递减）：
  strict-ok  题干后 ≤300 字内有独立答案段，且答案段长度合理（4~200 字）→ 可直接抽取
  placeholder 命中的是「查看答案」「略」「扫码」等占位符 → 不可抽取
  none       就近无答案信号 → 该文档本身就没答案（如纯题干真题卷）

同时统计：文档内答案覆盖率（按 source 分组），指出哪些来源文档是"有答案文档"、
哪些是"无答案文档"（如「0-（无答案版）25管综真题.pdf」名字里就写明了）。

用法：
    python scripts/probe_strict_alignment.py --narrow 300
只读。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

LAYER_DEF = [
    ("L1-真题", re.compile(r"真题|试卷|联考|真题解析")),
    ("L2-习题题库", re.compile(r"习题|试题库|题库|练习|复习题|配套题")),
    ("L3-讲义正文", re.compile(r"课件|讲义|教案|笔记|总结|精讲|考点|教材|全章节")),
]

# 就近答案信号（要求前面有分隔符，避免命中题干中间）
NEAR_ANS = re.compile(
    r"(?:【答案】|【参考答案】|\[答案\]|答案\s*[:：]|解\s*[:：]|答\s*[:：]|"
    r"故\s*选\s*[A-DＡ-Ｄ]|所以答案|因此答案|答案为)")
# 占位符：命中说明答案不可抽取
PLACEHOLDER = re.compile(r"查看答案|见解析|扫码|略$|答案略|（略）")
# 下一题/下一答案的边界：题号 + 换行/句号
NEXT_Q = re.compile(r"(?:^|\n)\s*\d{1,3}\s*[．.、]\s*|查看答案|下一题")
TAIL_NOISE = re.compile(
    r"(第\d+页\s*---|\(OCR\)|微信公众号|公众号|免费分享|考研资料|视频课程|"
    r"qq\d{6,}|东坡哥|水木观畴|研池大叔|笃学考研|名师精品课程|电话：|客服)")


def layer_of(source: str) -> str:
    s = source or ""
    for name, pat in LAYER_DEF:
        if pat.search(s):
            return name
    return "L4-未归类"


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def probe(qnorm: str, body: str, narrow: int) -> dict:
    """在归一化正文中定位题干并做就近答案探测。"""
    if len(qnorm) < 8 or not body:
        return {"hit": False, "why": "题干过短/正文缺失"}
    idx = -1
    hit_len = 0
    for L in (24, 18, 14, 10, 8):
        if len(qnorm) < L:
            continue
        idx = body.find(qnorm[:L])
        if idx >= 0:
            hit_len = L
            break
    if idx < 0:
        return {"hit": False, "why": "题干未在文档中定位"}
    end = idx + max(hit_len, len(qnorm))
    window = body[end: end + narrow]
    m = NEAR_ANS.search(window)
    if not m:
        return {"hit": False, "why": "就近无答案信号", "window": window[:120]}
    seg = window[m.end():]
    b = NEXT_Q.search(seg)
    if b and b.start() > 0:
        seg = seg[: b.start()]
    nm = TAIL_NOISE.search(seg)
    if nm and nm.start() > 0:
        seg = seg[: nm.start()]
    seg = seg.strip()
    if PLACEHOLDER.match(seg) or PLACEHOLDER.search(seg[:12]):
        return {"hit": True, "why": "占位符(查看答案等)", "answer": seg[:80]}
    if len(seg) < 4:
        return {"hit": True, "why": "答案段过短", "answer": seg[:80]}
    if len(seg) > 300:
        seg = seg[:300]
    return {"hit": True, "why": "strict-ok", "answer": seg[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--narrow", type=int, default=300, help="就近答案搜索窗口（字）")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=300)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=300000")

    rows = con.execute(
        "SELECT id, content, source, question_type, subject, chapter, options "
        "FROM quiz_questions "
        "WHERE (answer IS NULL OR trim(answer)='') AND coalesce(is_junk,0)=0"
    ).fetchall()
    print(f"目标: {len(rows)} 条\n")

    # 题干内已有答案的先排除（这部分走零成本切分）
    import probe_answer_recoverability as P1
    rows = [r for r in rows if not P1.split_inline_answer(r["content"])["ok"]]
    print(f"排除题干内已含答案后，剩 {len(rows)} 条待外部对齐\n")

    docs = con.execute(
        "SELECT id, file_name, content FROM documents "
        "WHERE content IS NOT NULL AND length(content)>800").fetchall()
    idx = defaultdict(list)
    norm_cache = {}
    for d in docs:
        base = re.sub(r"\.(txt|pdf|docx?)$", "", d["file_name"], flags=re.I)[:14]
        idx[base].append(d)
        norm_cache[d["id"]] = norm(d["content"])
    print(f"候选文档: {len(docs)}\n")

    groups = defaultdict(list)
    for r in rows:
        groups[r["source"]].append(r)

    stat = Counter()
    by_layer = defaultdict(Counter)
    by_src = defaultdict(Counter)
    strict_samples = defaultdict(list)
    doc_has_answer = {}   # source -> 该文档是否存在任何答案信号（文档级画像）

    for src, items in groups.items():
        fname = re.sub(r"^(知识库|真题):", "", src or "")
        stem = re.sub(r"\.(txt|pdf|docx?)$", "", fname, flags=re.I)[:14]
        cands = idx.get(stem, [])
        if not cands:
            for k, v in idx.items():
                if stem and (stem[:8] in k or k[:8] in stem):
                    cands = v
                    break
        body = norm_cache[cands[0]["id"]] if cands else ""
        doc_has_answer[src] = bool(body and NEAR_ANS.search(body))

        for r in items:
            lay = layer_of(src)
            res = probe(norm(r["content"]), body, args.narrow)
            key = res["why"]
            stat[key] += 1
            by_layer[lay][key] += 1
            by_src[src][key] += 1
            if res["why"] == "strict-ok" and len(strict_samples[lay]) < 8:
                strict_samples[lay].append((dict(r), cands[0]["file_name"] if cands else "", res["answer"]))

    print("=" * 76)
    print("一、就近对齐结果（P2-strict）")
    print("=" * 76)
    for k, v in stat.most_common():
        print(f"  {k}: {v}  ({v*100//max(1,len(rows))}%)")

    print("\n按层:")
    for lay in ["L1-真题", "L2-习题题库", "L3-讲义正文", "L4-未归类"]:
        c = by_layer.get(lay)
        if not c:
            continue
        tot = sum(c.values())
        ok = c["strict-ok"]
        print(f"  {lay:<12} 总 {tot:>5}  可抽取 {ok:>4} ({ok*100//max(1,tot)}%)  "
              f"占位符 {c['占位符(查看答案等)']:>4}  其他 {tot-ok-c['占位符(查看答案等)']:>4}")

    print("\n按来源文档（题数≥10，按 strict-ok 占比排序，TOP20）:")
    for src, c in sorted(by_src.items(), key=lambda kv: -sum(kv[1].values()))[:20]:
        tot = sum(c.values())
        ok = c["strict-ok"]
        ph = c["占位符(查看答案等)"]
        print(f"  {tot:>4}题 ok={ok:<4} 占位={ph:<4} 文档有答案信号={doc_has_answer.get(src)}  {src}")

    print("\n严格可抽取抽样（每层 6 条）:")
    for lay, items in strict_samples.items():
        print(f"\n=== {lay} ===")
        for r, doc, ans in items[:6]:
            print(f"\n[id={r['id']}] src={r['source']}")
            print(f"  对齐文档: {doc}")
            print(f"  题干     : {(r['content'] or '')[:130]}")
            print(f"  ▶答案    : {ans}")

    strict = stat["strict-ok"]
    print("\n" + "=" * 76)
    print("二、汇总（不含题干内已含答案的 163 条）")
    print("=" * 76)
    print(f"  待外部对齐总数            : {len(rows)}")
    print(f"  strict-ok 可抽取          : {strict}")
    print(f"  占位符（查看答案，抽取无意义）: {stat['占位符(查看答案等)']}")
    print(f"  不可抽取                 : {len(rows) - strict - stat['占位符(查看答案等)']}")

    if args.json_out:
        out = os.path.join(BASE_DIR, args.json_out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({
                "narrow": args.narrow, "total": len(rows),
                "stat": dict(stat),
                "by_layer": {k: dict(v) for k, v in by_layer.items()},
                "by_source": {k: dict(v) for k, v in by_src.items()},
                "doc_has_answer": doc_has_answer,
                "strict_samples": {k: v[:8] for k, v in strict_samples.items()},
            }, f, ensure_ascii=False, indent=2)
        print(f"\n[JSON] {out}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
