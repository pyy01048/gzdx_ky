# -*- coding: utf-8 -*-
"""S1 前 10 条答案切分验证（干跑，绝不写库）。

用途：让 team-lead 亲眼确认「切分后的 answer 与 content 是否干净」——
  - answer 不得残留 【答案】/【解析】/题号 等标记
  - content 不得被截断成半句、不得为空
  - 不得串题（不得含下一题题号/题面）
  - 必须记录 source_answer_doc（答案来自哪份文档）

同时检测 G1 内部的重复题（同答案多次出现 = 疑似重复入库），
因为重复会把「69 条」虚增成有效题目更少。

用法：
    python scripts/s1_dryrun_answers.py            # 默认前 10 条
    python scripts/s1_dryrun_answers.py --all      # 全部 69 条（仅统计）
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
OUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "diagnostics"))
PRECISION_JSON = os.path.join(OUT_DIR, "alignment_precision.json")

# ---------------------------------------------------------------- 切分后的洁净度检查

# 任何残留的题库标记都必须清掉（切分后 answer 里不应出现）
LEFTOVER_MARK = re.compile(
    r"【答案】|【解析】|【详解】|【参考答案】|【分析】|查看答案|下一题"
)
# 答案里出现"题号+题面"= 串题
NEXT_STEM = re.compile(r"\n\s*\d{1,3}\s*[．.、]\s*[^\n]{4,}")
# —— 串题的第二种形态：整段被压成单行，题号/大题标题/答案标记都黏在一起 ——
# 例：#883 "C15、门电路的电压传输曲线反映（）的关系A、...答案：A二、填空题（每题5分）1、计算..."
SERIAL_STEM = re.compile(r"(?:^|。|；|\s)\d{1,3}\s*[、．.]\s*[^\s]")
SERIAL_SECTION = re.compile(r"[一二三四五六七八九十]\s*[、．.]\s*\S{2,12}")
INLINE_ANS_MARK = re.compile(r"答案\s*[:：]|故\s*选|所以答案|因此答案|故答案为")
# 答案里出现页眉页脚/水印 = 噪声
NOISE = re.compile(
    r"第\d+页|kaoshidian|kaoyanshiti|微信公众号|免费分享|考研资料|"
    r"视频课程|加QQ|qq\d{6,}|电话：|客服|东坡哥|水木观畴|研池大叔|"
    r"名师精品课程|^\s*[-—–]{3,}\s*$"
)
# —— 「推导陈述」型答案：讲的是怎么算，不是结论本身 ——
# 例：#542 "D触发器的特性方程为…；T触发器的…，对比可得。"（没给最终表达式）
#     #872 "可以选择换卡诺图或是用公式法展开成最小项形式，然后最大项就是…"
#     #510 "图中所示是或非电路，。"
#     #874 "对于任意一个逻辑式Y，若将其中所有的'·'换成…则得到的结果就是。"
# 这类答案对刷题毫无意义（用户看不到最终答案），必须降级。
NARRATIVE_LEAD = re.compile(
    r"^\s*(?:可以选择|可以采用|对比可得|比较可得|图中所示|图\s*\d+\s*所示|"
    r"对于任意|对于任何|一般将|通常将|设\s*[A-Za-z]|根据反演|由\s|首先|然后|"
    r"本题|上述|按照|利用)"
)
# 结论型答案至少应含一个等号或明确的集合/符号表达
CONCLUSION_HINT = re.compile(
    r"[=＝]|∑|Π|[（(]\s*\d+\s*,\s*\d+|[A-Za-z]\s*[′']?\s*[A-Za-z]"
)

MAX_ANSWER_LEN = 200

# 题干与答案的相关性校验：中文技术题答案至少应与题干共享若干实词
_STOP = set("的是和与或及在对于下列如图所示已知试求问答题解一个可以采用"
            "进行其中因为所以则就都而且不我们要它该此其如果需要将".split())
_TOKEN = re.compile(r"[A-Za-z]{2,}|[一-鿿]{2,6}|\d+")


def _tokens(text: str) -> set[str]:
    toks = set()
    for m in _TOKEN.finditer(text or ""):
        t = m.group(0)
        if t in _STOP:
            continue
        toks.add(t.lower())
    return toks


def _answer_is_formulaic(ans: str) -> bool:
    """答案是否为纯算式/纯符号型（如 '(1101.1011)2＝(15.54)8'、'F＝XY＋YZ＋XZ'）。

    这类答案与题干天然不共享中文实词，相关性校验不适用，必须豁免。
    """
    s = re.sub(r"[\s，,。；;、]", "", ans or "")
    if not s:
        return False
    # 中文实词（2 字以上的汉字串）占比低 → 视为公式型
    cjk = re.findall(r"[一-鿿]{2,}", s)
    cjk_chars = sum(len(x) for x in cjk)
    return cjk_chars / len(s) < 0.35


def relevance(content: str, answer: str) -> int:
    """题干与答案的实词重合数（用于识别"抓到了隔壁题的答案"）。"""
    ct = _tokens(content)
    at = _tokens(answer)
    if not ct or not at:
        return 0
    return len(ct & at)


def clean_answer(ans: str) -> tuple[str, list[str]]:
    """清洗答案：去标记、去页眉页脚、压缩空白。返回 (clean, 问题列表)。"""
    issues: list[str] = []
    s = ans or ""
    if LEFTOVER_MARK.search(s):
        issues.append("残留题库标记")
        s = LEFTOVER_MARK.sub("", s)
    if INLINE_ANS_MARK.search(s):
        issues.append("串题：答案里含'答案：/故选/因此答案'等下一题的答案标记")
    if SERIAL_SECTION.search(s) or SERIAL_STEM.search(s):
        issues.append("串题：答案里含'一、/1、'等大题或题号标题")
    if NOISE.search(s):
        issues.append("含页眉/水印噪声")
        s = NOISE.sub(" ", s)
    if NEXT_STEM.search(s):
        issues.append("疑似串题（含下一题题号+题面）")
    s = re.sub(r"[ \t　]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s).strip()
    # 推导陈述型答案（讲方法不讲结论）—— 对刷题无价值
    if NARRATIVE_LEAD.match(s) and not CONCLUSION_HINT.search(s):
        issues.append("推导陈述型答案：无最终结论，只讲了怎么算")
    if NARRATIVE_LEAD.match(s) and CONCLUSION_HINT.search(s):
        # 既有叙述又有结论：若结论在句尾，抽取结论；否则整段需人工
        if s.rstrip("。.；;，,")[-1] not in "）)】〕":
            issues.append("答案尾部可能被截断，结论可能未取到")
    if len(s) > MAX_ANSWER_LEN:
        issues.append(f"答案过长({len(s)}字)截断")
        s = s[:MAX_ANSWER_LEN]
    if len(s) < 2:
        issues.append("答案过短")
    return s, issues


def check_content(content: str) -> list[str]:
    """检查题干本身是否「可作答」——这是写答案前最后一道闸门。

    只看答案是不够的：实测 36 条「答案干净」的样本里，
    有相当一部分题干本身是 OCR 公式碎片（"7 o/ 6t -3.7| 0+ 0+ R u?/V4"）
    或本身已含答案体（"解：…"，"4习题解答123 解：…"）。
    给这种题补答案毫无意义 —— 该走的是隔离，不是补答案。
    """
    issues: list[str] = []
    c = (content or "").strip()
    if not c:
        issues.append("content 为空")
        return issues
    if len(c) < 6:
        issues.append("content 过短")
    if LEFTOVER_MARK.search(c):
        issues.append("content 内残留【答案】标记")
    if re.search(r"\n\s*\d{1,3}\s*[．.、]\s*[^\n]{4,}", c):
        issues.append("content 内含多题（题号未切净）")
    # 题干自身就是答案体（习题解答 / 解：/ 答：开头）
    if CONTENT_IS_ANSWER.match(c):
        issues.append("题干本身就是答案/解答体（不是题目）")
    # 题干是选择题选项列表 —— 没有独立题干，无法作答
    if OPTION_ONLY.match(c):
        issues.append("题干只有选项没有问句，不可作答")
    # 题干是纯 OCR 公式碎片
    if mostly_symbolic(c):
        issues.append("题干为 OCR 符号碎片，不可作答")
    return issues


# 题干自身即答案/解答体
CONTENT_IS_ANSWER = re.compile(
    r"^\s*(?:\d+\s*)?(?:习题解答|解答|答案|解析|分析|【答】|【解】|解\s*[:：]|"
    r"答\s*[:：]|因为|由于|根据图|由图|解\s*[：:])"
)
# 题干只有选项：出现 3 个以上 "A．/A、" 式选项标记
OPTION_ONLY = re.compile(r"(?:[（(]?\s*[A-DＡ-Ｄ]\s*[．.、][^\n]{1,60}){3,}")

_SYMBOL_POOL = set("=＝、，,。；;：:()（）[]【】+-*/∧∨·.．\s")


def mostly_symbolic(text: str, threshold: float = 0.42) -> bool:
    """判断文本是否为 OCR 公式碎片（符号占比超过阈值）。

    汉字/字母/数字之外的字符占比高，且可读汉字极少 → 视为碎片。
    """
    s = re.sub(r"\s+", "", text or "")
    if len(s) < 8:
        return False
    readable = re.findall(r"[一-鿿A-Za-z0-9]", s)
    if not readable:
        return True
    # 汉字占比：题干应主要是汉字（+少量字母数字），汉字 <25% 视为碎片
    cjk = re.findall(r"[一-鿿]", s)
    return len(cjk) / len(readable) < 0.25


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="跑全部 G1")
    ap.add_argument("-n", type=int, default=10, help="干跑前 N 条（默认 10）")
    args = ap.parse_args()

    with open(PRECISION_JSON, encoding="utf-8") as f:
        rows = json.load(f)["rows"]
    g1 = [r for r in rows if r["grade"] == "G1-可用"]

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    # ---- 重复检测：同答案 / 同题干 出现多次 ----
    by_ans: dict[str, list[int]] = defaultdict(list)
    for r in g1:
        by_ans[re.sub(r"\s+", "", r["answer"])[:60]].append(r["id"])
    dup_ans = {k: v for k, v in by_ans.items() if len(v) > 1}
    dup_ids = {i for v in dup_ans.values() for i in v}
    n_dup_groups = len(dup_ans)
    n_dup_ids = len(dup_ids)

    probe = g1 if args.all else g1[: args.n]

    L = []
    L.append("=" * 78)
    L.append(f"S1 答案切分干跑报告（只读，未写库）  G1 池 = {len(g1)} 条，本次干跑 {len(probe)} 条")
    L.append("=" * 78)
    L.append("")
    L.append("### 0. 写库前必知：G1 池内部重复情况")
    L.append(f"  答案文本重复组: {n_dup_groups} 组，涉及 {n_dup_ids} 条")
    for k, v in dup_ans.items():
        L.append(f"    ids={v}  answer≈{k[:50]}")
    L.append(f"  → 去重后唯一题目数约 {len(g1) - (n_dup_ids - n_dup_groups)} 条")
    L.append("")

    L.append("### 1. 逐条切分结果（写入 answer 的内容 / content 是否保持原样）")
    L.append("")
    stat = Counter()
    detail = []
    for r in probe:
        q = con.execute(
            "SELECT id, source, content, answer, analysis, subject, chapter, is_junk "
            "FROM quiz_questions WHERE id = ?", (r["id"],),
        ).fetchone()
        if q is None:
            L.append(f"[#{r['id']}] !! 题库中已不存在")
            continue
        raw_ans = r["answer"]
        clean, a_issues = clean_answer(raw_ans)
        c_issues = check_content(q["content"] or "")
        rel = relevance(q["content"] or "", clean)
        formulaic = _answer_is_formulaic(clean)
        if not formulaic and rel < 2 and len(clean) > 8:
            a_issues = a_issues + [f"题干/答案实词重合仅 {rel} 个，疑似抓到隔壁题答案"]
        ok = not a_issues and not c_issues and not (q["answer"] or "").strip()

        stat["total"] += 1
        stat["ok"] += 1 if ok else 0
        stat["with_answer_already"] += 1 if (q["answer"] or "").strip() else 0
        stat["junk"] += 1 if q["is_junk"] else 0
        stat["dup"] += 1 if r["id"] in dup_ids else 0

        L.append(f"[#{r['id']}]  {'✅ 可写库' if ok else '⚠️ 需人工'}"
                 f"{'  [重复]' if r['id'] in dup_ids else ''}"
                 f"{'  [is_junk=1]' if q['is_junk'] else ''}")
        L.append(f"  source(题来源)     : {q['source']}")
        L.append(f"  source_answer_doc  : {r['hit']}   ← 答案取自这份文档")
        L.append(f"  subject / chapter  : {q['subject']} / {q['chapter']}")
        L.append(f"  content (保持不变) : {(q['content'] or '')[:150]}")
        L.append(f"  content 检查       : {'OK' if not c_issues else ' / '.join(c_issues)}")
        L.append(f"  answer 原样(对齐抽到): {raw_ans[:200]}")
        L.append(f"  answer 清洗后(将写入): {clean}")
        L.append(f"  answer 检查        : {'OK' if not a_issues else ' / '.join(a_issues)}"
                 f"   (题干/答案实词重合={rel}{'，公式型已豁免' if formulaic else ''})")
        L.append("")

        detail.append({
            "id": r["id"], "source": q["source"], "source_answer_doc": r["hit"],
            "subject": q["subject"], "chapter": q["chapter"], "is_junk": q["is_junk"],
            "is_dup": r["id"] in dup_ids, "relevance": rel,
            "formulaic": formulaic,
            "answer_raw": raw_ans, "answer_clean": clean,
            "answer_issues": a_issues, "content_issues": c_issues,
            "content_unchanged": (q["content"] or "")[:300],
            "ok": ok,
        })

    L.append("=" * 78)
    L.append("### 2. 干跑汇总")
    L.append(f"  干跑条数            : {stat['total']}")
    L.append(f"  可直接写库          : {stat['ok']}")
    L.append(f"  需人工确认          : {stat['total'] - stat['ok']}")
    L.append(f"  其中库内已有 answer : {stat['with_answer_already']}（应跳过，不覆盖）")
    L.append(f"  其中 is_junk=1      : {stat['junk']}（隔离题，建议先不写）")
    L.append(f"  其中与同组重复      : {stat['dup']}")
    L.append("")
    L.append("### 3. 拟写库 SQL（尚未执行，等确认）")
    L.append("  -- 每条写入 3 个字段：answer / analysis / source_answer_doc")
    L.append("  UPDATE quiz_questions")
    L.append("     SET answer = ?,")
    L.append("         analysis = COALESCE(NULLIF(analysis,''), ''),")
    L.append("         source_answer_doc = ?,")
    L.append("         verified = 0            -- 0=未人工核验，前端可据此打标")
    L.append("   WHERE id = ? AND (answer IS NULL OR trim(answer) = '');")
    L.append("  -- source_answer_doc 为新增列（VARCHAR(200)），需先 ALTER TABLE 加列")
    L.append("")

    os.makedirs(OUT_DIR, exist_ok=True)
    text = "\n".join(L)
    with open(os.path.join(OUT_DIR, "s1_dryrun_answers.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(OUT_DIR, "s1_dryrun_answers.json"), "w", encoding="utf-8") as f:
        json.dump({"stat": dict(stat), "dup_groups": {k: v for k, v in dup_ans.items()},
                   "rows": detail}, f, ensure_ascii=False, indent=2)
    print(text)


if __name__ == "__main__":
    main()
