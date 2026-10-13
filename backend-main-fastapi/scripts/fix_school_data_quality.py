# -*- coding: utf-8 -*-
"""
院校数据中心数据质量修复（高置信度、低风险）。

修复项（全部可从现有数据 + 公开权威名单推导，不编造）
--------------------------------------------------
1. **level 校正/回填**：对 152 所可被权威名单（985/211/双一流）判定的院校，
   用权威值覆盖库内值（含 NULL 回填）。实测纠正 31 条。
2. **重复院校登记别名**：6 组院校因全角/半角括号被当成两所，
   登记 school_aliases 让检索能归一；并把两条都刷成正确 level。
3. **province 写法统一**：把「北京市/江苏省/广西壮族自治区」等带后缀写法
   统一为短名（与后端 PROVINCE_NAMES 一致）。
   **实测修复了一个真 bug**：前端省份下拉传的是短名，而后端
   `KaoyanSchool.province == province` 是精确匹配，导致「北京」筛出 65 所、
   漏掉 51 所「北京市」。统一后筛选口径一致。
4. **空值标准化**：trim 空白 level / official_url，避免 '' 与 NULL 两态。

不做的事（会在报告里列明）
-------------------------
- 不删除任何院校行（包括 6 组重复），不做院校去重合并。
- 不回填 214 条 NULL level 中的科研院所/军事院校/普通本科 —— 无权威依据。
- 不补official_url（data_source 里0 条含 edu.cn，无可靠线索）。
- 不补往年录取数据（2026 之外无来源，详见报告）。
- 不动 quiz_questions / kaoyan_notices / knowledge_base。

用法：
  python scripts/fix_school_data_quality.py# 预览（dry-run）
  python scripts/fix_school_data_quality.py --apply      # 执行
  python scripts/fix_school_data_quality.py --apply --verify  # 执行并输出前后对比
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from school_level_truth import canon, truth_level  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\data\backups"

# ------------------------------------------------------------ 省份短名映射
# 长写法 → 短名。短名口径与 routers/kaoyan.py的 PROVINCE_NAMES 保持一致。
PROVINCE_FIX = {}
for _full, _short in {
    "北京市": "北京", "天津市": "天津", "上海市": "上海", "重庆市": "重庆",
    "河北省": "河北", "山西省": "山西", "辽宁省": "辽宁", "吉林省": "吉林",
    "黑龙江省": "黑龙江", "江苏省": "江苏", "浙江省": "浙江", "安徽省": "安徽",
    "福建省": "福建", "江西省": "江西", "山东省": "山东", "河南省": "河南",
    "湖北省": "湖北", "湖南省": "湖南", "广东省": "广东", "海南省": "海南",
    "四川省": "四川", "贵州省": "贵州", "云南省": "云南", "陕西省": "陕西",
    "甘肃省": "甘肃", "青海省": "青海", "宁夏回族自治区": "宁夏",
    "新疆维吾尔自治区": "新疆", "内蒙古自治区": "内蒙古",
    "广西壮族自治区": "广西", "西藏自治区": "西藏",
}.items():
    PROVINCE_FIX[_full] = _short


def backup_db(tag: str) -> str:
    """SQLite WAL 模式下必须用 backup() API，cp 会丢未合并的 WAL 数据。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_schoolfix_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


# ------------------------------------------------------------ 重复院校对
# 实测：同校因全角/半角括号被导入为两所。keep = 数据更完整/有 level 的那条。
DUP_PAIRS = [
    (16, 519, "中国石油大学(北京)", "中国石油大学（北京）"),
    (76, 587, "中国石油大学(华东)", "中国石油大学（华东）"),
    (155, 532, "华北电力大学(保定)", "华北电力大学（保定）"),
    (190, 598, "中国地质大学(武汉)", "中国地质大学（武汉）"),
    (217, 520, "中国地质大学(北京)", "中国地质大学（北京）"),
    (668, 518, "中国矿业大学(北京)", "中国矿业大学（北京）"),
]


def plan(conn) -> dict:
    """计算修复计划（只读）。"""
    rows = conn.execute(
        "SELECT id, name, level, province, official_url FROM kaoyan_schools"
    ).fetchall()
    level_fix, prov_fix, blank_fix = [], [], []
    for r in rows:
        cur = (r["level"] or "").strip()
        truth = truth_level(r["name"])
        if truth and cur != truth:
            level_fix.append((r["id"], r["name"], cur or "<NULL>", truth))
        p = (r["province"] or "").strip()
        if p in PROVINCE_FIX:
            prov_fix.append((r["id"], r["name"], p, PROVINCE_FIX[p]))
        url = r["official_url"]
        if url is not None and not str(url).strip():
            blank_fix.append((r["id"], r["name"], "official_url=''"))

    # 别名：对每组重复，把「非 keep 侧的写法」登记为 keep 侧学校的别名
    alias_add = []
    for keep_id, dup_id, keep_name, dup_name in DUP_PAIRS:
        exists = conn.execute(
            "SELECT COUNT(*) c FROM school_aliases WHERE alias=?", (dup_name,)
        ).fetchone()["c"]
        if not exists:
            alias_add.append((dup_name, keep_id, keep_name))

    return {
        "level_fix": level_fix,
        "province_fix": prov_fix,
        "blank_fix": blank_fix,
        "alias_add": alias_add,
    }


