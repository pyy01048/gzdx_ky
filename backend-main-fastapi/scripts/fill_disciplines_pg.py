# -*- coding: utf-8 -*-
"""学科门类填充（PostgreSQL 版）。

数据来源：教育部《研究生教育学科专业目录（2022年）》学科门类（公开权威标准）。
仅填充 14 个学科门类顶层（parent_code=NULL），不编造一级学科（一级学科较多且
需权威代码，后续有数据源再补）。

幂等：按 code 唯一键查重，重复执行不产生重复。
"""
from __future__ import annotations

import argparse
import sys

import psycopg

DB = dict(host="127.0.0.1", port=5432, dbname="kaoyan", user="kaoyan", password="kaoyan")

# (code, name, category, description)  —— 2022版学科门类
DISCIPLINES = [
    ("01", "哲学", "学科门类", "哲学学科门类，含哲学一级学科。"),
    ("02", "经济学", "学科门类", "经济学学科门类，含理论经济学、应用经济学、统计学等。"),
    ("03", "法学", "学科门类", "法学学科门类，含法学、政治学、社会学、马克思主义理论等。"),
    ("04", "教育学", "学科门类", "教育学学科门类，含教育学、心理学、体育学等。"),
    ("05", "文学", "学科门类", "文学学科门类，含中国语言文学、外国语言文学、新闻传播学等。"),
    ("06", "历史学", "学科门类", "历史学学科门类，含考古学、中国史、世界史等。"),
    ("07", "理学", "学科门类", "理学学科门类，含数学、物理学、化学、天文学、地理学等。"),
    ("08", "工学", "学科门类", "工学学科门类，含力学、机械工程、电子科学与技术、信息与通信工程、计算机科学与技术等。"),
    ("09", "农学", "学科门类", "农学学科门类，含作物学、园艺学、农业资源与环境等。"),
    ("10", "医学", "学科门类", "医学学科门类，含基础医学、临床医学、公共卫生与预防医学等。"),
    ("11", "军事学", "学科门类", "军事学学科门类，含军事思想及军事历史、战略学、战役学等。"),
    ("12", "管理学", "学科门类", "管理学学科门类，含管理科学与工程、工商管理学、公共管理学等。"),
    ("13", "艺术学", "学科门类", "艺术学学科门类，含艺术学理论、音乐与舞蹈学、戏剧与影视学等。"),
    ("14", "交叉学科", "学科门类", "交叉学科门类（2020年增设），含集成电路科学与工程、国家安全学等。"),
]

def main() -> int:
    parser = argparse.ArgumentParser(description="学科门类填充")
    parser.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = parser.parse_args()

    conn = psycopg.connect(**DB)
    cur = conn.cursor()
    try:
        cur.execute("SELECT code FROM disciplines")
        existing = {r[0] for r in cur.fetchall()}
        plan = [d for d in DISCIPLINES if d[0] not in existing]
        print(f"拟新增学科门类 {len(plan)} 条（现有 {len(existing)}）")
        if args.apply:
            for code, name, cat, desc in plan:
                cur.execute(
                    "INSERT INTO disciplines (code, name, category, parent_code, description, sort_order) "
                    "VALUES (%s,%s,%s,NULL,%s,%s) ON CONFLICT (code) DO NOTHING",
                    (code, name, cat, desc, int(code)),
                )
            conn.commit()
            print(f"已写库 {len(plan)} 条")
        else:
            for row in plan:
                print("  ", row[:3])
    finally:
        conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
