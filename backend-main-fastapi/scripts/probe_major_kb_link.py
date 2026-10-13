# -*- coding: utf-8 -*-
"""
可行性探查：kaoyan_majors（院校专业）能否与知识库 documents/knowledge_chunks 打通？

核心思路
--------
院校专业的初试科目名（去`(301)` 前缀后）本身就是与知识库「科目」对接的天然键。
例如专业考「信号与系统」→ 知识库有 subject='信号与系统' 的文档；
考「408」→ 知识库有 subject='计算机学科专业基础408'。

匹配分三级（**只统计，不写库**）
--------------------------------
- **L1 精确**：初试科目名（剥掉科目代码与括号后缀）与知识库 subject 完全相等。
- **L2 归一**：经同义词/别名归一后相等（如 '408'↔'计算机学科专业基础408'、
  '数电'↔'数字电子技术'、'模电'↔'模拟电子技术'、'数模电'→两者兼有）。
- **L3 模糊**：知识库 subject 与专业名称/科目名存在关键词交集
  （如专业名'电子信息'+科目'电子技术基础' → 数字电子技术/模拟电子技术）。

输出
----
- 整体匹配率（按专业条数）
- 抽样 20 个专业的逐条匹配详情
- 知识库侧「哪些 subject 有需求但无文档」（供给缺口）

用法：
  python scripts/probe_major_kb_link.py
  python scripts/probe_major_kb_link.py --sample 20
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")

DB_URI = "file:D:/平台/database/kaoyan.db?mode=ro"
CONN = sqlite3.connect(DB_URI, uri=True)
CONN.row_factory = sqlite3.Row

# ------------------------------------------------------------ 科目代码剥离
_CODE_RE = re.compile(r"^\s*\(?\d{3,4}[A-Za-z]?\)?\s*")
_NOISE_RE = re.compile(r"[（(].*?[)）]|含.*?$|，.*?$|、.*?$")
_WS_RE = re.compile(r"\s+")


def decode_subjects(raw) -> list:
    """把 exam_subjects 还原成去代码的科目名列表。

    注意：库内实际存的是**一个用 ' | ' 拼接的 JSON 字符串**（不是 JSON 数组），
    例如 '"(301)数学（一） | (201)英语（一） | (802)通信类专业综合"'。
    因此必须先按分隔符再切，否则整条会被当成一个科目名。
    """
    if not raw:
        return []
    try:
        d = json.loads(raw)
    except Exception:
        return []
    if isinstance(d, str):
        d = [d]
    if not isinstance(d, list):
        return []
    # 先把 JSON 数组内部可能的 ' | ' 拼接也拆开
    flat = []
    for item in d:
        for seg in re.split(r"\s*\|\s*", str(item)):
            if seg.strip():
                flat.append(seg)
    out = []
    for seg in flat:
        seg = _CODE_RE.sub("", seg).strip()
        seg = _NOISE_RE.sub("", seg).strip()
        seg = _WS_RE.sub("", seg)
        if seg:
            out.append(seg)
    return out


# ------------------------------------------------------------ 公共课识别
# 公共课（政治/英语/数学）**不能**作为"专业<->教材"的关联依据：
# 832 条专业里 825 条都考数学+英语，任何匹配都会因它们而虚高。
# 真正的择校价值在**专业课**（第 3 门），本探查只用专业课做匹配。
PUBLIC_SUBJECTS = {
    "\u653f\u6cbb", "\u82f1\u8bed", "\u82f1\u8bed\u4e00", "\u82f1\u8bed\u4e8c", "\u6570\u5b66",
    "\u6570\u5b66\u4e00", "\u6570\u5b66\u4e8c", "\u6570\u5b66\u4e09",
    "\u82f1\u8bed\u6216\u4fc4\u8bed", "\u82f1\u8bed\u6216\u4fc4\u8bed\u6216\u65e5\u8bed",
    "\u65e5\u8bed", "\u4fc4\u8bed",
}


def professional_subject(subjects):
    """从科目列表中取出专业课（非公共课）。"""
    ps = [s for s in subjects if s not in PUBLIC_SUBJECTS]
    return ps[0] if ps else None


# ------------------------------------------------------------ 科目名归一
# 左侧：考研专业课标准名；右侧：知识库 subject 候选
SUBJECT_ALIAS = {
    "408": ["\u8ba1\u7b97\u673a\u5b66\u79d1\u4e13\u4e1a\u57fa\u7840408", "408"],
    "\u8ba1\u7b97\u673a\u5b66\u79d1\u4e13\u4e1a\u57fa\u7840": ["\u8ba1\u7b97\u673a\u5b66\u79d1\u4e13\u4e1a\u57fa\u7840408", "408"],
    "\u8ba1\u7b97\u673a\u5b66\u79d1\u4e13\u4e1a\u57fa\u7840\u7efc\u5408": ["\u8ba1\u7b97\u673a\u5b66\u79d1\u4e13\u4e1a\u57fa\u7840408", "408"],
    "\u8ba1\u7b97\u673a\u4e13\u4e1a\u57fa\u7840\u7efc\u5408": ["\u8ba1\u7b97\u673a\u5b66\u79d1\u4e13\u4e1a\u57fa\u7840408", "408"],
    "\u4e13\u4e1a\u57fa\u7840\u7efc\u5408": ["\u8ba1\u7b97\u673a\u5b66\u79d1\u4e13\u4e1a\u57fa\u7840408", "408"],
    "\u6570\u7535": ["\u6570\u5b57\u7535\u5b50\u6280\u672f"],
    "\u6570\u5b57\u7535\u5b50": ["\u6570\u5b57\u7535\u5b50\u6280\u672f"],
    "\u6570\u5b57\u7535\u8def": ["\u6570\u5b57\u7535\u5b50\u6280\u672f"],
    "\u6570\u5b57\u7535\u8def\u4e0e\u903b\u8f91\u8bbe\u8ba1": ["\u6570\u5b57\u7535\u5b50\u6280\u672f"],
    "\u6570\u6a21\u7535": ["\u6a21\u62df\u7535\u5b50\u6280\u672f", "\u6570\u6a21\u7535", "\u6570\u5b57\u7535\u5b50\u6280\u672f"],
    "\u6a21\u7535": ["\u6a21\u62df\u7535\u5b50\u6280\u672f"],
    "\u6a21\u62df\u7535\u5b50\u6280\u672f\u57fa\u7840": ["\u6a21\u62df\u7535\u5b50\u6280\u672f"],
    "\u6570\u5b57\u7535\u5b50\u6280\u672f\u57fa\u7840": ["\u6570\u5b57\u7535\u5b50\u6280\u672f"],
    "\u7535\u5b50\u6280\u672f\u57fa\u7840": ["\u6570\u5b57\u7535\u5b50\u6280\u672f", "\u6a21\u62df\u7535\u5b50\u6280\u672f", "\u6570\u6a21\u7535"],
    "\u7535\u5b50\u6280\u672f": ["\u6570\u5b57\u7535\u5b50\u6280\u672f", "\u6a21\u62df\u7535\u5b50\u6280\u672f", "\u6570\u6a21\u7535"],
    "\u7535\u5b50\u6280\u672f\u7efc\u5408": ["\u6570\u5b57\u7535\u5b50\u6280\u672f", "\u6a21\u62df\u7535\u5b50\u6280\u672f", "\u6570\u6a21\u7535"],
    "\u7535\u5b50\u79d1\u5b66\u4e0e\u6280\u672f\u7efc\u5408": ["\u6570\u5b57\u7535\u5b50\u6280\u672f", "\u6a21\u62df\u7535\u5b50\u6280\u672f", "\u6570\u6a21\u7535"],
    "\u6a21\u62df\u4e0e\u6570\u5b57\u7535\u5b50\u6280\u672f": ["\u6a21\u62df\u7535\u5b50\u6280\u672f", "\u6570\u5b57\u7535\u5b50\u6280\u672f", "\u6570\u6a21\u7535"],
    "\u7535\u5b50\u7535\u8def": ["\u6a21\u62df\u7535\u5b50\u6280\u672f", "\u6570\u5b57\u7535\u5b50\u6280\u672f"],
    "\u7535\u8def": ["\u7535\u8def", "\u7535\u8def\u5206\u6790"],
    "\u7535\u8def\u5206\u6790": ["\u7535\u8def", "\u7535\u8def\u5206\u6790"],
    "\u7535\u8def\u539f\u7406": ["\u7535\u8def", "\u7535\u8def\u5206\u6790"],
    "\u7535\u8def\u57fa\u7840": ["\u7535\u8def", "\u7535\u8def\u5206\u6790"],
    "\u7535\u8def\u7406\u8bba": ["\u7535\u8def", "\u7535\u8def\u5206\u6790"],
    "\u4fe1\u53f7\u4e0e\u7cfb\u7edf": ["\u4fe1\u53f7\u4e0e\u7cfb\u7edf"],
    "\u4fe1\u53f7\u4e0e\u7ebf\u6027\u7cfb\u7edf": ["\u4fe1\u53f7\u4e0e\u7cfb\u7edf"],
    "\u4fe1\u53f7\u4e0e\u7cfb\u7edf\u5206\u6790": ["\u4fe1\u53f7\u4e0e\u7cfb\u7edf"],
    "\u4fe1\u53f7\u7cfb\u7edf\u4e0e\u4fe1\u53f7\u5904\u7406": ["\u4fe1\u53f7\u4e0e\u7cfb\u7edf"],
    "\u4fe1\u53f7\u7cfb\u7edf\u4e0e\u6570\u5b57\u7535\u8def": ["\u4fe1\u53f7\u4e0e\u7cfb\u7edf", "\u6570\u5b57\u7535\u5b50\u6280\u672f"],
    "\u901a\u4fe1\u539f\u7406": ["\u901a\u4fe1\u539f\u7406"],
    "\u901a\u4fe1\u7c7b\u4e13\u4e1a\u7efc\u5408": ["\u901a\u4fe1\u539f\u7406"],
    "\u901a\u4fe1\u4e0e\u7cfb\u7edf": ["\u4fe1\u53f7\u4e0e\u7cfb\u7edf"],
    "\u4fe1\u53f7\u4e0e\u7cfb\u7edf\u4e00": ["\u4fe1\u53f7\u4e0e\u7cfb\u7edf"],
    "\u6570\u5b57\u7535\u5b50\u6280\u672f\u57fa\u7840\uff08\u6570\u5b57\u4e0e\u6a21\u62df\u7535\u8def\uff09": ["\u6570\u5b57\u7535\u5b50\u6280\u672f", "\u6a21\u62df\u7535\u5b50\u6280\u672f", "\u6570\u6a21\u7535"],
    "\u7535\u5b50\u6280\u672f\u57fa\u7840\u2160": ["\u6570\u5b57\u7535\u5b50\u6280\u672f", "\u6a21\u62df\u7535\u5b50\u6280\u672f", "\u6570\u6a21\u7535"],
    "\u6570\u5b57\u903b\u8f91\u4e0e\u4fe1\u53f7\u7cfb\u7edf": ["\u6570\u5b57\u7535\u5b50\u6280\u672f", "\u4fe1\u53f7\u4e0e\u7cfb\u7edf"],
    "\u4fe1\u53f7\u7cfb\u7edf\u4e0e\u6570\u5b57\u903b\u8f91": ["\u4fe1\u53f7\u4e0e\u7cfb\u7edf", "\u6570\u5b57\u7535\u5b50\u6280\u672f"],
    "\u6570\u5b57\u7535\u8def\u548c\u4fe1\u53f7\u4e0e\u7cfb\u7edf": ["\u6570\u5b57\u7535\u5b50\u6280\u672f", "\u4fe1\u53f7\u4e0e\u7cfb\u7edf"],
    "\u5fae\u673a\u63a7\u5236\u4e0e\u540e\u5904\u7406": ["\u7535\u5b50\u79d1\u5b66\u4e0e\u6280\u672f\u57fa\u7840408"],
}


def kb_subjects() -> set:
    return {r[0] for r in CONN.execute(
        "SELECT DISTINCT subject FROM documents WHERE subject IS NOT NULL")}


def build_index():
    """返回 {归一keys: [(subject, doc_count), ...]}"""
    idx = defaultdict(list)
    cnt = defaultdict(int)
    for r in CONN.execute(
            "SELECT subject, COUNT(*) c FROM documents"
            " WHERE subject IS NOT NULL GROUP BY subject"):
        cnt[r["subject"]] = r["c"]
    for subj, c in cnt.items():
        key = _WS_RE.sub("", subj)
        idx[key].append((subj, c))
    return idx


def match_level(subjects: list, major_name: str, idx) -> tuple:
    """**只对专业课**做匹配。返回 (level, [命中的知识库 subject])。

    公共课（数学/英语/政治）已在调用方剔除——它们人人必考，
    拿来匹配会让匹配率虚高到 98% 以上，毫无信息量。
    """
    ps = professional_subject(subjects)
    if ps is None:
        return "NOPROF", []
    key = _WS_RE.sub("", ps)

    # L1 精确：专业课名 == 知识库 subject
    if key in idx:
        return "L1", [idx[key][0][0]]

    # L2 别名归一：专业课名 → 知识库 subject
    hits2 = []
    for alias_key, cands in SUBJECT_ALIAS.items():
        if key == _WS_RE.sub("", alias_key):
            for cd in cands:
                ck = _WS_RE.sub("", cd)
                if ck in idx:
                    hits2.append(idx[ck][0][0])
    if hits2:
        return "L2", sorted(set(hits2))

    # L3 弱信号：专业课名含知识库 subject 的关键词（或反之）
    nm = _WS_RE.sub("", major_name)
    hits3 = []
    for key2, lst in idx.items():
        # 专业课名包含知识库科目（如「半导体物理与器件」⊃「半导体物理」）
        if len(key2) >= 2 and (key2 in key or key in key2):
            hits3.append(lst[0][0])
    if hits3:
        return "L3", sorted(set(hits3))
    return "MISS", []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=20)
    args = ap.parse_args()

    idx = build_index()
    print("=" * 78)
    print("知识库侧供给（documents.subject去重）")
    print("=" * 78)
    for key, lst in sorted(idx.items(), key=lambda x: -x[1][0][1]):
        print(f"  {key:<28s} {lst[0][1]:>5d} 篇")

    majors = CONN.execute(
        "SELECT m.id, m.name, m.code, m.exam_subjects, m.degree_type,"
        "       s.name AS school "
        "FROM kaoyan_majors m JOIN kaoyan_schools s ON s.id=m.school_id"
    ).fetchall()

    stats = Counter()
    detail = []
    for m in majors:
        subs = decode_subjects(m["exam_subjects"])
        lvl, hits = match_level(subs, m["name"], idx)
        stats[lvl] += 1
        detail.append((m, subs, lvl, hits))

    total = len(majors)
    print("\n" + "=" * 78)
    print(f"匹配结果（按专业条数，总 {total}）")
    print("=" * 78)
    for lvl in ("L1", "L2", "L3", "MISS", "NOPROF"):
        n = stats[lvl]
        print(f"  {lvl:<5s} {n:4d} 条  {n*100.0/total:5.1f}%")
    linked = stats["L1"] + stats["L2"] + stats["L3"]
    print(f"\n  ** 可关联（L1+L2+L3）: {linked}/{total} = {linked*100.0/total:.1f}% **")
    strong = stats["L1"] + stats["L2"]
    print(f"  ** 高置信度（L1+L2）  : {strong}/{total} = {strong*100.0/total:.1f}% **")

    print("\n" + "=" * 78)
    print(f"抽样 {args.sample} 个专业（按 id 均匀分布）")
    print("=" * 78)
    step = max(1, total // args.sample)
    for m, subs, lvl, hits in detail[::step][:args.sample]:
        print(f"\n  [{m['id']}] {m['school']} / {m['name'][:26]}"
              f"  code={m['code']} {m['degree_type'] or ''}")
        print(f"       初试科目: {'、'.join(subs) if subs else '<空>'}")
        print(f"       匹配={lvl}  命中知识库科目={hits if hits else '无'}")

    print("\n" + "=" * 78)
    print("供给缺口：常考科目但知识库无对应文档")
    print("=" * 78)
    need = Counter()
    for m, subs, lvl, hits in detail:
        if lvl != "MISS":
            continue
        ps = professional_subject(subs)
        if ps:
            need[ps] += 1
    for s, n in need.most_common(20):
        print(f"  {s:<28s} {n:4d} 个专业考它，但知识库无对应 subject")

    print("\n" + "=" * 78)
    print("反向：知识库有但无专业考的subject（可能是过剩供给）")
    print("=" * 78)
    used = set()
    for _m, subs, _lvl, hits in detail:
        used.update(hits)
    for key, lst in sorted(idx.items(), key=lambda x: -x[1][0][1]):
        if key not in used and lst[0][0] not in used:
            print(f"  {key:<28s} {lst[0][1]:>5d} 篇")


if __name__ == "__main__":
    main()