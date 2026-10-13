# -*- coding: utf-8 -*-
"""跨文档对齐结果的**精确率评估**（只读）—— 判断 124 条命中里有多少能直接写库。

`probe_crossdoc_alignment.py` 找到了 124 条"可对齐"，但人工抽查发现质量参差：
有的答案精准对应本题（[1185] 用ROM实现全加器 → 「有7根行线，23根列线」），
有的串到了下一题（[873] 拿到的是下一题的【解析】），有的题干本身残缺导致对不上。

本脚本对每条命中做质量分级，输出「可直接写库 / 需人工复核」两条准确条数。

分级规则（确定性，可复现）：
  G1-可用     答案段不含下一题标记、不以【解析】开头（说明拿到的是真答案不是解析）、
              长度合理（4~300 字）、且不含占位符
  G2-需复核   答案以【解析】开头 / 含多处【答案】/【解析】（串题迹象）/
              长度 >300（吞进相邻内容）/ 过短（<6 字，多为符号残片）
  G3-不可用   占位符「查看答案」/ 空 / 明显是题号而非答案

用法：
    python scripts/assess_alignment_precision.py
    python scripts/assess_alignment_precision.py --dump-all     # 打印全部 124 条明细
只读。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

SRC_JSON = os.path.join(BASE_DIR, "data", "diagnostics", "crossdoc_alignment.json")

PLACEHOLDER = re.compile(r"查看答案|答案略|（略）|扫码|见解析")
# 题库惯例：【答案】<答案>【解析】<解析>。若切出的段以【解析】开头，说明切过了头
STARTS_WITH_PARSE = re.compile(r"^\s*[【\[〔]?\s*解析")
# 段内出现 >=2 次答案/解析标记 → 吞进了相邻题
MULTI_MARK = re.compile(r"【答案】|【解析】|【参考答案】")
# 段内残留任何标记（即使只有 1 处）→ 说明切分边界不干净，答案里混进了标记或邻题内容
ANY_MARK = re.compile(r"【答案】|【解析】|【参考答案】|查看答案")
# 段首是"题号+题面"形态（如 "14逻辑函数，当变量ABC取值为110时…"）→ 拿的是下一题的题干
NEXT_STEM = re.compile(r"^\s*\d{1,3}\s*(?:[．.、]|[\u4e00-\u9fa5]{2,})")
# 段内出现"如图X所示/图X-Y"→ 多半是邻题的图注
FIG_REF = re.compile(r"如图\s*\d|图\s*\d+[-－]\d+|图\s*P\d")


def grade(answer: str) -> tuple:
    """返回 (等级, 原因)。等级 ∈ {G1-可用, G2-需复核, G3-不可用}。

    注意 G1 的门槛是**保守**的：宁可漏判为 G2 送去复核，也不要把串题的答案写进题库。
    实测中"看起来干净"的答案里有相当比例其实切过了头（段首是下一题的题面），
    因此 G1 要求同时满足：无任何标记残留 + 段首不是题号形态 + 无邻题图注 + 长度适中。
    """
    a = (answer or "").strip()
    if not a:
        return "G3-不可用", "答案为空"
    if PLACEHOLDER.search(a[:20]):
        return "G3-不可用", f"占位符：{a[:20]}"
    if len(a) < 6:
        return "G3-不可用", f"过短({len(a)}字)，符号残片"
    if STARTS_WITH_PARSE.match(a):
        return "G2-需复核", "以【解析】开头，切过了头（拿到的是解析不是答案）"
    if ANY_MARK.search(a):
        return "G2-需复核", "残留【答案】/【解析】标记，切分边界不干净"
    if NEXT_STEM.match(a):
        return "G2-需复核", "段首是题号+题面，拿到的是下一题的题干"
    if len(a) > 200:
        return "G2-需复核", f"过长({len(a)}字)，吞进相邻内容"
    if FIG_REF.search(a) and len(a) < 60:
        return "G2-需复核", "答案主体是图注（邻题图表）"
    return "G1-可用", f"答案段干净完整({len(a)}字)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-all", action="store_true", help="打印全部明细")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    with open(SRC_JSON, encoding="utf-8") as f:
        data = json.load(f)
    det = data["detail"]
    print(f"命中总数: {len(det)}\n")

    stat = Counter()
    by_hit = Counter()
    rows = []
    for d in det:
        g, why = grade(d.get("answer", ""))
        stat[g] += 1
        by_hit[(d.get("hit", "")[:40], g)] += 1
        rows.append({"id": d["id"], "grade": g, "why": why,
                     "source": d.get("source", ""), "hit": d.get("hit", ""),
                     "content": d.get("content", ""), "answer": d.get("answer", "")})

    print("=" * 76)
    print("一、质量分级")
    print("=" * 76)
    for k, v in stat.most_common():
        print(f"  {k}: {v}  ({v*100//max(1,len(det))}%)")

    print("\n二、按命中来源 × 等级")
    src_stat = Counter()
    for (hit, g), v in by_hit.items():
        src_stat[(hit, g)] += v
    for (hit, g), v in sorted(src_stat.items(), key=lambda x: -x[1])[:24]:
        print(f"  {v:>4}  {g:<10}{hit}")

    print("\n" + "=" * 76)
    print("三、G1-可用 明细（可直接写库的答案）")
    print("=" * 76)
    g1 = [r for r in rows if r["grade"] == "G1-可用"]
    for r in g1[: args.dump_all and len(g1) or 25]:
        print(f"\n[id={r['id']}] {r['why']} | hit={r['hit'][:50]}")
        print(f"  Q: {(r['content'] or '').replace(chr(10),' ')[:130]}")
        print(f"  A: {r['answer'][:220]}")

    if args.dump_all:
        print("\n" + "=" * 76)
        print("四、G2-需复核 明细")
        print("=" * 76)
        for r in [x for x in rows if x["grade"] == "G2-需复核"]:
            print(f"\n[id={r['id']}] {r['why']} | hit={r['hit'][:50]}")
            print(f"  Q: {(r['content'] or '').replace(chr(10),' ')[:130]}")
            print(f"  A: {r['answer'][:200]}")

    print("\n" + "=" * 76)
    print("四、结论（准确条数）")
    print("=" * 76)
    print(f"  可直接写库（G1）        : {stat['G1-可用']}")
    print(f"  需人工复核（G2）        : {stat['G2-需复核']}")
    print(f"  不可用（G3）            : {stat['G3-不可用']}")
    print(f"  → 自动补答案的安全条数  : {stat['G1-可用']}（建议这批做 --apply，其余只入库到待复核表）")

    if args.json_out:
        out = os.path.join(BASE_DIR, args.json_out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"stat": dict(stat), "rows": rows}, f, ensure_ascii=False, indent=2)
        print(f"\n[JSON] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
