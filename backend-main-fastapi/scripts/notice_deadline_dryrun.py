# -*- coding: utf-8 -*-
"""紧急通知截止日抽取 —— 诊断 + dry-run（**只读，不写库**）。

用法：
    python scripts/notice_deadline_dryrun.py           # 全量 1004 条
    python scripts/notice_deadline_dryrun.py --id 7    # 只看某条
    python scripts/notice_deadline_dryrun.py --level urgent
    python scripts/notice_deadline_dryrun.py --dump-misses 80

做四件事（全部基于真库只读）：
  1. 统计现有 `deadline_date` 覆盖情况，按 importance_level 分层
  2. 用当前 `extract_dates()` 在 1004 条标题上 dry-run，统计覆盖
  3. **把失败分成两类**：
       A 类「有日期特征但没抽出来」——标题含报名/截止/确认/复试/考试等
           硬截止语义，却没有落到 deadline_date。**这是规则要补的**
       B 类「真的没有日期」——标题本身不含任何日期短语，无信息可抽。
           **这类不该硬抽**，硬抽就是编数据
  4. 打印 A 类清单（id / title / 命中句式 / 抽出什么），供人工核对

纪律：全程只 SELECT，0 DELETE 0 UPDATE。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.kaoyan.notice_alert import (  # noqa: E402
    cn_today,
    extract_dates,
    load_rules,
    parse_date_loose,
)

# 标题里出现这些词 => 该通知**语义上**含"必须行动的时间节点"
# 用于把失败分成「规则该补」和「无信息可抽」两类。
DEADLINE_FEATURE_RE = re.compile(
    r"报名|截止|逾期|确认|缴费|提交|复试|考试|初试|推免|预报名|调剂|"
    r"公布|公示|时间|安排|考核|面试|资格审查|材料|申请"
)

# 明确的日期短语存在性（**必须 月+日 同时出现**，不能把裸「2027年」当日期）
ANY_DATE_SHAPE_RE = re.compile(
    r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]"
    r"|[一二三四五六七八九十]{1,3}\s*月\s*[一二三四五六七八九十]{1,3}\s*[日号]"
)

# 模糊日期（下旬/月底/上旬/中旬/月内）——单独统计，因为这类需要特殊设计
FUZZY_DATE_RE = re.compile(
    r"[一二三四五六七八九十\d]{1,2}\s*月\s*(上旬|中旬|下旬|月底|末|初)"
)

# 只含年份词（如「2027年」）但**没有** X月X日 —— 这类标题"看起来像有日期"，
# 实际只有招生年份，**不含任何可抽取的时间节点**。本次最大的认知陷阱：
# 1004 条里 620 条属于此类，极易被误统计成「有日期特征但没抽出来」。
YEAR_ONLY_RE = re.compile(r"(20\d{2})\s*年")


def fmt_dates(dates: list) -> str:
    """把抽取结果压成一行可读文本。"""
    if not dates:
        return "-"
    parts = []
    for d in dates[:4]:
        flag = "D" if d.get("is_deadline") else " "
        parts.append(f"{flag}{d['date']}({d['kind']}/{d['date_text']})")
    return " ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", type=int, default=None, help="只看某条通知")
    ap.add_argument("--level", default=None,
                    help="只看某等级：urgent / important / normal")
    ap.add_argument("--with-body", action="store_true",
                    help="按「标题+content正文」口径统计（用于验证导入正文后的覆盖率提升；"
                         "content 列不存在时自动退回标题口径）")
    ap.add_argument("--dump-misses", type=int, default=0,
                    help="打印前 N 条 A 类（有特征未抽出）明细")
    args = ap.parse_args()

    import sqlite3
    conn = sqlite3.connect(r"D:\平台\database\kaoyan.db")
    conn.row_factory = sqlite3.Row

    sql = ("SELECT id, title, notice_type, publish_date, importance_level, "
           "importance_reason, deadline_date, events_json FROM kaoyan_notices")
    if args.with_body:
        sql = ("SELECT id, title, notice_type, publish_date, importance_level, "
               "importance_reason, deadline_date, events_json, content FROM kaoyan_notices")
    cond, argv = [], []
    if args.id:
        cond.append("id = ?")
        argv.append(args.id)
    if args.level:
        cond.append("importance_level = ?")
        argv.append(args.level)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY id"
    try:
        rows = [dict(r) for r in conn.execute(sql, argv).fetchall()]
    except sqlite3.OperationalError as e:
        if args.with_body and "content" in str(e):
            print("  [提示] content 列尚未迁移（先跑 scripts/notice_content_migration.py "
                  "--apply），自动退回标题口径")
            sql = sql.replace(", content FROM kaoyan_notices",
                              " FROM kaoyan_notices")
            rows = [dict(r) for r in conn.execute(sql, argv).fetchall()]
            args.with_body = False
        else:
            raise
    conn.close()

    mode = "标题+正文(content)" if args.with_body else "仅标题"
    print("=" * 78)
    print(f"  统计口径: {mode}")
    print("=" * 78)

    rules = load_rules()
    today = cn_today()

    # ---------------------------------------------------------------- 统计容器
    by_level = Counter()
    has_deadline = Counter()
    miss_a_feature_no_date = Counter()   # A 类：有截止语义特征，但无 deadline
    miss_a_with_shape = Counter()        # A 类子项：标题里其实有日期形状却没抽出来
    miss_b_no_feature = Counter()        # B 类：无截止语义特征（不该硬抽）
    miss_b_no_feature_with_shape = Counter()  # B 类子项：有日期形状但语义上不是截止
    extracted_new = Counter()            # 本次能新增 deadline 的条数（按等级）
    fuzzy_only = Counter()               # 只能抽出模糊日期（下旬/月底）的条数

    a_detail: list = []
    new_values: dict = {}  # notice_id -> (deadline, kind, date_text)
    year_only_titles = Counter()   # 只含「2027年」这类招生年份、无 X月X日

    for r in rows:
        lvl = r["importance_level"] or "normal"
        by_level[lvl] += 1
        title = r["title"] or ""
        ref = parse_date_loose(r["publish_date"])
        pub = parse_date_loose(r["publish_date"])

        if YEAR_ONLY_RE.search(title) and not ANY_DATE_SHAPE_RE.search(title):
            year_only_titles[lvl] += 1

        dates = extract_dates(f"{title}\n{r.get('content') or ''}"
                              if args.with_body else title,
                              ref_date=ref, rules=rules)
        deadline = next((d["date"] for d in dates if d.get("is_deadline")), None)
        # 模糊日期（下旬/月底）单独看，不能直接落 deadline_date
        fuzzy = [d for d in dates if FUZZY_DATE_RE.search(d["date_text"] or "")]

        existing = (r["deadline_date"] or "").strip()

        if existing:
            has_deadline[lvl] += 1
            continue

        if deadline:
            extracted_new[lvl] += 1
            new_values[r["id"]] = (deadline,
                                   next(d["kind"] for d in dates
                                        if d["is_deadline"]),
                                   next(d["date_text"] for d in dates
                                        if d["is_deadline"]))
            if fuzzy and not any(
                    d.get("is_deadline") and not FUZZY_DATE_RE.search(
                        d["date_text"] or "")
                    for d in dates):
                fuzzy_only[lvl] += 1
            continue

        # ---- 未抽出 deadline，分类 ----
        has_feature = bool(DEADLINE_FEATURE_RE.search(title))
        has_shape = bool(ANY_DATE_SHAPE_RE.search(title))
        if has_feature:
            miss_a_feature_no_date[lvl] += 1
            if has_shape:
                miss_a_with_shape[lvl] += 1
            a_detail.append({
                "id": r["id"],
                "level": lvl,
                "publish": pub.isoformat() if pub else None,
                "title": title,
                "has_date_shape": has_shape,
                "extracted": fmt_dates(dates),
                "reason": (r["importance_reason"] or "")[:90],
            })
        else:
            miss_b_no_feature[lvl] += 1
            if has_shape:
                miss_b_no_feature_with_shape[lvl] += 1

    # ---------------------------------------------------------------- 报告
    print("=" * 78)
    print("  1. 现状：deadline_date 覆盖（真库 1004 条）")
    print("=" * 78)
    total = sum(by_level.values())
    print(f"  总条数 {total}")
    for lvl in ("urgent", "important", "normal"):
        if by_level.get(lvl):
            hd = has_deadline.get(lvl, 0)
            print(f"  {lvl:<10} 共 {by_level[lvl]:>4}  已有 deadline {hd:>3}  "
                  f"空缺 {by_level[lvl] - hd:>4}")

    print()
    print("=" * 78)
    print("  2. 本次 dry-run：现有规则还能补出多少 deadline")
    print("=" * 78)
    tot_new = sum(extracted_new.values())
    print(f"  可新增 deadline_date: {tot_new} 条")
    for lvl in ("urgent", "important", "normal"):
        if extracted_new.get(lvl):
            print(f"    {lvl:<10} +{extracted_new[lvl]:>3}   "
                  f"(其中仅模糊日期 {fuzzy_only.get(lvl, 0)})")

    print()
    print("=" * 78)
    print("  3. 失败分类（关键：A 类=规则要补，B 类=真的没信息，不该硬抽）")
    print("=" * 78)
    print("  A 类「有截止语义特征但没抽出 deadline」")
    for lvl in ("urgent", "important", "normal"):
        if miss_a_feature_no_date.get(lvl):
            print(f"    {lvl:<10} {miss_a_feature_no_date[lvl]:>3} 条   "
                  f"其中标题含日期形状 {miss_a_with_shape.get(lvl, 0):>3}")
    print(f"    → A 类合计 {sum(miss_a_feature_no_date.values())} 条"
          f"（其中含日期形状 {sum(miss_a_with_shape.values())} 条）")
    print()
    print("  B 类「无截止语义特征」")
    for lvl in ("urgent", "important", "normal"):
        if miss_b_no_feature.get(lvl):
            print(f"    {lvl:<10} {miss_b_no_feature[lvl]:>3} 条   "
                  f"其中标题含日期形状 {miss_b_no_feature_with_shape.get(lvl, 0):>3}")
    print(f"    → B 类合计 {sum(miss_b_no_feature.values())} 条"
          f"（其中含日期形状 {sum(miss_b_no_feature_with_shape.values())} 条）")
    print()
    print("  B 类**不应该**被硬抽 —— 标题里没有截止语义，硬填就是编数据。")
    print("  B 类中含日期形状的那部分，日期属于「往年情况/事件日/其他事项」，")
    print("  正好是「防误抽」要守住的地方。")

    print()
    print("=" * 78)
    print("  3.5 关键陷阱：「只有招生年份、没有 X月X日」的标题")
    print("=" * 78)
    print("  这类标题含「2027年」等年份词，**看起来像有日期**，实际只有招生届别，")
    print("  不含任何可抽取的时间节点。它们全部落在 A 类里，是最容易被误统计成")
    print("  「规则漏抽」的部分 —— 实际是数据源本身没有日期。")
    for lvl in ("urgent", "important", "normal"):
        if year_only_titles.get(lvl):
            print(f"    {lvl:<10} {year_only_titles[lvl]:>3} 条")
    print(f"    → 合计 {sum(year_only_titles.values())} 条 / 全库 {total} 条")

    # 覆盖率
    covered = has_deadline.get("urgent", 0) + extracted_new.get("urgent", 0)
    urgent_total = by_level.get("urgent", 0)
    print()
    print("=" * 78)
    print("  4. urgent 覆盖率")
    print("=" * 78)
    print(f"  urgent {urgent_total} 条")
    print(f"    已有 deadline            {has_deadline.get('urgent', 0):>3}")
    print(f"    本次可补                 {extracted_new.get('urgent', 0):>3}")
    print(f"    补后覆盖率               {covered}/{urgent_total} = "
          f"{covered / max(1, urgent_total) * 100:.1f}%")
    print(f"    仍空缺（A 类）           "
          f"{miss_a_feature_no_date.get('urgent', 0):>3}")
    print(f"    仍空缺（B 类）           {miss_b_no_feature.get('urgent', 0):>3}")

    if args.dump_misses:
        print()
        print("=" * 78)
        print(f"  5. A 类明细（前 {args.dump_misses} 条，供人工核对）")
        print("=" * 78)
        for d in a_detail[:args.dump_misses]:
            shape = "有日期形状" if d["has_date_shape"] else "无日期形状"
            print(f"  #{d['id']:<5}[{d['level']:<9}] {d['publish'] or 'NULL':<10} "
                  f"{shape} | {d['title'][:66]}")
            if d["extracted"] != "-":
                print(f"        已抽出: {d['extracted']}")
        if len(a_detail) > args.dump_misses:
            print(f"  …… 其余 {len(a_detail) - args.dump_misses} 条省略")

    print()
    print("=" * 78)
    print("  6. 可新增 deadline 明细（写库前核对用）")
    print("=" * 78)
    for nid, (dl, kind, dtext) in sorted(new_values.items(),
                                         key=lambda kv: kv[1][0]):
        row = next(x for x in rows if x["id"] == nid)
        print(f"  #{nid:<5} {dl}  {kind:<16} 「{dtext}」  "
              f"{(row['title'] or '')[:52]}")
    print(f"  合计 {len(new_values)} 条")


if __name__ == "__main__":
    main()
