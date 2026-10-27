#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入 kyzz 考研政治历年真题 (2010-2024) 到 quiz_questions 表。

数据源: scripts/data/kyzz_politics/{10..24}.json
来源仓库: github.com/Programming010-cpu/kyzz
字段:
  title        题干
  type         单选/多选
  xuanxiang    {"A":"A.xxx","B":"B.xxx",...} 选项 JSON 字符串
  right_text   答案 (A / B / C / D / AB...)
  jiexi        解析 HTML
  chuchu       "2018考研真题" 等

运行: python scripts/import_kyzz_politics_pg.py
"""
import os
import re
import sys
import json
import glob
import logging

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from import_open_quiz_bank_pg import (
    clean_text, make_options, normalize_answer, answer_in_options,
    quality_gate, write_records, make_record, stats,
)

DATA_DIR = os.path.join(BASE_DIR, "data", "kyzz_politics")
SUBJECT = "政治"
SUBJECT_ID = 10
SOURCE = "kyzz-politics-zhenti"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_kyzz_politics")


def parse_year(chuchu: str):
    """从 '2018考研真题' 提取年份。"""
    m = re.search(r"(19|20)\d{2}", chuchu or "")
    return int(m.group(0)) if m else None


def parse_kyzz_file(fp: str) -> list:
    """解析单个 kyzz JSON 文件为 records。"""
    records = []
    with open(fp, encoding="utf-8") as f:
        data = json.load(f)
    timu = data.get("detail", {}).get("timu", [])
    year = parse_year(os.path.basename(fp))
    for idx, q in enumerate(timu, 1):
        title = clean_text(q.get("title", ""))
        qtype_cn = q.get("type", "")
        right_text = q.get("right_text", "")
        jiexi = clean_text(q.get("jiexi", ""))
        chuchu = q.get("chuchu", "")
        year_val = parse_year(chuchu) or year

        # 选项：优先 xuanxiang JSON
        xuanxiang = q.get("xuanxiang", "")
        opt_list = []
        if isinstance(xuanxiang, str) and xuanxiang.strip():
            try:
                xj = json.loads(xuanxiang)
                for k, v in xj.items():
                    opt_list.append((str(k).strip().upper(), clean_text(str(v))))
            except Exception:
                opt_list = []
        if not opt_list and q.get("xuan_text"):
            # xuan_text: "A.xxx|B.xxx|C.xxx|D.xxx"
            for part in str(q.get("xuan_text", "")).split("|"):
                part = part.strip()
                m = re.match(r"([A-Z])[\.、:．]\s*(.*)", part)
                if m:
                    opt_list.append((m.group(1), clean_text(m.group(2))))
                elif part:
                    opt_list.append((part[0].upper(), clean_text(part[1:])))
        options = make_options(opt_list) if opt_list else None

        # 题型映射
        if "多选" in qtype_cn:
            qtype = "multiple"
        elif "单选" in qtype_cn:
            qtype = "single"
        elif "判断" in qtype_cn:
            qtype = "judge"
        elif "填空" in qtype_cn:
            qtype = "fill"
        elif "简答" in qtype_cn or "分析" in qtype_cn:
            qtype = "essay"
        else:
            qtype = "single"

        # 答案归一化
        answer = normalize_answer(right_text)

        rec = make_record(
            source=SOURCE,
            subject=SUBJECT,
            subject_id=SUBJECT_ID,
            content=title,
            options=options,
            answer=answer,
            analysis=jiexi,
            question_type=qtype,
            chapter="考研政治历年真题（选择题）",
            knowledge_point=None,
            source_label=f"开源题库:Programming010-cpu/kyzz({chuchu or f'{year_val}年考研政治真题'})",
            difficulty=3,
            year=year_val,
            paper=f"{year_val}年考研政治真题" if year_val else None,
            external_suffix=f"kyzz_{year_val}_{idx}",
        )
        records.append(rec)
    return records


def load_all_records() -> list:
    all_records = []
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
    for fp in files:
        try:
            recs = parse_kyzz_file(fp)
            log.info("解析 %s: %d 题", os.path.basename(fp), len(recs))
            stats["total_parsed"] += len(recs)
            all_records.extend(recs)
        except Exception as e:
            log.error("解析 %s 失败: %s", os.path.basename(fp), e)
    return all_records


def main():
    log.info("开始导入 kyzz 考研政治真题...")
    records = load_all_records()
    log.info("共解析 %d 题，开始写入数据库...", len(records))

    conn = psycopg.connect("host=127.0.0.1 port=5432 user=kaoyan password=kaoyan_dev_2026 dbname=kaoyan")
    try:
        inserted = write_records(conn, records)
        log.info("成功插入 %d 题", inserted)
    finally:
        conn.close()

    print("\n===== kyzz 政治真题导入统计 =====")
    print(f"解析总数: {stats['total_parsed']}")
    print(f"成功插入: {stats['inserted']}")
    for k in sorted(stats.keys()):
        if k.startswith("skipped"):
            v = stats[k]
            if v:
                print(f"  {k}: {v}")
    from collections import Counter
    print("按来源:", dict(stats["by_source"]))
    print("按科目:", dict(stats["by_subject"]))


if __name__ == "__main__":
    main()