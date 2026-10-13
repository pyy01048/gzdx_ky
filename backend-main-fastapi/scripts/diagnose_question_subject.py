# -*- coding: utf-8 -*-
"""quiz_questions 科目字段错配诊断（M1-1b，只读��2026-10）。

背景：M1-1 知识点关联回填时发现，剩余未链题**大量是科目字段写错**——
如 `subject='政治'` 的 814 题里混入成百道**模电/数电（半导体、放大器、逻辑门）**内容；
这类题在本学科知识点里找不到匹配，导致关联覆盖率上不去。

本脚本**只诊断、绝不改库**：
  1. 用分科术语词典对每题题干做关键词命中，判断"内容实际属于哪个科目"；
  2. 与现行 `subject` 不一致且证据充分者，列入**错配清单**；
  3. 统计"无 chapter"题的科目分布（决定知识点关联的天花板）；
  4. 落盘：`docx/_analysis/question-subject-mismatch.md`（人读）
          `tools/datasource/question_subject_mismatch.json`（结构化，供修复脚本用）。

用法：
    python scripts/diagnose_question_subject.py            # 直接跑（只读）
    python scripts/diagnose_question_subject.py --sample 40
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)
REPO_ROOT = os.path.dirname(BASE_DIR)  # D:\平台


# --------------------------------------------------------------------------- #
# 分科术语词典（高区分度：命中即强烈指向该科目；不含"电路/信号"这类跨科泛词）
# --------------------------------------------------------------------------- #
LEXICON: dict[str, list[str]] = {
    # 数字电子技术：逻辑代数 / 门电路 / 时序 / 存储 / 转换
    "数字电子技术": [
        "逻辑函数", "逻辑表达式", "逻辑代数", "卡诺图", "真值表", "最小项", "最大项",
        "与非门", "或非门", "与门", "或门", "异或", "同或", "门电路", "三态门",
        "组合逻辑", "时序逻辑", "触发器", "JK触发器", "D触发器", "RS触发器", "T触发器",
        "计数器", "寄存器", "移位寄存器", "译码器", "编码器", "数据选择器", "数据分配器",
        "竞争冒险", "同步时序", "异步时序", "进制", "数制", "二进制", "十六进制",
        "格雷码", "BCD", "功耗", "TTL", "CMOS", "555", "施密特", "多谐振荡",
        "D/A转换", "A/D转换", "数模转换", "模数转换", "采样保持", "量化误差",
        "D/A转换器", "A/D转换器", "DA转换", "AD转换", "数字量", "模拟量",
        "半导体存储", "ROM", "RAM", "EPROM", "EEPROM", "可编程逻辑",
        "CB7520", "AD7524", "AD7533", "74161", "移位寄存器", "并行比较", "逐次逼近",
    ],
    # 模拟电子技术：器件 / 放大 / 运放 / 电源 / 振荡 / 频率响应
    "模拟电子技术": [
        "二极管", "三极管", "晶体管", "场效应管", "场效应", "PN结", "P型半导体", "N型半导体",
        "共射", "共集", "共基", "放大电路", "放大器", "多级放大", "差动放大", "差分放大",
        "静态工作点", "偏置电路", "分压式偏置", "射极输出", "射极跟随", "共模", "差模",
        "运算放大", "运放", "集成运放", "电压比较器", "有源滤波", "模拟乘法器",
        "负反馈", "正反馈", "反馈组态", "深度负反馈", "自激振荡",
        "整流", "桥式整流", "滤波电路", "稳压", "稳压二极管", "直流电源", "功率放大",
        "甲类", "乙类", "甲乙类", "交越失真", "波特图", "频率响应", "上限频率", "下限频率",
        "通频带", "截止频率", "放大倍数", "输入电阻", "输出电阻", "耦合", "阻容耦合",
        "变容二极管", "光电二极管", "稳压管", "振荡器", "振荡电路", "LC振荡", "RC振荡",
    ],
    # 政治
    "政治": [
        "马克思主义", "毛泽东", "中国特色", "社会主义", "唯物", "唯心", "辩证法", "矛盾",
        "实践", "生产力", "生产关系", "近代史", "思想道德", "法治", "时政", "毛中特",
        "史纲", "马原", "生产力", "上层建筑", "经济基础", "剩余价值", "剥削", "阶级",
        "人民群众", "社会存在", "社会意识", "认识论", "真理", "价值规律",
        "半殖民地", "鸦片战争", "五四运动", "改革开放", "中国特色社会主义",
    ],
    # 计算机学科专业基础408
    "计算机学科专业基础408": [
        "数据结构", "线性表", "链表", "栈", "队列", "二叉树", "哈夫曼", "图的遍历",
        "最短路径", "拓扑排序", "快速排序", "堆排序", "哈希", "B树", "红黑树",
        "计算机组成", "指令系统", "流水线", "Cache", "虚拟内存", "操作系统", "进程",
        "线程", "死锁", "页面置换", "文件系统", "计算机网络", "TCP", "IP协议",
        "路由算法", "滑动窗口", "OSI", "页表", "中断向量", "总线",
    ],
    # 数学
    "数学": [
        "极限", "导数", "微分", "积分", "级数", "矩阵", "行列式", "特征值", "向量组",
        "概率", "分布", "期望", "方差", "洛必达", "中值定理", "偏导", "二重积分",
        "微分方程", "泰勒", "拐点", "渐近线", "函数", "连续", "可导",
    ],
    # 英语
    "英语": [
        "词汇", "阅读理解", "完形填空", "翻译", "作文", "语法", "长难句", "短语",
        "从句", "词义", "同义词", "passage", "underlined", "according to",
        "the author", "paragraph", "following",
    ],
}

#: 判定为"电子类"（数电或模电）时用于最终归科的比较键
ELEC_SUBJECTS = ("数字电子技术", "模拟电子技术")


def _normalize(text: str) -> str:
    """归一化：去掉空白，并把全角/异形符号折叠为半角，提升术语命中率。

    实测题库 OCR 常把 `/` 写成 `／`、`A/D` 写成 `A／D `、`Iᴄ` 等，
    不做归一化会漏掉大量 "D/A转换"、"A/D转换" 命中。
    """
    if not text:
        return ""
    t = text.replace("\u3000", "").replace(" ", "").replace("\t", "")
    trans = str.maketrans({
        "／": "/", "（": "(", "）": ")", "，": ",", "：": ":", "；": ";",
        "Ａ": "A", "Ｄ": "D", "Ｃ": "C", "Ｂ": "B",
        "－": "-", "―": "-", "．": ".", "、": "",
    })
    return t.translate(trans)


def _hit_count(text: str, terms: list[str]) -> tuple[int, list[str]]:
    """返回 (命中数, 命中词列表)。text 需已归一化；术语在词典中同样以归一化形式书写。"""
    if not text:
        return 0, []
    hits = [t for t in terms if t in text]
    return len(hits), hits


def _score_all(text: str) -> tuple[str, int, dict, list[str]]:
    """对题干跑全部词典，返回 (最佳科目, 最佳分, 各科分, 最佳科命中词)。"""
    norm = _normalize(text)
    scores: dict[str, int] = {}
    hits_by: dict[str, list[str]] = {}
    for subj, terms in LEXICON.items():
        n, hits = _hit_count(norm, terms)
        scores[subj] = n
        hits_by[subj] = hits
    if not scores:
        return "", 0, {}, []
    best = max(scores, key=lambda s: scores[s])
    return best, scores[best], scores, hits_by[best]


def _load_rows(cur: sqlite3.Cursor) -> list[dict]:
    rows = cur.execute(
        "SELECT id, subject, chapter, content, question_type FROM quiz_questions"
    ).fetchall()
    return [
        {"id": r[0], "subject": r[1], "chapter": r[2],
         "content": r[3] or "", "qtype": r[4]}
        for r in rows
    ]


def _estimate_kp_recovery(
    cur: sqlite3.Cursor, mismatch: list[dict], linked_ids: set[int]
) -> dict:
    """估算"若按建议科目改写后，能挽回多少同科目知识点关联"。

    复用 M1-1 的回填第 2 层判据（`match_question_rule`），对每条错配题
    用"建议科目"重新匹配一次，判断是否能新增一条**同科目**知识点链。
    仅作收益量级参考，不写库。任何导入/异常都降级为 0（只读诊断不因它失败）。
    """
    try:
        from scripts.backfill_kp_links_v2 import (
            _load_points, _points_by_subject, match_question_rule,
        )

        points = _load_points(cur)
        by_subj = _points_by_subject(points)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:120]}", "recovered": 0}

    qmap: dict[int, dict] = {}
    for m in mismatch:
        qmap[m["id"]] = {
            "id": m["id"], "subject": m["suggested_subject"],
            "chapter": m["chapter"], "content": m.get("snippet", ""),
        }
    # snippet 只有前 120 字，重取完整题干以保证匹配质量
    ids = list(qmap)
    placeholders = ",".join("?" * len(ids)) if ids else "NULL"
    full = {
        r[0]: r[1] for r in cur.execute(
            f"SELECT id, content FROM quiz_questions WHERE id IN ({placeholders})", ids
        )
    } if ids else {}
    for qid, q in qmap.items():
        q["content"] = full.get(qid, q["content"])

    recovered, already = 0, 0
    for qid, q in qmap.items():
        if qid in linked_ids:
            already += 1
            continue
        if match_question_rule(q, by_subj.get(q["subject"], [])):
            recovered += 1
    return {
        "mismatch_total": len(mismatch),
        "mismatch_already_linked": already,
        "mismatch_unlinked": len(mismatch) - already,
        "would_gain_same_subject_link": recovered,
        "note": "按建议科目重跑第2层判据后，可新增的同科目知识点关联题数（量级参考）",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="quiz_questions 科目字段错配诊断（只读）")
    ap.add_argument("--min-hits", type=int, default=2,
                    help="判定错配所需的最佳科目命中数下限（默认 2，加大更保守）")
    ap.add_argument("--min-margin", type=int, default=1,
                    help="最佳科目须领先次优科目的最小分差（默认 1）")
    ap.add_argument("--sample", type=int, default=30, help="报告样例条数")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=60)
    cur = con.cursor()
    rows = _load_rows(cur)
    # 已链知识点的题目 id（收益估算用）
    linked_ids = {r[0] for r in cur.execute(
        "SELECT DISTINCT question_id FROM question_knowledge_links")}

    total = len(rows)
    print(f"数据库: {DB_PATH}")
    print(f"题目总数: {total}\n")

    mismatch: list[dict] = []
    per_subject_total = Counter()
    per_subject_mismatch = Counter()
    no_chapter = Counter()

    for r in rows:
        s = r["subject"] or ""
        per_subject_total[s] += 1
        if not (r["chapter"] or "").strip():
            no_chapter[s] += 1

        best, best_score, scores, best_hits = _score_all(r["content"])
        if not best:
            continue
        # 次优科目分（排除最佳）
        second = max((v for k, v in scores.items() if k != best), default=0)
        # 错配判据：最佳科目 ≠ 现行科目；证据充分；且明确领先
        if (
            best != s
            and best_score >= args.min_hits
            and (best_score - second) >= args.min_margin
        ):
            mismatch.append({
                "id": r["id"],
                "current_subject": s,
                "suggested_subject": best,
                "evidence_hits": best_hits[:8],
                "scores": {k: v for k, v in scores.items() if v > 0},
                "chapter": r["chapter"],
                "qtype": r["qtype"],
                "snippet": r["content"][:120].replace("\n", " "),
            })
            per_subject_mismatch[s] += 1

    # ---- 控制台汇总 ----
    print("== 错配清单（按现行科目）==")
    for s in sorted(per_subject_total, key=lambda x: -per_subject_total[x]):
        m = per_subject_mismatch.get(s, 0)
        print(f"  {s:<24} 共 {per_subject_total[s]:>5}  错配 {m:>4} "
              f"({m / per_subject_total[s] * 100:.1f}%)")
    print(f"  ---- 合计错配 {len(mismatch)} 题")

    print("\n== 无 chapter 题（按科目）==")
    for s, n in no_chapter.most_common():
        print(f"  {s:<24} {n:>5} / {per_subject_total[s]:>5} "
              f"({n / per_subject_total[s] * 100:.1f}%)")
    print(f"  合计无 chapter {sum(no_chapter.values())} / {total} "
          f"({sum(no_chapter.values()) / total * 100:.1f}%)")

    # 建议科目分布
    sug = Counter(m["suggested_subject"] for m in mismatch)
    print("\n== 错配题的建议归属分布 ==")
    for s, n in sug.most_common():
        print(f"  → {s:<24} {n}")

    # ---- 收益估算 ----
    recovery = _estimate_kp_recovery(cur, mismatch, linked_ids)
    print("\n== 收益估算（修正 subject 后能挽回的同科目知识点关联）==")
    if "error" in recovery:
        print(f"  （估算跳过：{recovery['error']}）")
    else:
        print(f"  错配 {recovery['mismatch_total']} 题，其中已链 "
              f"{recovery['mismatch_already_linked']}、未链 {recovery['mismatch_unlinked']}")
        print(f"  修正后预计可新增同科目知识点链：{recovery['would_gain_same_subject_link']} 题")

    if args.sample > 0 and mismatch:
        print(f"\n----- 错配样例（前 {args.sample} 条）-----")
        for m in mismatch[: args.sample]:
            print(f"  Q{m['id']} [{m['current_subject']}→{m['suggested_subject']}] "
                  f"证据{m['evidence_hits'][:4]}\n      「{m['snippet'][:70]}」")

    # ---- 落盘 JSON ----
    out_json = os.path.join(REPO_ROOT, "tools", "datasource",
                            "question_subject_mismatch.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": DB_PATH,
        "params": {"min_hits": args.min_hits, "min_margin": args.min_margin},
        "total_questions": total,
        "mismatch_count": len(mismatch),
        "by_current_subject": {
            s: {"total": per_subject_total[s],
                "mismatch": per_subject_mismatch.get(s, 0)}
            for s in per_subject_total
        },
        "no_chapter_by_subject": dict(no_chapter),
        "suggested_distribution": dict(sug),
        "kp_recovery_estimate": recovery,
        "mismatches": mismatch,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n已写结构化清单 → {out_json}")

    # ---- 落盘 Markdown 报告 ----
    _write_markdown(payload, args.sample, out_json)
    print(f"已写报告 → docx/_analysis/question-subject-mismatch.md")
    con.close()
    return 0


def _write_markdown(payload: dict, sample: int, json_path: str) -> None:
    lines: list[str] = []
    a = lines.append
    a("# quiz_questions 科目字段错配诊断报告（M1-1b）")
    a("")
    a(f"> 生成时间：{payload['generated_at']}　数据库：`{payload['db_path']}`")
    a(f"> 只读诊断，未改任何数据。判据：最佳科目命中 ≥ {payload['params']['min_hits']} "
      f"且领先次优 ≥ {payload['params']['min_margin']}。")
    a("")
    a(f"题目总数 **{payload['total_questions']}**，检出疑似错配 **"
      f"{payload['mismatch_count']}** 题。")
    a("")

    a("## 1. 错配清单规模（按现行科目）")
    a("")
    a("| 现行科目 | 题目数 | 疑似错配 | 占比 |")
    a("|---|---:|---:|---:|")
    for s, d in sorted(payload["by_current_subject"].items(),
                       key=lambda kv: -kv[1]["mismatch"]):
        tot, m = d["total"], d["mismatch"]
        pct = (m / tot * 100) if tot else 0.0
        a(f"| {s} | {tot} | {m} | {pct:.1f}% |")
    a("")

    a("## 2. 无 chapter 题的科目分布（决定知识点关联天花板）")
    a("")
    a("| 科目 | 无 chapter | 该科总数 | 占比 |")
    a("|---|---:|---:|---:|")
    nc = payload["no_chapter_by_subject"]
    for s in sorted(nc, key=lambda x: -nc[x]):
        tot = payload["by_current_subject"].get(s, {}).get("total", 0)
        pct = (nc[s] / tot * 100) if tot else 0.0
        a(f"| {s} | {nc[s]} | {tot} | {pct:.1f}% |")
    total_nc = sum(nc.values())
    a(f"| **合计** | **{total_nc}** | **{payload['total_questions']}** | "
      f"**{total_nc / payload['total_questions'] * 100:.1f}%** |")
    a("")

    a("## 3. 错配题的建议归属分布")
    a("")
    a("| 建议科目 | 题数 |")
    a("|---|---:|")
    for s, n in sorted(payload["suggested_distribution"].items(), key=lambda kv: -kv[1]):
        a(f"| {s} | {n} |")
    a("")

    rec = payload.get("kp_recovery_estimate", {})
    a("## 4. 收益估算（修正 subject 对知识点关联的影响）")
    a("")
    if "error" in rec:
        a(f"- 估算跳过：{rec['error']}")
    else:
        a(f"- 错配题 {rec.get('mismatch_total', 0)} 题中，已链 {rec.get('mismatch_already_linked', 0)}、"
          f"未链 {rec.get('mismatch_unlinked', 0)}。")
        a(f"- 若按建议科目重跑知识点关联第 2 层判据，预计可**新增同科目知识点链 "
          f"{rec.get('would_gain_same_subject_link', 0)} 题**。")
        a("- 说明：科目纠错主要价值在**归类正确性/薄弱点分析/按知识点刷题**；"
          "对知识点关联覆盖率提升有限，因为多数错配题仍缺 `chapter`、题干也不含精确知识点名。")
    a("")

    a(f"## 5. 错配样例（前 {sample} 条）")
    a("")
    for m in payload["mismatches"][:sample]:
        a(f"- **Q{m['id']}** `{m['current_subject']}` → `{m['suggested_subject']}`　"
          f"证据：{ '、'.join(m['evidence_hits'][:5]) }")
        a(f"  - {m['snippet'][:100]}")
    a("")

    a("## 6. 说明与建议")
    a("")
    a("- 本报告仅列出**证据充分**的错配（命中 ≥ 阈值且领先次优科目），保守起见不含模糊项。")
    a("- `tools/datasource/question_subject_mismatch.json` 含全量清单，供修复脚本消费。")
    a("- 修复前建议人工抽验；修复需**幂等 + 备份 + dry-run + 标注 data_source**，"
      "由独立脚本 `fix_question_subject.py` 执行（本轮不做）。")
    a("")
    with open(os.path.join(REPO_ROOT, "docx", "_analysis",
                           "question-subject-mismatch.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
