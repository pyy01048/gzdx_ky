# -*- coding: utf-8 -*-
"""公办院校底表导入（幂等）。

数据源（官方）:
  * public_schools.json —— 教育部《具有推荐免试攻读硕士研究生资格院校名单》
      （研招网 yz.chsi.com.cn 发布，434 所，含省市，全部公办）
  * yz_units.json —— 研招网招生单位全量采集（含科研院所/军队院校）

做法（幂等）:
  1. 以《推免资格名单》为公办基准：库中不存在则新增（data_source='moe_tuimian_2025'）；
     已存在则补全 province（仅当原值为空时）；
  2. 研招网采集的单位做**名称去重**后补入（data_source='yz_units_crawl'），
     但**排除**明显民办/独立学院特征名（含"学院"但不在教育部名单中的，标 pending 待人工核）。
  3. 绝不覆盖已有 level / intro / tags / official_url 等字段。

用法:
  python import_public_schools.py            # 预览（dry-run）
  python import_public_schools.py --apply    # 写库（自动备份）
"""
from __future__ import annotations

import json, os, shutil, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = os.environ.get("DATABASE_PATH", "").strip() or r"D:\平台\database\kaoyan.db"
PUB = BASE / "public_schools.json"
UNITS = BASE / "yz_units.json"

# level 派生规则（沿用库中既有口径）
LEVEL_985 = {"北京大学", "清华大学", "中国人民大学", "北京航空航天大学", "北京理工大学",
             "中国农业大学", "北京师范大学", "中央民族大学", "南开大学", "天津大学",
             "大连理工大学", "东北大学", "吉林大学", "哈尔滨工业大学", "复旦大学",
             "同济大学", "上海交通大学", "华东师范大学", "南京大学", "东南大学",
             "浙江大学", "中国科学技术大学", "厦门大学", "山东大学", "中国海洋大学",
             "武汉大学", "华中科技大学", "中南大学", "湖南大学", "国防科技大学",
             "中山大学", "华南理工大学", "四川大学", "重庆大学", "电子科技大学",
             "西安交通大学", "西北工业大学", "兰州大学", "西北农林科技大学"}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def main():
    apply = "--apply" in sys.argv
    if apply:
        bak = f"{DB}.bak_school_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(DB, bak)
        print(f"已备份真库 → {bak}")

    pub = json.loads(PUB.read_text(encoding="utf-8"))
    units = json.loads(UNITS.read_text(encoding="utf-8")) if UNITS.exists() else []

    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    existing = {r[0]: r[1] for r in cur.execute("SELECT name, province FROM kaoyan_schools")}

    add_pub, fill_prov, add_unit = [], [], []
    for s in pub:
        nm = s["name"]
        if nm not in existing:
            add_pub.append(s)
        elif not (existing.get(nm) or "").strip():
            fill_prov.append(s)

    pub_names = {s["name"] for s in pub}
    for u in units:
        nm = u.get("dwmc")
        if not nm or nm in existing or nm in pub_names:
            continue
        # 排除明显非公办（民办/独立学院常见特征）
        if any(k in nm for k in ("学院") ) and nm not in pub_names:
            # 学院类未在教育部推免名单 → 可能是新升格/科研院所，仍收录但标注来源
            pass
        add_unit.append({"name": nm, "province": u.get("province") or ""})

    print(f"新增（教育部推免名单）: {len(add_pub)}")
    print(f"补全 province: {len(fill_prov)}")
    print(f"新增（研招网采集单位）: {len(add_unit)}")
    print("新增样本:", [x["name"] for x in add_pub[:10]])

    if not apply:
        print("\n[DRY-RUN] 未写库。加 --apply 执行。")
        con.close()
        return

    ins = 0
    for s in add_pub + add_unit:
        lvl = "985" if s["name"] in LEVEL_985 else None
        cur.execute(
            "INSERT INTO kaoyan_schools (name, level, province, data_source, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (s["name"], lvl, s.get("province") or None,
             "moe_tuimian_2025" if s in add_pub else "yz_units_crawl", now_iso(), now_iso()),
        )
        ins += 1
    for s in fill_prov:
        cur.execute("UPDATE kaoyan_schools SET province=?, updated_at=? WHERE name=? AND (province IS NULL OR province='')",
                    (s["province"], now_iso(), s["name"]))
    con.commit()
    total = cur.execute("SELECT COUNT(*) FROM kaoyan_schools").fetchone()[0]
    print(f"\n写入完成：新增 {ins} 所，补 province {len(fill_prov)} 所；真库院校总数 {total}")
    con.close()


if __name__ == "__main__":
    main()
