# -*- coding: utf-8 -*-
"""`/import` 正文解析 —— 单测（纯函数层，不连库）。

覆盖 team-lead 指定的 5 类：
  1. 正文含截止日            → 抽出
  2. 正文含多个日期          → 取哪个（取**最早的 deadline**，理由见 pick_deadline）
  3. 正文含「截止」但是往年   → **不抽**（防误抽，最重要的一条）
  4. 正文为空                → 走标题口径，行为不变
  5. 跨年                    → 10 月发布的通知，报名在次年

另补 2 类边界：
  6. 模糊日期（下旬/月底）   → 不当 deadline，避免精确化编造
  7. 正文只有事件日无截止     → 不误判成截止

跑法：
    python scripts/notice_import_body_test.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.kaoyan.notice_alert import (  # noqa: E402
    extract_dates,
    pick_deadline,
)

PASS = FAIL = 0
FAILURES: list = []


def check(name: str, got, want, note: str = "") -> None:
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
        print(f"  [OK ] {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  [BAD] {name}\n         got ={got!r}\n         want={want!r}")
    if note:
        print(f"         {note}")


def dl_of(text: str, ref: date = None) -> str:
    """取 deadline_date（走与 /import 完全相同的链路）。"""
    dates = extract_dates(text, ref_date=ref)
    return pick_deadline(dates) or ""


print("=" * 78)
print("  1. 正文含截止日 → 应抽出")
print("=" * 78)
check(
    "正文含「报名截止时间」",
    dl_of("XX大学2027年硕士研究生招生简章\n网上报名时间为2026年10月5日至10月25日，"
          "报名截止时间为2026年10月25日，逾期不予受理。",
          ref=date(2026, 9, 1)),
    "2026-10-25",
)
check(
    "正文含「请于X月X日前完成」",
    dl_of("XX大学推免复试通知\n请于2026年9月20日前完成复试确认，逾期视为放弃。",
          ref=date(2026, 9, 1)),
    "2026-09-20",
)
check(
    "正文含「现场确认时间」",
    dl_of("XX大学报考点公告\n现场确认时间为2026年11月5日。",
          ref=date(2026, 10, 20)),
    "2026-11-05",
)

print()
print("=" * 78)
print("  2. 正文含多个日期 → 取最早的 deadline（理由：越早的截止越不能错过）")
print("=" * 78)
# 这里有两个 deadline：报名截止 10-25 与现场确认截止 11-05。
# 报名截止更早，且是整条链路的入口，漏了就再无机会 → 取 10-25。
multi = ("XX大学2027年报名公告\n"
         "网上报名时间为2026年10月5日至10月25日，报名截止时间为2026年10月25日。\n"
         "现场确认截止时间为2026年11月5日。\n"
         "初试时间为2026年12月20日。")
check("多 deadline 取最早", dl_of(multi, ref=date(2026, 9, 1)), "2026-10-25")
check("事件全量抽取（4个日期）", len(extract_dates(multi, ref_date=date(2026, 9, 1))), 4,
      "10-05=报名开始(event_start,非截止) / 10-25=报名截止 / 11-05=确认截止 / 12-20=初试")

print()
print("=" * 78)
print("  3. 正文含「截止」但是往年情况 → **不抽**（防误抽，最重要）")
print("=" * 78)
# 「去年报名截止时间为2025年10月25日」——描述往年，当前周期已过，
# 若抽出来会变成一个永远"已过期"的假截止日，用户每次打开都看到过期告警。
past = ("XX大学2027年招生简章\n"
        "去年报名截止时间为2025年10月25日，请各位考生注意时间节点。")
check("往年截止日不抽", dl_of(past, ref=date(2026, 9, 1)), "",
      "「去年」+ 2025 且早于参考日 180 天以上 → 不产生 deadline")
# 另一形态：正文写明"已结束"
ended = ("XX大学2026年推免通知\n"
         "预报名已于2025年9月25日截止，正式报名通道已关闭。")
check("已结束的截止不抽", dl_of(ended, ref=date(2025, 9, 1)), "",
      "同上，往年事件不应变成待办截止")

print()
print("=" * 78)
print("  4. 正文为空 → 走标题口径，行为与迁移前完全一致")
print("=" * 78)
check("正文 None 走标题", dl_of("XX大学报名截止时间为2026年10月25日"), "2026-10-25")
check("正文空串走标题", dl_of("XX大学报名截止时间为2026年10月25日\n"), "2026-10-25")
check("标题无日期+正文空 → 不抽", dl_of("2027年全国硕士研究生招生考试网上报名公告"), "",
      "这正是真库 620 条「只有届别无月日」的真实形态，保持不抽")

print()
print("=" * 78)
print("  5. 跨年：10 月发布的通知，报名在次年")
print("=" * 78)
# 10 月发布、正文只写「1月5日」→ 应落到次年 1 月，而不是同年（已过期）
check("纯月日跨年到次年", dl_of("XX大学公告\n报名截止时间为1月5日。", ref=date(2026, 10, 20)),
      "2027-01-05",
      "无年份 + 参考日(10月)已过该月日 → +1 年")
# 反例：3 月发布、正文「10月25日」→ 同年 10 月（尚未到）
check("未到的月日不加年", dl_of("XX大学公告\n报名截止时间为10月25日。", ref=date(2026, 3, 1)),
      "2026-10-25")
# 自带年份优先于上下文年份
check("自带年份优先", dl_of("关于2027年硕士招生的通知\n报名截止时间为2026年10月25日。",
                        ref=date(2027, 3, 1)),
      "2026-10-25", "日期自带 2026 不被标题的 2027 覆盖")

print()
print("=" * 78)
print("  6. 模糊日期（下旬/月底）→ 不当 deadline（不精确化编造）")
print("=" * 78)
check("「3月下旬复试」不产生 deadline",
      dl_of("XX大学复试通知\n复试时间为2027年3月下旬，具体安排另行通知。",
            ref=date(2027, 1, 1)),
      "", "模糊日期进 events_json 展示，但不写 deadline_date")
check("「10月底截止」不产生 deadline",
      dl_of("XX大学公告\n报名截止时间为10月底。", ref=date(2026, 9, 1)),
      "")

print()
print("=" * 78)
print("  7. 正文只有事件日、无截止语义 → 不误判成截止")
print("=" * 78)
check("成绩公布日不算截止",
      dl_of("XX大学公告\n成绩公布时间为2027年2月21日。", ref=date(2027, 1, 1)),
      "")
check("公示日不算截止",
      dl_of("XX大学公告\n拟录取名单公示时间为2026年4月10日。", ref=date(2026, 4, 1)),
      "")
check("考试日算 deadline_exam（进 deadline 列）",
      dl_of("XX大学公告\n初试时间为2026年12月20日。", ref=date(2026, 9, 1)),
      "2026-12-20", "考试日是硬节点，漏了整年作废，属于 deadline_exam 类")

print()
print("=" * 78)
print(f"  结果: {PASS} 通过 / {FAIL} 失败")
if FAILURES:
    print("  失败项: " + ", ".join(FAILURES))
print("=" * 78)
raise SystemExit(1 if FAIL else 0)
