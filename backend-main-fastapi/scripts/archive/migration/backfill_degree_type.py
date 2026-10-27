# -*- coding: utf-8 -*-
"""
回填 kaoyan_majors.degree_type（学硕 / 专硕）—— 置信度分级，只写高置信度。

判定依据（权威来源）
--------------------
《学位授予和人才培养学科目录》/《专业学位类别及代码》：
  专业学位类别代码是有明确码段区间的：
    0251-0257 经济 / 0351-0354 法政 / 0451-0454 教育 / 0551-0552 新闻传播
    0851-0862 工程（电子信息 0854、机械 0855、材料与化工 0856、能源动力 0858、
                  生物与医药 0860、交通运输 0861 …）
    0951-0954 农学 / 1051-1059 医学 / 1151 军事 / 1251-1257 管理 / 1351-1357 艺术
  学术学位则是「XX00」式的学科代码：07xx 理学、0801-0840 工学、1105 军事学、
  1202 工商管理学、1401/1404/1405 交叉学科。

因此**码段本身就是权威判据**，比「代码末位」可靠得多（末位只能区分 0/1/2 与
6/7/8，但库内 0854 有 43 个不同专业名、0824 混了军医类，不足以单独判据）。

置信度分级
----------
- **A（写入）**：code 命中权威专业学位码段 → 专硕；命中权威学术学位码段 → 学硕。
- **B（写入但标记）**：码段明确、但 name 含方向后缀等噪声，仍按 A 写（码段权威）。
- **C（不写）**：code 为空 / 码段不在任何权威名单 / 「(0824J1)」这类带字母J 的
  交叉计划代码 —— 留 NULL，不猜。

用法：
  python scripts/backfill_degree_type.py             # dry-run
  python scripts/backfill_degree_type.py --apply --verify
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\data\backups"

# ------------------------------------------------ 权威专业学位码段（→ 专硕）
# 3 位前缀（不含第 4 位，因为第 4 位是二级学科/领域码）
PROF_PREFIX3 = {
    # 经济
    "025",  # 应用统计/金融/税务/国际商务/保险/资产评估/审计
    # 法政
    "035",  # 法律/社会工作/警务/知识产权
    # 教育
    "045",  # 教育/体育/汉语国际教育/应用心理
    # 新闻传播
    "055",  # 翻译/新闻与传播
    # 工程（8 大工程专业学位类别）
    "085",  # 建筑…电子信息/机械/材料与化工/资源与环境/能源动力/土木水利
    "086",  # 生物与医药/交通运输/风景园林
    # 农学
    "095",  # 农业/兽医/林业
    # 医学
    "105",  # 临床医学/口腔医学/公共卫生/护理/药学/中医/医学技术
    # 军事
    "115",  # 军事
    # 管理
    "125",  # 工商管理/公共管理/会计/旅游管理/图书情报/工程管理/审计
    # 艺术
    "135",  # 艺术（含音乐舞蹈戏剧影视戏曲美术书法设计）
}

# ------------------------------------------------ 权威学术学位码段（→ 学硕）
# 注意：专业学位码段是「白名单式」的（上面 PROF_PREFIX3 已穷举），
# 凡不在专业学位名单内、且落在合法学科门类内的一律是学术学位。
ACAD_PREFIX3 = {
    # 理学门类 07（含 0701数学…0711系统科学…0774电子科学与技术）
    "070", "071", "072", "073", "074", "075", "076", "077",
    # 工学门类 0801-0840
    "080", "081", "082", "083", "084",
    # 工学门类 2024 新增学术学位（集成电路 0873、低空技术与工程 0899）
    "087", "089",
    # 军事学
    "110",
    # 管理学（学术学位 1201-1206；125x 才是专业学位）
    "120",
    # 交叉学科（学术学位性质）
    "140",
}


def classify(code: str):
    """按权威码段判定学位类型。

    返回 '专硕' / '学硕' / None（无法判定，不写库）。
    """
    if not code:
        return None, "code 为空"
    c = str(code).strip()
    # 带字母的交叉计划代码（如 0824J1）—— 码段语义不确定，不写
    if not c[:3].isdigit():
        return None, "code 含字母(J 计划)，码段不确定"
    p3 = c[:3]
    if p3 in PROF_PREFIX3:
        return "专硕", "命中专业学位码段"
    if p3 in ACAD_PREFIX3:
        return "学硕", "命中学术学位码段"
    return None, f"码段 {p3} 不在权威名单"


def backup_db(tag: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_degreetype_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)          # WAL 模式必须用 backup() API，cp 会丢数据
    finally:
        out.close()
        src.close()
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, code, name, degree_type, exam_subjects FROM kaoyan_majors"
    ).fetchall()

    plan, skipped = [], Counter()
    skip_samples = {}
    for r in rows:
        dt, why = classify(r["code"])
        if dt is None:
            skipped[why] += 1
            skip_samples.setdefault(why, []).append(
                f"{r['code'] or '<空>'} {r['name'][:28]}")
            continue
        if (r["degree_type"] or "").strip() == dt:
            continue
        plan.append((r["id"], r["code"], r["name"], r["degree_type"] or "<NULL>", dt, why))

    print("=" * 76)
    print("degree_type 回填计划")
    print("=" * 76)
    print(f"\n总专业 {len(rows)} 条；可判定 "
          f"{len(rows) - sum(skipped.values())} 条；已有值需改 {len(plan)} 条")
    print("\n[判定分布]（码段判定，非名称猜测）")
    dist = Counter(p[4] for p in plan)
    for k, v in dist.most_common():
        print(f"    -> {k}: {v}")
    print("\n[跳过明细]（不猜，留 NULL）")
    for why, n in skipped.most_common():
        print(f"    {why}: {n} 条")
        for s in skip_samples[why][:3]:
            print(f"        e.g. {s}")

    print("\n[按码段细分分布]")
    by = Counter()
    for r in rows:
        dt, _ = classify(r["code"])
        by[(str(r["code"] or "<空>")[:3], dt or "未判定")] += 1
    for (p3, dt), n in sorted(by.items()):
        print(f"    {p3}xx-> {str(dt):<8s} {n}")

    if args.verify:
        print("\n[抽样核对 20 条]")
        for p in plan[:20]:
            print(f"    {p[0]:<5d} {str(p[1]):<9s} {p[2][:30]:<32s} "
                  f"{p[3]:<8s} -> {p[4]}")

    if not args.apply:
        print("\n>>> dry-run。加 --apply 执行。")
        return

    bak = backup_db("degreetype")
    print(f"\n已备份：{bak}")
    now = datetime.now()
    n = 0
    for mid, _c, _nm, _old, dt, _w in plan:
        cur = conn.execute(
            "UPDATE kaoyan_majors SET degree_type=? WHERE id=?", (dt, mid))
        n += cur.rowcount
    conn.commit()
    print(f"实际写入 {n} 条")

    if args.verify:
        print("\n[修复后填充率]")
        for col in ("degree_type", "research_direction", "reference_books"):
            c = conn.execute(
                f"SELECT COUNT(*) FROM kaoyan_majors WHERE {col} IS NOT NULL"
                " AND TRIM(" + col + ")<>''").fetchone()[0]
            print(f"    {col:22s} {c}/832  ({c*100.0/832:.1f}%)")
        print("\n[校验：已写入的 degree_type 是否全部合法]")
        bad = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_majors WHERE degree_type IS NOT NULL"
            " AND TRIM(degree_type)<>'' AND degree_type NOT IN ('学硕','专硕')"
        ).fetchone()[0]
        print(f"    非法值: {bad}")
        print("\n[校验：学硕应当考数学（一）占比高]")
        for dt in ("学硕", "专硕"):
            tot = conn.execute(
                "SELECT COUNT(*) FROM kaoyan_majors WHERE degree_type=?", (dt,)
            ).fetchone()[0]
            m1 = 0
            for (v,) in conn.execute(
                "SELECT exam_subjects FROM kaoyan_majors WHERE degree_type=?", (dt,)
            ):
                if v and "数学（一）" in str(v):
                    m1 += 1
            pct = f"{m1*100.0/tot:.1f}%" if tot else "n/a"
            print(f"    {dt}: {tot} 条，考数学（一）{m1} 条 = {pct}")
    conn.close()


if __name__ == "__main__":
    main()