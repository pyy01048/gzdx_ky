#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入开源考研题库到 quiz_questions 表 (PostgreSQL)

数据源:
  1. zhangyu-1000t        : 2026张宇考研数学1000题(数学一) HTML 题库  -> 数学
  2. structured-kaoyan-english : 1998-2025 考研英语真题结构化 JSON     -> 英语
  3. xiao1000_questions.json  : 肖秀荣1000题 JSON                    -> 政治
  4. manmanxue1500_questions.json : 漫漫学1500题 JSON                -> 政治
  5. openexam.seed.db     : 公务员行测题库(常识-政治)                 -> 政治
  6. 408-quiz JSON        : 王道408题库(数据结构/操作系统/计组/计网)  -> 计算机
  7. egg781_data_ds_q.js  : 数据结构研习社题库                       -> 数据结构
  8. politics_md          : 考研政治真题 Markdown                     -> 政治
  9. cacheflow408 md      : CacheFlow408 题库 Markdown                -> 计算机(备用)

运行: python scripts/import_open_quiz_bank_pg.py
"""
import os
import sys
import re
import json
import glob
import html
import hashlib
import logging
from collections import Counter

import psycopg
from psycopg.rows import dict_row

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "open_quiz_bank")

DB_DSN = "host=127.0.0.1 port=5432 user=kaoyan password=kaoyan_dev_2026 dbname=kaoyan"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_open_quiz_bank")

# 外部 id 前缀
EXT_PREFIX = "github_openquiz"

# 质量过滤计数
stats = {
    "total_parsed": 0,
    "inserted": 0,
    "skipped_no_content": 0,
    "skipped_content_short": 0,
    "skipped_no_answer": 0,
    "skipped_bad_options": 0,
    "skipped_answer_not_in_options": 0,
    "skipped_garbled": 0,
    "skipped_duplicate": 0,
    "skipped_invalid_type": 0,
    "skipped_other": 0,
    "by_source": Counter(),
    "by_subject": Counter(),
}


def clean_text(s):
    """清理文本中的 HTML 标签、实体、多余空白"""
    if not s:
        return ""
    s = str(s)
    # 移除非法 Unicode 控制字符 (如 \u0000)
    s = "".join(ch for ch in s if ch >= "\u0001" or ch in ("\n", "\t", "\r"))
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    s = s.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # 去 HTML 标签
    s = re.sub(r"<[^>]+>", "", s)
    # 去 LaTeX 行内/行间标记保留内容
    s = re.sub(r"\$+", "", s)
    # 去 markdown 图片
    s = re.sub(r"!\[.*?\]\(.*?\)", "", s)
    # 去 markdown 链接保留文字
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    # 合并空白
    s = re.sub(r"\s+", " ", s).strip()
    return s


def detect_garbled(s):
    """检测乱码/异常字符"""
    if not s:
        return True
    # 常见乱码字符
    garbled_chars = ["锟斤拷", "烫烫烫", "屯屯屯", "????", "���"]
    for g in garbled_chars:
        if g in s:
            return True
    # 控制字符
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", s):
        return True
    # 过多的特殊符号
    return False


def normalize_answer(ans):
    """归一化答案: 去掉括号和空白, 大写"""
    if not ans:
        return ""
    ans = clean_text(ans)
    ans = re.sub(r"[\(\)（）、.\s]", "", ans)
    return ans.upper()


def make_options(opt_list):
    """将 [('A', 'text'), ...] 或 [{'key','text'}] 转为 canonical JSON 数组"""
    result = []
    for item in opt_list:
        if isinstance(item, dict):
            key = clean_text(str(item.get("key", ""))).strip().upper()
            text = clean_text(str(item.get("text", item.get("content", ""))))
        else:
            key = clean_text(str(item[0])).strip().upper()
            text = clean_text(str(item[1]))
        if not key or not text:
            return None
        result.append({"key": key, "text": text})
    if not (2 <= len(result) <= 10):
        return None
    # 检查 key 唯一性
    keys = [o["key"] for o in result]
    if len(set(keys)) != len(keys):
        return None
    return result


def answer_in_options(answer, options):
    """检查 answer 是否在选项 keys 中 (多选如 'AB'/'AD' 逐个检查)"""
    if not options:
        return False
    keys = {o["key"] for o in options}
    ans = normalize_answer(answer)
    if not ans:
        return False
    # 多选答案形如 "AB" / "A,B" / "A、B"
    ans_letters = re.sub(r"[^A-Z]", "", ans)
    if not ans_letters:
        return False
    return all(ch in keys for ch in ans_letters)


def quality_gate(record):
    """
    基础质量过滤。record 为 dict:
      content, options(list[dict]|None), answer, analysis, question_type, subject, ...
    返回 (ok, reason)
    """
    content = clean_text(record.get("content", ""))
    if not content:
        return False, "no_content"
    if len(content) < 5:
        return False, "content_short"
    if detect_garbled(content):
        return False, "garbled"

    qtype = record.get("question_type", "single")
    answer = record.get("answer", "")
    options = record.get("options")  # list[dict] or None

    # 选择题必须有选项和答案
    if qtype in ("single", "multiple"):
        if not options or len(options) < 2:
            return False, "bad_options"
        if not answer_in_options(answer, options):
            return False, "answer_not_in_options"
    else:
        # 非选择题(判断/填空/计算等) 必须有答案
        if not normalize_answer(answer) and not clean_text(record.get("analysis", "")):
            return False, "no_answer"

    return True, "ok"


def make_record(source, subject, subject_id, content, options, answer, analysis,
                question_type, chapter=None, chapter_id=None, knowledge_point=None,
                source_label=None, difficulty=3, year=None, paper=None,
                external_suffix=None):
    """构造标准 record dict"""
    external_id = f"{EXT_PREFIX}_{external_suffix}" if external_suffix else None
    rec = {
        "source": source,
        "subject": subject,
        "subject_id": subject_id,
        "content": clean_text(content),
        "options": options,
        "answer": normalize_answer(answer) if options else clean_text(answer),
        "analysis": clean_text(analysis) if analysis else None,
        "question_type": question_type,
        "chapter": chapter,
        "chapter_id": chapter_id,
        "knowledge_point": knowledge_point,
        "source_label": source_label or f"开源题库:{source}",
        "difficulty": difficulty,
        "year": year,
        "paper": paper,
        "external_id": external_id,
        "external_suffix": external_suffix,
    }
    return rec


# =========================================================
# 数据源 1: zhangyu-1000t (张宇1000题, 数学一) HTML
# =========================================================
def parse_zhangyu():
    """解析张宇1000题 HTML 章节文件"""
    records = []
    chap_dir = os.path.join(DATA_DIR, "zhangyu_chapters")
    if not os.path.isdir(chap_dir):
        log.warning("zhangyu_chapters 目录不存在: %s", chap_dir)
        return records
    files = sorted(glob.glob(os.path.join(chap_dir, "chapter-*.html")))
    for fp in files:
        chapter_name = os.path.basename(fp).replace("chapter-", "").replace(".html", "")
        try:
            with open(fp, "r", encoding="utf-8") as f:
                html_content = f.read()
        except Exception as e:
            log.warning("读取失败 %s: %s", fp, e)
            continue
        # 提取每道题 article
        arts = re.findall(r'<article class="question".*?</article>', html_content, re.S)
        for idx, a in enumerate(arts, 1):
            # 题型
            kind_m = re.search(r'<span class="q-kind">([^<]+)</span>', a)
            kind = kind_m.group(1).strip() if kind_m else "选择题"
            # 题干 (含选项)
            stem_m = re.search(r'<div class="q-stem">(.*?)</div>', a, re.S)
            if not stem_m:
                continue
            stem_html = stem_m.group(1)
            # 提取选项
            opt_blocks = re.findall(r'<span class="opt"><b class="opt-key">\(([^)]+)\)</b><span class="opt-val">(.*?)</span></span>', stem_html, re.S)
            options = None
            stem_text = stem_html
            if opt_blocks:
                opt_list = []
                for key, val in opt_blocks:
                    opt_list.append((key.strip().upper(), clean_text(val)))
                options = make_options(opt_list)
                # 从题干中移除选项 HTML
                stem_text = re.sub(r'<div class="options">.*?</div>', "", stem_html, flags=re.S)
            stem_text = clean_text(stem_text)
            # 答案
            ans_m = re.search(r'<span class="answer-body">(.*?)</span>', a, re.S)
            answer = clean_text(ans_m.group(1)) if ans_m else ""
            # 解析: 匹配 analysis-body 直到其闭合 div (不依赖 answer-line)
            ana_m = re.search(r'<div class="analysis-body">(.*?)</div>\s*</div>\s*</div>\s*</div>', a, re.S)
            if not ana_m:
                ana_m = re.search(r'<div class="analysis-body">(.*?)</div>', a, re.S)
            analysis = clean_text(ana_m.group(1)) if ana_m else ""

            # 映射题型
            qtype_map = {"选择题": "single", "填空题": "fill", "解答题": "calc"}
            qtype = qtype_map.get(kind, "single")

            # 选择题从答案中提取字母 (如 "(B)" -> "B")
            if qtype == "single" and options:
                answer = normalize_answer(answer)
                if answer and not answer_in_options(answer, options):
                    # 尝试从答案文本中提取字母
                    m = re.search(r'[A-D]', answer)
                    if m:
                        answer = m.group(0)
            elif qtype == "fill":
                answer = answer  # 填空答案是表达式

            rec = make_record(
                source="zhangyu-1000t",
                subject="数学",
                subject_id=8,
                content=stem_text,
                options=options,
                answer=answer,
                analysis=analysis,
                question_type=qtype,
                chapter=f"张宇1000题 第{chapter_name}章",
                knowledge_point=None,
                source_label="开源题库:jlshdsdk/zhangyu-1000t(2026张宇考研数学1000题-数学一)",
                difficulty=3,
                external_suffix=f"zhangyu_{chapter_name}_{idx}",
            )
            records.append(rec)
    return records


# =========================================================
# 数据源 2: structured-kaoyan-english (考研英语真题 JSON)
# =========================================================
def parse_english():
    """解析考研英语真题 JSON"""
    records = []
    data_root = os.path.join(DATA_DIR, "eng", "data")
    if not os.path.isdir(data_root):
        log.warning("英语数据目录不存在: %s", data_root)
        return records
    json_files = sorted(glob.glob(os.path.join(data_root, "*", "*.json")))
    for fp in json_files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log.warning("英语 JSON 解析失败 %s: %s", fp, e)
            continue
        year = data.get("year")
        exam = data.get("exam", "英语")
        # 遍历 sections
        for sec in data.get("sections", []):
            sec_title = sec.get("title", "")
            for g in sec.get("groups", []):
                gtype = g.get("type", "unknown")
                questions = g.get("questions", [])
                passage = g.get("passage", [])
                # passage 可能是 list[str] 或 str
                if isinstance(passage, list):
                    passage_text = "\n".join(passage)
                else:
                    passage_text = str(passage)
                for q in questions:
                    number = q.get("number")
                    opts = q.get("options", {})  # dict A->text
                    answer = q.get("answer", "")
                    explanation = q.get("explanation", "")
                    # 生成题干
                    if gtype in ("cloze",):
                        # 完形填空: 题干 = 文章 + 空格题号
                        stem = f"完形填空（第{number}题）\n{passage_text}"
                    elif gtype in ("reading",):
                        stem = f"阅读理解（第{number}题）\n{passage_text}"
                    elif gtype in ("matching", "heading_matching", "ordering", "gap_fill"):
                        stem = f"新题型（第{number}题）\n{passage_text}"
                    elif gtype in ("translation", "translation_sentences", "translation_full"):
                        stem = f"翻译题（第{number}题）\n{passage_text}"
                    elif gtype == "writing":
                        stem = f"写作（第{number}题）\n{passage_text}"
                    else:
                        stem = f"第{number}题\n{passage_text}"

                    # 选项
                    options = None
                    qtype = "single"
                    if opts and isinstance(opts, dict):
                        opt_list = []
                        for k, v in opts.items():
                            opt_list.append((str(k).strip().upper(), str(v)))
                        options = make_options(opt_list)
                        # 完形/阅读/新题型均为单选
                        qtype = "single"
                    elif gtype in ("translation", "translation_sentences", "translation_full", "writing"):
                        qtype = "essay"
                    else:
                        qtype = "essay"

                    # 章节映射
                    chapter_map = {
                        "cloze": ("完形填空", 82),
                        "reading": ("阅读理解 Part A", 83),
                        "matching": ("阅读理解 Part B 新题型", 84),
                        "heading_matching": ("阅读理解 Part B 新题型", 84),
                        "ordering": ("阅读理解 Part B 新题型", 84),
                        "gap_fill": ("阅读理解 Part B 新题型", 84),
                        "translation": ("翻译", 85),
                        "translation_sentences": ("翻译", 85),
                        "translation_full": ("翻译", 85),
                        "writing": ("大作文", 87),
                    }
                    chapter, ch_id = chapter_map.get(gtype, ("阅读理解 Part A", 83))

                    rec = make_record(
                        source="structured-kaoyan-english",
                        subject="英语",
                        subject_id=9,
                        content=stem,
                        options=options,
                        answer=answer,
                        analysis=explanation,
                        question_type=qtype,
                        chapter=chapter,
                        chapter_id=ch_id,
                        knowledge_point=None,
                        source_label=f"开源题库:LIziak112/structured-kaoyan-english({year}年考研英语真题)",
                        difficulty=3,
                        year=year,
                        paper=f"{year}年考研英语真题",
                        external_suffix=f"eng_{year}_{gtype}_{number}",
                    )
                    records.append(rec)
    return records


# =========================================================
# 数据源 3/4: 肖秀荣1000题 & 漫漫学1500题 (政治)
# =========================================================
POLITICS_CHAPTER_MAP = {
    "马原": ("马克思主义基本原理", 88),
    "mayuan": ("马克思主义基本原理", 88),
    "毛中特": ("毛泽东思想和中国特色社会主义理论体系", 89),
    "maozhongte": ("毛泽东思想和中国特色社会主义理论体系", 89),
    "习思想": ("毛泽东思想和中国特色社会主义理论体系", 89),
    "sixiang": ("毛泽东思想和中国特色社会主义理论体系", 89),
    "史纲": ("中国近现代史纲要", 90),
    "shigang": ("中国近现代史纲要", 90),
    "思修": ("思想道德与法治", 91),
    "sixiu": ("思想道德与法治", 91),
    "时政": ("形势与政策", 92),
}


def parse_politics_json(fp, source, suffix_prefix):
    """解析肖秀荣/漫漫学政治 JSON"""
    records = []
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log.warning("政治 JSON 解析失败 %s: %s", fp, e)
        return records
    if not isinstance(data, list):
        return records
    for i, item in enumerate(data):
        content = item.get("content", "")
        opts_raw = item.get("options", [])
        answer = item.get("answer", "")
        analysis = item.get("analysis", "")
        qtype_raw = item.get("type", "single")  # single / multiple
        disc = item.get("disc", "")
        disc_label = item.get("disc_label", "")
        qno = item.get("qno", i + 1)

        qtype = "multiple" if str(qtype_raw).lower() in ("multiple", "multi") else "single"
        options = None
        if opts_raw:
            opt_list = []
            for o in opts_raw:
                if isinstance(o, dict):
                    opt_list.append((str(o.get("key", "")).strip().upper(), str(o.get("content", ""))))
                else:
                    opt_list.append(("", str(o)))
            options = make_options(opt_list)

        chapter, ch_id = POLITICS_CHAPTER_MAP.get(disc_label, ("形势与政策", 92))

        rec = make_record(
            source=source,
            subject="政治",
            subject_id=10,
            content=content,
            options=options,
            answer=answer,
            analysis=analysis,
            question_type=qtype,
            chapter=chapter,
            chapter_id=ch_id,
            knowledge_point=disc_label,
            source_label=f"开源题库:chenyingxinghen/kaoyan_shuati({source})",
            difficulty=3,
            external_suffix=f"{suffix_prefix}_{i}",
        )
        records.append(rec)
    return records


# =========================================================
# 数据源 5: openexam.seed.db (公务员行测-常识-政治)
# =========================================================
def parse_openexam_politics():
    """解析考公题库中 changshi/zhengzhi 题目 -> 政治"""
    records = []
    db_path = os.path.join(DATA_DIR, "openexam.seed.db")
    if not os.path.exists(db_path):
        log.warning("openexam.seed.db 不存在")
        return records
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT q.id, q.content, q.options, q.answer, q.analysis, q.difficulty, p.title, p.year
        FROM questions q
        LEFT JOIN papers p ON q.paper_id = p.id
        WHERE q.category='changshi' AND q.sub_category='zhengzhi'
    """)
    for i, (qid, content, options_str, answer, analysis, difficulty, paper_title, year) in enumerate(cur.fetchall()):
        options = None
        try:
            if options_str:
                opts_json = json.loads(options_str)
                opt_list = []
                for o in opts_json:
                    opt_list.append((str(o.get("key", "")).strip().upper(), str(o.get("content", ""))))
                options = make_options(opt_list)
        except Exception:
            options = None
        rec = make_record(
            source="openexam-gwy",
            subject="政治",
            subject_id=10,
            content=content,
            options=options,
            answer=answer,
            analysis=analysis,
            question_type="single",
            chapter="形势与政策",
            chapter_id=92,
            knowledge_point="时政常识",
            source_label=f"开源题库:chenyingxinghen/kaoyan_shuati(公务员行测常识·政治: {paper_title})",
            difficulty=int(difficulty) if difficulty else 3,
            year=int(year) if year else None,
            paper=paper_title,
            external_suffix=f"gwy_pol_{i}",
        )
        records.append(rec)
    conn.close()
    return records


