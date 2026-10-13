# -*- coding: utf-8 -*-
"""第三层判定：这 2123 条里有多少其实是「讲义/教材正文段落」而非离散试题（只读）。

动机：分层画像显示大量 C 级题 content 是几百字的知识点段落（"图解分析法：静态工作点的
图解分析…"、"逻辑函数的表示方法…"），这类内容**不该补答案**（它不是题），
而应该：① 转成 knowledge_points 知识点，或② 直接隔离。

判定「疑似正文（非题）」的信号（任一强信号即判正文）：
  S1 无问句标记：不含 ？/?/____/（ ）/求/试/简述/写出/画出/说明/计算/证明/分析 中任何一个
  S2 无判分点：不含填空标记 ____ 或选择标记（ ）/A. 等
  S3 段落感强：长度 ≥120 字 且 含"知识点/本章/重点/小结/总结/方法/步骤/例如/首先/其次"等
  S4 广告/水印噪声：含"考研/上岸/QQ/公众号/关注"等非知识内容占比高
另判「疑似答案体误入」：以"解/答/答案/故"开头或含大段推导结论。

输出与 diagnose_no_answer_questions 的三套分类做交叉，给出最终四分类处置建议：
  KEEP-可补答案 / FIX-改写为知识点 / JUNK-隔离

用法：
    python scripts/classify_no_answer_final.py
只读。
"""
from __future__ import annotations

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

# 问句/题型标记（与门禁 Q_MARK 对齐但更严格：要求真的可判分）
ASK = ("？", "?", "____", "＿＿", "（ ）", "( )", "求", "试", "简述", "写出", "画出",
       "说明", "计算", "证明", "分析", "论述", "列举", "选择", "判断", "填空", "已知")
# 明确的可判分结构
GRADEABLE = re.compile(r"_{3,}|＿{2,}|[（(]\s*[）)]|【答案】|答案\s*[:：]|A[.、．]|B[.、．]")
# 段落/讲义感
NARRATIVE = re.compile(
    r"本章|知识点|重点|难点|小结|总结|方法|步骤|例如|首先|其次|因此|从而|"
    r"所谓|也就是|需要注意|掌握|理解|定义|分类|特点|优点|缺点|应用|作用|原理|"
    r"教材|本章内容|要求掌握|会计算|会读")
WATERMARK = re.compile(r"(考研|上岸|QQ群?|qq\d{6,}|微信公众号|公众号|加微信|关注我|资料)")
ANSWER_TAIL = re.compile(r"(解\s*[:：]|答\s*[:：]|故\s*[可|能]|所以\s*[A-Z0-9]|"
                         r"因此\s*[A-Z0-9]|由此\s*(得|可|可求))")
LONG_PARA = 120


def verdict(content: str, question_type: str) -> tuple:
    """返回 (处置建议, 原因)。处置 ∈ {KEEP-可补答案, FIX-改写为知识点, JUNK-隔离}。"""
    c = (content or "").strip()
    n = len(c)
    if n < 20:
        return "JUNK-隔离", "题干过短(<20字)，无作答空间"

    ask = sum(1 for k in ASK if k in c)
    grade = bool(GRADEABLE.search(c))
    narrative = bool(NARRATIVE.search(c))
    wm = len(WATERMARK.findall(c))
    ans_tail = bool(ANSWER_TAIL.search(c))
    qt_essay = (question_type or "") == "essay"

    # 强判定 1：完全无任何问句/题型标记 → 正文
    if ask == 0 and not grade:
        return "FIX-改写为知识点", "无任何问句/判分标记，是知识点段落"

    # 强判定 2：水印广告占比高
    if wm >= 3 and n < 200:
        return "JUNK-隔离", f"含{wm}处广告水印，非知识内容"

    # 讲义长段落：有问句但整体是叙述性讲解、无明确判分点
    if n >= LONG_PARA and narrative and not grade and ans_tail:
        return "FIX-改写为知识点", "长段落+叙述性讲解+含推导结论，是讲义正文"

    # 简答题但内容是知识陈述（无问号且是陈述句）
    if qt_essay and n >= LONG_PARA and ask <= 1 and not grade:
        return "FIX-改写为知识点", "标记为简答但实为知识点陈述"

    if grade or ask >= 1:
        return "KEEP-可补答案", f"有{ask}处问句标记/判分结构"
    return "FIX-改写为知识点", "弱问句特征，倾向知识点"


LAYER_SRC = [
    ("L1-真题", re.compile(r"真题|试卷|联考|真题解析")),
    ("L2-习题题库", re.compile(r"习题|试题库|题库|练习|复习题|配套题")),
    ("L3-讲义正文", re.compile(r"课件|讲义|教案|笔记|总结|精讲|考点|教材|全章节")),
]


def layer_of(source: str) -> str:
    s = source or ""
    for name, pat in LAYER_SRC:
        if pat.search(s):
            return name
    return "L4-未归类"


def main() -> int:
    con = sqlite3.connect(DB_PATH, timeout=180)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=180000")
    rows = con.execute(
        "SELECT id, content, question_type, source, subject, chapter, options "
        "FROM quiz_questions "
        "WHERE (answer IS NULL OR trim(answer)='') AND coalesce(is_junk,0)=0"
    ).fetchall()
    print(f"目标: {len(rows)} 条\n")

    import probe_answer_recoverability as P1

    final = Counter()
    cross = defaultdict(Counter)
    reason = Counter()
    samples = defaultdict(list)
    for r in rows:
        v, why = verdict(r["content"], r["question_type"])
        lay = layer_of(r["source"])
        has_inline = P1.split_inline_answer(r["content"])["ok"]
        key = v if not has_inline else "KEEP-可补答案(题干内已有答案)"
        final[key] += 1
        cross[lay][key] += 1
        reason[(key, why)] += 1
        if len(samples[(key, why)]) < 3:
            samples[(key, why)].append(dict(r))

    print("=" * 76)
    print("一、最终三分类处置建议")
    print("=" * 76)
    for k, v in final.most_common():
        print(f"  {k}: {v}  ({v*100//len(rows)}%)")

    print("\n交叉分层:")
    for lay in ["L1-真题", "L2-习题题库", "L3-讲义正文", "L4-未归类"]:
        c = cross.get(lay)
        if not c:
            continue
        tot = sum(c.values())
        print(f"  {lay} (总{tot}):")
        for k, v in c.most_common():
            print(f"      {k}: {v}")

    print("\n" + "=" * 76)
    print("二、判定原因 TOP15")
    print("=" * 76)
    for (k, why), n in reason.most_common(15):
        print(f"  {k:<26}{why:<34}{n:>5}")

    print("\n" + "=" * 76)
    print("三、各处置类抽样题干（人工核验）")
    print("=" * 76)
    for (k, why), items in samples.items():
        print(f"\n### [{k}] {why}  （抽样 {len(items)}）")
        for r in items:
            c = (r["content"] or "").replace("\n", " ⏎ ")[:260]
            print(f"  [id={r['id']}] {r['subject']}/{r['question_type']} src={r['source']}")
            print(f"     {c}")

    out = os.path.join(BASE_DIR, "data", "diagnostics", "final_verdict.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"total": len(rows), "final": dict(final),
                   "cross": {k: dict(v) for k, v in cross.items()},
                   "reasons": {f"{a}|{b}": n for (a, b), n in reason.items()}}, f,
                  ensure_ascii=False, indent=2)
    print(f"\n[JSON] {out}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
