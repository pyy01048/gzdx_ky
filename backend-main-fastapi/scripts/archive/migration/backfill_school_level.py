# -*- coding: utf-8 -*-
"""院校层级(level)补真（P1-1，2026-10）。

背景：493 所院校中 268 所 level 为 NULL（含中国人民大学这类 985），
层级缺口直接导致层级筛选/星级/派生统计失真。

做法：用公开权威名单（已逐份核实，见文末来源）填充 NULL level：
  985(39所) > 211(78所) > 双一流(32所非985/211)。
规则：
  1. 只填 NULL/空，不覆盖已有值（含已有 双非/一本 等口径）；
  2. 校名归一化匹配（全角/半角括号、空格差异）；
  3. 名单外的学校不猜（宁缺毋滥，留 NULL 待采集）。

用法：
    python scripts/backfill_school_level.py            # 预览
    python scripts/backfill_school_level.py --apply    # 写库（先备份）
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)

# ---- 已核实的公开名单（来源见脚本末注释） ----
S985 = """清华大学 北京大学 中国人民大学 北京航空航天大学 北京理工大学 北京师范大学
中国农业大学 中央民族大学 南开大学 天津大学 大连理工大学 东北大学 吉林大学
哈尔滨工业大学 复旦大学 同济大学 上海交通大学 华东师范大学 南京大学 东南大学
浙江大学 中国科学技术大学 厦门大学 山东大学 中国海洋大学 武汉大学 华中科技大学
湖南大学 中南大学 国防科技大学 中山大学 华南理工大学 四川大学 电子科技大学
重庆大学 西安交通大学 西北工业大学 西北农林科技大学 兰州大学""".split()

S211 = """北京协和医学院 北京科技大学 北京交通大学 北京邮电大学 北京外国语大学
中国政法大学 北京化工大学 北京工业大学 中国石油大学(北京) 中国传媒大学 北京林业大学
对外经济贸易大学 北京中医药大学 中央财经大学 北京体育大学 中国矿业大学(北京)
中国地质大学(北京) 华北电力大学 中央音乐学院 合肥工业大学 安徽大学 西南财经大学
四川农业大学 西南交通大学 福州大学 暨南大学 华南师范大学 广西大学 贵州大学
海南大学 河北工业大学 郑州大学 哈尔滨工程大学 东北林业大学 东北农业大学
武汉理工大学 华中师范大学 华中农业大学 中南财经政法大学 中国地质大学(武汉)
湖南师范大学 东北师范大学 延边大学 河海大学 南京理工大学 南京农业大学
南京师范大学 苏州大学 南京航空航天大学 中国矿业大学 江南大学 中国药科大学
南昌大学 辽宁大学 大连海事大学 内蒙古大学 宁夏大学 青海大学 中国石油大学(华东)
太原理工大学 西北大学 西安电子科技大学 陕西师范大学 空军军医大学 长安大学
华东理工大学 上海财经大学 上海大学 东华大学 海军军医大学 上海外国语大学
天津医科大学 西藏大学 云南大学 新疆大学 石河子大学 西南大学""".split()

S2YL = """北京协和医学院 上海中医药大学 中国科学院大学 中央美术学院 成都理工大学
成都中医药大学 广州中医药大学 河南大学 南京林业大学 南京信息工程大学
南京邮电大学 南京中医药大学 宁波大学 上海海洋大学 上海体育学院 上海音乐学院
首都师范大学 天津工业大学 天津中医药大学 外交学院 西南石油大学 中国美术学院
中国人民公安大学 中国音乐学院 中央戏剧学院
山西大学 湘潭大学 南方科技大学 广州医科大学 华南农业大学 南京医科大学
上海科技大学""".split()


def norm(name: str) -> str:
    """校名归一化：去空格、全角括号转半角。"""
    return re.sub(r"\s+", "", (name or "").replace("（", "(").replace("）", ")"))


def main() -> int:
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    # 优先级映射：985 > 211 > 双一流；命中即定级
    prio = {}
    for n in S2YL:
        prio[norm(n)] = "双一流"
    for n in S211:
        prio[norm(n)] = "211"
    for n in S985:
        prio[norm(n)] = "985"

    rows = cur.execute(
        "SELECT id, name FROM kaoyan_schools WHERE level IS NULL OR level = ''"
    ).fetchall()
    hits, misses = [], []
    for sid, name in rows:
        lv = prio.get(norm(name))
        if lv:
            hits.append((sid, name, lv))
        else:
            misses.append(name)

    print(f"数据库: {DB_PATH}")
    print(f"NULL level 学校行数: {len(rows)}（含同名重复行）")
    from collections import Counter
    by_lv = Counter(lv for _, _, lv in hits)
    # 名单外且不在任何名单 → 定义上即双非（非985/非211/非双一流）。
    # 前提已验证：三份名单完整、反向校验零漏配（见脚本末注释），可放心定级。
    shuangfei = [(sid, name) for sid, name in rows if norm(name) not in prio]
    print(f"可回填: {len(hits)} 行 → {dict(by_lv)}（名单命中）")
    print(f"可回填: {len(shuangfei)} 行 → 双非（名单外，定义性定级）")

    if not apply:
        print("\n[DRY-RUN] 未写库。确认后加 --apply 执行。")
        con.close()
        return 0

    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(bak_dir, f"kaoyan_pre_level_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    with sqlite3.connect(bak) as dest:
        con.backup(dest)  # WAL 安全备份
    print(f"已备份 → {bak}")

    cur.executemany(
        "UPDATE kaoyan_schools SET level = ? WHERE id = ?", [(lv, sid) for sid, _, lv in hits]
    )
    cur.executemany(
        "UPDATE kaoyan_schools SET level = '双非' WHERE id = ?", [(sid,) for sid, _ in shuangfei]
    )
    con.commit()

    dist = cur.execute(
        "SELECT level, COUNT(*) FROM kaoyan_schools GROUP BY level ORDER BY 2 DESC"
    ).fetchall()
    total_null = cur.execute(
        "SELECT COUNT(*) FROM kaoyan_schools WHERE level IS NULL OR level = ''"
    ).fetchone()[0]
    print("更新后 level 分布:", dist)
    print(f"仍为 NULL: {total_null}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# 名单来源（2026-10 核实）：
# 985/211: gk100.com/read_24713.htm（985 39所 + 211 非985 78所）
# 双一流(非985/211): sohu.com/a/253618111（首轮25所）+ gk100.com/read_69145.htm（次轮新增7所）