# =========================================================
# 数据源 6: 408-quiz (王道408题库 JSON)
# =========================================================
# 408 各科目映射到 subjects / chapters
SUBJECT_408_MAP = {
    "数据结构": {
        "subject": "数据结构", "subject_id": 24,
        "chapters": {  # 章节关键词 -> (chapter title, chapter_id)
            "绪论": ("线性表", 179),
            "线性表": ("线性表", 179),
            "栈": ("栈队列与数组", 180),
            "队列": ("栈队列与数组", 180),
            "数组": ("栈队列与数组", 180),
            "串": ("栈队列与数组", 180),
            "树": ("树与二叉树", 181),
            "二叉树": ("树与二叉树", 181),
            "图": ("图", 182),
            "查找": ("查找", 183),
            "排序": ("排序", 184),
        },
    },
    "操作系统": {
        "subject": "操作系统", "subject_id": 25,
        "chapters": {
            "进程": ("进程与线程", 185),
            "线程": ("进程与线程", 185),
            "处理机": ("进程与线程", 185),
            "内存": ("内存管理", 186),
            "存储": ("内存管理", 186),
            "文件": ("文件管理", 187),
            "输入": ("IO管理", 188),
            "输出": ("IO管理", 188),
            "I/O": ("IO管理", 188),
            "IO": ("IO管理", 188),
        },
    },
    "计组": {
        "subject": "计算机基础", "subject_id": 23,
        "chapters": {
            "数据": ("计算机组成原理", 175),
            "存储": ("计算机组成原理", 175),
            "指令": ("计算机组成原理", 175),
            "中央处理": ("计算机组成原理", 175),
            "总线": ("计算机组成原理", 175),
            "I/O": ("计算机组成原理", 175),
            "IO": ("计算机组成原理", 175),
            "系统": ("计算机组成原理", 175),
        },
    },
    "计网": {
        "subject": "计算机网络", "subject_id": 5,
        "chapters": {
            "体系结构": ("概述", 46),
            "物理层": ("物理层", 47),
            "数据链路层": ("数据链路层", 48),
            "网络层": ("网络层", 49),
            "传输层": ("运输层", 50),
            "应用层": ("应用层", 51),
        },
    },
}


