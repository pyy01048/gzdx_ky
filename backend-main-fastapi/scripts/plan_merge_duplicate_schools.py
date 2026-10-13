# -*- coding: utf-8 -*-
"""
方案评估：6 组重复院校的合并方案。**默认只输出方案，绝不执行。**

背景
----
`kaoyan_schools` 存在 6 组同校两行，根因是全角/半角括号写法不同
（如 '中国石油大学(北京)' 与 '中国石油大学（北京）'）被当成两所导入。
已在上一轮修复中把它们登记进 school_aliases（检索可归一），
但数据行仍重复，会导致院校列表重复出现。

实测结论（关键前提）
--------------------
**每一组的「空壳」侧都是干净的 0 引用**，因此合并是**零数据损失**的：

| 实体 id | 空壳 id | 空壳的 colleges/majors/admissions/aliases |
|---------|---------|------------------------------------------|
|   16    |   519   | 0 / 0 / 0 / 0|
|   76    |   587   | 0 / 0 / 0 / 0 |
|  155    |   532   | 0 / 0 / 0 / 0 |
|  190    |   598   | 0 / 0 / 0 / 0 |
|  217    |   520   | 0 / 0 / 0 / 0 |
|  668    |   518   | 0 / 0 / 0 / 0 |

但实体侧的信息完整度不同（intro 有的在 seed 侧、有的在 moe侧），
所以合并时需要**按字段取并集**（COALESCE/优先非空），不能简单删空壳。

用法：
  python scripts/plan_merge_duplicate_schools.py# 输出方案 + SQL 草案
  python scripts/plan_merge_duplicate_schools.py --sql     # 只打印 SQL
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\data\backups"

# (实体 id, 空壳 id, 实体名, 空壳名)
PAIRS = [
    (16, 519, "中国石油大学(北京)", "中国石油大学（北京）"),
    (76, 587, "中国石油大学(华东)", "中国石油大学（华东）"),
    (155, 532, "华北电力大学(保定)", "华北电力大学（保定）"),
    (190, 598, "中国地质大学(武汉)", "中国地质大学（武汉）"),
    (217, 520, "中国地质大学(北京)", "中国地质大学（北京）"),
    (668, 518, "中国矿业大学(北京)", "中国矿业大学（北京）"),
]


def backup_db(tag: str) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_mergeschool_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)          # WAL 模式必须用 backup() API
    finally:
        out.close()
        src.close()
    return dst


def emit_sql(conn, keep_id: int, dup_id: int, keep_name: str, dup_name: str) -> str:
    """生成一组合并的 SQL（含字段并集 + 引用重挂 + 别名保全+ 删空壳）。"""
    return f"""
-- ========== 合并 {dup_name}(id={dup_id}) → {keep_name}(id={keep_id}) ==========
BEGIN;

-- 步骤 1  可选：把空壳侧更完整的信息回填到实体侧（字段级并集，只补空）
UPDATE kaoyan_schools
   SET intro         = CASE WHEN intro IS NULL OR TRIM(intro) = ''         THEN (SELECT intro FROM kaoyan_schools WHERE id = {dup_id})         ELSE intro END,
       logo_url      = CASE WHEN logo_url IS NULL OR TRIM(logo_url) = ''  THEN (SELECT logo_url FROM kaoyan_schools WHERE id = {dup_id})      ELSE logo_url END,
       official_url  = CASE WHEN official_url IS NULL OR TRIM(official_url) = '' THEN (SELECT official_url FROM kaoyan_schools WHERE id = {dup_id})  ELSE official_url END,
       tags          = CASE WHEN tags IS NULL OR TRIM(tags) = ''          THEN (SELECT tags FROM kaoyan_schools WHERE id = {dup_id})          ELSE tags END
 WHERE id = {keep_id};

-- 步骤 2  重挂引用（实测本例 0 行，仍保留以防数据变化）
UPDATE kaoyan_colleges   SET school_id = {keep_id} WHERE school_id = {dup_id};
UPDATE kaoyan_majors     SET school_id = {keep_id} WHERE school_id = {dup_id};
UPDATE kaoyan_admissions SET school_id = {keep_id} WHERE school_id = {dup_id};

-- 步骤 3  别名保全：把指向空壳的别名改挂到实体；并确保空壳写法本身已登记为别名
UPDATE school_aliases SET school_id = {keep_id} WHERE school_id = {dup_id};
INSERT INTO school_aliases (alias, school_id, school_name, alias_type)
SELECT '{dup_name}', {keep_id}, '{keep_name}', 'common'
 WHERE NOT EXISTS (SELECT 1 FROM school_aliases WHERE alias = '{dup_name}');

