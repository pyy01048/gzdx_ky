#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入考研政治真题 (2021/2023/2024) 到 quiz_questions 表。

数据源: scripts/data/kaoyan_politics_solutions/politics_{2021,2023,2024}.md
来源仓库: github.com/TsekaLuk/Kaoyan-Politics-Papers

格式说明:
  - 2021: 题干(可能行内带选项) + 【答案】X + 【解析】xxx
  - 2023: 题干 + 每行选项 + "答案：X"
  - 2024: 题干 + 选项（同行/换行），无答案 → 跳过

解析策略: 按题号切块，块内统一抽取行内/跨行选项。

运行: python scripts/import_politics_zhenti_pg.py
"""
import os
import re
import sys
import json
import logging

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from import_open_quiz_bank_pg import (
    clean_text, make_options, normalize_answer, answer_in_options,
    quality_gate, write_records, make_record, stats,
)

DATA_DIR = os.path.join(BASE_DIR, "data", "kaoyan_politics_solutions")
SUBJECT = "政治"
SUBJECT_ID = 10
SOURCE = "politics-zhenti-md"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_politics_zhenti")


# 行内选项匹配: "A.xxx B.xxx C.xxx D.xxx" 或 "A xxx B xxx"
INLINE_OPT_RE = re.compile(
    r"([A-D])[\.、．:：\s]\s*([^\nA-D]*(?:\([^)]*\))?[^\nA-D]*)"
)


def split_questions(lines):
    """按题号将文本切成块 [(qno, block_lines), ...]"""
    questions = []
    cur_no = None
    cur_lines = []
    for raw in lines:
        line = raw.rstrip("\n")
        m = re.match(r"^\s*(\d{1,2})[\.、．]\s*", line)
        if m:
            qno = int(m.group(1))
            # 跳过标题/页码中的数字误判：题号一般 1-38
            if 1 <= qno <= 50:
                if cur_no is not None:
                    questions.append((cur_no, cur_lines))
                cur_no = qno
                cur_lines = [line]
                continue
        if cur_no is not None:
            cur_lines.append(line)
    if cur_no is not None:
        questions.append((cur_no, cur_lines))
    return questions


def extract_inline_options(text):
    """从文本中抽取 A.xxx B.xxx C.xxx D.xxx 选项。返回 [(key, text), ...] 或 []"""
    results = []
    # 用前瞻切分: 遇到 A. / A、 / A: / A 空格 开始新选项（兼容小写 a-d）
    # 注意：只有选项字母后紧跟 . 、 ． : 或 空格+非中文 才切分，避免切碎题干
    parts = re.split(r"(?=[A-Da-d][\.、．:：])", text)
    for p in parts:
        p = p.strip()
        m = re.match(r"^([A-Da-d])[\.、．:：]\s*(.*)", p)
        if m and m.group(2).strip():
            # 清理尾部混入的下一选项内容（防御性）
            v = m.group(2).strip()
            results.append((m.group(1).upper(), v))
    # 如果只切出 1-2 个选项，尝试用空格分隔的格式 A xxx B xxx
    if len(results) < 4:
        parts2 = re.split(r"(?=[A-Da-d]\s)", text)
        for p in parts2:
            p = p.strip()
            m2 = re.match(r"^([A-Da-d])\s+(.*)", p)
            if m2 and m2.group(2).strip() and not re.match(r"^(年|月|日|项|选|的|是|在|对|人|时|于|与)", m2.group(2)):
                # 避免误切（如 'A 项表述错误' 中的 A 项）
                if not re.match(r"^(项|选|答|式|类|组|级)", m2.group(2)):
                    # 合并到 results（去重）
                    k = m2.group(1).upper()
                    v = m2.group(2).strip()
                    if k not in [r[0] for r in results]:
                        results.append((k, v))
    return results
    # 过滤掉"答案"等非选项
    filtered = []
    for k, v in results:
        v = re.sub(r"【答案】.*$", "", v)
        v = re.sub(r"答案[：:].*$", "", v)
        v = v.strip()
        if v and not re.match(r"^(答案|解析)", v):
            filtered.append((k, v))
    return filtered


def parse_block(qno, lines, year, fmt, answer_map=None):
    """解析一个题目块，返回 record dict 或 None
    answer_map: {qno: 'A'/'ABD'} 外部答案映射（可选）
    """
    block = "\n".join(lines)

    # 提取答案
    answer = ""
    am = re.search(r"【答案】\s*([A-D]+)", block)
    if am:
        answer = am.group(1)
    if not answer:
        am2 = re.search(r"答案[：:]\s*([A-D]+)", block)
        if am2:
            answer = am2.group(1)
    # 外部答案映射
    if not answer and answer_map and str(qno) in answer_map:
        answer = answer_map[str(qno)]

    # 提取解析
    analysis = ""
    jx = re.search(r"【解析】\s*(.*?)(?=\n\s*\n\s*\d+[\.、．]|\Z)", block, re.S)
    if jx:
        analysis = jx.group(1)
    else:
        # 2023 无【解析】，无分析
        pass

    # 去掉答案/解析标记后的题干区
    stem_zone = block
    stem_zone = re.split(r"【答案】|【解析】|答案[：:]", stem_zone)[0]

    # 抽取选项
    options_raw = extract_inline_options(stem_zone)
    if not options_raw:
        return None

    # 题干 = 去掉选项后的剩余文本
    content = re.sub(r"[A-D][\.、．:：]\s*[^\nA-D]*", "", stem_zone)
    content = clean_text(content)
    content = re.sub(r"\s*[（(]\s*[）)]\s*$", "", content)  # 去掉末尾空括号
    if len(content) < 5:
        return None

    qtype = "single"
    # 多选题答案含多个字母（如 AD / ABC / ABCD）
    if len(answer) >= 2:
        qtype = "multiple"

    options = make_options(options_raw)
    if not options:
        return None

    answer = normalize_answer(answer)
    if not answer:
        return None
    if not answer_in_options(answer, options):
        return None

    rec = make_record(
        source=SOURCE,
        subject=SUBJECT,
        subject_id=SUBJECT_ID,
        content=content,
        options=options,
        answer=answer,
        analysis=clean_text(analysis) if analysis else None,
        question_type=qtype,
        chapter="考研政治历年真题（选择题）",
        knowledge_point=None,
        source_label=f"开源题库:TsekaLuk/Kaoyan-Politics-Papers({year}年考研政治真题)",
        difficulty=3,
        year=year,
        paper=f"{year}年考研政治真题",
        external_suffix=f"polmd_{year}_{qno}",
    )
    ok, reason = quality_gate(rec)
    if not ok:
        stats[f"skipped_{reason}"] = stats.get(f"skipped_{reason}", 0) + 1
        return None
    return rec


def parse_file(fname):
    """解析单个文件"""
    year = int(fname.split("_")[1].split(".")[0])
    fp = os.path.join(DATA_DIR, fname)
    if not os.path.isfile(fp):
        log.warning("文件不存在: %s", fp)
        return []
    with open(fp, encoding="utf-8") as f:
        lines = f.readlines()

    # 读取外部答案映射（如果有）
    answer_map = None
    ans_fp = os.path.join(DATA_DIR, f"politics_{year}_answers.json")
    if os.path.isfile(ans_fp):
        try:
            with open(ans_fp, encoding="utf-8") as f:
                ans_data = json.load(f)
            if str(year) in ans_data:
                merged = {}
                for section in ("single", "multiple"):
                    merged.update(ans_data[str(year)].get(section, {}))
                answer_map = merged
                log.info("%s: 加载外部答案映射 %d 条", fname, len(merged))
        except Exception as e:
            log.warning("读取答案映射失败 %s: %s", ans_fp, e)

    questions = split_questions(lines)
    records = []
    for qno, qlines in questions:
        rec = parse_block(qno, qlines, year, str(year), answer_map)
        if rec:
            records.append(rec)
    return records


def main():
    log.info("开始导入政治真题 Markdown...")
    all_records = []
    for fname in ["politics_2021.md", "politics_2023.md", "politics_2024.md"]:
        recs = parse_file(fname)
        log.info("%s: 解析 %d 题", fname, len(recs))
        stats["total_parsed"] += len(recs)
        all_records.extend(recs)

    log.info("共解析 %d 题，开始写入数据库...", len(all_records))
    conn = psycopg.connect("host=127.0.0.1 port=5432 user=kaoyan password=kaoyan_dev_2026 dbname=kaoyan")
    try:
        inserted = write_records(conn, all_records)
        log.info("成功插入 %d 题", inserted)
    finally:
        conn.close()

    print("\n===== 政治真题导入统计 =====")
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