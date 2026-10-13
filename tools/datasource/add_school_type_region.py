# -*- coding: utf-8 -*-
"""kaoyan_schools 增加 type/region 列并回填（M3-1，幂等）。

背景: 现有表无 type（公办/科研院所/军队…）与 region（A/B 区），
      前端只能在浏览器里用省→大区映射表派生，全量拉取再过滤（脆弱）。

做法（只加不删，幂等）:
  1. ALTER TABLE kaoyan_schools ADD COLUMN type / region（仅当不存在）；
  2. 回填 region：按省份 → 考研 A/B 区（教育部国家线分区）；
  3. 回填 type：名称规则 + data_source 派生（moe_tuimian_2025/yz_units_crawl → 公办；
     名称含"研究所/研究院/科学院" → 科研院所；名称含"军医大学/陆军/海军/空军/国防/武警" → 军队院校）。

用法:
  python add_school_type_region.py            # 预览
  python add_school_type_region.py --apply    # 写库（自动备份）
"""
from __future__ import annotations

import shutil, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

DB = r"D:\平台\database\kaoyan.db"

# 考研 A/B 区（教育部国家线分区）
ZONE_A = {"北京", "天津", "河北", "山西", "辽宁", "吉林", "黑龙江", "上海", "江苏",
          "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东",
          "重庆", "四川", "陕西"}
ZONE_B = {"内蒙古", "广西", "海南", "贵州", "云南", "西藏", "甘肃", "青海", "宁夏", "新疆"}

# 省份别名归一（库中既有"北京市"也有"北京"）
def norm(p: str) -> str:
    return (p or "").replace("省", "").replace("市", "").replace("自治区", "").replace("壮族", "").replace("回族", "").replace("维吾尔", "").strip()


MILITARY_KW = ("军医大学", "陆军", "海军", "空军", "国防", "武警", "战略支援", "火箭军")
RESEARCH_KW = ("研究所", "研究院", "科学院", "社科院", "党校", "研究中心")


def main():
    apply = "--apply" in sys.argv
    if apply:
        bak = f"{DB}.bak_type_region_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(DB, bak)
        print(f"已备份 → {bak}")

    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    cols = {r[1] for r in cur.execute("PRAGMA table_info(kaoyan_schools)")}
    need = [c for c in ("type", "region") if c not in cols]
    print(f"缺失列: {need or '（无，已存在）'}")

    if need and not apply:
        print("[DRY-RUN] 将新增列:", need)

    if apply and need:
        for c in need:
            cur.execute(f"ALTER TABLE kaoyan_schools ADD COLUMN {c} VARCHAR(30)")
        con.commit()
        print(f"已新增列: {need}")

    # dry-run 时列可能尚未创建 → 用 NULL 占位
    has_type = "type" in cols
    has_region = "region" in cols
    sel = f"SELECT id, name, province, data_source, {'type' if has_type else 'NULL'}, {'region' if has_region else 'NULL'} FROM kaoyan_schools"
    rows = cur.execute(sel).fetchall()
    upd = []
    for sid, name, prov, src, t, r in rows:
        p = norm(prov)
        region = "A区" if p in ZONE_A else ("B区" if p in ZONE_B else None)
        if any(k in name for k in MILITARY_KW):
            typ = "军队院校"
        elif any(k in name for k in RESEARCH_KW):
            typ = "科研院所"
        elif src in ("moe_tuimian_2025", "yz_units_crawl") or "大学" in name or "学院" in name:
            typ = "公办"
        else:
            typ = "其他"
        if t != typ or r != region:
            upd.append((sid, typ, region))

    print(f"需回填 {len(upd)} 行")
    from collections import Counter
    print("type 分布:", dict(Counter(x[1] for x in upd)))
    print("region 分布:", dict(Counter(x[2] for x in upd)))

    if not apply:
        print("\n[DRY-RUN] 未写库。加 --apply 执行。")
        con.close()
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for sid, typ, region in upd:
        cur.execute("UPDATE kaoyan_schools SET type=?, region=?, updated_at=? WHERE id=?",
                    (typ, region, ts, sid))
    con.commit()
    print("\n完成。最终分布：")
    print("  type:", dict(Counter(r[0] for r in cur.execute("SELECT type FROM kaoyan_schools"))))
    print("  region:", dict(Counter(r[0] for r in cur.execute("SELECT region FROM kaoyan_schools"))))
    con.close()


if __name__ == "__main__":
    main()
