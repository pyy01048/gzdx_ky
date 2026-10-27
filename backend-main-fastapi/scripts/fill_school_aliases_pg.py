# -*- coding: utf-8 -*-
"""院校别名填充（PostgreSQL 版）。

从 kaoyan_schools 名称派生常用简称：
1. 通用规则：去「大学/学院/学校」后缀 → 「清华」类简称
   - 但「清华大学」→「清华」，「北京大学」→「北大」这类不是通用规则能覆盖的
   - 通用规则只做安全派生：长度≥4 且去后缀后 ≥2 字的「中国/中央/地方+名」类
2. 常见缩写映射表：985/211/双一流常见院校的约定俗成简称
3. 幂等：按 alias 唯一键查重，重复执行不产生重复
默认 dry-run，--apply 写库。
"""
from __future__ import annotations

import argparse
import re
import sys

import psycopg

DB = dict(host="127.0.0.1", port=5432, dbname="kaoyan", user="kaoyan", password="kaoyan")

# 常见院校缩写映射（985/211/双一流/知名院校）
COMMON_ABBR = {
    "北京大学": "北大", "清华大学": "清华", "复旦大学": "复旦", "上海交通大学": "上交",
    "浙江大学": "浙大", "南京大学": "南大", "中国科学技术大学": "中科大",
    "哈尔滨工业大学": "哈工大", "西安交通大学": "西交", "武汉大学": "武大",
    "华中科技大学": "华科", "中山大学": "中大", "四川大学": "川大",
    "南开大学": "南开", "天津大学": "天大", "山东大学": "山大", "东南大学": "东大",
    "同济大学": "同济", "厦门大学": "厦大", "北京师范大学": "北师大",
    "北京航空航天大学": "北航", "北京理工大学": "北理工", "中国农业大学": "中农大",
    "中央民族大学": "中央民大", "西北工业大学": "西工大", "兰州大学": "兰大",
    "重庆大学": "重大", "大连理工大学": "大工", "东北大学": "东北大学",
    "吉林大学": "吉大", "湖南大学": "湖大", "中南大学": "中南", "电子科技大学": "成电",
    "西安电子科技大学": "西电", "北京邮电大学": "北邮", "南京航空航天大学": "南航",
    "南京理工大学": "南理工", "哈尔滨工程大学": "哈工程", "武汉理工大学": "武理工",
    "西南交通大学": "西南交大", "北京交通大学": "北交大", "北京科技大学": "北科大",
    "北京工业大学": "北工大", "华东师范大学": "华东师大", "上海财经大学": "上财",
    "中央财经大学": "央财", "对外经济贸易大学": "贸大", "中国政法大学": "法大",
    "北京外国语大学": "北外", "上海外国语大学": "上外", "中国传媒大学": "中传",
    "中国人民大学": "人大", "中国海洋大学": "海大", "西北农林科技大学": "西农",
    "国防科技大学": "国防科大", "华南理工大学": "华南理工", "暨南大学": "暨大",
    "深圳大学": "深大", "苏州大学": "苏大", "郑州大学": "郑大", "云南大学": "云大",
    "广西大学": "西大", "贵州大学": "贵大", "南昌大学": "昌大", "太原理工大学": "太原理工",
    "安徽大学": "安大", "福州大学": "福大", "合肥工业大学": "合工大",
}

def main() -> int:
    parser = argparse.ArgumentParser(description="院校别名填充")
    parser.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = parser.parse_args()

    conn = psycopg.connect(**DB)
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, name FROM kaoyan_schools WHERE name IS NOT NULL AND name<>'' ORDER BY id")
        schools = cur.fetchall()

        # 收集已有别名避免冲突
        cur.execute("SELECT alias FROM school_aliases")
        existing = {r[0] for r in cur.fetchall()}

        plan = []  # (alias, school_id, school_name, alias_type)
        for sid, name in schools:
            name = (name or "").strip()
            if not name:
                continue
            # 1. 常见缩写
            abbr = COMMON_ABBR.get(name)
            if abbr and abbr not in existing:
                plan.append((abbr, sid, name, "abbr"))
                existing.add(abbr)
            # 2. 通用简称：去「大学/学院」后缀（仅当剩余部分≥2字且非纯地名）
            short = re.sub(r"(大学|学院|学校)$", "", name)
            if short != name and len(short) >= 2 and short not in existing:
                # 过滤掉太泛的（如「中国」「中央」「北京」单字组合）
                if len(short) >= 2 and short not in ("中国", "中央", "北京", "上海", "天津", "广东"):
                    plan.append((short, sid, name, "common"))
                    existing.add(short)

        print(f"院校 {len(schools)} 所，拟新增别名 {len(plan)} 条")
        if args.apply:
            for alias, sid, sname, atype in plan:
                cur.execute(
                    "INSERT INTO school_aliases (alias, school_id, school_name, alias_type) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (alias) DO NOTHING",
                    (alias, sid, sname, atype),
                )
            conn.commit()
            print(f"已写库 {len(plan)} 条")
        else:
            print("dry-run 样例：")
            for row in plan[:20]:
                print("  ", row)
    finally:
        conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
