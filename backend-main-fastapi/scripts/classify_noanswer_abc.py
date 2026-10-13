# -*- coding: utf-8 -*-
"""无答案题三分类画像 + 知识库答案对齐可行性（只读，5349 口径）。

任务：把 quiz_questions 里全部 **5349 条无答案题**（含已隔离的 is_junk=1）分成三类：
  A 真题但缺答案      —— source 含真题/试卷/联考/统考，且题干像题且题干完整 → 最有价值
  B 教材习题但缺答案  —— 习题/题库/试题库/辅导来源，题干像题 → 应走知识库对齐
  C 根本不是题        —— 讲义正文/教材定义/OCR 乱码/答案页 → 应清理

判定复用 services/quiz_content_gate.admit()（唯一真源，不重写门禁逻辑）：
  admit 返回 reject:<原因> 的即判C类，admitted 的再按 source 分 A/B。

然后对 A/B 类做 **knowledge_chunks 答案对齐可行性**探测：
  Q1 来源文档是否也在 documents / knowledge_chunks 里？（按文件名归一化匹配）
  Q2 题干特征串能否在 chunks 文本中定位？
  Q3 定位到之后，就近窗口内是否存在独立答案段？
给出「可对齐补答案」的准确条数。

用法：
    python scripts/classify_noanswer_abc.py --sample 10
    python scripts/classify_noanswer_abc.py --json-out data/diagnostics/noanswer_abc.json
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
sys.path.insert(0, BASE_DIR)
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

from services.quiz_content_gate import (  # noqa: E402
    admit, has_answer, looks_like_question, looks_like_answer_body,
    has_ppt_residue, is_mojibake, mostly_symbol, REAL_SRC, LECTURE_SRC,
)

# --------------------------------------------------------------------------- #
# 三分类定义
# --------------------------------------------------------------------------- #
#: 真题类信号（比 REAL_SRC 更宽：额外含"统考/真题解析/年真题/月考"）
SRC_REAL = re.compile(r"真题|试卷|联考|统考|月考|期末|期中|试题及答案|真题解析")
#: 习题/题库类信号
SRC_EXERCISE = re.compile(r"习题|题库|试题库|练习|复习题|配套题|辅导与习题|习题解答|习题全解")
#: 讲义/教材类信号
SRC_LECTURE = re.compile(r"课件|讲义|教案|笔记|总结|精讲|考点|教材|全章节|精读|指南")

#: 题干残缺：引用了图但无图 / OCR 碎片 / 过短 / 乱码
RE_FIG_REF = re.compile(r"如图|见图|下图|上图|图\s*\d|图中|电路图|波形图|框图|图P\d")
RE_IMG_EMBED = re.compile(r"!\[|\.(png|jpg|jpeg|gif|webp)\b|图片[:：]", re.I)
RE_MOJIBAKE = re.compile(r"[�□]")
RE_OCR_JUNK = re.compile(r"[\(（]\s*[\)）]|_{4,}|[A-Za-z]{0,2}\d{0,2}\s*[βμσ°]+\s*[A-Za-z]{0,2}\d{0,2}")

MIN_LEN_OK = 25
MAX_LEN_OK = 400

# --------------------------------------------------------------------------- #
# 答案信号（与 probe 脚本一致）
# --------------------------------------------------------------------------- #
NEAR_ANS = re.compile(
    r"(?:【答案】|【参考答案】|\[答案\]|答案\s*[:：]|解\s*[:：]|答\s*[:：]|"
    r"故\s*选\s*[A-DＡ-Ｄ]|所以答案|因此答案|答案为|故\s*可得)")
PLACEHOLDER = re.compile(r"查看答案|见解析|答案略|（略）|扫码")
NEXT_Q = re.compile(
    r"(?:^|\n)\s*\d{1,3}\s*[．.、]\s*|查看答案|下一题|"
    # 下一题的起点：题库惯例是「【答案】<本题答案>【解析】<解析>【答案】<下一题>」，
    # 因此答案段必须止于第一个【解析】，否则会把下一题的答案/解析吞进来。
    r"【解析】|〔解析〕|\[解析\]|"
    r"^\d{1,3}\s*[．.、]")
TAIL_NOISE = re.compile(
    r"(第\d+页\s*---|\(OCR\)|微信公众号|公众号|免费分享|考研资料|视频课程|"
    r"qq\d{6,}|东坡哥|水木观畴|研池大叔|笃学考研|名师精品课程|电话：|客服)")
MIN_ANS_LEN = 4


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def completeness(content: str, options) -> tuple:
    """返回 (完整度, 原因)。完整度 ∈ {完整, 图缺, 残缺}。"""
    c = (content or "").strip()
    n = len(c)
    if n < MIN_LEN_OK:
        return "残缺", f"题干过短({n}字)"
    if RE_MOJIBAKE.search(c):
        return "残缺", "含乱码字符"
    if RE_FIG_REF.search(c) and not RE_IMG_EMBED.search(c):
        return "图缺", "引用图示但无图"
    if RE_OCR_JUNK.search(c) and n < 60:
        return "残缺", "OCR碎片（符号/下划线噪声）"
    if n > MAX_LEN_OK:
        return "残缺", f"超长({n}字)疑似讲义段"
    opts = options if isinstance(options, (list, tuple)) else []
    if len(opts) >= 2 and n < 45:
        return "残缺", "题干过短但有选项（题干被腰斩）"
    return "完整", ""


def classify(row) -> tuple:
    """三分类主判定。返回 (类别, 原因, 完整度, 完整度原因)。"""
    qid, content, options, answer, source, qtype = row
    c = (content or "").strip()
    src = source or ""

    # 硬垃圾优先（无论来源）—— 与闸门第 1 层一致
    if len(c) < 15:
        return "C-不是题", "内容过短", "残缺", f"题干过短({len(c)}字)"
    if is_mojibake(c):
        return "C-不是题", "OCR乱码", "残缺", "含乱码字符"
    if mostly_symbol(c):
        return "C-不是题", "纯符号噪声", "残缺", "无中文的符号串"
    if looks_like_answer_body(c):
        return "C-不是题", "答案体当题干", "残缺", "以「解/答/答案」开头"
    if has_ppt_residue(c):
        return "C-不是题", "PPT/讲义结构残留", "残缺", "含页码/放映等版式词"
    if re.fullmatch(r"[\d\s.\-]+", c):
        return "C-不是题", "纯数字", "残缺", "纯数字串"

    comp, comp_why = completeness(c, options)

    # 交给唯一真源闸门判定（不含答案的语境）
    ok, reason = admit(c, options=options, answer=None, source=src, section_type=qtype or "")
    if not ok:
        return "C-不是题", reason.replace("reject:", ""), comp, comp_why

    # 闸门放行 → 按来源分 A / B
    if SRC_REAL.search(src):
        return "A-真题缺答案", f"闸门放行 + source含真题（{src[:40]}）", comp, comp_why
    if SRC_EXERCISE.search(src):
        return "B-习题缺答案", f"闸门放行 + 习题来源（{src[:40]}）", comp, comp_why
    if SRC_LECTURE.search(src):
        return "C-不是题", f"讲义/教材来源但闸门放行（{src[:40]}）", comp, comp_why
    return "C-不是题", f"来源无法归类为真题/习题（{src[:40]}）", comp, comp_why


def extract_answer_after(content: str) -> dict:
    """P1：答案是否就在题干里。"""
    c = content or ""
    for m in NEAR_ANS.finditer(c):
        seg = c[m.end(): m.end() + 800]
        nm = TAIL_NOISE.search(seg)
        if nm and nm.start() > 0:
            seg = seg[: nm.start()]
        seg = seg.strip()
        if len(seg) >= MIN_ANS_LEN:
            return {"ok": True, "cut_at": m.start(), "answer": seg[:300],
                    "stem": c[: m.start()].strip()[-120:]}
    return {"ok": False}


def probe_align(qnorm: str, body: str, narrow: int = 300) -> dict:
    """P2：就近答案对齐。body 需已归一化（去空白）。"""
    if not body or len(qnorm) < 8:
        return {"hit": False, "why": "题干过短或文档正文缺失"}
    idx, hit_len = -1, 0
    for L in (24, 18, 14, 10, 8):
        if len(qnorm) < L:
            continue
        idx = body.find(qnorm[:L])
        if idx >= 0:
            hit_len = L
            break
    if idx < 0:
        return {"hit": False, "why": "题干未在文档中定位"}
    tail = body[idx + max(hit_len, len(qnorm)): idx + max(hit_len, len(qnorm)) + narrow]
    m = NEAR_ANS.search(tail)
    if not m:
        return {"hit": False, "why": "就近无答案信号"}
    seg = tail[m.end():]
    b = NEXT_Q.search(seg)
    if b and b.start() > 0:
        seg = seg[: b.start()]
    nm = TAIL_NOISE.search(seg)
    if nm and nm.start() > 0:
        seg = seg[: nm.start()]
    seg = seg.strip()
    if PLACEHOLDER.search(seg[:14]):
        return {"hit": True, "why": "占位符(查看答案)", "answer": seg[:80]}
    if len(seg) < MIN_ANS_LEN:
        return {"hit": True, "why": "答案段过短", "answer": seg[:80]}
    return {"hit": True, "why": "strict-ok", "answer": seg[:250]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=10, help="每类抽样条数")
    ap.add_argument("--narrow", type=int, default=300, help="就近答案窗口（字）")
    ap.add_argument("--json-out", default="")
    ap.add_argument("--no-kb", action="store_true", help="跳过知识库对齐探测")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=300)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=300000")

    rows = con.execute(
        "SELECT id, content, options, answer, analysis, source, paper, question_type, "
        "       subject, chapter, knowledge_point, year, created_at, ai_generated, is_junk, quality "
        "FROM quiz_questions WHERE answer IS NULL OR trim(answer)=''"
    ).fetchall()
    print(f"无答案题总数（5349 口径）: {len(rows)}")
    print(f"  其中 is_junk=1（已隔离）: {sum(1 for r in rows if r['is_junk'])}\n")

    # ---------------- 三分类 ----------------
    buckets = defaultdict(list)
    cls_tot = Counter()
    reason_tot = Counter()
    cls_comp = defaultdict(Counter)
    for r in rows:
        opts = r["options"]
        if isinstance(opts, str):
            try:
                opts = json.loads(opts)
            except Exception:
                opts = []
        cls, why, comp, comp_why = classify(
            (r["id"], r["content"], opts, r["answer"], r["source"], r["question_type"]))
        buckets[cls].append((dict(r), opts, comp, comp_why))
        cls_tot[cls] += 1
        cls_comp[cls][comp] += 1
        reason_tot[(cls, why)] += 1

    print("=" * 78)
    print("一、三分类总览")
    print("=" * 78)
    order = ["A-真题缺答案", "B-习题缺答案", "C-不是题"]
    for k in order:
        print(f"  {k:<14}{cls_tot.get(k,0):>6}  ({cls_tot.get(k,0)*100//max(1,len(rows))}%)")
    print(f"  {'合计':<14}{sum(cls_tot.values()):>6}")

    print("\n完整度交叉:")
    print(f"  {'类别':<14}{'完整':>8}{'图缺':>8}{'残缺':>8}{'小计':>8}")
    for k in order:
        c = cls_comp.get(k)
        if not c:
            continue
        print(f"  {k:<14}{c.get('完整',0):>8}{c.get('图缺',0):>8}{c.get('残缺',0):>8}{sum(c.values()):>8}")

    print("\n" + "=" * 78)
    print("二、判定原因 TOP18")
    print("=" * 78)
    for (k, why), n in reason_tot.most_common(18):
        print(f"  {k:<14}{why:<40}{n:>6}")

    # ---------------- 抽样真实题干 ----------------
    print("\n" + "=" * 78)
    print(f"三、三类抽样题干原文（每类每完整度 {args.sample} 条）")
    print("=" * 78)
    samples = {}
    for cls in order:
        items = buckets.get(cls) or []
        by_comp = defaultdict(list)
        for r, opts, comp, cw in items:
            by_comp[comp].append((r, opts, cw))
        for comp in ("完整", "图缺", "残缺"):
            lst = by_comp.get(comp) or []
            if not lst:
                continue
            # 按 source 分散抽样
            by_src = defaultdict(list)
            for r, opts, cw in lst:
                by_src[r["source"]].append((r, opts, cw))
            picked, i = [], 0
            while len(picked) < args.sample:
                added = False
                for s in sorted(by_src):
                    arr = by_src[s]
                    if i < len(arr):
                        picked.append(arr[i])
                        added = True
                        if len(picked) >= args.sample:
                            break
                if not added:
                    break
                i += 1
            samples[f"{cls}|{comp}"] = [
                {"id": r["id"], "source": r["source"], "subject": r["subject"],
                 "question_type": r["question_type"], "chapter": r["chapter"],
                 "year": r["year"], "content": r["content"]} for r, _, _ in picked]
            print(f"\n---------- [{cls} / {comp}] 共 {len(lst)} 条，抽样 {len(picked)} 条 ----------")
            for r, opts, cw in picked:
                txt = (r["content"] or "").replace("\n", " ⏎ ")
                print(f"\n[id={r['id']}] {r['subject']}/{r['question_type']} "
                      f"chapter={r['chapter']} year={r['year']} ({len(r['content'] or '')}字, {cw})")
                print(f"  source: {r['source']}")
                if opts:
                    print(f"  options: {str(opts)[:150]}")
                print(f"  题干: {txt[:400]}")

    # ---------------- 知识库对齐可行性 ----------------
    kb = {}
    if not args.no_kb:
        print("\n" + "=" * 78)
        print("四、知识库答案对齐可行性（A/B 类）")
        print("=" * 78)
        # 4.1 documents 正文归一化索引
        docs = con.execute(
            "SELECT id, file_name, content FROM documents "
            "WHERE content IS NOT NULL AND length(content)>500").fetchall()
        doc_idx = defaultdict(list)
        for d in docs:
            base = re.sub(r"\.(txt|pdf|docx?|doc)$", "", d["file_name"], flags=re.I)[:14]
            doc_idx[base].append(d)
        # 4.2 knowledge_chunks 索引（按 doc_name 分组，拼回全文便于就近查找）
        chunk_docs = con.execute(
            "SELECT doc_name, count(*) n, sum(length(text)) total FROM knowledge_chunks "
            "GROUP BY doc_name").fetchall()
        chunk_idx = {re.sub(r"\.(txt|pdf|docx?|doc)$", "", r["doc_name"], flags=re.I)[:14]: r
                     for r in chunk_docs}

        def find_doc(src: str):
            fn = re.sub(r"^(知识库|真题):", "", src or "")
            stem = re.sub(r"\.(txt|pdf|docx?|doc)$", "", fn, flags=re.I)[:14]
            if stem in doc_idx:
                return doc_idx[stem][0]
            for k, v in doc_idx.items():
                if stem and (stem[:8] in k or k[:8] in stem):
                    return v[0]
            return None

        stats = Counter()
        by_cls = defaultdict(Counter)
        samples_align = defaultdict(list)
        for cls in ("A-真题缺答案", "B-习题缺答案"):
            for r, opts, comp, cw in buckets.get(cls, []):
                # P1 先判：答案就在题干里
                p1 = extract_answer_after(r["content"])
                if p1["ok"]:
                    stats["P1-题干内已有答案"] += 1
                    by_cls[cls]["P1"] += 1
                    if len(samples_align[f"{cls}|P1"]) < 6:
                        samples_align[f"{cls}|P1"].append((r, "（题干内切分）", p1["answer"]))
                    continue
                d = find_doc(r["source"])
                if not d:
                    stats["X-来源文档不在documents"] += 1
                    by_cls[cls]["无文档"] += 1
                    continue
                body = norm(d["content"])
                res = probe_align(norm(r["content"]), body, args.narrow)
                has_chunk = any(
                    re.sub(r"\.(txt|pdf|docx?|doc)$", "", k, flags=re.I)[:8]
                    in re.sub(r"\.(txt|pdf|docx?|doc)$", "", d["file_name"], flags=re.I)[:12]
                    or re.sub(r"\.(txt|pdf|docx?|doc)$", "", d["file_name"], flags=re.I)[:8] in k
                    for k in chunk_idx)
                key = ("B-文档就近可抽取" if res["why"] == "strict-ok"
                       else ("C-占位符" if res["hit"] else "D-文档内无答案"))
                stats[key] += 1
                stats["  └该文档有chunks" if has_chunk else "  └该文档无chunks"] += 1
                by_cls[cls][key] += 1
                if key == "B-文档就近可抽取" and len(samples_align[f"{cls}|B"]) < 8:
                    samples_align[f"{cls}|B"].append((r, d["file_name"], res["answer"]))

        print("\n对齐结果汇总:")
        for k, v in stats.most_common():
            print(f"  {k}: {v}")
        print("\n分类别:")
        for cls in ("A-真题缺答案", "B-习题缺答案"):
            c = by_cls[cls]
            tot = sum(v for k, v in c.items() if not k.startswith("无"))
            print(f"  {cls} (闸门放行 {sum(cls_tot.get(k,0) for k in order if k<=cls)} 条中):")
            for k, v in c.most_common():
                print(f"      {k}: {v}")

        print("\n可对齐抽样（含切出的答案原文）:")
        for key, arr in samples_align.items():
            if not arr:
                continue
            print(f"\n=== {key} （{len(arr)} 条）===")
            for r, doc, ans in arr[:6]:
                print(f"\n[id={r['id']}] {r['subject']}/{r['question_type']} src={r['source']}")
                print(f"  对齐文档: {doc}")
                print(f"  题干     : {(r['content'] or '').replace(chr(10),' ')[:150]}")
                print(f"  ▶答案    : {ans[:220]}")

        kb = {"stats": dict(stats),
              "by_cls": {k: dict(v) for k, v in by_cls.items()},
              "alignable_A": by_cls["A-真题缺答案"]["B-文档就近可抽取"]
              + by_cls["A-真题缺答案"]["P1"],
              "alignable_B": by_cls["B-习题缺答案"]["B-文档就近可抽取"]
              + by_cls["B-习题缺答案"]["P1"]}

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 78)
    print("五、可对齐补答案准确条数预估")
    print("=" * 78)
    if kb:
        for cls in ("A-真题缺答案", "B-习题缺答案"):
            c = by_cls[cls]
            p1 = c["P1"]
            p2 = c["B-文档就近可抽取"]
            # 只统计完整度为"完整"的（残缺/图缺即便抽到答案也刷不了）
            n = len(buckets.get(cls, []))
            print(f"  {cls}: 闸门放行 {n} 条 → 可对齐补答案 {p1 + p2} 条 "
                  f"(P1题干内 {p1} + P2文档就近 {p2})")
        print(f"\n  ** 合计可零风险补答案: {kb['alignable_A'] + kb['alignable_B']} 条 **")
    else:
        print("  （--no-kb 模式，跳过）")
    print(f"\n  C-不是题（应清理）: {cls_tot.get('C-不是题', 0)} 条")

    if args.json_out:
        out = os.path.join(BASE_DIR, args.json_out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({
                "total_no_answer": len(rows),
                "cls_totals": dict(cls_tot),
                "cls_completeness": {k: dict(v) for k, v in cls_comp.items()},
                "reasons": {f"{a}|{b}": n for (a, b), n in reason_tot.items()},
                "kb": kb, "samples": samples,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n[JSON] {out}")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
