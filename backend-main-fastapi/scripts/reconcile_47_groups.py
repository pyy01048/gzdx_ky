# -*- coding: utf-8 -*-
"""47 组冲突裁决表对账（只读）。

用途：team-lead 追问「41 组『有正确侧』是否已执行」。
本脚本从我提交的 47 组裁决表（表A 22 组 + 表B 25 组）逐组核对当前库状态。

47 组 = 22 组（带下划线信号，G01-G22）+ 25 组（OCR 异体，O01-O25）
其中 6 组是「两侧都错」→ team-lead 已裁决并于 16:01 写库隔离
剩余 41 组是「有正确侧」→ **当时未写库**（等 team-lead 放行）
"""
from __future__ import annotations

import sqlite3
import sys

DB_PATH = r"D:\平台\database\kaoyan.db"

# (组号, idA, idB, 正确侧id或None(两侧都错), 判定标签)
TABLE = [
    # ---- 表 A：22 组下划线不对称 ----
    ("G01", 191, 8166, 8166, "两个都对/表述不同"),
    ("G02", 197, 8172, 8172, "8172 对"),
    ("G03", 198, 8176, 8176, "8176 对"),
    ("G04", 269, 1854, 1854, "两个都对/标点不同"),
    ("G05", 270, 1855, 1855, "1855 对"),
    ("G06", 287, 8062, 8062, "两个都对/分隔符不同"),
    ("G07", 288, 8063, None, "两侧都错→已隔离"),
    ("G08", 290, 8066, 8066, "8066 对"),
    ("G09", 344, 8108, 8108, "8108 对"),
    ("G10", 345, 8109, 8109, "8109 对"),
    ("G11", 346, 8112, 8112, "8112 对"),
    ("G12", 350, 8116, 8116, "8116 对"),
    ("G13", 395, 8147, 8147, "8147 对"),
    ("G14", 396, 8148, 8148, "8148 对"),
    ("G15", 400, 8152, None, "两侧都错→已隔离"),
    ("G16", 401, 8153, 8153, "8153 对"),
    ("G17", 1073, 1313, 1073, "1073 对"),
    ("G18", 1770, 8177, 8177, "8177 对"),
    ("G19", 6750, 6764, 6764, "6764 对"),
    ("G20", 6823, 8055, 6823, "6823 对"),
    ("G21", 6838, 8103, 8103, "两个都对/标点不同"),
    ("G22", 6839, 8107, 6839, "两个都对/表述详略"),
    # ---- 表 B：25 组 OCR 异体 ----
    ("O01", 63, 1530, 1530, "都对/判断同义"),
    ("O02", 64, 1532, None, "两侧都错→已隔离"),
    ("O03", 65, 1533, 1533, "1533 对"),
    ("O04", 66, 1534, 66, "66 对"),
    ("O05", 86, 1539, 1539, "1539 对"),
    ("O06", 88, 1541, 88, "88 对"),
    ("O07", 90, 1544, 1544, "都对/1544 更全"),
    ("O08", 91, 1545, 91, "91 对"),
    ("O09", 92, 1546, 1546, "1546 对"),
    ("O10", 93, 1547, 1547, "都对/1547 更全"),
    ("O11", 94, 1548, 1548, "1548 对"),
    ("O12", 116, 1554, 1554, "1554 对"),
    ("O13", 121, 1558, 1558, "都对/1558 更全"),
    ("O14", 122, 1559, 122, "122 对"),
    ("O15", 140, 1562, None, "两侧都错→已隔离"),
    ("O16", 142, 1564, None, "两侧都错→已隔离"),
    ("O17", 144, 1566, 1566, "都对/1566 更全"),
    ("O18", 146, 1569, 1569, "都对/1569 更全"),
    ("O19", 315, 8083, None, "两侧都错→已隔离"),
    ("O20", 372, 8131, 8131, "8131 对"),
    ("O21", 6752, 6768, 6752, "6752 对(含噪声)"),
    ("O22", 6753, 6769, 6769, "6769 对"),
    ("O23", 6760, 8201, 6760, "都对/仅格式"),
    ("O24", 6886, 8390, 8390, "8390 对(本就双 junk)"),
    ("O25", 7887, 8071, 8071, "8071 对"),
]


def main() -> int:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    allids = sorted({i for _, a, b, _, _ in TABLE for i in (a, b)})
    marks = ",".join("?" * len(allids))
    rows = conn.execute(
        f"SELECT id, is_junk, answer FROM quiz_questions WHERE id IN ({marks})", allids
    ).fetchall()
    conn.close()
    m = {r["id"]: r for r in rows}

    print(f"{'组':<5}{'idA':<7}{'idB':<7}{'正确侧':<8}{'错误侧':<8}"
          f"{'错误侧is_junk':<14}{'状态'}")
    print("-" * 78)

    both_wrong = []      # 两侧都错（已执行）
    pending = []         # 有正确侧但错误侧还没标 junk
    missing = []
    for gid, a, b, keep, note in TABLE:
        ra, rb = m.get(a), m.get(b)
        if not ra or not rb:
            missing.append((gid, a, b))
            print(f"{gid:<5}{a:<7}{b:<7} —— 数据库中缺失")
            continue
        if keep is None:                      # 两侧都错
            bad = sorted([a, b])
            both_wrong.append((gid, bad, ra, rb))
            st = "✅ 已写库" if all(m[i]["is_junk"] == 1 for i in bad) else "❌ 未写库"
            print(f"{gid:<5}{a:<7}{b:<7}{'—':<8}"
                  f"{'/'.join(map(str,bad)):<8}{ra['is_junk']}/{rb['is_junk']:<12}{st}")
        else:
            wrong = b if keep == a else a
            r = m[wrong]
            if r["is_junk"] == 1:
                st = "已标 junk"
            elif r["is_junk"] == 0:
                st = "⬜ 未执行"
                pending.append((gid, keep, wrong))
            else:
                st = f"NULL junk={r['is_junk']}"
                pending.append((gid, keep, wrong))
            print(f"{gid:<5}{a:<7}{b:<7}{keep:<8}{wrong:<8}{r['is_junk']:<14}{st}")

    print()
    print(f"47 组对账完成：")
    print(f"  两侧都错（已写库）        : {len(both_wrong)} 组")
    print(f"  有正确侧·错误侧仍未标 junk: {len(pending)} 组")
    print(f"  数据库缺失               : {len(missing)} 组 {missing if missing else ''}")
    if pending:
        pend_ids = [w for _, _, w in pending]
        print(f"\n待写库错误侧 id（{len(pend_ids)} 条）:")
        print("  " + ",".join(map(str, sorted(pend_ids))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
