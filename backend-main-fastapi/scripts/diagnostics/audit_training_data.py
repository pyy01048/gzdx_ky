# -*- coding: utf-8 -*-
"""训练数据质量体检：找出导致"照抄"的样本特征。

背景：评测发现微调模型照抄率 0.72（在复述资料而非答疑）。
最可能的原因是样本把大段原文塞进 user 消息，模型只学会"续写原文"。
本脚本量化确认这一点，并给出清洗依据。
"""
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
LORA = os.path.join(BASE, "data", "lora_finetune")


def load(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def copy_ratio(answer, question, n=12):
    a = re.sub(r"\s+", "", answer or "")
    q = re.sub(r"\s+", "", question or "")
    if len(a) < n or not q:
        return 0.0
    grams = [a[i:i + n] for i in range(len(a) - n + 1)]
    return sum(1 for g in grams if g in q) / len(grams) if grams else 0.0


def main():
    for split in ("train.jsonl", "val.jsonl"):
        path = os.path.join(LORA, split)
        if not os.path.exists(path):
            continue
        data = load(path)
        print("=" * 74)
        print(f"{split}  {len(data)} 条")
        print("=" * 74)

        q_lens, a_lens, ratios = [], [], []
        with_exam_dump = 0
        pure_english = 0
        assistant_too_short = 0
        for obj in data:
            msgs = obj.get("messages") or []
            q = next((m["content"] for m in msgs if m.get("role") == "user"), "")
            a = next((m["content"] for m in msgs if m.get("role") == "assistant"), "")
            q_lens.append(len(q or ""))
            a_lens.append(len(a or ""))
            ratios.append(copy_ratio(a, q))
            # 题干里塞了大段"资料原文"（讲解要点/基于以下资料）
            if re.search(r"(请根据以下|请基于以下|讲解要点|资料内容)", q or "") and len(q or "") > 800:
                with_exam_dump += 1
            cn = sum(1 for ch in (q or "") if "\u4e00" <= ch <= "\u9fff")
            if (q or "") and cn / max(len(q), 1) < 0.2:
                pure_english += 1
            if len(a or "") < 30:
                assistant_too_short += 1

        def stat(name, xs):
            xs = sorted(xs)
            if not xs:
                print(f"  {name}: 无数据")
                return
            n = len(xs)
            print(f"  {name:<22} 均值 {sum(xs)/n:>8.0f}  中位 {xs[n//2]:>8.0f}  "
                  f"p90 {xs[int(n*0.9)]:>8.0f}  最大 {xs[-1]:>8.0f}")

        stat("user 消息长度", q_lens)
        stat("assistant 长度", a_lens)
        print(f"  {'答案照抄题干比例':<22} 均值 {sum(ratios)/max(len(ratios),1):.3f}")
        print()
        print(f"  ⚠️ 题干塞大段原文(>800字)的样本: {with_exam_dump}  "
              f"({with_exam_dump/max(len(data),1)*100:.1f}%)")
        print(f"  ⚠️ 纯英文题干样本:            {pure_english}  "
              f"({pure_english/max(len(data),1)*100:.1f}%)")
        print(f"  ⚠️ assistant 短于 30 字样本:  {assistant_too_short}  "
              f"({assistant_too_short/max(len(data),1)*100:.1f}%)")

        # 照抄率分布
        buckets = Counter()
        for r in ratios:
            if r > 0.8:
                buckets[">0.8 纯抄"] += 1
            elif r > 0.5:
                buckets["0.5-0.8 高度雷同"] += 1
            elif r > 0.2:
                buckets["0.2-0.5 部分重合"] += 1
            else:
                buckets["<0.2 正常"] += 1
        print("\n  答案与题干重合度分布:")
        for k in (">0.8 纯抄", "0.5-0.8 高度雷同", "0.2-0.5 部分重合", "<0.2 正常"):
            if buckets[k]:
                print(f"     {k:<18} {buckets[k]:>5}  ({buckets[k]/max(len(data),1)*100:.1f}%)")

        # 样例
        worst = sorted(zip(ratios, data), key=lambda x: -x[0])[:2]
        print("\n  照抄最严重的样本（user 截断 150 字）:")
        for r, obj in worst:
            msgs = obj.get("messages") or []
            q = next((m["content"] for m in msgs if m.get("role") == "user"), "")
            a = next((m["content"] for m in msgs if m.get("role") == "assistant"), "")
            print(f"     copy={r:.2f} | user={q[:150]!r}")
            print(f"                | assistant={a[:100]!r}")
        print()


if __name__ == "__main__":
    main()
