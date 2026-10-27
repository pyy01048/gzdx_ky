# -*- coding: utf-8 -*-
"""为 kaoyan_subjects 添加二级学科（一级学科代码 4 位）。

数据源：kaoyan_majors 中出现的 subject_code 及其代表专业名。
结构：code=4位（如 0701），category='一级学科'，parent_code=前2位门类代码。
幂等：按 code 查重，已存在则跳过。
"""
from __future__ import annotations

import sys

import psycopg

sys.stdout.reconfigure(encoding="utf-8")

DB = dict(host="127.0.0.1", port=5432, dbname="kaoyan", user="kaoyan", password="kaoyan_dev_2026")

# 从 kaoyan_majors 提取 subject_code -> (代表专业名, 专业数)
CODE_NAMES = {
    "0701": ("数学", 243), "0702": ("物理学", 171), "0703": ("化学", 192),
    "0704": ("天文学", 14), "0705": ("地理学", 44), "0706": ("大气科学", 11),
    "0707": ("海洋科学", 22), "0708": ("地球物理学", 15), "0709": ("地质学", 28),
    "0710": ("生物学", 148), "0711": ("系统科学", 26), "0712": ("科学技术史", 18),
    "0713": ("生态学", 71), "0714": ("统计学", 71),
    "0751": ("气象", 12), "0752": ("数据科学", 2),
    "0770": ("集成电路科学与工程", 1), "0771": ("基础心理学", 1),
    "0772": ("力学", 1), "0773": ("材料科学与工程", 9),
    "0774": ("电子科学与技术", 4), "0775": ("计算机科学与技术", 6),
    "0776": ("环境科学与工程", 9), "0777": ("生物医学工程", 16),
    "0778": ("基础医学", 3), "0779": ("营养与食品卫生学", 1),
    "0780": ("药学", 5), "0784": ("教育技术学", 18),
    "0787": ("遥感科学与技术", 1), "0788": ("智能科学与技术", 1),
    "0789": ("纳米科学与工程", 1), "0799": ("康复科学与技术", 1),
    "0801": ("力学", 79), "0802": ("机械工程", 199),
    "0803": ("光学工程", 92), "0804": ("仪器科学与技术", 66),
    "0805": ("材料科学与工程", 199), "0806": ("冶金工程", 23),
    "0807": ("动力工程及工程热物理", 88), "0808": ("电气工程", 100),
    "0809": ("电子科学与技术", 98), "0810": ("信息与通信工程", 144),
    "0811": ("控制科学与工程", 142), "0812": ("计算机科学与技术", 201),
    "0813": ("建筑学", 43), "0814": ("土木工程", 73),
    "0815": ("水利工程", 28), "0816": ("测绘科学与技术", 17),
    "0817": ("化学工程与技术", 81), "0818": ("地质资源与地质工程", 10),
    "0819": ("矿业工程", 5), "0820": ("石油与天然气工程", 6),
    "0821": ("纺织科学与工程", 9), "0822": ("轻工技术与工程", 9),
    "0823": ("交通运输工程", 17), "0824": ("船舶与海洋工程", 7),
    "0825": ("航空宇航科学与技术", 22), "0826": ("兵器科学与技术", 8),
    "0827": ("核科学与技术", 8), "0828": ("农业机械化工程", 18),
    "0829": ("林业工程", 8), "0830": ("环境科学与工程", 63),
    "0831": ("生物医学工程", 33), "0832": ("食品科学与工程", 44),
    "0833": ("城乡规划学", 26), "0835": ("软件工程", 44),
    "0836": ("生物工程", 7), "0837": ("安全科学与工程", 8),
    "0838": ("公安技术", 3), "0839": ("网络空间安全", 37),
    "0851": ("建筑", 7), "0853": ("城乡规划", 9),
    "0854": ("计算机技术", 121), "0855": ("机械", 64),
    "0856": ("材料与化工", 84), "0857": ("资源与环境", 63),
    "0858": ("电气工程", 21), "0859": ("土木水利", 30),
    "0860": ("生物与医药", 68), "0861": ("交通运输", 8),
    "0862": ("风景园林", 12), "0871": ("管理科学与工程", 4),
    "0876": ("智能科学与技术", 1),
}

# 门类代码映射（学科门类）
CATEGORY_CODES = {
    "07": "理学", "08": "工学", "09": "农学", "10": "医学",
    "11": "军事学", "12": "管理学", "13": "艺术学", "14": "交叉学科",
}


def main() -> None:
    conn = psycopg.connect(**DB)
    cur = conn.cursor()

    # 读取已有 code，避免重复
    cur.execute("SELECT code FROM kaoyan_subjects")
    existing = {r[0] for r in cur.fetchall()}
    print(f"库内已有学科记录: {len(existing)}")

    # 门类代码是否齐全
    cur.execute("SELECT code, name FROM kaoyan_subjects WHERE category='学科门类'")
    gate_map = {r[0]: r[1] for r in cur.fetchall()}
    print(f"已有门类: {len(gate_map)}")

    inserted = 0
    skipped = 0
    for code in sorted(CODE_NAMES):
        if code in existing:
            skipped += 1
            continue
        name, cnt = CODE_NAMES[code]
        parent = code[:2]
        parent_name = gate_map.get(parent) or CATEGORY_CODES.get(parent, "")
        description = f"一级学科 {name}（{code}），隶属{parent_name}门类，当前收录 {cnt} 个考研招生专业。"
        sort_order = int(code) if code.isdigit() else 9999
        try:
            cur.execute(
                """
                INSERT INTO kaoyan_subjects (code, name, category, parent_code, description, sort_order, created_at)
                VALUES (%s, %s, '一级学科', %s, %s, %s, now())
                """,
                (code, name, parent, description, sort_order),
            )
            inserted += 1
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            skipped += 1

    conn.commit()
    print(f"新增一级学科: {inserted}")
    print(f"跳过已存在: {skipped}")

    cur.execute("SELECT count(*) FROM kaoyan_subjects")
    print(f"kaoyan_subjects 总记录: {cur.fetchone()[0]}")

    # 验证层级
    cur.execute("""
        SELECT code, name, category, parent_code FROM kaoyan_subjects
        WHERE category='一级学科' ORDER BY code LIMIT 15
    """)
    print("=== 一级学科样例 ===")
    for r in cur.fetchall():
        print(f"  {r[0]} {r[1]} (parent={r[3]})")
    conn.close()


if __name__ == "__main__":
    main()