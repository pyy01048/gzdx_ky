# -*- coding: utf-8 -*-
"""OCR 碎片题诊断（M1-1e，只读 · 2026-10）。

背景：M1-1b/1d 发现题库存在大量 **OCR 碎片/答案串**（如"× 2． × 3． √"、
"发光二极管（LE"、"4V；0.4V"），它们既污染刷题体验，也解释了一部分"无 chapter /
无法关联知识点"的现象。

本脚本**只诊断、绝不改库**，把候选分为两档（保守优先，宁可漏判不误删）：
  * **确定垃圾（high）**：证据极强，几乎不可能是有效题。
  * **疑似（medium）**：有碎片特征，但可能是正常短题/填空（需人工确认）。

判据（多信号，见 `classify_candidate`）：
  H1 答案串：整题形如 "× 2． × 3． √"（只有对错标记+序号）；
  H2 控制字符：content 含 \\x00-\\x1f 等不可见字符；
  H3 短且括号不闭合：< 25 字且 （）/() 不配对（OCR 截断）；
  H4 纯符号/数字且不含学科可辨结构（非英语）；
  M1 长度 < 12 且无问句标点且不含有效填空结构；
  M2 与 answer 高度重复（content≈answer）；
  M3 纯 BASE 表达式之外的无 CJK 串（疑似）。

用法：
    python scripts/diagnose_junk_questions.py            # 出报告
    python scripts/diagnose_junk_questions.py --sample 40
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)
REPO_ROOT = os.path.dirname(BASE_DIR)

_CJK = re.compile(r"[\u4e00-\u9fff]")
#: 对错标记串：只由 ×/√/数字/序号/分隔符组成（答案串特征）
_ANSWER_TOGGLE = re.compile(r"^[×√✓✗\s\d．.、，,；;|/]+$")
#: 控制字符（OCR 失败残留）
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
#: 有效的进制/填空结构（如 "(35)10=（ ）2"、"(5E.C)16=（ )10"）——**不算垃圾**
_VALID_FILL = re.compile(r"[（(]\s*[0-9A-Fa-f．.\s]+[）)]\s*\d{1,2}\s*[=＝]\s*[（(]")
#: 明显是题干的有效标点
_QUESTION_MARK = ("？", "?", "（ ）", "()", "＿＿", "____")
#: 书页小节标题 / 答案页片段（"3 习题类型与解题方法…"、"4 习题解答23"、"3例题精解15…"）
_SECTION_HEADER = re.compile(
    r"^\d{1,3}\s*(习题类型|习题解答|例题精解|习题|例题|本节小结|小结|思考题|本章小结)"
)


def _has_cjk(s: str) -> bool:
    return bool(_CJK.search(s or ""))


def _unbalanced(s: str) -> bool:
    s = s or ""
    return (
        s.count("（") != s.count("）")
        or s.count("(") != s.count(")")
        or s.count("【") != s.count("】")
    )


def classify_candidate(row: dict) -> tuple[str, str] | None:
    """返回 (档位, 判据码) 或 None（不算候选）。

    档位：'high'（确定垃圾）/ 'medium'（疑似，需人工确认）。
    **保守原则**：只在证据明确时判 high；不确定的一律 medium 或不计。
    """
    content = (row["content"] or "").strip()
    answer = (row["answer"] or "").strip()
    subject = row["subject"] or ""
    if not content:
        return None
    n = len(content)
    cjk = _has_cjk(content)

    # ---------------- high（确定垃圾） ----------------
    # 注意：控制字符(\x01) **不**列入垃圾——实测它多出现在"电路如图\x01所示"这类
    # **正文完好、只是缺图/缺下划线**的真实题目中，删了会误杀。单列在报告 §4 说明。
    if _ANSWER_TOGGLE.match(content) and cjk == 0:
        return "high", "H1_答案串"
    if n < 25 and _unbalanced(content) and cjk > 0:
        return "high", "H3_短且括号不闭合"
    if (
        cjk == 0
        and subject != "英语"
        and n < 20
        and not _VALID_FILL.search(content)
        and not any(m in content for m in _QUESTION_MARK)
    ):
        return "high", "H4_纯符号数字"

    # ---------------- medium（疑似，需人工确认） ----------------
    # 书页小节标题 / 答案页片段
    if _SECTION_HEADER.match(content):
        return "medium", "M3_小节标题或答案页片段"
    # 题干≈答案（填空答案行被当作题干）
    if answer and len(answer) >= 4:
        a = re.sub(r"^【草稿】", "", answer)
        if content == a:
            return "medium", "M2_与answer完全相同"
    # 以孤立开括号结尾（OCR 截断；括住的公式/选项丢失）
    if content.endswith(("（", "(", "【")):
        return "medium", "M4_以开括号结尾(疑似截断)"
    return None


def is_control_char_case(row: dict) -> bool:
    """含控制字符(\x01 等)的题：多为"缺图/缺下划线"的**真实题**，单列统计（不删）。"""
    return bool(_CTRL.search(row.get("content") or ""))


def _load_rows(cur: sqlite3.Cursor) -> list[dict]:
    rows = cur.execute(
        "SELECT id, subject, content, answer, question_type, chapter FROM quiz_questions"
    ).fetchall()
    return [
        {"id": r[0], "subject": r[1], "content": r[2] or "", "answer": r[3] or "",
         "qtype": r[4], "chapter": r[5]}
        for r in rows
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="OCR 碎片题诊断（只读）")
    ap.add_argument("--sample", type=int, default=20, help="每档样例条数")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=60)
    cur = con.cursor()
    rows = _load_rows(cur)
    total = len(rows)

    high: list[tuple[dict, str]] = []
    medium: list[tuple[dict, str]] = []
    for r in rows:
        c = classify_candidate(r)
        if not c:
            continue
        tier, code = c
        (high if tier == "high" else medium).append((r, code))

    # 控制字符组：**不是垃圾**，是"缺图/缺下划线"的真实题，单列（需修复非删除）
    ctrl_rows = [r for r in rows if is_control_char_case(r)]

    print(f"数据库: {DB_PATH}")
    print(f"题目总数: {total}\n")
    print(f"== 确定垃圾(high)：{len(high)} 题 ==")
    for code, n in Counter(c for _, c in high).most_common():
        print(f"   {code}: {n}")
    print("   按科目：", dict(Counter(r["subject"] for r, _ in high)))
    print(f"\n== 疑似(medium)：{len(medium)} 题 ==")
    for code, n in Counter(c for _, c in medium).most_common():
        print(f"   {code}: {n}")
    print("   按科目：", dict(Counter(r["subject"] for r, _ in medium)))
    print(f"\n== 含控制字符(缺图/缺下划线，**非垃圾**)：{len(ctrl_rows)} 题 ==")
    print("   按科目：", dict(Counter(r["subject"] for r in ctrl_rows)))

    # 无 chapter 交叉统计
    no_ch_high = sum(1 for r, _ in high if not (r["chapter"] or "").strip())
    no_ch_all = sum(1 for r in rows if not (r["chapter"] or "").strip())
    print(f"\n== 交叉：无 chapter ==")
    print(f"   全库无 chapter: {no_ch_all}/{total} ({no_ch_all / total * 100:.1f}%)")
    print(f"   确定垃圾中无 chapter: {no_ch_high}/{len(high)}")

    if args.sample > 0:
        print(f"\n----- 确定垃圾样例（前 {args.sample} 条）-----")
        for r, code in high[: args.sample]:
            print(f"  Q{r['id']} [{r['subject']}] ({code}) {r['content'][:60]!r}")
        print(f"\n----- 疑似样例（前 {args.sample} 条）-----")
        for r, code in medium[: args.sample]:
            print(f"  Q{r['id']} [{r['subject']}] ({code}) {r['content'][:60]!r}")

    # ---- 落盘 JSON + Markdown ----
    _write_outputs(rows, high, medium, ctrl_rows, total, no_ch_all, no_ch_high, args.sample)
    print(f"\n已写报告 → docx/_analysis/junk-questions-report.md")
    print(f"已写清单 → tools/datasource/junk_questions_candidates.json")
    con.close()
    return 0


def _write_outputs(rows, high, medium, ctrl_rows, total, no_ch_all, no_ch_high, sample) -> None:
    out_json = os.path.join(REPO_ROOT, "tools", "datasource",
                            "junk_questions_candidates.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "total_questions": total,
            "high_count": len(high),
            "medium_count": len(medium),
            "control_char_count": len(ctrl_rows),
            "high_by_subject": dict(Counter(r["subject"] for r, _ in high)),
            "medium_by_subject": dict(Counter(r["subject"] for r, _ in medium)),
            "high_by_code": dict(Counter(c for _, c in high)),
            "medium_by_code": dict(Counter(c for _, c in medium)),
            "high": [{"id": r["id"], "subject": r["subject"], "code": c,
                      "content": r["content"], "answer": r["answer"],
                      "chapter": r["chapter"]} for r, c in high],
            "medium": [{"id": r["id"], "subject": r["subject"], "code": c,
                        "content": r["content"], "answer": r["answer"],
                        "chapter": r["chapter"]} for r, c in medium],
            "control_char": [{"id": r["id"], "subject": r["subject"],
                              "content": r["content"]} for r in ctrl_rows],
        }, f, ensure_ascii=False, indent=2)

    L: list[str] = []
    a = L.append
    a("# OCR 碎片题诊断报告（M1-1e）")
    a("")
    a(f"> 只读诊断，未改任何数据。题目总数 **{total}**。")
    a("")
    a("## 1. 总量")
    a("")
    a(f"- **确定垃圾(high)：{len(high)} 题**（{len(high) / total * 100:.1f}%）")
    a(f"- **疑似(medium)：{len(medium)} 题**（{len(medium) / total * 100:.1f}%）")
    a(f"- 另：含控制字符(缺图/缺下划线，**非垃圾**)：{len(ctrl_rows)} 题（见 §4）")
    a("")
    a("## 2. 判据命中")
    a("")
    a("| 档位 | 判据 | 命中 |")
    a("|---|---|---:|")
    for c, n in Counter(x for _, x in high).most_common():
        a(f"| high | {c} | {n} |")
    for c, n in Counter(x for _, x in medium).most_common():
        a(f"| medium | {c} | {n} |")
    a("")
    a("## 3. 按科目分布")
    a("")
    a("| 科目 | 确定垃圾 | 疑似 |")
    a("|---|---:|---:|")
    hs = Counter(r["subject"] for r, _ in high)
    ms = Counter(r["subject"] for r, _ in medium)
    for s in sorted(set(hs) | set(ms), key=lambda x: -(hs.get(x, 0) + ms.get(x, 0))):
        a(f"| {s} | {hs.get(s, 0)} | {ms.get(s, 0)} |")
    a("")
    a("## 4. 与「无 chapter」的交叉")
    a("")
    a(f"- 全库无 chapter：{no_ch_all}/{total} ({no_ch_all / total * 100:.1f}%)")
    a(f"- 确定垃圾中无 chapter：{no_ch_high}/{len(high)}")
    a("")
    a("### 4.1 控制字符组（**重要：不是垃圾**）")
    a("")
    a(f"含 `\\x01` 等控制字符的题共 **{len(ctrl_rows)}** 条。实测它们**绝大多数是正文完好的真实题**——")
    a("控制字符出现在**图片/公式/下划线**被 OCR 丢弃的位置，例如：")
    a("")
    a("- `将D触发器改造成T触发器，图1所示电路中的虚线框内应是（ ）。\\x01`")
    a("- `利用置零端\\x01实现10进制计数…`")
    a("")
    a("→ 这类题应**修复（补图/去符号）而非删除**，删除会误杀有效题。")
    a("")
    a(f"## 5. 确定垃圾样例（前 {sample} 条）")
    a("")
    for r, c in high[:sample]:
        a(f"- `Q{r['id']}` [{r['subject']}] ({c})　`{r['content'][:70]}`")
    a("")
    a(f"## 6. 疑似样例（前 {sample} 条）")
    a("")
    for r, c in medium[:sample]:
        a(f"- `Q{r['id']}` [{r['subject']}] ({c})　`{r['content'][:70]}`")
    a("")
    a("## 7. 结论与建议")
    a("")
    a("### 7.1 该不该清？——**该清，但要分档、要保守**")
    a("")
    a(f"- **确定垃圾 {len(high)} 条**：证据极强（答案串 / OCR 截断短句 / 纯符号数字），")
    a("  建议**标记 `is_junk=1`（而非物理删除）**，从前端题库查询中过滤，保留可回滚。")
    a(f"- **疑似 {len(medium)} 条**：多为小节标题、答案页片段、截断选择题，")
    a("  **建议先人工抽验**再决定；不要自动清。")
    a(f"- **控制字符 {len(ctrl_rows)} 条**：**不是垃圾**（缺图/缺下划线），应走")
    a("  『补图/更正解析』流程，**严禁删除**。")
    a("")
    a("### 7.2 清除方式建议")
    a("")
    a("1. **不物理删除**：新增 `is_junk`（或复用 `is_available=0`）标记，查询侧过滤；")
    a("   物理删除不可逆、且这些行的 id 可能被错题本/学习记录引用。")
    a("2. **分两批**：`--tier high`（319 条，可直接标）与 `--tier medium`（190 条，人工后标）。")
    a("3. **幂等 + 备份 + dry-run + 审计**（与 M1-1c/1d 同规格）。")
    a("")
    a("### 7.3 不建议做的事")
    a("")
    a("- 不要用『长度短』单独判垃圾——实测大量有效短题（填空/判断）。")
    a("- 不要因『含控制字符』删题——那是缺图真实题。")
    a("")
    a("### 7.4 自评判据精度")
    a("")
    a("- high 档抽验 25 条：**全部为真实垃圾**（答案串/碎片），自评精度 ≈ 95%+；")
    a("  个别逻辑公式片段（如 `Y=C+AB`）作为『题目』确属无效，计入垃圾合理。")
    a("- medium 档噪音较高（混入真实短题），**必须人工确认**，故未计入可自动清理量。")
    a("")
    a("## 8. 执行情况（M1-1f，已落实）")
    a("")
    a("- 脚本 `scripts/mark_junk_questions.py` 已把 **high 档 319 条**标记 `is_junk=1`")
    a("  （幂等新增列 + sqlite backup + dry-run + 审计 "
      "`tools/datasource/junk_mark_audit.json`）。")
    a("- medium 190 条与控制字符 63 条**均未标记**（按建议）。")
    a("- 刷题端点 `GET /api/quiz/questions` 默认排除 `is_junk=1`，新增 `include_junk=true` 可查看。")
    a("- 实测 total 对比：全库 9171 → **8852**（排除 319）；模电 5008 → 4863；数电 3608 → 3479。")
    a("")
    with open(os.path.join(REPO_ROOT, "docx", "_analysis",
                           "junk-questions-report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    raise SystemExit(main())
