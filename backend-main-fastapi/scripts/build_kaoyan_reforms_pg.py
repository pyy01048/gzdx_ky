# -*- coding: utf-8 -*-
"""从院校公告中提取考研改革动态写入 kaoyan_reforms（PostgreSQL）。

数据源：kaoyan_notices 表（标题含改革关键词的公告）。
策略：
1. 筛选非噪声公告中标题含改革关键词的记录。
2. 按标题关键词归类 change_type。
3. 从标题/公告元数据提取 year、关键词、url、source。
4. change_detail 基于标题生成结构化描述。
5. detail_hash 用 md5(title+school_name) 去重。

用法：
    python scripts/build_kaoyan_reforms_pg.py --dry-run
    python scripts/build_kaoyan_reforms_pg.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter

import psycopg

sys.stdout.reconfigure(encoding="utf-8")

DB = dict(host="127.0.0.1", port=5432, dbname="kaoyan", user="kaoyan", password="kaoyan_dev_2026")

# 改革类型关键词映射
CHANGE_TYPE_RULES = [
    ("参考书目调整", ["参考书", "参考书目", "书目"]),
    ("考试科目调整", ["初试科目", "考试科目", "自命题科目", "科目调整", "考试范围"]),
    ("考试大纲发布", ["考试大纲", "大纲"]),
    ("招生专业目录调整", ["专业目录", "招生目录"]),
    ("新增专业或方向", ["新增", "新设"]),
    ("招生政策变化", ["新变化", "调整", "变更", "改革", "变化", "政策"]),
    ("学费标准调整", ["学费"]),
    ("学制调整", ["学制", "修业年限"]),
    ("招生简章发布", ["招生简章", "简章"]),
    ("免试推荐", ["推免", "免试", "推荐免试"]),
    ("专项计划", ["退役大学生", "骨干计划", "强军计划", "专项"]),
]

# 通用关键词（所有改革类公告都打上）
COMMON_KEYWORDS = ["考研", "硕士研究生", "招生"]


def classify_change_type(title: str) -> str:
    """根据标题返回改革类型。"""
    for ctype, kws in CHANGE_TYPE_RULES:
        for kw in kws:
            if kw in title:
                return ctype
    return "其他"


def extract_year(title: str, publish_date: str | None) -> int | None:
    """从标题或发布日期提取年份。"""
    m = re.search(r"(20\d{2})", title or "")
    if m:
        return int(m.group(1))
    if publish_date:
        m = re.search(r"(20\d{2})", publish_date)
        if m:
            return int(m.group(1))
    return None


def extract_keywords(title: str, change_type: str) -> str:
    """提取关键词：改革类型 + 标题中的关键片段。"""
    kws = [change_type] + COMMON_KEYWORDS
    # 标题中的年份关键词
    m = re.search(r"(20\d{2})", title or "")
    if m:
        kws.append(m.group(1) + "考研")
    # 标题中带书名号的参考书
    books = re.findall(r"[《《]([^》」]+)[》」]", title or "")
    if books:
        kws.extend(books[:3])
    # 科目关键词
    for kw in ["数学", "英语", "政治", "专业课", "408", "电路", "数据结构"]:
        if kw in title:
            kws.append(kw)
            break
    return "、".join(dict.fromkeys(kws))


def build_change_detail(title: str, notice_type: str | None, school_name: str) -> str:
    """基于标题生成结构化改革描述。"""
    t = (title or "").strip()
    ntype = notice_type or "公告"
    return f"【{school_name}】发布{ntype}：{t}。建议考生及时核对报考专业的初试科目、参考书目与招生政策，以院校官网最新发布为准。"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = psycopg.connect(**DB)
    cur = conn.cursor()

    # 读取候选公告（仅明确的改革信号词，不含宽泛的"招生"）
    cur.execute("""
        SELECT id, school_id, school_name, title, notice_type, publish_date, url, source
        FROM kaoyan_notices
        WHERE is_noise = false
          AND title IS NOT NULL
          AND (
               title LIKE '%调整%' OR title LIKE '%变更%' OR title LIKE '%改革%'
            OR title LIKE '%参考书%' OR title LIKE '%大纲%' OR title LIKE '%新增%'
            OR title LIKE '%变化%' OR title LIKE '%科目%' OR title LIKE '%目录%'
            OR title LIKE '%学费%' OR title LIKE '%学制%' OR title LIKE '%简章%'
            OR title LIKE '%免试%' OR title LIKE '%专项%' OR title LIKE '%考试范围%'
          )
        ORDER BY publish_date DESC NULLS LAST
    """)
    rows = cur.fetchall()
    print(f"候选公告数: {len(rows)}")

    records = []
    seen_hashes = set()
    type_counter = Counter()

    for nid, school_id, school_name, title, notice_type, publish_date, url, source in rows:
        # 过滤博士相关（本表聚焦硕士研究生考研改革）
        if title and ("博士" in title or "博士生" in title):
            continue
        ctype = classify_change_type(title)
        # 过滤掉"其他"类型——不是明确改革信号
        if ctype == "其他":
            continue
        year = extract_year(title, publish_date)
        keywords = extract_keywords(title, ctype)
        detail = build_change_detail(title, notice_type, school_name)
        detail_hash = hashlib.md5((str(school_name) + "|" + str(title)).encode("utf-8")).hexdigest()

        # 标题太短的跳过
        if not title or len(title) < 8:
            continue
        # 去重
        if detail_hash in seen_hashes:
            continue
        seen_hashes.add(detail_hash)

        records.append((
            school_id or 0, school_name or "", nid, notice_type or "", title,
            year, ctype, detail, keywords, 0.8, url or "", source or "", detail_hash,
        ))
        type_counter[ctype] += 1

    print(f"生成改革记录数: {len(records)}")
    print()
    print("=== 改革类型分布 ===")
    for k, v in type_counter.most_common():
        print(f"  {k}: {v}")

    if not args.apply:
        print("\n[dry-run] 未写入数据库。加 --apply 执行。")
        conn.close()
        return

    try:
        cur.execute("DELETE FROM kaoyan_reforms")
        print(f"已清空旧表: {cur.rowcount}")
        with conn.cursor() as cur2:
            cur2.executemany(
                """
                INSERT INTO kaoyan_reforms
                    (school_id, school_name, notice_id, notice_type, title, year,
                     change_type, change_detail, keywords, confidence, url, source, created_at, detail_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, to_char(now(), 'YYYY-MM-DD HH24:MI:SS'), %s)
                """,
                records,
            )
            print(f"写入改革记录: {cur2.rowcount}")
        conn.commit()
        print("提交成功！")
    except Exception as exc:
        conn.rollback()
        print(f"写入失败，已回滚: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()