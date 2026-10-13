# -*- coding: utf-8 -*-
"""考研通知噪声识别（dry-run 默认，只报数 + 抽样，不写库）。

背景
----
用户是**硕士考生**。实测全库 1002 条通知里：
* 纯「公告」类 693 条，混入大量节气/人名/节日祝福/栏目名/赛事活动内容；
* 46 所院校中有 8 所「招生核心类 = 0」（如桂林电子科技大学 50 条通知全是噪声）。

已有的降级信号（`services/kaoyan/notice_rules.yaml` 的 keyword_rules）只覆盖
「党务/活动类」28 条 + 「纯博士相关」167 条 = 195 条（19.5%），
**节气/人名/节日祝福/栏目名这批完全没被覆盖**。

设计原则（防误杀）
----------------
1. **优先复用已有信号**：先统计 `importance_reason` 里已命中的降级规则，
   只对"未被覆盖"的部分新增判据。
2. **高精度优先，宁缺勿滥**：每条判据都要求**短标题精确匹配**或
   **强特征词**，避免把「光电工程学院2027年硕士研究生招生简章」
   这类真通知误杀。
3. 所有判据输出「置信度」：high = 可自动隔离，review = 需人工确认。
4. **本脚本不写库**，只报数和抽样，等 team-lead 核对后再决定写库方式。

用法
----
    python scripts/detect_notice_noise.py            # dry-run，报数 + 抽样
    python scripts/detect_notice_noise.py --full      # 打印全量命中清单
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"

# --------------------------------------------------------------------------- #
# 已有的降级信号（与 notice_rules.yaml 的 reason 文案保持一致）
# --------------------------------------------------------------------------- #
EXISTING_NOISE_REASONS = [
    "与考研无关的党务/活动类",
    "纯博士相关",
]

# --------------------------------------------------------------------------- #
# 招生核心词：命中任一即"不是噪声"，一票否决（防误杀的第一道闸）
# --------------------------------------------------------------------------- #
ADMISSION_WORDS = [
    "招生", "简章", "章程", "专业目录", "目录", "考试大纲", "大纲", "参考书目",
    "报名", "复试", "调剂", "录取", "拟录取", "分数线", "国家线", "初试",
    "推免", "免试", "夏令营", "预推免", "考点", "准考证", "考试安排",
    "培养方案", "学费", "学制", "奖助", "科目", "成绩", "查分",
    "硕士学位", "博士学位", "研究生院", "研招办", "专项计划", "骨干计划",
    "士兵计划", "同等学力", "专业学位", "学术学位",
]

# --------------------------------------------------------------------------- #
# 判据 1：二十四节气（标题**就是**节气名，精确匹配）
# --------------------------------------------------------------------------- #
SOLAR_TERMS = {
    "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑",
    "立秋", "处暑", "白露", "秋分", "寒露", "霜降",
    "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
}

# --------------------------------------------------------------------------- #
# 判据 2：节日/祝福语
# --------------------------------------------------------------------------- #
FESTIVAL_WORDS = [
    "中秋", "元宵", "新春", "元旦", "端午", "粽", "劳动节", "三八",
    "妇女节", "青年节", "国庆", "七夕", "春节", "过年", "拜年",
    "阖家", "祝福", "安康", "喜乐", "岁序", "辞旧",
    "劳动最光荣", "庆祝.*成立", "建党", "建军",
]

# --------------------------------------------------------------------------- #
# 判据 3：栏目名 / 导航项（短标题 + 常见栏目后缀）
# --------------------------------------------------------------------------- #
#: 零宽/不可见字符：库内有标题带 U+200B 零宽空格（如 "\u200b王敬宇"），
#: 不剥离会导致长度判断和精确匹配全部失效。
_INVISIBLE_RE = re.compile(r"[\u200b-\u200d\ufeff\u00a0\s]+")

COLUMN_PATTERNS = [
    r"^(现任|历任|第?\d+届)?领导",
    r"^(学校|我校|学院)?(简介|概况|章程)$",
    r"^(校园|学校)?(地图|风貌|掠影|晨曦|风光|美景)$",
    r"^(学报|校报|期刊|简报)$",
    r"^(组织机构|院系设置|部门设置)$",
    r"^[^\s]{2,10}(工程学院|学院|学部|研究院)$",
    r"^(通知公告|公告|新闻|动态|首页)$",
    # 外部站点导航项（如「广西互联网违法和不良信息举报中心」）
    r"举报中心$",
]

# --------------------------------------------------------------------------- #
# 判据 4：赛事 / 活动 / 党务行政
# --------------------------------------------------------------------------- #
EVENT_WORDS = [
    "竞赛", "挑战赛", "锦标赛", "巡回赛", "联赛", "运动会", "球赛",
    "研讨会", "座谈会", "论坛", "报告会", "开幕式", "闭幕式", "典礼",
    "慰问", "考察", "调研", "走访", "座谈", "授牌", "签约", "揭牌",
    "义诊", "演出", "晚会", "文化节", "艺术节", "开放日",
    "主题党日", "党史", "党课", "组织生活", "党员", "党组织",
    "中华民族", "统一战线", "统战",
]


def has_admission_word(title: str) -> bool:
    return any(w in title for w in ADMISSION_WORDS)


def classify_noise(title: str) -> tuple[str, str]:
    """返回 (判据标签, 置信度)。非噪声返回 ("", "")。

    置信度：
      high   —— 标题即节气名 / 纯祝福语 / 明显栏目名，可自动隔离
      review —— 赛事活动类，可能误伤「XX竞赛获奖名单」这类对考生有用的信息
    """
    # 先剥离零宽/不可见字符，否则长度判断与精确匹配都会失效
    # （实例：库内 id=388 标题是 "\u200b王敬宇"，带零宽空格前缀）
    t = _INVISIBLE_RE.sub("", title or "").strip()
    if not t:
        return "", ""

    # ---- 判据 1：节气（精确匹配，最高精度）----
    if t in SOLAR_TERMS:
        return "节气", "high"

    # ---- 判据 2：节日/祝福语 ----
    # 要求：标题含节日词 且 不含任何招生词 且 标题较短（避免长公告里提到节日）
    if any(re.search(w, t) for w in FESTIVAL_WORDS) and not has_admission_word(t) and len(t) <= 20:
        return "节日祝福", "high"

    # ---- 判据 3：栏目名 / 导航项 ----
    for pat in COLUMN_PATTERNS:
        if re.match(pat, t) and not has_admission_word(t):
            return "栏目名", "high"

    # ---- 判据 4：赛事 / 活动 / 党务 ----
    if any(w in t for w in EVENT_WORDS) and not has_admission_word(t):
        return "赛事活动", "review"

    # ---- 判据 5：极短人名标题（2-4 字，无招生词，非栏目名）----
    # 实例：徐华蕊 / 张文涛 / 王敬宇（桂电的人名导航项）
    if (2 <= len(t) <= 4 and re.fullmatch(r"[\u4e00-\u9fa5]+", t)
            and not has_admission_word(t)):
        return "疑似人名", "review"

    return "", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="打印全量命中清单")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT id, school_id, school_name, title, notice_type, "
            "       publish_date, importance_reason, url "
            "FROM kaoyan_notices ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    total = len(rows)
    print("=" * 76)
    print("考研通知噪声识别（dry-run，未写库）")
    print("=" * 76)
    print(f"  全库通知总数: {total}")

    # ---- 已有降级信号 ----
    already = 0
    for r in rows:
        reason = (r[6] or "")
        if any(k in reason for k in EXISTING_NOISE_REASONS):
            already += 1
    print(f"  已被现有规则降级: {already} 条 ({already / total * 100:.1f}%)")

    # ---- 新增判据（只对未被现有规则覆盖的行生效）----
    new_hits: list[tuple] = []
    by_kind: Counter = Counter()
    by_conf: Counter = Counter()
    for r in rows:
        reason = (r[6] or "")
        if any(k in reason for k in EXISTING_NOISE_REASONS):
            continue  # 已覆盖，不重复计数
        kind, conf = classify_noise(r[3])
        if kind:
            new_hits.append((r, kind, conf))
            by_kind[kind] += 1
            by_conf[conf] += 1

    print()
    print("=" * 76)
    print("新增判据命中（未被现有规则覆盖的部分）")
    print("=" * 76)
    for kind, n in by_kind.most_common():
        print(f"  {kind:12s} {n:4d} 条")
    print(f"  {'合计':12s} {len(new_hits):4d} 条  "
          f"(high={by_conf['high']} / review={by_conf['review']})")
    print()
    print(f"  降级后总噪声 = {already} + {len(new_hits)} = {already + len(new_hits)} 条 "
          f"({(already + len(new_hits)) / total * 100:.1f}%)")

    # ---- 抽样 ----
    print()
    print("=" * 76)
    print("抽样（每类前 12 条，供人工核对误杀风险）")
    print("=" * 76)
    for kind in ["节气", "节日祝福", "栏目名", "赛事活动", "疑似人名"]:
        sub = [(r, c) for r, k, c in new_hits if k == kind]
        if not sub:
            continue
        print()
        print(f"--- {kind}（{len(sub)} 条）---")
        for r, conf in sub[:12]:
            print(f"  [{conf:6s}] id={r[0]:<5} {r[2][:12]:14s} | {r[3][:40]}")

    # ---- 院校维度：哪些学校噪声最集中 ----
    print()
    print("=" * 76)
    print("噪声最集中的院校 TOP15（新增判据口径）")
    print("=" * 76)
    by_school: Counter = Counter()
    for r, _kind, _conf in new_hits:
        by_school[r[2]] += 1
    for name, n in by_school.most_common(15):
        tot = sum(1 for r in rows if r[2] == name)
        print(f"  {name[:16]:18s} 新增噪声 {n:3d} / 该校通知 {tot:3d} 条 "
              f"({n / tot * 100:.0f}%)")

    # ---- 招生核心类 = 0 的院校（噪声导致"零招生信息"）----
    print()
    print("=" * 76)
    print("招生核心类 = 0 的院校（含新增噪声判据后的复算）")
    print("=" * 76)
    CORE = ("简章", "目录", "大纲", "调剂", "录取", "复试")
    agg: dict[str, list[int]] = {}
    for r in rows:
        a = agg.setdefault(r[2], [0, 0])
        a[0] += 1
        if r[4] in CORE:
            a[1] += 1
    zero = [(n, v) for n, v in agg.items() if v[1] == 0]
    for n, v in sorted(zero, key=lambda kv: -kv[1][0]):
        print(f"  {n[:16]:18s} 总通知 {v[0]:3d} / 招生核心类 0")
    print(f"  合计 {len(zero)} 所")

    if args.full:
        print()
        print("=" * 76)
        print("全量命中清单")
        print("=" * 76)
        for r, kind, conf in new_hits:
            print(f"  [{conf:6s}] {kind:6s} id={r[0]:<5} {r[2][:14]:16s} | {r[3]}")
    else:
        print()
        print("[dry-run] 未写库。加 --full 看全量清单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