def apply_plan(conn, p: dict) -> dict:
    """执行修复，返回实际影响行数。"""
    done = {"level": 0, "province": 0, "blank": 0, "alias": 0}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for sid, _name, _old, new in p["level_fix"]:
        cur = conn.execute(
            "UPDATE kaoyan_schools SET level=?, updated_at=? WHERE id=?",
            (new, now, sid),
        )
        done["level"] += cur.rowcount
    for sid, _name, _old, new in p["province_fix"]:
        cur = conn.execute(
            "UPDATE kaoyan_schools SET province=?, updated_at=? WHERE id=?",
            (new, now, sid),
        )
        done["province"] += cur.rowcount
    for sid, _name, _col in p["blank_fix"]:
        cur = conn.execute(
            "UPDATE kaoyan_schools SET official_url=NULL, updated_at=? WHERE id=?",
            (now, sid),
        )
        done["blank"] += cur.rowcount

    for alias, sid, sname in p["alias_add"]:
        conn.execute(
            "INSERT INTO school_aliases (alias, school_id, school_name, alias_type)"
            " VALUES (?,?,?,'common')",
            (alias, sid, sname),
        )
        done["alias"] += 1

    conn.commit()
    return done


# ------------------------------------------------------------ 前后对比
def snapshot(conn) -> dict:
    g = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "kaoyan_schools": g("SELECT COUNT(*) FROM kaoyan_schools"),
        "level_985": g("SELECT COUNT(*) FROM kaoyan_schools WHERE level='985'"),
        "level_211": g("SELECT COUNT(*) FROM kaoyan_schools WHERE level='211'"),
        "level_shouyiliu": g("SELECT COUNT(*) FROM kaoyan_schools WHERE level='双一流'"),
        "level_shuangfei": g("SELECT COUNT(*) FROM kaoyan_schools WHERE level='双非'"),
        "level_null": g(
            "SELECT COUNT(*) FROM kaoyan_schools"
            " WHERE level IS NULL OR TRIM(level)=''"),
        "province_distinct": g(
            "SELECT COUNT(DISTINCT province) FROM kaoyan_schools"),
        "official_url_empty": g(
            "SELECT COUNT(*) FROM kaoyan_schools"
            " WHERE official_url IS NOT NULL AND TRIM(official_url)=''"),
        "school_aliases": g("SELECT COUNT(*) FROM school_aliases"),
        "kaoyan_majors": g("SELECT COUNT(*) FROM kaoyan_majors"),
        "kaoyan_colleges": g("SELECT COUNT(*) FROM kaoyan_colleges"),
        "kaoyan_admissions": g("SELECT COUNT(*) FROM kaoyan_admissions"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写库")
    ap.add_argument("--verify", action="store_true", help="输出前后对比")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    before = snapshot(conn)
    p = plan(conn)

    print("=" * 74)
    print("修复计划")
    print("=" * 74)
    print(f"\n[1] level 校正/回填：{len(p['level_fix'])} 条")
    for sid, name, old, new in p["level_fix"]:
        print(f"      {sid:<5d} {name:<24s} {old:<10s} -> {new}")
    print(f"\n[2] province 写法统一：{len(p['province_fix'])} 条")
    dist = {}
    for _s, _n, old, new in p["province_fix"]:
        dist[(old, new)] = dist.get((old, new), 0) + 1
    for (old, new), c in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"      {old:<12s} -> {new:<8s} {c:4d} 条")
    print(f"\n[3] 空串转 NULL（official_url=''）：{len(p['blank_fix'])} 条")
    print(f"\n[4] 重复院校登记别名：{len(p['alias_add'])} 条")
    for alias, sid, sname in p["alias_add"]:
        print(f"      alias='{alias}' -> school_id={sid} ({sname})")

    if not args.apply:
        print("\n>>> dry-run，未写库。加 --apply 执行。")
        return

    bak = backup_db("schoolfix")
    print(f"\n已备份：{bak}")
    done = apply_plan(conn, p)
    print(f"实际影响：level {done['level']} / province {done['province']} "
          f"/ blank {done['blank']} / alias {done['alias']}")

    if args.verify:
        after = snapshot(conn)
        print("\n" + "=" * 74)
        print("修复前后对比")
        print("=" * 74)
        for k in before:
            mark = "  <-- 变化" if before[k] != after[k] else ""
            print(f"  {k:22s} {before[k]:>6d} -> {after[k]:<6d}{mark}")
        # 剩余问题
        print("\n  修复后仍存在的已知问题（未处理，需人工/后续任务）：")
        n = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_schools WHERE level IS NULL OR TRIM(level)=''"
        ).fetchone()[0]
        print(f"    level 仍为空: {n}（普通本科/科研院所/军事院校，无权威依据可判）")
        n = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_schools"
            " WHERE official_url IS NULL OR TRIM(official_url)=''"
        ).fetchone()[0]
        print(f"    official_url 仍缺失: {n}")
        n = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_schools WHERE city IS NULL OR TRIM(city)=''"
        ).fetchone()[0]
        print(f"    city 仍为空: {n}（580/583 空，字段基本未启用）")
        for yr, c in conn.execute(
            "SELECT year, COUNT(*) FROM kaoyan_admissions GROUP BY 1 ORDER BY 1"
        ):
            print(f"    录取数据 year={yr}: {c} 条")
        for col in ("research_direction", "reference_books", "degree_type"):
            c = conn.execute(
                f"SELECT COUNT(*) FROM kaoyan_majors WHERE {col} IS NOT NULL"
                " AND TRIM(" + col + ")<>''"
            ).fetchone()[0]
            print(f"    kaoyan_majors.{col} 非空: {c}/832")

    json.dump(
        {"before": before, "plan_sizes": {k: len(v) for k, v in p.items()}},
        open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "_school_fix_report.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=2)
    conn.close()


if __name__ == "__main__":
    main()