# -*- coding: utf-8 -*-
"""训练集质检：剔除 OCR 残片、臆造模板答案和会被截断的超长样本。

背景：build_qa_dataset.py 出来的 v2 数据集里仍有少量有害样本
（题干本身是答案卡、公式乱码、答案教模型"无法解答"、
prompt 过长导致 assistant 目标被 max_len 截掉一半）。
这类样本训练出来的行为是"瞎答/拒答/半句话"，直接拉低答疑评测。

用法：
    python scripts/qc_dataset.py \
        --in-dir data/lora_finetune_v2 --out-dir data/lora_finetune_v3
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: 明确是坏答案的模板（教拒答 / 臆造概念对 / 空话）
_BAD_ANSWER = (
    "无法正确解答",
    "题目存在",
    "本题考的是",
    "该判断题属于",
    "该题属于",
)

#: 题干以这些字符结尾 → OCR 把题目截断了
#: 注意不含 。和 + - * /：陈述句题干合法以「。」结尾，算式结尾的减号也常见于合法题干
_TRUNCATION_TAIL = "（(［[【＝=:：，、"

#: 答案卡碎片：「68.B 69.B 70.A」这种 数字+点+选项字母 的连续串。
#: 必须带分隔点，否则合法的「A．111 B. 010」（数值后跟下一个选项字母）会被误杀。
_KEY_DUMP = re.compile(r"\d{1,3}\s*[．.]+\s*[ABCDabcd√×对错]")
_UNDERSCORE = re.compile(r"_{2,}|＿{2,}")


def est_tokens(s: str) -> int:
    """粗估 Qwen 分词长度：CJK 一字一 token，其余约 3.5 字符一 token。"""
    cjk = sum(1 for c in s if "一" <= c <= "鿿")
    return cjk + max(0, len(s) - cjk) // 4


def bad_reason(q: str, a: str, *, token_budget: int) -> str | None:
    """返回该样本被剔除的原因，合格返回 None。"""
    if "\ufffd" in q or "\ufffd" in a:
        return "乱码(U+FFFD)"
    if any(ord(c) < 32 and c not in "\n\t" for c in q + a):
        return "控制字符"
    if len(q.strip()) < 12:
        return "题干过短"
    if q.rstrip()[-1:] in _TRUNCATION_TAIL:
        return "题干被截断"
    if q.count("（") > q.count("）") + 1 or q.count("(") > q.count(")") + 1:
        return "括号不配对"
    if len(_KEY_DUMP.findall(q)) >= 3 and not _UNDERSCORE.search(q):
        return "答案卡碎片当题干"
    if any(t in a for t in _BAD_ANSWER):
        return "坏答案模板"
    if len(a.strip()) < 8:
        return "答案过短"
    if est_tokens(q) + est_tokens(a) > token_budget:
        return "超长会被截断"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", default="data/lora_finetune_v2")
    ap.add_argument("--out-dir", default="data/lora_finetune_v3")
    #: 与训练侧 TRAIN_MAX_LEN 对齐：留出 system + 模板 + 生成余量
    ap.add_argument("--token-budget", type=int, default=600)
    args = ap.parse_args()

    rows = []
    for name in ("train.jsonl", "val.jsonl"):
        path = os.path.join(args.in_dir, name)
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    d["_split"] = name
                    rows.append(d)

    kept, dropped = [], Counter()
    for r in rows:
        msgs = r["messages"]
        q = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
        a = msgs[-1]["content"] if msgs[-1]["role"] == "assistant" else ""
        reason = bad_reason(q, a, token_budget=args.token_budget)
        if reason:
            dropped[reason] += 1
        else:
            kept.append(r)

    print(f"输入 {len(rows)} 条 → 保留 {len(kept)} 条（剔除 {len(rows) - len(kept)} 条，"
          f"{100 * (len(rows) - len(kept)) / max(1, len(rows)):.1f}%）")
    for k, v in dropped.most_common():
        print(f"  {k:<20} {v}")

    print("\n保留集按来源:", dict(Counter(r.get("source", "?") for r in kept)))
    print("保留集按学科:", dict(Counter(r.get("subject", "?") for r in kept).most_common()))
    tl = [est_tokens(r["messages"][-2]["content"]) for r in kept]
    tl.sort()
    print(f"题干 token 估算 中位 {tl[len(tl) // 2]}  p95 {tl[int(len(tl) * 0.95)]}  最大 {tl[-1]}")

    os.makedirs(args.out_dir, exist_ok=True)
    for name in ("train.jsonl", "val.jsonl"):
        sub = [r for r in kept if r["_split"] == name]
        with io.open(os.path.join(args.out_dir, name), "w", encoding="utf-8") as f:
            for r in sub:
                f.write(json.dumps({k: v for k, v in r.items() if k != "_split"},
                                   ensure_ascii=False) + "\n")
        print(f"  [✓] {os.path.join(args.out_dir, name)}  {len(sub)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