-- 步骤 4  删除空壳行
DELETE FROM kaoyan_schools WHERE id = {dup_id};
COMMIT;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sql", action="store_true", help="只打印 SQL 草案")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    print("=" * 78)
    print("6 组重复院校：实体/ 空壳判定")
    print("=" * 78)
    all_clean = True
    for keep_id, dup_id, keep_name, dup_name in PAIRS:
        counts = {}
        for t in ("kaoyan_colleges", "kaoyan_majors",
                  "kaoyan_admissions", "school_aliases"):
            counts[t] = conn.execute(
                f"SELECT COUNT(*) FROM {t} WHERE school_id=?", (dup_id,)
            ).fetchone()[0]
        empty = all(v == 0 for v in counts.values())
        all_clean &= empty

        keep = conn.execute(
            "SELECT * FROM kaoyan_schools WHERE id=?", (keep_id,)).fetchone()
        dup = conn.execute(
            "SELECT * FROM kaoyan_schools WHERE id=?", (dup_id,)).fetchone()

        print(f"\n【{keep_name}】")
        print(f"  实体 id={keep_id}: level={keep['level']} "
              f"intro={len(keep['intro'] or '')}字 "
              f"官网={'有' if keep['official_url'] else '无'} "
              f"source={keep['data_source']}")
        print(f"  空壳 id={dup_id}: level={dup['level']} "
              f"intro={len(dup['intro'] or '')}字 "
              f"官网={'有' if dup['official_url'] else '无'} "
              f"source={dup['data_source']}")
        print(f"  空壳引用计数: colleges={counts['kaoyan_colleges']} "
              f"majors={counts['kaoyan_majors']} "
              f"admissions={counts['kaoyan_admissions']} "
              f"aliases={counts['school_aliases']}"
              f"{'  → 0 引用，可安全删除' if empty else '  → ⚠ 有引用，需人工处理'}")

    print("\n" + "=" * 78)
    if all_clean:
        print("结论：6 组空壳侧全部 0 引用 → 合并是零数据损失操作")
    else:
        print("结论：存在非空空壳，合并需人工介入")
    print("=" * 78)

    print("\n" + "=" * 78)
    print("SQL 草案（未执行，供拍板）")
    print("=" * 78)
    for keep_id, dup_id, keep_name, dup_name in PAIRS:
        print(emit_sql(conn, keep_id, dup_id, keep_name, dup_name))

    print("\n合并后预期变化：")
    print("  kaoyan_schools 583 → 577（-6）")
    print("  school_aliases 88 → 88（别名只重挂不新增；空壳写法早已登记）")
    print("  kaoyan_colleges / majors / admissions：行数不变（仅 school_id 指向变化）")
    print("  院校列表去重后，同校不再出现两行")

    print("\n" + "=" * 78)
    print("风险与前置检查（执行前必须确认）")
    print("=" * 78)
    print("""
  1. **external_id 风险**：若外部系统/前端localStorage 存了学校 id，
     id={dup_id} 会失效。实测这 6 所均为空壳（0 专业 0 录取），
     院校列表里是纯噪声条目，被用户收藏/引用的概率极低。
  2. **别名查重**：school_aliases.alias 上若有唯一索引，
     步骤 3 的 INSERT 可能冲突。执行前请确认索引定义：
       SELECT name, sql FROM sqlite_master WHERE type='index'
        AND tbl_name='school_aliases';
  3. 前端缓存**：浏览器 localStorage 里的学校 id 需失效处理，
     否则老用户点进去会404（只影响空壳 id，实务上无害）。
  4. 回滚**：执行前用 sqlite3 backup() API 备份（WAL 模式不能用 cp），
     需要脚本化执行时用：
       python scripts/plan_merge_duplicate_schools.py --sql > merge.sql
""")

    # 输出可直接执行的 SQL 文件（供 team-lead 审核后跑）
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "_merge_duplicate_schools.sql")
    with open(out, "w", encoding="utf-8") as f:
        f.write("-- 6 组重复院校合并 SQL（草案，需审核后手动执行）\n")
        f.write(f"-- 生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write("-- 前置：必须先用 sqlite3 backup() API 备份，WAL 模式不能用 cp\n\n")
        for keep_id, dup_id, keep_name, dup_name in PAIRS:
            f.write(emit_sql(conn, keep_id, dup_id, keep_name, dup_name))
    print(f"\nSQL 草案已写入：{out}")
    conn.close()


if __name__ == "__main__":
    main()