def parse_408quiz():
    """解析 408-quiz JSON"""
    records = []
    data_dir = os.path.join(DATA_DIR, "408quiz")
    if not os.path.isdir(data_dir):
        log.warning("408quiz 数据目录不存在")
        return records
    for fp in sorted(glob.glob(os.path.join(data_dir, "*.json"))):
        book = os.path.basename(fp).replace(".json", "")
        subj_cfg = SUBJECT_408_MAP.get(book)
        if not subj_cfg:
            log.warning("未知 408 科目文件: %s", fp)
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log.warning("408 JSON 解析失败 %s: %s", fp, e)
            continue
        subject = subj_cfg["subject"]
        subject_id = subj_cfg["subject_id"]
        for sec_id, sec in data.get("sections", {}).items():
            sec_title = sec.get("title", "")
            qs_list = sec.get("qs", [])
            for qi, qs in enumerate(qs_list):
                # 格式: [题号, 答案, 题干, 解析, [选项A-D], 图片]
                if not isinstance(qs, (list, tuple)) or len(qs) < 5:
                    continue
                q_no, answer, content, analysis = qs[0], qs[1], qs[2], qs[3]
                opt_strs = qs[4] if len(qs) > 4 else []
                options = None
                if opt_strs:
                    opt_list = []
                    for oi, opt in enumerate(opt_strs):
                        key = chr(ord("A") + oi)
                        # 去掉 "A. " 前缀
                        opt_text = re.sub(r"^[A-Z][.、．]\s*", "", str(opt)).strip()
                        opt_list.append((key, opt_text))
                    options = make_options(opt_list)

                # 章节映射
                chapter = None
                chapter_id = None
                for kw, (ch_name, ch_id) in subj_cfg["chapters"].items():
                    if kw in (sec_title or ""):
                        chapter, chapter_id = ch_name, ch_id
                        break

                rec = make_record(
                    source="408-quiz",
                    subject=subject,
                    subject_id=subject_id,
                    content=content,
                    options=options,
                    answer=answer,
                    analysis=analysis,
                    question_type="single",
                    chapter=chapter,
                    chapter_id=chapter_id,
                    knowledge_point=sec_title,
                    source_label=f"开源题库:zsc5725216-hub/408-quiz({book}-{sec_title})",
                    difficulty=3,
                    external_suffix=f"408quiz_{book}_{sec_id}_{qi}",
                )
                records.append(rec)
    return records


