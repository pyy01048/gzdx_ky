# -*- coding: utf-8 -*-
"""L2 相似层全量诊断（只读）。

目的：给出 0.86 阈值下 L2 的真实命中量 —— 这是判断 L2 是否有实用价值的唯一依据。
若命中量过大（几百组），说明 0.86 在本题库上区分度不足，L2 只是噪声，应调阈值
或改用其他判据。**不接受"闸门跑通就算完"。**

同时输出关键判别指标：命中组里有多少是真冲突（L1 能覆盖）vs 仅相似（L2 独有），
以及短题干占比、答案对分布，用来判断误杀风险。

用法：
    python scripts/diagnose_l2_similarity.py
    python scripts/diagnose_l2_similarity.py --threshold 0.92
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from difflib import SequenceMatcher

sys.path.insert(0, r"D:\平台\backend-main-fastapi")
from services.quiz_content_gate import (  # noqa: E402
    MAX_INDEX_STEM_LEN,
    MIN_CONFLICT_STEM_LEN,
    build_stem_answer_index,
    normalize_dedup,
    stem_signature,
)

DB_PATH = r"D:\平台\database\kaoyan.db"


def sim(a: str, b: str) -> float:
    """与 qbank_builder.similarity_ratio 同算法（SequenceMatcher.ratio）。"""
    return SequenceMatcher(None, a, b).ratio()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.86)
    args = ap.parse_args()
    th = args.threshold

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content, answer, is_junk FROM quiz_questions"
    ).fetchall()
    conn.close()

    print(f"[L2] 阈值 = {th}")
    print(f"[L2] 全库 {len(rows)} 条")

    # 用与生产同口径的过滤：排除已隔离题、题干长度区间、空答案
    cand = []
    for r in rows:
        if r["is_junk"]:
            continue
        a = normalize_dedup(r["answer"])
        s = stem_signature(r["content"])
        if not a or len(s) < MIN_CONFLICT_STEM_LEN or len(s) > MAX_INDEX_STEM_LEN:
            continue
        cand.append((r["id"], s, a, len(s)))
    print(f"[L2] 参与比对（is_junk=0 + 有答案 + 题干长度达标）= {len(cand)} 条")

    # 精确索引：L1 能覆盖的（用于判断某组是否已被 L1 覆盖）
    ans_of: dict[int, str] = {qid: a for qid, _s, a, _n in cand}

    # 长度分桶加速
    buckets: dict[int, list[tuple[int, str]]] = {}
    for qid, s, _a, _n in cand:
        buckets.setdefault(len(s), []).append((qid, s))

    assigned: set[int] = set()
    groups: list[list[tuple[int, str, str]]] = []
    for qid, s, a, n in cand:
        if qid in assigned:
            continue
        grp = [(qid, s, a)]
        assigned.add(qid)
        lo, hi = int(n * 0.6), int(n / 0.6) + 1
        for L in sorted(buckets):
            if L < lo:
                continue
            if L > hi:
                break
            for qid2, s2 in buckets[L]:
                if qid2 in assigned:
                    continue
                if sim(s, s2) >= th:
                    grp.append((qid2, s2, ans_of[qid2]))
                    assigned.add(qid2)
        if len(grp) > 1:
            groups.append(grp)

    print(f"[L2] 命中组 = {len(groups)} 组，涉及 "
          f"{sum(len(g) for g in groups)} 条（冗余 {sum(len(g)-1 for g in groups)} 条）")

    # 组内答案是否真的冲突；以及该组是否已被 L1（精确同题干）覆盖
    conflict_groups, same_answer_groups, l1_coverable = 0, 0, 0
    stem_len_hist = Counter()
    for g in groups:
        answers: dict[str, list[int]] = {}
        for qid, _s, a in g:
            answers.setdefault(a, []).append(qid)
        if len(answers) >= 2:
            conflict_groups += 1
            # 组内若存在"归一化题干完全相同"的成员，则该冲突 L1 已能拒收
            if len({s for _q, s, _a in g}) < len(g):
                l1_coverable += 1
        else:
            same_answer_groups += 1
        for _q, s, _a in g:
            stem_len_hist[min(len(s) // 20 * 20, 100)] += 1

    print(f"[L2] 其中答案互相冲突的组 = {conflict_groups}")
    print(f"[L2] 其中答案一致的组   = {same_answer_groups}（这类不是 L2 要找的目标）")
    print(f"[L2] 含精确同题干、L1 已能覆盖的组 = {l1_coverable}")
    print(f"[L2] → **L2 独有（相似但非精确、且答案不同）= "
          f"{conflict_groups - l1_coverable} 组**")
    print(f"[L2] 组内归一化题干长度分布 = {dict(sorted(stem_len_hist.items()))}（分桶/字）")

    # 抽样：展示 L2 独有的前 10 组，供人工判断区分度
    shown = 0
    for g in groups:
        answers: dict[str, list[int]] = {}
        for qid, _s, a in g:
            answers.setdefault(a, []).append(qid)
        if len(answers) < 2:
            continue
        if len({s for _q, s, _a in g}) < len(g):
            continue                       # L1 已覆盖，不属 L2 独有
        if shown >= 10:
            break
        shown += 1
        print(f"\n  样例{shown}:")
        for qid, s, a in g:
            print(f"    #{qid} sim对首条 | 题干…{s[:46]} | 答案={a[:22]}")
    if shown == 0:
        print("\n  （无 L2 独有样例）")

    # ===== 关键判别：冲突组里"答案详略差异" vs "真正互相矛盾" =====
    # 详略差异：一侧答案是另一侧的子串（长短版同一答案）→ 属冗余，不是错答
    # 真矛盾：互不为子串 → 至少一侧可能真的错，L2 才有人工复核价值
    contain, real_conflict = 0, 0
    real_samples: list[tuple[int, str]] = []
    for g in groups:
        answers = sorted({a for _q, _s, a in g})
        if len(answers) < 2:
            continue
        if len({s for _q, s, _a in g}) < len(g):
            continue
        joined_ok = any(
            any(x in y or y in x for y in answers if y != x) for x in answers)
        if joined_ok:
            contain += 1
        else:
            real_conflict += 1
            if len(real_samples) < 12:
                for qid, _s, a in g:
                    real_samples.append((qid, a))
    print(f"\n[判别] L2 独有 {conflict_groups - l1_coverable} 组再分类：")
    print(f"  答案互为子串（长/短版，属冗余非错答）= {contain} 组")
    print(f"  答案互不包含（疑似真矛盾，有复核价值）= {real_conflict} 组")
    if real_samples:
        print("  真矛盾样例 id:答案 =")
        for qid, a in real_samples:
            print(f"    #{qid} → {a[:40]}")

    verdict = ("L2 实用：命中量小、可作为人工复核线索" if len(groups) <= 50 else
               f"L2 存疑：命中 {len(groups)} 组，0.86 在此题库区分度不足，"
               "建议调高阈值或改用其他判据")
    print(f"\n[结论] {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
