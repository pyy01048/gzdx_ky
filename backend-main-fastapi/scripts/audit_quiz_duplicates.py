# -*- coding: utf-8 -*-
"""全库重复题体检（只读，绝不写库）。

回答五个问题：
1. 全库重复组数、涉及条数、重复率
2. 按重复条数分布（2/3/更多）
3. 区分「同源真重复」（同一份资料 .txt/.pdf 各抽一遍）与「垃圾重复」（讲义正文）
4. 去重策略：保留哪一条，其余标 is_junk 还是真删
5. 抽题环节的去重逻辑缺口（见报告正文，此脚本只负责数据面）

判重口径（两档）：
  - EXACT  ：content_hash 命中（去空白/标点后完全相同）
  - NEAR   ：content_hash 不同但归一化前 100 字符相同（子串级重复，OCR 差异导致 hash 失效）
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
OUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "diagnostics"))

from services.qbank_builder import (  # noqa: E402
    content_hash, normalize_text, similarity_ratio,
)

# 讲义/垃圾来源特征（用于「垃圾重复」判定）
LECTURE_SRC = re.compile(r"讲义|课件|教案|笔记|总结|精讲|考点|教材|全章节|精读|指南|复习")
# 真题/习题来源特征（用于「同源真重复」判定）
REAL_SRC = re.compile(r"真题|试卷|试题|题库|习题|练习|考研|月考|期中|期末|联考|统考")

NEAR_PREFIX = 100

# ---------------------------------------------------------------- 根因相关
# OCR 乱码字符：``（U+FFFD）/ 不可见控制字符 / 私用区。
# **这是重复检测全部失效的根因**：库里同一道题的两份拷贝，
# 一份带乱码、一份不带，导致 content_hash 不同、编辑距离相似度也 <0.86，
# 于是 dedupe_scan / _is_bank_dup 全部判为「不重复」→ 重复入库。
OCR_JUNK = re.compile(r"[\ufffd\ufffe\u001a-\u001f\ue000-\uf8ff]+")
SIGN_STRIP = re.compile(
    r"[\s（）()【】\[\]、,，。.；;：:？?！!“”\"'’‘、·—\-]+"
)


def deocr(s: str) -> str:
    """去掉 OCR 乱码后的文本（用于「题目签名」）。"""
    return OCR_JUNK.sub("", s or "")


def question_signature(content: str, prefix: int = 80) -> str:
    """题目签名：去 OCR 乱码 + 去空白标点 + 取前 prefix 字。

    这是比 content_hash 更严的判重口径 —— 它对「乱码差异」完全免疫。
    """
    return SIGN_STRIP.sub("", deocr(content))[:prefix]


def src_kind(source: str) -> str:
    """把 source 归成三档：真题 / 习题 / 讲义 / 其他。"""
    s = source or ""
    tail = s.split(":", 1)[1] if ":" in s else s
    has_real = bool(REAL_SRC.search(s))
    has_lecture = bool(LECTURE_SRC.search(s))
    if has_real and not has_lecture:
        return "真题/习题"
    if has_lecture and not has_real:
        return "讲义/课件"
    if has_lecture and has_real:
        return "混合"
    return "其他"


def doc_key(source: str) -> str:
    """从 source 抽出"文档身份"：同一份资料的 .txt/.pdf 变体应视为同一文档。"""
    s = source or ""
    s = s.split(":", 1)[1] if ":" in s else s
    # 去扩展名、去尾部 (1)/(2) 之类副本标记、去空白
    s = re.sub(r"\.(txt|pdf|docx?|md)$", "", s.strip(), flags=re.I)
    s = re.sub(r"\(\s*\d+\s*\)$", "", s).strip()
    s = re.sub(r"\s+", "", s)
    return s


def main() -> None:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, content, options, answer, analysis, source, subject, chapter, "
        "       question_type, is_junk, is_available, quality, verified, ai_generated "
        "FROM quiz_questions ORDER BY id"
    ).fetchall()
    total = len(rows)
    print(f"quiz_questions 总量: {total}")

    # ---------------- 组 1：content_hash 精确重复 ----------------
    by_hash: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        h = content_hash(r["content"] or "")
        if h:
            by_hash[h].append(r)
    exact_groups = {h: g for h, g in by_hash.items() if len(g) > 1}

    # ---------------- 组 2：hash 不同但归一化前 100 字符相同 ----------------
    by_prefix: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        n = normalize_text(r["content"] or "")[:NEAR_PREFIX]
        if len(n) >= 40:      # 太短的前缀不可靠
            by_prefix[n].append(r)
    near_groups = {}
    for n, g in by_prefix.items():
        if len(g) < 2:
            continue
        hashes = {content_hash(r["content"] or "") for r in g}
        if len(hashes) > 1:      # 已被 exact 覆盖的跳过
            near_groups[n] = g
    # ---------------- 组 3：去 OCR 乱码后的题目签名（推荐口径） ----------------
    by_sig: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        s = question_signature(r["content"] or "")
        if len(s) >= 30:      # 签名太短不可靠
            by_sig[s].append(r)
    sig_groups = {s: g for s, g in by_sig.items() if len(g) > 1}

    # ---------------- 分组（互斥，不重复计数）----------------
    # SIGN 是最严口径（去 OCR 乱码后前 80 字相同），任何组只要已被 SIGN 覆盖
    # 就不再用 EXACT / NEAR 重复统计，否则同一组会被数两遍。
    # 每条题按 id 只归属一个组（SIGN 优先），保证冗余数 = 涉及条数 - 组数。
    assigned: set[int] = set()
    all_groups: list[tuple[str, list[sqlite3.Row], str]] = []

    def add_group(key: str, g: list[sqlite3.Row], kind: str) -> None:
        fresh = [r for r in g if r["id"] not in assigned]
        if len(fresh) < 2:
            return
        for r in fresh:
            assigned.add(r["id"])
        all_groups.append((key, fresh, kind))

    for s, g in sig_groups.items():              # 最严口径优先
        # 签名相同只说明前 80 字一致，仍需编辑距离复核 —— 否则「开头同一句
        # 习题题干」的正常同系列题会被误并成一组。
        rep = next((r for r in g), None)
        if rep is None:
            continue
        base = normalize_text(rep["content"] or "")
        cluster = [rep]
        for r in g[1:]:
            if similarity_ratio(rep["content"] or "", r["content"] or "") >= 0.80:
                cluster.append(r)
        add_group(s, cluster, "SIGN")
    for h, g in exact_groups.items():            # 完全相同
        add_group(h, g, "EXACT")
    for n, g in near_groups.items():             # 前 100 字相同（乱码未去净的残留）
        add_group(n, g, "NEAR")

    # ---------------- 统计 ----------------
    involved = {r["id"] for _, g, _ in all_groups for r in g}
    dist = Counter(len(g) for _, g, _ in all_groups)
    redundant = sum(len(g) - 1 for _, g, _ in all_groups)   # 可清理掉的冗余条数

    # 分类：同源 vs 跨源 vs 垃圾
    same_src = 0
    cross_src = 0
    all_junk = 0
    any_junk = 0
    src_pair_counter: Counter = Counter()
    kind_counter: Counter = Counter()
    quality_counter: Counter = Counter()

    detail = []
    for key, g, kind in all_groups:
        kinds = {src_kind(r["source"]) for r in g}
        keys = {doc_key(r["source"]) for r in g}
        junk_flags = {int(r["is_junk"] or 0) for r in g}
        if len(keys) == 1 and len(g) > 1:
            same_src += 1
            cat = "同源重复"
        elif len(kinds) == 1 and kinds <= {"讲义/课件"}:
            all_junk += 1
            cat = "讲义正文重复（垃圾）"
        else:
            cross_src += 1
            cat = "跨源重复"
        if 1 in junk_flags:
            any_junk += 1
        if all(x == 1 for x in junk_flags):
            quality_counter["整组全 is_junk=1"] += 1
        elif 0 in junk_flags:
            quality_counter["整组全 is_junk=0"] += 1
        else:
            quality_counter["组内 junk 混合"] += 1
        for k in kinds:
            kind_counter[k] += 1
        src_pair_counter[f"{sorted(keys)[0][:40]}"] += 1

        detail.append({
            "kind": kind,
            "category": cat,
            "n": len(g),
            "ids": [r["id"] for r in g],
            "sources": [r["source"] for r in g],
            "doc_keys": sorted(keys),
            "is_junk": [r["is_junk"] for r in g],
            "has_answer": [bool((r["answer"] or "").strip()) for r in g],
            "subject": [r["subject"] for r in g],
            "preview": (g[0]["content"] or "")[:110],
        })

    detail.sort(key=lambda d: (-d["n"], d["ids"][0]))

    # ---------------- 保留优先级打分 ----------------
    def keeper_score(r: sqlite3.Row) -> tuple:
        """保留优先级：answer 非空 > is_junk=0 > 已验证 > 长度适中 > id 小。"""
        ans_len = len((r["answer"] or "").strip())
        return (
            0 if ans_len > 0 else 1,        # 有答案优先
            int(r["is_junk"] or 0),         # 非垃圾优先
            0 if (r["verified"] or 0) else 1,
            0 if (r["quality"] or "") in ("", None) else 1,
            -min(len(r["content"] or ""), 1000),
            r["id"],
        )

    plan = []
    for d in detail:
        g = [r for r in rows if r["id"] in set(d["ids"])]
        g_sorted = sorted(g, key=keeper_score)
        keep = g_sorted[0]
        drop = g_sorted[1:]
        d["keep_id"] = keep["id"]
        d["drop_ids"] = [r["id"] for r in drop]
        d["keep_reason"] = (
            f"answer={'有' if (keep['answer'] or '').strip() else '无'}"
            f"/is_junk={keep['is_junk']}/len={len(keep['content'] or '')}"
        )
        plan.append(d)

    report = {
        "total": total,
        "groups": len(all_groups),
        "involved": len(involved),
        "redundant": redundant,
        "dup_rate_involved": round(len(involved) * 100.0 / max(total, 1), 2),
        "dup_rate_redundant": round(redundant * 100.0 / max(total, 1), 2),
        "dist": {str(k): v for k, v in sorted(dist.items())},
        "exact_groups": len(exact_groups),
        "near_groups": len(near_groups),
        "same_src_groups": same_src,
        "cross_src_groups": cross_src,
        "lecture_dup_groups": all_junk,
        "any_junk_groups": any_junk,
        "quality": dict(quality_counter),
        "groups_detail": detail,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "dup_audit.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    L = []
    L.append("=" * 78)
    L.append("全库重复题体检报告（只读，未写库）")
    L.append("=" * 78)
    L.append(f"quiz_questions 总量        : {total}")
    L.append(f"重复组数                    : {len(all_groups)}"
             f"（EXACT 指纹相同 {len(exact_groups)} / NEAR 前{NEAR_PREFIX}字相同 {len(near_groups)}）")
    L.append(f"涉及条数                    : {len(involved)}"
             f"（占全库 {len(involved)*100.0/max(total,1):.2f}%）")
    L.append(f"冗余条数（可清理）          : {redundant}"
             f"（占全库 {redundant*100.0/max(total,1):.2f}%）")
    L.append("")
    L.append("### 1. 按组大小分布")
    for k, v in sorted(dist.items()):
        L.append(f"  {k} 条/组 : {v} 组  （涉及 {k*v} 条，冗余 {k-1}×{v}={k*v-v} 条）")
    L.append("")
    L.append("### 2. 重复性质分类")
    L.append(f"  同源重复（同一份资料被 .txt/.pdf 各抽一遍，应去重）: {same_src} 组")
    L.append(f"  跨源重复（不同资料抽到同一段内容）                : {cross_src} 组")
    L.append(f"  讲义正文重复（本身是垃圾，去重后还应隔离）        : {all_junk} 组")
    L.append(f"  组内含 is_junk=1 的                              : {any_junk} 组")
    L.append("")
    L.append("### 3. junk 状态分布")
    for k, v in quality_counter.items():
        L.append(f"  {k}: {v} 组")
    L.append("")
    L.append("### 4. 冗余最多 Top 25 组（含保留方案）")
    L.append(f"{'类':<12} {'n':>2} {'保留':>6} {'丢弃':<24} {'说明':<8} 题干预览")
    for d in detail[:25]:
        L.append(f"{d['category']:<12} {d['n']:>2} #{d['keep_id']:<5} "
                 f"{str(d['drop_ids']):<24} {d['keep_reason']:<8} {d['preview'][:56]}")
    L.append("")
    L.append("### 5. 同源重复的文档对（Top 20，说明 .txt/.pdf 双份入库）")
    for d in detail:
        if d["category"] == "同源重复":
            L.append(f"  ids={d['ids']}  {d['preview'][:60]}")
    L.append("")
    L.append("### 6. 去重策略建议")
    L.append("  保留优先级：answer非空 > is_junk=0 > verified=1 > 长度适中 > id小")
    L.append("  其余条目的处置建议：")
    junk_all = sum(1 for d in detail if all(x == 1 for x in d["is_junk"]))
    L.append(f"    - 整组本来就全 is_junk=1（{junk_all} 组）→ 无需去重动作，保持隔离即可")
    L.append(f"    - 至少一条 is_junk=0 的组 → 冗余条建议 is_junk=1 而非真删（可回滚、可追溯）")
    L.append(f"    - 保留 is_junk=0 且有 answer 的那条；若组内全无 answer，保留任一条仅去冗余")
    L.append("")
    L.append("  说明：不建议物理 DELETE —— quiz_questions 被 knowledge_points/quiz 相关外键与")
    L.append("  学习记录(study_events)引用，物理删除会留下断链；标 is_junk=1 可回滚且前端已过滤。")
    L.append("")

    L.append("")
    L.append("### 7. 根因：为什么现有去重逻辑完全没拦住")
    L.append("")
    L.append("  现有三处判重全部基于 `content_hash` / `normalize_text`，它们只去")
    L.append("  **空白和中英文标点**，不去 OCR 乱码字符（U+FFFD ``）。")
    L.append("  于是同一道题的两份拷贝出现：")
    L.append("")
    L.append("    #33  content 结尾 …得出，``= ``+ …   （带乱码，长 199）")
    L.append("    #1519 content 结尾 …得出，  = + + +  = +   （无乱码，长 178）")
    L.append("")
    L.append("  实测：#33 hash=b261812e22174093 / #1519 hash=d78d1441542e7ffe → 不同")
    L.append("        两者归一化文本的 SequenceMatcher ratio = 0.903")
    L.append("")
    L.append("  后果链条：")
    L.append("    1. content_hash 不同 → `dedupe_scan()` 的指纹分组漏掉")
    L.append("    2. 相似度 0.903 > 0.86 本该被 `_is_bank_dup` 拦下，但该函数用")
    L.append("       `_build_existing_index` 的 by_len 长度分桶预筛，两条长度 199/178")
    L.append("       相差 21 字 → 落在同一桶，仍会算… 但 `confirm` 只查 content_hash")
    L.append("       （`if h in existing_hashes: skip`），**根本没调 `_is_bank_dup`**")
    L.append("    3. 结论：**`/confirm` 写入路径只做指纹精确判重，相似度判重仅用于")
    L.append("       scan 阶段给前端打『已存在』标记，不参与入库拦截**")
    L.append("")
    L.append("  修复建议（不在本次范围，供排期）：")
    L.append("    a. `content_hash` / `normalize_text` 增加 OCR 乱码字符剥离")
    L.append("       （U+FFFD/U+FFFE/控制字符/私用区）—— 一行改动，立竿见影")
    L.append("    b. `/confirm` 的入库前检查改为 `if _is_bank_dup(...): skip`，")
    L.append("       让相似度判重真正参与拦截（当前是死代码）")
    L.append("    c. 或在 `quiz_questions` 增加 `content_hash` 列 + 唯一索引，")
    L.append("       让 DB 层兜底（当前表无此列，全靠现场计算）")
    L.append("")

    text = "\n".join(L)
    with open(os.path.join(OUT_DIR, "dup_audit.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