# =========================================================
# 数据源 7: egg781 数据结构题库 (JS)
# =========================================================
def parse_egg781():
    """解析 egg781 数据结构题库 JS"""
    records = []
    fp = os.path.join(DATA_DIR, "egg781_data_ds_q.js")
    if not os.path.exists(fp):
        log.warning("egg781 数据文件不存在")
        return records
    with open(fp, "r", encoding="utf-8") as f:
        content = f.read()
    # 提取每个题目对象
    # 对象形如 { id: 'c1q1', chapter: 'ch1', no: 1, type: 'choice', difficulty: 3,
    #           points: [...], stem: `...`, options: [...], answer: 'B', analysis: `...` }
    # 用正则切分对象 (从 { 到 } 但需要注意嵌套)
    # 简化: 按 "id: 'c..." 定位
    items = re.split(r"\n\{\n", content)[1:]
    chapter_titles = {
        "ch1": "绪论", "ch2": "线性表", "ch3": "栈队列与数组", "ch4": "串",
        "ch5": "树与二叉树", "ch6": "图", "ch7": "查找", "ch8": "排序",
    }
    for idx, blk in enumerate(items):
        id_m = re.search(r"id:\s*'([^']+)'", blk)
        chapter_m = re.search(r"chapter:\s*'([^']+)'", blk)
        type_m = re.search(r"type:\s*'([^']+)'", blk)
        difficulty_m = re.search(r"difficulty:\s*(\d+)", blk)
        points_m = re.search(r"points:\s*\[(.*?)\]", blk, re.S)
        stem_m = re.search(r"stem:\s*`(.*?)`\s*,", blk, re.S)
        options_m = re.search(r"options:\s*\[(.*?)\]\s*,", blk, re.S)
        answer_m = re.search(r"answer:\s*'([^']*)'", blk)
        analysis_m = re.search(r"analysis:\s*`(.*?)`\s*\n?\s*\}", blk, re.S)

        if not stem_m:
            continue
        stem = stem_m.group(1)
        qtype_raw = type_m.group(1) if type_m else "choice"
        difficulty = int(difficulty_m.group(1)) if difficulty_m else 3
        points = ""
        if points_m:
            points = clean_text(points_m.group(1))
        answer = answer_m.group(1) if answer_m else ""
        analysis = clean_text(analysis_m.group(1)) if analysis_m else ""
        chapter_code = chapter_m.group(1) if chapter_m else ""
        chapter_title = chapter_titles.get(chapter_code, "数据结构")

        # 选项
        options = None
        if options_m:
            opt_strs = re.findall(r"'([^']*)'", options_m.group(1))
            if len(opt_strs) >= 2:
                opt_list = [(chr(ord("A") + i), s) for i, s in enumerate(opt_strs)]
                options = make_options(opt_list)

        qtype = "single" if qtype_raw == "choice" else "calc"
        rec = make_record(
            source="egg781",
            subject="数据结构",
            subject_id=24,
            content=stem,
            options=options,
            answer=answer,
            analysis=analysis,
            question_type=qtype,
            chapter=chapter_title,
            chapter_id=None,
            knowledge_point=points,
            source_label="开源题库:egg781/egg781.github.io(数据结构研习社题库)",
            difficulty=difficulty,
            external_suffix=f"egg781_{idx}",
        )
        records.append(rec)
    return records


