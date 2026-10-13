# -*- coding: utf-8 -*-
"""kaoyan_schools.level 回填（依据研招网 syl 双一流标记 + 985 名单）。

逻辑:
  1. 985 名单（39 所）→ level='985'
  2. 研招网采集 syl='1' → level='双一流'（若已是 985/211 则不覆盖）
  3. 其余保持原值；None 视为未分类（不强行编造）

用法:
  python backfill_school_level.py [--apply]
"""
from __future__ import annotations

import json, shutil, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = r"D:\平台\database\kaoyan.db"

# 985 名单（39 所，教育部）
S985 = {
    "北京大学", "清华大学", "中国人民大学", "北京航空航天大学", "北京理工大学", "中国农业大学",
    "北京师范大学", "中央民族大学", "南开大学", "天津大学", "大连理工大学", "东北大学", "吉林大学",
    "哈尔滨工业大学", "复旦大学", "同济大学", "上海交通大学", "华东师范大学", "南京大学", "东南大学",
    "浙江大学", "中国科学技术大学", "厦门大学", "山东大学", "中国海洋大学", "武汉大学", "华中科技大学",
    "中南大学", "湖南大学", "国防科技大学", "中山大学", "华南理工大学", "四川大学", "重庆大学",
    "电子科技大学", "西安交通大学", "西北工业大学", "兰州大学", "西北农林科技大学",
}


def main():
    apply = "--apply" in sys.argv
    units = json.loads((BASE / "yz_units.json").read_text(encoding="utf-8"))
    syl1 = {u["dwmc"] for u in units if u.get("syl") == "1"}
    print(f"985 名单 {len(S985)} 所；研招网 syl=1（双一流）{len(syl1)} 所")

    if apply:
        bak = f"{DB}.bak_level_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(DB, bak)
        print(f"已备份 → {bak}")

    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    rows = cur.execute("SELECT id, name, level FROM kaoyan_schools").fetchall()

    upd_985, upd_syl = [], []
    for sid, name, lvl in rows:
        if name in S985:
            if lvl != "985":
                upd_985.append((sid, name, lvl))
        elif name in syl1 and lvl not in ("985", "211", "双一流"):
            upd_syl.append((sid, name, lvl))

    print(f"将设为 985: {len(upd_985)}；将设为 双一流: {len(upd_syl)}")
    print("985 样本:", [x[1] for x in upd_985[:6]])
    print("双一流 样本:", [x[1] for x in upd_syl[:6]])

    if not apply:
        print("\n[DRY-RUN] 未写库。加 --apply 执行。")
        con.close()
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for sid, name, _ in upd_985:
        cur.execute("UPDATE kaoyan_schools SET level='985', updated_at=? WHERE id=?", (ts, sid))
    for sid, name, _ in upd_syl:
        cur.execute("UPDATE kaoyan_schools SET level='双一流', updated_at=? WHERE id=?", (ts, sid))
    con.commit()
    from collections import Counter
    dist = Counter(r[0] for r in cur.execute("SELECT level FROM kaoyan_schools"))
    print(f"\n完成。level 分布: {dict(dist)}")
    con.close()


if __name__ == "__main__":
    main()
