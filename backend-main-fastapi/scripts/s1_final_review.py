# -*- coding: utf-8 -*-
"""S1 最终人工复核：把自动闸门结果 + 人工阅读判定合成最终四档结论（只读）。

自动闸门（s1_dryrun_answers.py）只能拦下明显的串题/碎片，
剩下"答案对不对题"必须人眼读一遍 —— 本文件就是那个人眼判定的记录。
"""

from __future__ import annotations

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "diagnostics"))

# id -> (档位, 判定说明)
#  A-确认可写    ：题对、答对、无截断、无串题
#  B-小瑕疵可写  ：题对答对，题干/答案有可修的小瑕疵（写库时顺带修）
#  C-需人工截断  ：题对但答案被 200 字上限截断，需放宽上限重抽
#  D-串题/不可用 ：答案与题面无关，或题面本身不可作答
MANUAL: dict[int, tuple[str, str]] = {
    875:  ("A", "题对答对无瑕疵"),
    997:  ("A", "题对答对无瑕疵"),
    4254: ("B", "答案正确；题干尾部混入下一题标题「二、选择题…」，写库时截掉"),
    489:  ("B", "答案正确；与 #829 为同一道题的重复条目，保留其一"),
    829:  ("B", "答案正确；与 #489 重复，保留其一"),
    564:  ("B", "答案正确；与 #1185 重复，保留其一"),
    1185: ("B", "答案正确；与 #564 重复，保留其一"),

    7953: ("C", "答案对但超 200 字被截断在「F＝D＋」，需放宽上限重抽"),
    7971: ("C", "答案对但截断在「((A\"B\")」，需放宽上限重抽"),
    5704: ("C", "题干带 OCR 噪声尾巴「Yzv)」；答案为整段推导，需人工确认完整结论"),
    5864: ("C", "题答对得上，但答案截断丢失了 (3)(4) 两小问"),
    7805: ("C", "答案截断在「ic/mA4」符号堆，结论未取到"),
    8556: ("C", "答案截断在「求电压放」，(2) 问未答"),
    8557: ("C", "题干含大量 OCR 噪声「Us.R 姬清影 'i Lv\"gm Va .二」，答案本身可用"),

    4380: ("D", "串题：题干问「30 个脉冲后计数值（选择题）」，答案却是另一题的卡诺图推导"),
    8641: ("D", "串题：题干问「RW 中点时 IEQ/Ad/Ri」，答案是另一题的简答 (1)(2)(3)(4)"),
    4339: ("D", "串题：题干问「555 单稳态波形与脉宽 tw」，答案讲多谐振荡器/施密特触发器"),
    4406: ("D", "串题：答案尾部串入下一题「8选1数据选择器 74HC151 产生 Y＝…」"),
    5857: ("D", "题干与答案均为 OCR 公式碎片，无可读题面"),
    7831: ("D", "答案为「(1)C(2)F(3)E(4」截断乱码"),
    6148: ("D", "题干为公式碎片「0iμF R R? R Rr 18kΩ…」，用户看不到题"),
    5923: ("D", "题干为频谱图 OCR 碎片「201g|AJ/dB 40| 60| -20 dB/十倍频…」"),
    5687: ("D", "题干本身已含「解：」完整解答，不是题目 —— 应隔离而非补答案"),
    4051: ("B", "题答对得上（逐项排除法，答案 D 集电极开路）；但 is_junk=1 且选项顺序错乱，建议先解隔离"),
    5869: ("D", "题干已含「解：」完整解答，题干本身不是题；答案本身正确 —— 与 5687 同类"),
}


def main() -> None:
    with open(os.path.join(OUT_DIR, "s1_dryrun_answers.json"), encoding="utf-8") as f:
        data = json.load(f)
    rows = {r["id"]: r for r in data["rows"]}

    buckets: dict[str, list[tuple[int, str]]] = {
        "A-确认可写": [], "B-小瑕疵可写": [], "C-需人工截断": [], "D-串题/不可用": [],
    }
    unjudged = []
    for qid, (grade, note) in MANUAL.items():
        buckets[{"A": "A-确认可写", "B": "B-小瑕疵可写",
                 "C": "C-需人工截断", "D": "D-串题/不可用"}[grade]].append((qid, note))
    # 自动闸门已拦、且人工表未覆盖的
    for qid, r in rows.items():
        if qid in MANUAL:
            continue
        auto = "；".join(r["answer_issues"] + r["content_issues"])
        if not r["ok"] or auto:
            buckets["D-串题/不可用"].append((qid, f"自动闸门已拦：{auto or '未通过'}"))
        else:
            unjudged.append(qid)

    L = ["=" * 78, "S1 最终四档结论（人工复核完成）  源池 = G1 69 条", "=" * 78]
    for k, items in buckets.items():
        L.append("")
        L.append(f"### {k}（{len(items)} 条）")
        for qid, note in sorted(items):
            L.append(f"  #{qid:<5} {note}")
    if unjudged:
        L.append("")
        L.append(f"### 未判定（{len(unjudged)} 条）: {unjudged}")

    n_a = len(buckets["A-确认可写"])
    n_b = len(buckets["B-小瑕疵可写"])
    n_c = len(buckets["C-需人工截断"])
    n_d = len(buckets["D-串题/不可用"])
    L.append("")
    L.append("=" * 78)
    L.append(f"汇总：69 条 → A {n_a} / B {n_b} / C {n_c} / D {n_d}")
    L.append(f"  可零风险写库 (A+B)      = {n_a + n_b} 条")
    L.append(f"  其中真正唯一（去掉4条重复）= {n_a + n_b - 4} 条")
    L.append(f"  放宽答案长度上限后可救回   = {n_c} 条（需重抽+再复核）")
    L.append(f"  应丢弃/隔离              = {n_d} 条")
    L.append("")

    text = "\n".join(L)
    with open(os.path.join(OUT_DIR, "s1_final_review.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