# =========================================================
# 数据源 8: 政治真题 Markdown
# =========================================================
def parse_politics_md():
    """解析考研政治真题 Markdown (单选题)"""
    records = []
    md_dir = os.path.join(DATA_DIR, "politics_md")
    if not os.path.isdir(md_dir):
        log.warning("politics_md 目录不存在")
        return records
    for fp in sorted(glob.glob(os.path.join(md_dir, "*.md"))):
        year_m = re.search(r"(\d{4})", os.path.basename(fp))
        year = int(year_m.group(1)) if year_m else None
        with open(fp, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 解析单选题: 题号 + 题干 + A/B/C/D + 答案: X
        current = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 匹配题号行: "1." 或 "1．"
            m = re.match(r"^(\d+)[.．、]\s*(.*)", line)
            if m and current is None:
                qno = int(m.group(1))
                stem_start = m.group(2)
                current = {"no": qno, "content": stem_start, "options": [], "answer": None}
                continue
            # 匹配选项
            if current is not None:
                om = re.match(r"^([A-D])[.．、]\s*(.*)", line)
                if om:
                    current["options"].append((om.group(1), om.group(2)))
                    continue
                # 匹配答案
                am = re.match(r"^答案[：:]\s*([A-D]+)", line)
                if am:
                    current["answer"] = am.group(1)
                    continue
                # 如果新题目开始了, 保存 current
                if re.match(r"^\d+[.．、]", line) and current:
                    _flush_politics_record(records, current, year, os.path.basename(fp))
                    m2 = re.match(r"^(\d+)[.．、]\s*(.*)", line)
                    current = {"no": int(m2.group(1)), "content": m2.group(2), "options": [], "answer": None}
                    continue
                # 否则追加到题干
                current["content"] += " " + line
        if current:
            _flush_politics_record(records, current, year, os.path.basename(fp))
    return records


def _flush_politics_record(records, item, year, paper):
    """将一道政治真题写入 records"""
    content = item.get("content", "")
    options_raw = item.get("options", [])
    answer = item.get("answer", "")
    if len(options_raw) < 4:
        return
    options = make_options(options_raw)
    if not options:
        return
    rec = make_record(
        source="politics-zhenti",
        subject="政治",
        subject_id=10,
        content=content,
        options=options,
        answer=answer,
        analysis=None,
        question_type="single",
        chapter="形势与政策",
        chapter_id=92,
        knowledge_point=None,
        source_label=f"开源题库:TsekaLuk/Kaoyan-Politics-Papers({year}年考研政治真题)",
        difficulty=3,
        year=year,
        paper=paper,
        external_suffix=f"polzhenti_{year}_{item.get('no')}",
    )
    records.append(rec)


# =========================================================
# 数据源 9: CacheFlow408 (备用)
# =========================================================
def parse_cacheflow408():
    """解析 CacheFlow408 题库 Markdown"""
    records = []
    md_dir = os.path.join(DATA_DIR, "cacheflow408")
    if not os.path.isdir(md_dir):
        return records
    subj_map = {
        "数据结构_题库": ("数据结构", 24),
        "操作系统_题库": ("操作系统", 25),
        "组成原理_题库": ("计算机基础", 23),
        "计算机网络_题库": ("计算机网络", 5),
    }
    for fp in sorted(glob.glob(os.path.join(md_dir, "*.md"))):
        base = os.path.basename(fp).replace(".md", "")
        if base not in subj_map:
            continue
        subject, subject_id = subj_map[base]
        with open(fp, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 解析格式: ### 第N题 / **题目**：... / **选项**：... / **答案**：X / **解析**：... / **考察知识点**：...
        i = 0
        idx = 0
        while i < len(lines):
            line = lines[i].strip()
            m = re.match(r"^###\s*第(\d+)题", line)
            if m:
                qno = int(m.group(1))
                content = ""
                options_raw = []
                answer = ""
                analysis = ""
                kp = ""
                j = i + 1
                while j < len(lines):
                    l2 = lines[j].strip()
                    if re.match(r"^###\s*第\d+题", l2):
                        break
                    if l2.startswith("**题目**"):
                        content = l2.replace("**题目**", "").replace("：", ":", 1).strip()
                        # 可能跨行
                        while j + 1 < len(lines) and not lines[j+1].strip().startswith("**"):
                            j += 1
                            content += " " + lines[j].strip()
                    elif l2.startswith("**选项**"):
                        opt_str = l2.replace("**选项**", "").replace("：", ":", 1).strip()
                        # 形如 "D. 抽象数据类型 | C. 数据关系 | A. 数据元素 | B. 数据对象"
                        parts = re.split(r"\s*\|\s*", opt_str)
                        for p in parts:
                            om = re.match(r"^([A-Z])[.．、]\s*(.*)", p.strip())
                            if om:
                                options_raw.append((om.group(1), om.group(2)))
                    elif l2.startswith("**答案**"):
                        answer = l2.replace("**答案**", "").replace("：", ":", 1).strip()
                    elif l2.startswith("**解析**"):
                        analysis = l2.replace("**解析**", "").replace("：", ":", 1).strip()
                        while j + 1 < len(lines) and not lines[j+1].strip().startswith("**") and not re.match(r"^###", lines[j+1].strip()):
                            j += 1
                            analysis += " " + lines[j].strip()
                    elif l2.startswith("**考察知识点**"):
                        kp = l2.replace("**考察知识点**", "").replace("：", ":", 1).strip()
                    j += 1
                i = j
                options = make_options(options_raw) if options_raw else None
                rec = make_record(
                    source="cacheflow408",
                    subject=subject,
                    subject_id=subject_id,
                    content=content,
                    options=options,
                    answer=answer,
                    analysis=analysis,
                    question_type="single" if options else "calc",
                    chapter=None,
                    chapter_id=None,
                    knowledge_point=kp,
                    source_label=f"开源题库:ya1u737/CacheFlow408({base})",
                    difficulty=3,
                    external_suffix=f"cacheflow_{base}_{idx}",
                )
                records.append(rec)
                idx += 1
            else:
                i += 1
    return records


# =========================================================
# 数据库写入
# =========================================================
INSERT_SQL = """
INSERT INTO quiz_questions (
    content, options, answer, analysis, rubric, max_score,
    question_type, answer_type, difficulty, source_kind,
    source_label, year, paper, source_paper, external_id,
    subject_id, subject, chapter_id, chapter, knowledge_point,
    confidence, quality, ai_generated, verified, variant_group,
    answer_source, answer_confidence, is_available, is_junk, is_retest,
    figure_missing, validation_status, validation_errors, validated_at,
    created_at, updated_at, classify_confidence, classify_source,
    needs_review, images
) VALUES (
    %(content)s, %(options)s, %(answer)s, %(analysis)s,
    NULL, NULL, %(question_type)s, 'objective', %(difficulty)s,
    'external_import', %(source_label)s, %(year)s, %(paper)s, NULL,
    %(external_id)s, %(subject_id)s, %(subject)s, %(chapter_id)s,
    %(chapter)s, %(knowledge_point)s, 'medium', NULL, FALSE, FALSE, NULL,
    'source_extract', 0.9, TRUE, FALSE, FALSE, 0, 'pending', '[]',
    NULL, NOW(), NOW(), 0.9, 'external_import', FALSE, '[]'
)
ON CONFLICT (external_id) DO NOTHING
"""


def write_records(conn, records):
    """批量写入 quiz_questions，返回插入数"""
    inserted = 0
    with conn.cursor() as cur:
        for rec in records:
            # 质量过滤
            ok, reason = quality_gate(rec)
            if not ok:
                stats[f"skipped_{reason}"] = stats.get(f"skipped_{reason}", 0) + 1
                continue
            # 构造参数字典
            params = {
                "content": rec["content"],
                "options": json.dumps(rec["options"], ensure_ascii=False) if rec["options"] else None,
                "answer": rec["answer"],
                "analysis": rec["analysis"],
                "question_type": rec["question_type"],
                "difficulty": rec["difficulty"],
                "source_label": rec["source_label"],
                "year": rec["year"],
                "paper": rec["paper"],
                "external_id": rec["external_id"],
                "subject_id": rec["subject_id"],
                "subject": rec["subject"],
                "chapter_id": rec["chapter_id"],
                "chapter": rec["chapter"],
                "knowledge_point": rec["knowledge_point"],
            }
            try:
                cur.execute(INSERT_SQL, params)
                if cur.rowcount > 0:
                    inserted += 1
                    stats["inserted"] += 1
                    stats["by_source"][rec["source"]] += 1
                    stats["by_subject"][rec["subject"]] += 1
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                stats["skipped_duplicate"] = stats.get("skipped_duplicate", 0) + 1
                # 重新开启事务
                continue
            except Exception as e:
                conn.rollback()
                log.warning("写入失败 external_id=%s: %s", rec.get("external_id"), e)
                stats["skipped_other"] = stats.get("skipped_other", 0) + 1
                continue
        conn.commit()
    return inserted


def load_all_records():
    """加载所有数据源的 records"""
    all_records = []
    parsers = [
        ("zhangyu-1000t", parse_zhangyu),
        ("structured-kaoyan-english", parse_english),
        ("xiao1000", lambda: parse_politics_json(
            os.path.join(DATA_DIR, "xiao1000_questions.json"), "肖秀荣1000题", "xiao1000")),
        ("manmanxue1500", lambda: parse_politics_json(
            os.path.join(DATA_DIR, "manmanxue1500_questions.json"), "漫漫学1500题", "manmanxue1500")),
        ("openexam-gwy", parse_openexam_politics),
        ("408-quiz", parse_408quiz),
        ("egg781", parse_egg781),
        ("politics-zhenti", parse_politics_md),
        ("cacheflow408", parse_cacheflow408),
    ]
    for name, parser in parsers:
        try:
            recs = parser()
            log.info("解析 %s: %d 题", name, len(recs))
            stats["total_parsed"] += len(recs)
            all_records.extend(recs)
        except Exception as e:
            log.error("解析 %s 失败: %s", name, e)
    return all_records


def main():
    log.info("开始导入开源题库...")
    records = load_all_records()
    log.info("共解析 %d 题，开始写入数据库...", len(records))

    conn = psycopg.connect(DB_DSN)
    try:
        inserted = write_records(conn, records)
        log.info("成功插入 %d 题", inserted)
    finally:
        conn.close()

    # 输出统计
    print("\n===== 导入统计 =====")
    print(f"解析总数: {stats['total_parsed']}")
    print(f"成功插入: {stats['inserted']}")
    print(f"\n按来源:")
    for src, cnt in stats["by_source"].most_common():
        print(f"  {src}: {cnt}")
    print(f"\n按科目:")
    for subj, cnt in stats["by_subject"].most_common():
        print(f"  {subj}: {cnt}")
    print(f"\n跳过原因:")
    for k, v in stats.items():
        if k.startswith("skipped") and v:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
