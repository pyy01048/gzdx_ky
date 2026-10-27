# -*- coding: utf-8 -*-
"""无答案题（C 级）分层画像 + 补答案可行性诊断（只读，2026-10）。

背景：quiz_questions 共 9164 题，其中 2123 条 quality='C'（无答案、可浏览不可刷），
前端 Quiz 列表新增 answerable=True 默认过滤后这批题对用户"隐身"。
本脚本回答三个问题：
  1. 这 2123 条分层画像：真题？习题？讲义正文误入？OCR 残缺？
  2. 每层抽样打印真实题干原文（人工核验用）
  3. 答案是否已存在于 knowledge_base（documents.content / knowledge_chunks）
     —— 若是，则属"抽取对齐"问题（高可靠），否则只能靠模型生成（需复核）

判定复用 scripts/quiz_quality_gate.py 的 classify()，不重写门禁逻辑。

用法：
    python scripts/diagnose_no_answer_questions.py            # 全量报告 + 每层抽样
    python scripts/diagnose_no_answer_questions.py --sample 20
    python scripts/diagnose_no_answer_questions.py --align-only 200   # 抽样做知识库对齐探测
    python scripts/diagnose_no_answer_questions.py --json-out data/diagnostics/no_answer_profile.json
只读：不写 quiz_questions，不删任何数据。
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

# 复用 quiz_quality_gate 的门禁判定（scripts 目录无 __init__.py，按文件路径加载）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quiz_quality_gate import classify  # noqa: E402

# ---------------------------------------------------------------- 层定义
# L1 真题：有 paper 或 source 含「真题/试题/试卷/联考/真题解析」
# L2 习题/题库：source 含「习题解答/试题库/题库/练习/习题/复习题」
# L3 讲义正文：source 含「课件/讲义/教案/笔记/总结/精讲/考点/教材」
# L4 其他（无法归类）
LAYER_DEF = [
    ("L1-真题", re.compile(r"真题|试卷|联考|真题解析")),
    ("L2-习题题库", re.compile(r"习题|试题库|题库|练习|习题解答|复习题|配套题")),
    ("L3-讲义正文", re.compile(r"课件|讲义|教案|笔记|总结|精讲|考点|教材|全章节")),
]

# 题干残缺信号：引用了图/表但正文无图；含"如图"且无图注
RE_FIG_REF = re.compile(r"如图|见图|下图|上图|图\s*\d|图中|电路图|波形图|框图")
RE_MOJIBAKE = re.compile(r"[�□]")
RE_OCR_JUNK = re.compile(r"[\(\（][\s\)\）]{1,}|_____{3,}")


def layer_of(source: str, paper: str) -> str:
    s = f"{source or ''} {paper or ''}"
    for name, pat in LAYER_DEF:
        if pat.search(s):
            return name
    return "L4-未归类"


def completeness(content: str, options) -> tuple:
    """返回 (完整度标签, 原因)。完整度分三档：完整 / 图缺 / 残缺。"""
    c = (content or "").strip()
    if RE_MOJIBAKE.search(c):
        return "残缺", "含乱码字符"
    if RE_OCR_JUNK.search(c) and len(c) < 40:
        return "残缺", "OCR碎片（括号/下划线噪声）"
    if RE_FIG_REF.search(c):
        # 引用了图但正文没有任何可渲染图片信息
        if not re.search(r"!\[|\.(png|jpg|jpeg|gif)\b|图片[:：]", c, re.I):
            return "图缺", "引用图示但无图（不可作答）"
    if len(c) < 25:
        return "残缺", f"题干过短({len(c)}字)"
    return "完整", ""


def align_probe(content: str, doc_candidates: list) -> dict:
    """在来源文档正文里探测答案是否已存在（抽取对齐可行性）。

    做法：取题干首个 12 字特征串在候选文档 content 中定位，
    命中则看其后 400 字窗口内是否出现答案信号词（答案/故选/解:/参考答案）。
    """
    key = re.sub(r"\s+", "", (content or ""))[:12]
    if len(key) < 8:
        return {"hit": False, "reason": "题干太短无法定位"}
    for name, body in doc_candidates:
        if not body:
            continue
        idx = body.find(key)
        if idx < 0:
            # 退化：取前 8 字
            key2 = key[:8]
            idx = body.find(key2)
            if idx < 0:
                continue
            key = key2
        window = body[idx: idx + 900]
        ans_sig = re.search(r"(参考答案|答案[:：]|【答案】|故\s*选|解[:：])", window)
        return {
            "hit": True,
            "doc": name,
            "offset": idx,
            "answer_signal": bool(ans_sig),
            "window": window[:500],
        }
    return {"hit": False, "reason": "来源文档中未定位到该题干"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=10, help="每层抽样条数")
    ap.add_argument("--align-only", type=int, default=0,
                    help="对前 N 条 C 类题做知识库对齐探测（较慢，读 documents.content）")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=120000")

    rows = con.execute(
        "SELECT id, content, options, answer, analysis, subject, chapter, "
        "       knowledge_point, source, paper, question_no, question_type, "
        "       year, created_at, ai_generated, is_junk, quality, external_id "
        "FROM quiz_questions "
        "WHERE (answer IS NULL OR trim(answer)='') AND coalesce(is_junk,0)=0"
    ).fetchall()
    print(f"无答案且未隔离的题数: {len(rows)}\n")

    # ---------------- 分层画像 ----------------
    profile = defaultdict(Counter)      # layer -> counter
    buckets = defaultdict(list)         # (layer, completeness) -> rows
    layer_tot = Counter()
    layer_reason = Counter()
    for r in rows:
        g, why = classify((r["id"], r["content"], r["answer"], r["source"],
                           r["question_type"], r["options"]))
        if g != "C":  # 门禁重判后不是 C 的（历史漂移）
            profile["__gate_" + g][why] += 1
            continue
        lay = layer_of(r["source"], r["paper"])
        comp, creason = completeness(r["content"], r["options"])
        layer_tot[lay] += 1
        profile[lay][f"{comp}|{creason}"] += 1
        buckets[(lay, comp)].append(dict(r))
        layer_reason[(lay, comp, creason)] += 1

    print("=" * 78)
    print("一、分层画像（层 × 完整度）")
    print("=" * 78)
    hdr = f"{'层':<14}{'完整':>8}{'图缺':>8}{'残缺':>8}{'小计':>8}"
    print(hdr)
    tot = Counter()
    for lay in ["L1-真题", "L2-习题题库", "L3-讲义正文", "L4-未归类"]:
        b = {k[1]: len(v) for k, v in buckets.items() if k[0] == lay}
        cs = Counter()
        for k, v in buckets.items():
            if k[0] == lay:
                cs[k[1]] += len(v)
        print(f"{lay:<14}{cs.get('完整',0):>8}{cs.get('图缺',0):>8}{cs.get('残缺',0):>8}{layer_tot.get(lay,0):>8}")
        tot.update(cs)
    print(f"{'合计':<14}{tot.get('完整',0):>8}{tot.get('图缺',0):>8}{tot.get('残缺',0):>8}{sum(layer_tot.values()):>8}")
    gate_drift = {k: dict(v) for k, v in profile.items() if k.startswith("__gate_")}
    if gate_drift:
        print(f"\n[门禁重判漂移] {gate_drift}")

    print("\n" + "=" * 78)
    print("二、完整度原因明细 TOP20")
    print("=" * 78)
    for (lay, comp, rs), n in layer_reason.most_common(20):
        print(f"  {lay:<12}{comp:<5}{rs:<20}{n:>6}")

    print("\n" + "=" * 78)
    print("三、各层科目/题型分布（判断是否学科错配）")
    print("=" * 78)
    for lay in ["L1-真题", "L2-习题题库", "L3-讲义正文", "L4-未归类"]:
        items = [r for k, v in buckets.items() if k[0] == lay for r in v]
        if not items:
            continue
        subj = Counter(r["subject"] for r in items).most_common(5)
        qt = Counter(r["question_type"] for r in items).most_common(6)
        print(f"\n{lay} ({len(items)}):")
        print(f"   科目: {subj}")
        print(f"   题型: {qt}")

    # ---------------- 抽样真实题干 ----------------
    print("\n" + "=" * 78)
    print(f"四、抽样题干原文（每层每完整度 {args.sample} 条）")
    print("=" * 78)
    samples = {}
    for (lay, comp), items in sorted(buckets.items()):
        print(f"\n---------- [{lay} / {comp}] 共 {len(items)} 条，抽样 {args.sample} 条 ----------")
        # 多样化抽样：按 source 分散取，避免同一文档刷屏
        by_src = defaultdict(list)
        for r in items:
            by_src[r["source"]].append(r)
        picked = []
        i = 0
        while len(picked) < args.sample:
            added = False
            for src in sorted(by_src):
                lst = by_src[src]
                if i < len(lst):
                    picked.append(lst[i])
                    added = True
                    if len(picked) >= args.sample:
                        break
            if not added:
                break
            i += 1
        samples[f"{lay}|{comp}"] = [
            {k: r[k] for k in ("id", "source", "subject", "chapter", "question_type",
                               "question_no", "content")}
            for r in picked
        ]
        for r in picked:
            c = (r["content"] or "").replace("\n", " ⏎ ")
            print(f"\n[id={r['id']}] type={r['question_type']} subj={r['subject']} "
                  f"chapter={r['chapter']}")
            print(f"  source: {r['source']}")
            print(f"  题干({len(r['content'] or '')}字): {c[:400]}")

    # ---------------- 知识库对齐探测 ----------------
    align_stat = Counter()
    align_detail = []
    if args.align_only > 0:
        print("\n" + "=" * 78)
        print(f"五、知识库答案对齐探测（抽 {args.align_only} 条）")
        print("=" * 78)
        # 预载 documents 正文（懒加载：按 source 关键词匹配 file_name）
        docs = con.execute(
            "SELECT id, file_name, content FROM documents WHERE content IS NOT NULL AND length(content)>500"
        ).fetchall()
        print(f"可用文档（正文>500字）: {len(docs)}")

        targets = []
        for (lay, comp), items in sorted(buckets.items()):
            step = max(1, len(items) // max(1, args.align_only // 8))
            targets += [(lay, comp, r) for r in items[::step]][: args.align_only]
        for lay, comp, r in targets:
            fname = re.sub(r"^知识库:", "", r["source"] or "")
            fname = re.sub(r"^真题:", "", fname)
            stem = re.sub(r"\.(txt|pdf|docx?)$", "", fname, flags=re.I)
            cands = []
            for d in docs:
                base = re.sub(r"\.(txt|pdf|docx?)$", "", d["file_name"], flags=re.I)
                if stem and (stem[:12] in base or base[:12] in stem):
                    cands.append((d["file_name"], d["content"]))
            res = align_probe(r["content"], cands)
            key = f"{lay}|{'答案同窗' if res.get('answer_signal') else '仅题干命中' if res.get('hit') else '文档未命中'}"
            align_stat[key] += 1
            if len(align_detail) < 40:
                align_detail.append({
                    "id": r["id"], "layer": lay, "completeness": comp,
                    "source": r["source"], "doc_matched": len(cands),
                    "probe": {k: v for k, v in res.items() if k != "window"},
                    "window_head": (res.get("window") or "")[:260],
                })
        print("\n对齐探测汇总:")
        for k, n in align_stat.most_common():
            print(f"  {k}: {n}")
        print("\n明细样本（前 40 条）:")
        for d in align_detail:
            print(f"\n[id={d['id']}] {d['layer']}/{d['completeness']} docs={d['doc_matched']} "
                  f"probe={d['probe']}")
            if d["window_head"]:
                print(f"   窗口: {d['window_head']}")

    # ---------------- 汇总建议 ----------------
    print("\n" + "=" * 78)
    print("六、可补答案候选量估算")
    print("=" * 78)
    fillable = sum(len(v) for (l, c), v in buckets.items()
                   if c == "完整" and l in ("L1-真题", "L2-习题题库"))
    clearn = sum(len(v) for (l, c), v in buckets.items() if c != "完整")
    lecture = sum(len(v) for (l, c), v in buckets.items() if l == "L3-讲义正文" and c == "完整")
    print(f"  高可靠可补（真题/习题 + 题干完整）: {fillable}")
    print(f"  需人工复核或改写（讲义正文 + 完整）  : {lecture}")
    print(f"  建议清理（残缺/图缺，不可作答）    : {clearn}")

    if args.json_out:
        out = os.path.join(BASE_DIR, args.json_out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({
                "total_no_answer_visible": len(rows),
                "layer_totals": dict(layer_tot),
                "completeness": dict(tot),
                "reasons": {f"{a}|{b}|{c}": n for (a, b, c), n in layer_reason.items()},
                "fillable": fillable, "needs_review": lecture, "cleanup": clearn,
                "align_stat": dict(align_stat),
                "align_detail": align_detail,
                "samples": samples,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n[JSON 已写出] {out}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
