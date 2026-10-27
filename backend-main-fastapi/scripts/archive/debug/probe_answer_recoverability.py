# -*- coding: utf-8 -*-
"""答案可抽取性探测（只读）：2123 条无答案题里，答案是否已经"躺在题干里"或"躺在知识库正文里"。

背景：分层画像显示大量 C 级题的 content 实际是「题干 + 解析/解答」的整段文本
（抽取器把题目和配套解析一起切进 content，没写进 answer 字段）。
这类题**不需要 LLM 生成**，只需按答案信号正则切分即可，属于高可靠的"抽取对齐"问题。

本脚本三路探测（互不排斥）：
  P1 题干内答案：content 中出现「解:」「答案:」「答:」等信号，且信号后有实质内容
  P2 同文档答案：题干特征串能在 documents.content 定位，其后窗口内出现答案信号
  P3 完全无解：以上皆无 —— 只能靠模型生成或人工出题

同时输出可执行的抽取规则命中率（模拟切分，不写库）。

用法：
    python scripts/probe_answer_recoverability.py --sample 8
    python scripts/probe_answer_recoverability.py --json-out data/diagnostics/answer_recoverability.json
只读：不修改 quiz_questions / documents。
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quiz_quality_gate import classify  # noqa: E402

LAYER_DEF = [
    ("L1-真题", re.compile(r"真题|试卷|联考|真题解析")),
    ("L2-习题题库", re.compile(r"习题|试题库|题库|练习|复习题|配套题")),
    ("L3-讲义正文", re.compile(r"课件|讲义|教案|笔记|总结|精讲|考点|教材|全章节")),
]

# ---- P1 题干内答案信号（按优先级） ----
# 说明：分「强信号」（明确答案段）与「弱信号」（含"解"字的推导）
ANS_STRONG = re.compile(
    r"(?:^|\n|。|；|\s)(?:【答案】|【解】|参考答案|答案\s*[:：]|解\s*[:：]|答\s*[:：]|"
    r"故\s*选|所以答案|因此答案|答案为)")
ANS_WEAK = re.compile(r"(?:^|\n)\s*(?:解|答)\s*[:：]")

# 题干尾部噪声（页眉页脚/公众号广告），出现即认为答案段已结束
TAIL_NOISE = re.compile(
    r"(第\d+页\s*---|\(OCR\)|微信公众号|公众号|免费分享|考研资料|视频课程|"
    r"QQ|qq\d{6,}|加QQ|东坡哥|水木观畴|研池大叔|笃学考研|名师精品课程|"
    r"kaoshidian|电话：|客服)")

MIN_ANS_LEN = 4


def layer_of(source: str, paper: str) -> str:
    s = f"{source or ''} {paper or ''}"
    for name, pat in LAYER_DEF:
        if pat.search(s):
            return name
    return "L4-未归类"


def split_inline_answer(content: str) -> dict:
    """尝试从题干里切出答案段。返回 {ok, answer_preview, tail_preview, cut_at}。"""
    c = content or ""
    best = None
    for m in ANS_STRONG.finditer(c):
        start = m.end()
        seg = c[start: start + 800]
        # 命中尾部噪声则截断
        nm = TAIL_NOISE.search(seg)
        if nm and nm.start() > 0:
            seg = seg[: nm.start()]
        seg = seg.strip()
        if len(seg) >= MIN_ANS_LEN:
            best = (m.start(), seg)
            break
    if best is None:
        m = ANS_WEAK.search(c)
        if m:
            seg = c[m.end(): m.end() + 800]
            nm = TAIL_NOISE.search(seg)
            if nm and nm.start() > 0:
                seg = seg[: nm.start()]
            seg = seg.strip()
            if len(seg) >= MIN_ANS_LEN * 2:
                best = (m.start(), seg)
    if best is None:
        return {"ok": False}
    cut, seg = best
    return {
        "ok": True,
        "cut_at": cut,
        "answer_preview": seg[:180],
        "stem_preview": c[:cut].strip()[-120:],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=8, help="每种结果抽样条数")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--no-kb", action="store_true", help="跳过 P2 知识库探测（更快）")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=180)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=180000")

    rows = con.execute(
        "SELECT id, content, options, answer, source, paper, question_type, subject, chapter "
        "FROM quiz_questions "
        "WHERE (answer IS NULL OR trim(answer)='') AND coalesce(is_junk,0)=0"
    ).fetchall()
    print(f"目标: {len(rows)} 条无答案且未隔离的题\n")

    # ---------- P1 题干内答案 ----------
    stat = Counter()
    by_layer = defaultdict(Counter)
    p1_items = []
    for r in rows:
        lay = layer_of(r["source"], r["paper"])
        res = split_inline_answer(r["content"])
        if res["ok"]:
            stat["P1-题干内含答案"] += 1
            by_layer[lay]["P1"] += 1
            p1_items.append((lay, dict(r), res))
        else:
            stat["P2/P3-需外部来源"] += 1
            by_layer[lay]["待查"] += 1

    print("=" * 76)
    print("一、P1 题干内答案可抽取性")
    print("=" * 76)
    for k, v in stat.most_common():
        print(f"  {k}: {v}  ({v*100//max(1,len(rows))}%)")
    print("\n按层分布:")
    for lay in ["L1-真题", "L2-习题题库", "L3-讲义正文", "L4-未归类"]:
        c = by_layer[lay]
        tot = c["P1"] + c["待查"]
        if tot:
            print(f"  {lay:<12} 总 {tot:>5}  题干内含答案 {c['P1']:>5}  需外部来源 {c['待查']:>5}")

    print(f"\n---------- P1 抽样题干（每层 {args.sample} 条，含切分预览）----------")
    bylay = defaultdict(list)
    for lay, r, res in p1_items:
        bylay[lay].append((r, res))
    for lay, items in bylay.items():
        print(f"\n=== {lay} （可抽 {len(items)} 条，抽样 {args.sample}）===")
        # 按 source 分散抽样
        seen_src = Counter()
        picked = []
        for r, res in items:
            if seen_src[r["source"]] >= 2:
                continue
            seen_src[r["source"]] += 1
            picked.append((r, res))
            if len(picked) >= args.sample:
                break
        for r, res in picked:
            print(f"\n[id={r['id']}] type={r['question_type']} src={r['source']}")
            print(f"  题干尾部 : ...{res['stem_preview']}")
            print(f"  ▶可抽答案: {res['answer_preview']}")

    # ---------- P2 知识库对齐（仅对 P1 未命中的） ----------
    p2_stat = Counter()
    p2_items = []
    if not args.no_kb:
        print("\n" + "=" * 76)
        print("二、P2 来源文档正文对齐探测（仅 P1 未命中的题）")
        print("=" * 76)
        docs = con.execute(
            "SELECT id, file_name, content FROM documents "
            "WHERE content IS NOT NULL AND length(content)>800"
        ).fetchall()
        print(f"候选文档（正文>800字）: {len(docs)}")
        # source 前缀 -> 候选文档索引
        index = defaultdict(list)
        for d in docs:
            base = re.sub(r"\.(txt|pdf|docx?)$", "", d["file_name"], flags=re.I)
            index[base[:14]].append(d)

        pending = [r for r in rows if not split_inline_answer(r["content"])["ok"]]
        # 按 source 分组探测（同文档只读一次正文）
        groups = defaultdict(list)
        for r in pending:
            groups[r["source"]].append(r)

        # 归一化正文（去所有空白）——题干与文档 OCR 空格差异极大，必须归一化后再匹配
        norm_cache = {}

        def norm(s: str) -> str:
            return re.sub(r"\s+", "", s or "")

        for src, items in groups.items():
            fname = re.sub(r"^(知识库|真题):", "", src or "")
            stem = re.sub(r"\.(txt|pdf|docx?)$", "", fname, flags=re.I)[:14]
            cands = index.get(stem, [])
            if not cands:
                for k, v in index.items():
                    if stem and (stem[:8] in k or k[:8] in stem):
                        cands = v
                        break
            if cands:
                dn = cands[0]["id"]
                if dn not in norm_cache:
                    norm_cache[dn] = norm(cands[0]["content"])
                body = norm_cache[dn]
                doc_name = cands[0]["file_name"]
            else:
                body, doc_name = "", ""
            for r in items:
                q = norm(r["content"])
                if not body or len(q) < 8:
                    p2_stat["P3-来源文档缺失或题干过短"] += 1
                    continue
                idx = -1
                hit_len = 0
                # 逐级降级：题干前 24/18/14/10/8 字任一命中即可定位
                for L in (24, 18, 14, 10, 8):
                    if len(q) < L:
                        continue
                    idx = body.find(q[:L])
                    if idx >= 0:
                        hit_len = L
                        break
                if idx < 0:
                    p2_stat["P3-知识库未定位"] += 1
                    continue
                window = body[idx: idx + 1600]
                tail = window[hit_len:]
                m = ANS_STRONG.search(tail) or ANS_WEAK.search(tail)
                if m:
                    seg = tail[m.end():]
                    nm = TAIL_NOISE.search(seg)
                    if nm and nm.start() > 0:
                        seg = seg[: nm.start()]
                    if len(seg.strip()) >= MIN_ANS_LEN:
                        p2_stat["P2-知识库同窗含答案"] += 1
                        p2_items.append((layer_of(r["source"], r["paper"]), dict(r),
                                         doc_name, seg.strip()[:180]))
                        continue
                    p2_stat["P3-知识库窗口无实质答案"] += 1
                else:
                    p2_stat["P3-知识库窗口无答案信号"] += 1
        print("\nP2 探测汇总:")
        for k, v in p2_stat.most_common():
            print(f"  {k}: {v}")
        byl = defaultdict(list)
        for lay, r, doc, seg in p2_items:
            byl[lay].append((r, doc, seg))
        for lay, items in byl.items():
            print(f"\n=== {lay} / P2 知识库对齐抽样（{len(items)} 条，抽样 {args.sample}）===")
            for r, doc, seg in items[: args.sample]:
                print(f"\n[id={r['id']}] src={r['source']}")
                print(f"  对齐文档: {doc}")
                print(f"  题干     : {(r['content'] or '')[:150]}")
                print(f"  ▶窗口答案: {seg}")

    # ---------- 汇总方案量 ----------
    print("\n" + "=" * 76)
    print("三、处置方案量估算")
    print("=" * 76)
    p1 = stat["P1-题干内含答案"]
    p2 = p2_stat.get("P2-知识库同窗含答案", 0)
    p3 = len(rows) - p1 - p2
    print(f"  方案A 零成本抽取（题干内已有答案，直接切分）    : {p1}")
    print(f"  方案B 高可靠对齐（来源文档同窗含答案，需定位）  : {p2}")
    print(f"  方案C 需人工/模型出题（两路都查不到）          : {p3}")

    if args.json_out:
        out = os.path.join(BASE_DIR, args.json_out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({
                "total": len(rows),
                "p1_inline_answer": p1,
                "p2_kb_alignment": p2,
                "p3_needs_authoring": p3,
                "p2_stat": dict(p2_stat),
                "by_layer": {k: dict(v) for k, v in by_layer.items()},
                "p1_samples": [
                    {"id": r["id"], "layer": lay, "source": r["source"],
                     "stem_tail": res["stem_preview"], "answer": res["answer_preview"]}
                    for lay, r, res in p1_items[:200]
                ],
                "p2_samples": [
                    {"id": r["id"], "layer": lay, "source": r["source"], "doc": doc,
                     "answer": seg}
                    for lay, r, doc, seg in p2_items[:200]
                ],
            }, f, ensure_ascii=False, indent=2)
        print(f"\n[JSON] {out}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
