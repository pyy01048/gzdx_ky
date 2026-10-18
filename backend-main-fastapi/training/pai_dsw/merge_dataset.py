#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并多来源训练集 → 最终 train/val（去重 + 照抄质检 + 分布报告）。

一条龙里数据来自三处，必须统一收口再喂训练：
  1. v3（build_qa_dataset.py 从知识分块抽的定义句+主题问答，2484 条）
  2. OCR 产物里的新知识（ocr_extract.py 从 79GB 原文件抽的文字）
  3. 合成数据（gen_synthetic.py 用 7B 造的问答，5 类能力）

统一收口做四件事：
  - 去重（同一问题只留一条，答案取最长的那份）
  - 照抄质检（答案不能是问题切片，否则模型学会复读——v2 时代的血泪教训）
  - 来源配比（某来源占比过高会让模型偏科，可 --max-source-share 压制）
  - 划分 train/val（固定随机种子，可复现）

用法：
    python3 merge_dataset.py --out-dir /mnt/workspace/train_data_v4 \
        data/lora_finetune_v3/train.jsonl \
        /mnt/workspace/synth/socratic.jsonl \
        /mnt/workspace/synth/contrast.jsonl \
        /mnt/workspace/synth/gen_quiz.jsonl \
        /mnt/workspace/synth/summarize.jsonl \
        /mnt/workspace/synth/flashcards.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def answer_is_copy(question: str, answer: str, *, n: int | None = None) -> bool:
    """答案是否基本照抄问题。

    n 随问题长度自适应：v3 提问均值仅 17 字，固定 n=16 时 16-gram 在短问题里
    根本不存在，命中恒为 0，防线形同虚设。故短问题降 n，长问题保持 16。
    """
    a, q = _norm(answer), _norm(question)
    if len(a) < 8 or len(q) < 4:
        return False
    if n is None:
        n = max(6, min(16, len(q) // 3))
    if len(a) < n:
        return False
    grams = [a[i:i + n] for i in range(len(a) - n + 1)]
    return bool(grams) and sum(1 for g in grams if g in q) / len(grams) > 0.5


def load(paths: list[str]) -> list[dict]:
    items: list[dict] = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"  [!] 跳过不存在的文件: {p}")
            continue
        n = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    it = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msgs = it.get("messages") or []
                if len(msgs) < 3:
                    continue
                if msgs[-1].get("role") != "assistant":
                    continue
                # 系统提示必须存在：训练与推理 system 不一致会明显掉点
                if msgs[0].get("role") != "system" or not msgs[0].get("content"):
                    it["messages"] = [{"role": "system", "content":
                                       "你是一位考研辅导老师，负责计算机与电子信息类"
                                       "（834 电子技术基础）以及数学二、英语二、政治的答疑。"}
                                      ] + msgs
                items.append(it)
                n += 1
        print(f"  {path.name:<24} {n:>6} 条")
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description="合并训练集（去重+质检+配比）")
    ap.add_argument("inputs", nargs="+", help="一个或多个 jsonl 路径")
    ap.add_argument("--out-dir", default="/mnt/workspace/train_data_v4")
    ap.add_argument("--val-ratio", type=float, default=0.1)
    ap.add_argument("--max-source-share", type=float, default=0.0,
                    help="单一来源占比上限（0=不限）；建议 0.45 防止某类数据灌顶")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print("=" * 70)
    print("合并训练集")
    print("=" * 70)
    print("输入:")
    items = load(args.inputs)
    print(f"\n读入合计 {len(items)} 条")

    if not items:
        print("✗ 没有可用样本")
        return 2

    # —— 去重：同一问题保留答案最长的那份（信息量最大）——
    best: dict[str, dict] = {}
    for it in items:
        q = _norm(it["messages"][1]["content"])[:150]
        if not q:
            continue
        cur = best.get(q)
        if cur is None or len(it["messages"][2]["content"]) > len(cur["messages"][2]["content"]):
            best[q] = it
    deduped = list(best.values())
    print(f"去重后 {len(deduped)} 条（去掉 {len(items) - len(deduped)} 条）")

    # —— 照抄质检 ——
    kept = []
    dropped = 0
    for it in deduped:
        if answer_is_copy(it["messages"][1]["content"], it["messages"][2]["content"]):
            dropped += 1
            continue
        kept.append(it)
    print(f"照抄质检剔除 {dropped} 条（必须为 0 才是健康的；非 0 说明上游质检漏了）")

    # —— 来源配比压制 ——
    if args.max_source_share > 0:
        by_src: dict[str, list[dict]] = defaultdict(list)
        for it in kept:
            by_src[it.get("source", "unknown")].append(it)
        cap = int(len(kept) * args.max_source_share)
        final = []
        for src, group in by_src.items():
            group.sort(key=lambda x: len(x["messages"][2]["content"]), reverse=True)
            final.extend(group[:cap])
        print(f"来源配比压制（上限 {args.max_source_share:.0%}）："
              f"{len(kept)} → {len(final)} 条")
        kept = final

    # —— 分布报告 ——
    print("\n按来源:")
    for k, v in Counter(it.get("source", "unknown") for it in kept).most_common():
        print(f"   {k:<16} {v:>6}  {v/len(kept):.0%}")
    print("按科目:")
    for k, v in Counter(it.get("subject", "?") for it in kept).most_common(10):
        print(f"   {k:<16} {v:>6}")

    ql = [len(it["messages"][1]["content"]) for it in kept]
    al = [len(it["messages"][2]["content"]) for it in kept]
    print(f"\n提问长度 均值 {sum(ql)/len(ql):.0f} 最长 {max(ql)}")
    print(f"回答长度 均值 {sum(al)/len(al):.0f} 最长 {max(al)}")

    # —— 划分写出 ——
    rng = random.Random(args.seed)
    rng.shuffle(kept)
    n_val = max(1, int(len(kept) * args.val_ratio))
    val, train = kept[:n_val], kept[n_val:]

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("train.jsonl", train), ("val.jsonl", val)):
        p = out / name
        with open(p, "w", encoding="utf-8") as f:
            for it in data:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        print(f"[✓] {p}  {len(data)} 条")

    print(f"\n最终数据集: {out}（train {len(train)} + val {len(val)}）")
    print("下一步：python3 train_dsw.py --data-dir "
          f"{out} --output-dir /mnt/workspace/lora_out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())