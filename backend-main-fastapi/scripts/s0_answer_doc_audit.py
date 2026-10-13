# -*- coding: utf-8 -*-
"""S0 答案文档抽题体检（只读，不做任何写库）。

回答三个问题：
1. 答案版真题文档（file_name 含"答案/解析"）里，哪些一篇都没抽出题？→ 真实闲置资产
2. 已抽出的题（source 匹配答案文档）的 answer 填充率如何？
3. answer 为空的题里，content 结尾是否本来就带着答案（"该拆没拆"）？
   —— 若是，这是最高 ROI 动作：拆答案即可，无需重新抽题。

判真源：services/quiz_content_gate.admit()（仅用于参考，不做门禁过滤，本脚本只做统计）
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
OUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "diagnostics"))

# ---------------------------------------------------------------- 正则

# 文档名里带"答案/解析"即视为答案版
DOC_ANSWER_NAME = re.compile(r"答案|解析|详解|答案版")

# source 形如 "真题:2023年5月数电月考试卷答案.txt"，也可能直接是文件名
SRC_PREFIX = re.compile(r"^(真题|习题|讲义|试题库|[^:]{1,10}):")

# 题库里出现即视为"带答案信号"
ANS_MARK = re.compile(
    r"【答案】|【参考答案】|参考答案|答案\s*[:：]|"
    r"【解析】|【详解】|解析\s*[:：]|"
    r"解答\s*[:：]|【解】|解\s*[:：]|"
    r"故\s*选|所以答案|因此答案|答案为|故答案"
)

# 题库排版惯例：答案段止于第一个【解析】
NEXT_Q = re.compile(
    r"(?:^|\n)\s*\d{1,3}\s*[．.、]\s*|查看答案|下一题|"
    r"【解析】|【详解】|〔解析〕|\[解析\]|"
    r"^\d{1,3}\s*[．.、]"
)

MIN_DOC_LEN = 500


def strip_source_prefix(source: str) -> str:
    """把 '真题:2023年5月数电月考试卷答案.txt' 归一为 '2023年5月数电月考试卷答案.txt'。"""
    if not source:
        return ""
    s = source.strip()
    if ":" in s or "：" in s:
        # 只在首个分隔符处切一刀，避免误伤文件名里的点/斜杠
        for sep in (":", "："):
            if sep in s:
                head, tail = s.split(sep, 1)
                # 前缀不应过长且不应含路径分隔符，避免把长文件名切坏
                if 0 < len(head) <= 12 and "/" not in head and "\\" not in head:
                    return tail.strip()
    return s


def split_inline_answer(content: str) -> dict:
    """探测 content 内部是否自带 '答案/解析' 段。

    返回 {ok, cut_at, answer_preview, stem_preview}。
    ok=True 表示 content 里确实带了一个可拆的答案段（"该拆没拆"）。
    """
    if not content:
        return {"ok": False, "cut_at": -1, "answer_preview": "", "stem_preview": content}
    m = ANS_MARK.search(content)
    if not m:
        return {"ok": False, "cut_at": -1, "answer_preview": "", "stem_preview": content[:120]}
    cut = m.start()
    tail = content[cut:]
    # 答案段必须在遇到下一题标记前终止
    nq = NEXT_Q.search(tail, 1)
    seg = tail[: nq.start()] if nq else tail
    # 去掉前导标记文字，只留实质内容
    seg = ANS_MARK.sub("", seg, count=1).strip(" ：:、,，。;；-—【】")
    if len(seg) < 2 or len(seg) > 200:
        return {"ok": False, "cut_at": cut, "answer_preview": seg[:80], "stem_preview": content[:cut][:120]}
    return {
        "ok": True,
        "cut_at": cut,
        "answer_preview": seg[:100],
        "stem_preview": content[:cut].strip()[:120],
    }


def main() -> None:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # ---------------- 1. 文档侧：答案版真题文档 ----------------
    docs = cur.execute(
        "SELECT id, file_name, content, subject FROM documents "
        "WHERE file_name IS NOT NULL AND content IS NOT NULL AND length(content) >= ?",
        (MIN_DOC_LEN,),
    ).fetchall()

    answer_docs = [d for d in docs if DOC_ANSWER_NAME.search(d["file_name"] or "")]
    # file_name -> doc row（取正文最长的一份为主）
    doc_by_name: dict[str, sqlite3.Row] = {}
    for d in answer_docs:
        name = (d["file_name"] or "").strip()
        if not name:
            continue
        cur_doc = doc_by_name.get(name)
        if cur_doc is None or len(d["content"]) > len(cur_doc["content"]):
            doc_by_name[name] = d

    # ---------------- 2. 题侧：全部题按归一 source 归组 ----------------
    all_q = cur.execute(
        "SELECT id, source, content, answer, analysis, is_junk, subject, question_type "
        "FROM quiz_questions"
    ).fetchall()

    q_by_src: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for q in all_q:
        q_by_src[strip_source_prefix(q["source"])].append(q)

    # ---------------- 3. 文档 -> 是否抽出过题 ----------------
    idle_docs = []       # 一篇题都没抽出的答案版文档
    used_docs = []       # 抽出过题的答案版文档
    for name, d in doc_by_name.items():
        qs = q_by_src.get(name, [])
        rec = {
            "doc_id": d["id"],
            "file_name": name,
            "doc_len": len(d["content"]),
            "n_questions": len(qs),
            "n_answered": sum(1 for x in qs if (x["answer"] or "").strip()),
            "n_junk": sum(1 for x in qs if x["is_junk"]),
        }
        (used_docs if qs else idle_docs).append(rec)

    used_docs.sort(key=lambda r: -r["n_questions"])
    idle_docs.sort(key=lambda r: -r["doc_len"])

    # ---------------- 4. 已抽出题（903 条口径）的 answer 填充率 ----------------
    from_answer_doc = [q for q in all_q if DOC_ANSWER_NAME.search(strip_source_prefix(q["source"] or ""))]
    ans_stat = Counter()
    inline_splittable = []
    for q in from_answer_doc:
        has_ans = bool((q["answer"] or "").strip())
        has_ana = bool((q["analysis"] or "").strip())
        ans_stat["total"] += 1
        ans_stat["has_answer"] += has_ans
        ans_stat["has_analysis"] += has_ana
        if has_ans:
            ans_stat["answered_not_junk"] += (not q["is_junk"])
        else:
            r = split_inline_answer(q["content"] or "")
            if r["ok"]:
                ans_stat["no_answer_but_inline"] += 1
                inline_splittable.append({"id": q["id"], "source": q["source"], **r})
            else:
                ans_stat["no_answer_no_inline"] += 1

    # ---------------- 5. 全库口径：answer 为空但 content 自带答案 ----------------
    all_inline = Counter()
    all_inline_samples = []
    for q in all_q:
        if (q["answer"] or "").strip():
            continue
        r = split_inline_answer(q["content"] or "")
        if r["ok"]:
            all_inline["inline"] += 1
            if len(all_inline_samples) < 15:
                all_inline_samples.append({"id": q["id"], "source": q["source"], "is_junk": q["is_junk"], **r})
        else:
            all_inline["clean"] += 1

    report = {
        "db": DB_PATH,
        "quiz_total": len(all_q),
        "answer_docs_total": len(doc_by_name),
        "answer_docs_used": len(used_docs),
        "answer_docs_idle": len(idle_docs),
        "answer_docs_idle_chars": sum(r["doc_len"] for r in idle_docs),
        "from_answer_doc": ans_stat,
        "all_no_answer_inline": all_inline,
        "idle_docs": idle_docs[:60],
        "used_docs": used_docs[:40],
        "inline_samples": all_inline_samples,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "s0_answer_doc_audit.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ---------------- 文本报告 ----------------
    L = []
    L.append("=" * 78)
    L.append("S0 答案文档抽题体检报告（只读）")
    L.append("=" * 78)
    L.append(f"题库总数: {len(all_q)}")
    L.append("")
    L.append("### 1. 答案版真题文档 → 抽题覆盖")
    L.append(f"答案版文档（file_name 含 答案/解析/详解，正文>=500字）: {len(doc_by_name)} 份")
    L.append(f"  已抽出题: {len(used_docs)} 份")
    L.append(f"  一篇题都没抽出（真闲置资产）: {len(idle_docs)} 份，"
             f"合计正文 {sum(r['doc_len'] for r in idle_docs):,} 字")
    L.append("")
    L.append("--- 闲置文档 Top 30（按正文字数） ---")
    L.append(f"{'doc_id':>6} {'字数':>8}  file_name")
    for r in idle_docs[:30]:
        L.append(f"{r['doc_id']:>6} {r['doc_len']:>8,}  {r['file_name']}")
    L.append("")
    L.append("--- 已抽题文档 Top 20（按题数） ---")
    L.append(f"{'doc_id':>6} {'题数':>5} {'有答案':>6} {'junk':>5} {'字数':>8}  file_name")
    for r in used_docs[:20]:
        L.append(f"{r['doc_id']:>6} {r['n_questions']:>5} {r['n_answered']:>6} "
                 f"{r['n_junk']:>5} {r['doc_len']:>8,}  {r['file_name']}")
    L.append("")
    L.append("### 2. 来自答案文档的题：answer 填充率")
    L.append(f"总条数: {ans_stat['total']}")
    L.append(f"  answer 非空: {ans_stat['has_answer']} "
             f"({ans_stat['has_answer']*100.0/max(ans_stat['total'],1):.1f}%)")
    L.append(f"  analysis 非空: {ans_stat['has_analysis']}")
    L.append(f"  answer 空 但 content 自带答案段（该拆没拆）: {ans_stat['no_answer_but_inline']}")
    L.append(f"  answer 空 且 content 干净: {ans_stat['no_answer_no_inline']}")
    L.append("")
    L.append("### 3. 全库口径：answer 为空的题里有多少 content 自带答案")
    L.append(f"  可内联拆分: {all_inline['inline']}")
    L.append(f"  确实没答案: {all_inline['clean']}")
    L.append("")
    L.append("--- 内联拆分样例（最多 15 条） ---")
    for s in all_inline_samples:
        L.append(f"[#{s['id']}] junk={s['is_junk']} src={s['source']}")
        L.append(f"   题干: {s['stem_preview']}")
        L.append(f"   答案: {s['answer_preview']}")
    L.append("")

    text = "\n".join(L)
    with open(os.path.join(OUT_DIR, "s0_answer_doc_audit.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
