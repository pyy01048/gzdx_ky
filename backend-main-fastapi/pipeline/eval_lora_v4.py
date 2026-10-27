# -*- coding: utf-8 -*-
"""微调模型效果评测：新旧模型同题对比 + 结构化打分。

为什么需要这个脚本
------------------
"训练提高了准确率"不能靠感觉，也不能只看 eval_loss（不同数据分布下 loss
不可直接比较）。本脚本用**同一组测试题**分别请求旧模型与新模型，从三个
可量化维度对比：

  1. **模板套用率**：回答是否仍是「答案是：… 解析：… 考点：…」的填空模板
     （v3b 的实测缺陷，清洗数据训练后应显著下降）
  2. **错误章节标注率**：回答里是否出现「（第N章 …）」这类章节标注
     （数据里的章节几乎全错，剥离后训练的模型不应再生成）
  3. **回答长度与内容量**：被硬截断数据训练的模型回答偏短；
     新数据应让回答更完整

测试题来自三个层次：
  * 概念题（数电/模电核心概念，训练数据覆盖的主场）
  * 原理题（要求解释机制，考验"讲解"而非"填空"）
  * 对照题（训练数据之外的问题，看泛化）

用法
----
    python pipeline/eval_lora_v4.py                       # 需 Ollama 已启动
    python pipeline/eval_lora_v4.py --new kaoyan-assistant-v4
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT = BASE_DIR.parent / "data" / "lora_v4_eval_report.json"

OLLAMA = "http://127.0.0.1:11434/api/generate"

#: 模板套用检测（v3b 的三大特征）
_TEMPLATE_PREFIX = re.compile(r"^\s*答案是\s*[:：]")
_PARSE_MARK = re.compile(r"解析\s*[:：]")
_POINT_MARK = re.compile(r"考点\s*[:：]")
_CHAPTER_MARK = re.compile(r"[（(]\s*第\s*[0-9一二三四五六七八九十]+\s*章")

TESTS = [
    # (题面, 期望回答包含的关键要素——至少命中部分才算相关)
    ("共模信号和差模信号的区别是什么？", ["差模", "共模", "区别", "大小", "方向", "极性"]),
    ("卡诺图化简的主要步骤有哪些？", ["卡诺图", "圈", "相邻", "最小项", "化简"]),
    ("三极管放大的外部条件是什么？", ["发射结", "集电结", "正向", "反向", "偏置"]),
    ("什么是采样定理？", ["采样", "频率", "奈奎斯特", "2倍", "恢复"]),
    ("D触发器和JK触发器有什么不同？", ["D", "JK", "时钟", "翻转", "保持", "特性"]),
    ("为什么差分放大电路能抑制零点漂移？", ["差分", "对称", "共模", "漂移", "抵消"]),
    ("组合逻辑电路和时序逻辑电路的区别？", ["组合", "时序", "记忆", "状态", "存储"]),
    ("什么是虚短和虚断？", ["虚短", "虚断", "运放", "输入", "电流", "电压"]),
]


def ask(model: str, question: str, timeout: int = 120) -> str:
    body = json.dumps({
        "model": model, "prompt": question, "stream": False,
        "options": {"temperature": 0.3, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("response", "")


def score(answer: str) -> dict:
    """对单条回答打结构化指标。"""
    return {
        "len_chars": len(answer),
        "template_prefix": bool(_TEMPLATE_PREFIX.match(answer)),
        "has_parse_mark": bool(_PARSE_MARK.search(answer)),
        "has_point_mark": bool(_POINT_MARK.search(answer)),
        "chapter_mark": bool(_CHAPTER_MARK.search(answer)),
    }


def relevance(answer: str, keys: list[str]) -> float:
    """期望关键词命中率（0~1）。"""
    if not keys:
        return 0.0
    return sum(1 for k in keys if k in answer) / len(keys)


def eval_model(model: str, questions) -> dict:
    rows = []
    for q, keys in questions:
        t = time.time()
        try:
            a = ask(model, q)
            el = time.time() - t
        except Exception as exc:  # noqa: BLE001
            rows.append({"q": q, "error": str(exc)[:120], "elapsed": time.time() - t})
            continue
        m = score(a)
        m.update({"q": q, "answer": a[:400], "elapsed": round(el, 1),
                  "relevance": round(relevance(a, keys), 2)})
        rows.append(m)
        print(f"    {q[:18]:<20} 模板={int(m['template_prefix'])} "
              f"章节={int(m['chapter_mark'])} 相关={m['relevance']:.0%} "
              f"长度={m['len_chars']} {el:.1f}s")
    ok_rows = [r for r in rows if "error" not in r]
    n = max(1, len(ok_rows))
    return {
        "model": model,
        "rows": rows,
        "metrics": {
            "template_rate": round(sum(r["template_prefix"] for r in ok_rows) / n, 2),
            "chapter_mark_rate": round(sum(r["chapter_mark"] for r in ok_rows) / n, 2),
            "parse_mark_rate": round(sum(r["has_parse_mark"] for r in ok_rows) / n, 2),
            "avg_len": round(statistics.mean(r["len_chars"] for r in ok_rows)),
            "avg_relevance": round(statistics.mean(r["relevance"] for r in ok_rows), 2),
            "avg_elapsed": round(statistics.mean(r["elapsed"] for r in ok_rows), 1),
            "errors": len(rows) - len(ok_rows),
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LoRA v4 新旧模型对比评测")
    p.add_argument("--old", default="kaoyan-assistant-v2:latest")
    p.add_argument("--new", default="kaoyan-assistant-v4:latest")
    p.add_argument("--skip-old", action="store_true", help="只测新模型")
    args = p.parse_args(argv)

    print("=" * 70)
    print("微调模型效果评测（同题对比）")
    print("=" * 70)

    results = {}
    if not args.skip_old:
        print(f"\n[1/2] 旧模型 {args.old}")
        results["old"] = eval_model(args.old, TESTS)
        print("  指标:", json.dumps(results["old"]["metrics"], ensure_ascii=False))
    print(f"\n[2/2] 新模型 {args.new}")
    results["new"] = eval_model(args.new, TESTS)
    print("  指标:", json.dumps(results["new"]["metrics"], ensure_ascii=False))

    if "old" in results:
        om, nm = results["old"]["metrics"], results["new"]["metrics"]
        print("\n" + "-" * 70)
        print("对比结论：")
        print(f"  模板套用率   {om['template_rate']:.0%} -> {nm['template_rate']:.0%}"
              f"  {'↓ 改善' if nm['template_rate'] < om['template_rate'] else '— 持平/上升'}")
        print(f"  错误章节率   {om['chapter_mark_rate']:.0%} -> {nm['chapter_mark_rate']:.0%}"
              f"  {'↓ 改善' if nm['chapter_mark_rate'] < om['chapter_mark_rate'] else '— 持平/上升'}")
        print(f"  平均回答长度 {om['avg_len']} -> {nm['avg_len']} 字")
        print(f"  关键词相关性 {om['avg_relevance']:.0%} -> {nm['avg_relevance']:.0%}")
        print("-" * 70)

    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告：{REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
