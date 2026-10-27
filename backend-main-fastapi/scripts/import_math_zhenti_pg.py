#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入考研数学一真题（1987-2024）到 quiz_questions 表 (PostgreSQL)

数据源:
  scripts/data/kaoyan_math_papers/*.md     （题目）
  scripts/data/kaoyan_math_solutions/*.md   （解析）

导入策略:
  A. 2022/2023/2024 解析文件自带完整题干+选项+答案+解析 -> 直接导入
  B. 1987-2021 配对导入：题目文件 (n) 题干 + 解析文件 (n)【答案】X【解】按题号配对
     - 选择题 (有 A/B/C/D 选项) -> single
     - 填空题 (无选项但有答案)  -> fill
     - 解答题 (有答案+解析)     -> calc

运行: python scripts/import_math_zhenti_pg.py
"""
import os
import re
import json
import glob
import logging
from collections import Counter

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
PAPER_DIR = os.path.join(PROJECT_ROOT, "scripts", "data", "kaoyan_math_papers")
SOL_DIR = os.path.join(PROJECT_ROOT, "scripts", "data", "kaoyan_math_solutions")

DB_DSN = "host=127.0.0.1 port=5432 user=kaoyan password=kaoyan_dev_2026 dbname=kaoyan"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_math_zhenti")

EXT_PREFIX = "math_zhenti"

stats = Counter()


# =========================================================
# 文本清洗（复用 import_open_quiz_bank_pg 的 clean_text 逻辑）
# =========================================================
def clean_text(s):
    """清理文本中的 HTML 标签、实体、多余空白"""
    if not s:
        return ""
    s = str(s)
    # 移除非法 Unicode 控制字符
    s = "".join(ch for ch in s if ch >= "\u0001" or ch in ("\n", "\t", "\r"))
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    s = s.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
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
    garbled_chars = ["锟斤拷", "烫烫烫", "屯屯屯", "????", "���"]
    for g in garbled_chars:
        if g in s:
            return True
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", s):
        return True
    return False


def normalize_answer(ans):
    """归一化答案: 去掉括号和空白, 大写"""
    if not ans:
        return ""
    ans = clean_text(ans)
    ans = re.sub(r"[\(\)（）、.\s]", "", ans)
    return ans.upper()


def make_options(opt_list):
    """将 [('A', 'text'), ...] 转为 canonical JSON 数组"""
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
    keys = [o["key"] for o in result]
    if len(set(keys)) != len(keys):
        return None
    return result


def answer_in_options(answer, options):
    """检查 answer 是否在选项 keys 中"""
    if not options:
        return False
    keys = {o["key"] for o in options}
    ans = normalize_answer(answer)
    if not ans:
        return False
    ans_letters = re.sub(r"[^A-Z]", "", ans)
    if not ans_letters:
        return False
    return all(ch in keys for ch in ans_letters)


def quality_gate(record):
    """基础质量过滤。record 为 dict"""
    content = clean_text(record.get("content", ""))
    if not content:
        return False, "no_content"
    if len(content) < 5:
        return False, "content_short"
    if detect_garbled(content):
        return False, "garbled"

    qtype = record.get("question_type", "single")
    answer = record.get("answer", "")
    options = record.get("options")

    if qtype in ("single", "multiple"):
        if not options or len(options) < 2:
            return False, "bad_options"
        if not answer_in_options(answer, options):
            return False, "answer_not_in_options"
    else:
        if not normalize_answer(answer) and not clean_text(record.get("analysis", "")):
            return False, "no_answer"
    return True, "ok"


# =========================================================
# INSERT SQL
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
    'past_exam', %(source_label)s, %(year)s, %(paper)s, NULL,
    %(external_id)s, %(subject_id)s, %(subject)s, %(chapter_id)s,
    %(chapter)s, %(knowledge_point)s, 'high', 'A', FALSE, TRUE, NULL,
    'source_extract', 0.95, TRUE, FALSE, FALSE, 0, 'pass', '[]',
    NULL, NOW(), NOW(), 0.95, 'external_import', FALSE, '[]'
)
ON CONFLICT (external_id) DO NOTHING
"""


def write_records(conn, records):
    """批量写入 quiz_questions，返回插入数"""
    inserted = 0
    with conn.cursor() as cur:
        for rec in records:
            ok, reason = quality_gate(rec)
            if not ok:
                stats[f"skipped_{reason}"] += 1
                continue
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
                    stats[f"by_year_{rec['year']}"] += 1
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                stats["skipped_duplicate"] += 1
                continue
            except Exception as e:
                conn.rollback()
                log.warning("写入失败 external_id=%s: %s", rec.get("external_id"), e)
                stats["skipped_other"] += 1
                continue
        conn.commit()
    return inserted


# =========================================================
# 直接导入：2022/2023/2024 解析自带题干+选项
# =========================================================
def extract_answer_2022(text):
    """从 2022 解析文本提取答案。格式: '答案 B.'"""
    m = re.search(r"答案\s*[（(]?\s*([A-D])\s*[）)]?\s*\.?", text)
    return m.group(1) if m else None


def extract_answer_bracket(text):
    """从 2023/2024 解析文本提取答案。格式: '【答案】(B)' / '【答案】（C）'"""
    m = re.search(r"【答案】\s*[（(]\s*([A-D])\s*[）)]", text)
    return m.group(1) if m else None


def extract_options_from_text(text):
    """从题干文本中提取内联选项 (A)...(B)...(C)...(D)...
    返回 (cleaned_content, options_list) 或 (original, None)
    """
    # 匹配 (A) xxx (B) xxx (C) xxx (D) xxx 模式
    # 选项可以跨行，但通常在题干后连续出现
    # 使用正则查找所有 (X) 选项标记
    opt_pattern = re.compile(r"[（(]\s*([A-D])\s*[）)]\s*")
    # 找所有选项标记位置
    matches = list(opt_pattern.finditer(text))
    if len(matches) < 2:
        return text, None
    # 检查是否形成 A/B/C/D 序列（允许从 A 开始连续）
    keys = [m.group(1) for m in matches]
    # 找最长的连续 A-B-C-D 序列
    best_start = None
    best_end = None
    i = 0
    while i < len(matches):
        if keys[i] == "A":
            j = i
            expected = "A"
            while j < len(matches) and keys[j] == expected:
                j += 1
                expected = chr(ord(expected) + 1)
            if j - i >= 2:
                best_start = i
                best_end = j
                i = j
                continue
        i += 1
    if best_start is None:
        return text, None
    # 选项文本从第一个选项标记开始到最后一个选项标记结束（含后续内容到下一个题号或答案）
    first_opt_pos = matches[best_start].start()
    last_match = matches[best_end - 1]
    # 题干 = 第一个选项标记之前的内容
    content = text[:first_opt_pos].strip()
    # 选项区间结束：延伸到 答案/【答案】/文本结束 之前
    opt_region_end = len(text)
    for marker in ("答案", "【答案】", "解", "分析"):
        idx = text.find(marker, last_match.end())
        if idx != -1 and idx < opt_region_end:
            opt_region_end = idx
    # 选项区文本
    opt_region = text[first_opt_pos: opt_region_end]
    # 从选项区提取每个选项
    opt_list = []
    for mi in range(best_start, best_end):
        m = matches[mi]
        key = m.group(1)
        # 选项文本从该标记结束到下一个标记开始
        start = m.end()
        if mi + 1 < best_end:
            end = matches[mi + 1].start()
        else:
            end = opt_region_end
        opt_text = text[start:end].strip()
        # 清理选项文本中的多余符号
        opt_text = re.sub(r"\s+", " ", opt_text).strip()
        opt_list.append((key, opt_text))
    return content, opt_list


def is_answer_line(line):
    """判断是否为答案行: '答案 B.' / '【答案】(B)' / '【答案】-2' / '(n)【答案】X'"""
    line = line.strip()
    if re.match(r"^答案\s*[（(]?\s*[A-D]", line):
        return True
    if line.startswith("【答案】"):
        return True
    if re.match(r"^[（(]\s*\d+\s*[）)]\s*【答案】", line):
        return True
    return False


def extract_qno_from_line(line):
    """从行首提取题号。兼容 '1 设...' / '(1) 曲线...' / '【1】已知...' / '(17)(本题满分...'
    排除答案行 '(2)B.' / '【答案】...' / '(n)【答案】...'。
    返回 (qno, rest) 或 None。
    """
    line = line.strip()
    if not line:
        return None
    if line.startswith("【答案】") or re.match(r"^答案\s*[（(]?\s*[A-D]", line):
        return None
    if re.match(r"^[（(]\s*\d+\s*[）)]\s*【答案】", line):
        return None
    # 匹配 (1) / （1) / 【1】 / 1 开头的题号
    m = re.match(r"^(?:[（(【]\s*)?(\d+)(?:\s*[）)】])?\s*[.、．]?\s*(.*)", line)
    if not m:
        return None
    qno = int(m.group(1))
    rest = m.group(2)
    # 排除答案行 '(2)B.'（rest 是单个字母且行很短）
    if re.match(r"^[A-D]\s*[.、．]?$", rest):
        return None
    return qno, rest


def extract_answer_from_line(line):
    """从答案行提取答案。
    '答案 B.' -> 'B'
    '【答案】(B)' -> 'B'
    '【答案】-2' -> '-2'
    '【答案】 $x+2y-z=0$' -> 'x+2y-z=0'
    '(n)【答案】X' -> 'X'
    """
    line = line.strip()
    # 格式1: 答案 B.
    m = re.match(r"^答案\s*[（(]?\s*([A-D])\s*[）)]?\s*\.?", line)
    if m:
        return m.group(1)
    # 格式2: 【答案】(B)
    m = re.match(r"^【答案】\s*[（(]\s*([A-D])\s*[）)]", line)
    if m:
        return m.group(1)
    # 格式3: 【答案】 内容 或 (n)【答案】 内容
    m = re.match(r"^(?:[（(]\s*\d+\s*[）)]\s*)?【答案】\s*(.*)", line)
    if m:
        ans = m.group(1).strip()
        # 去掉 LaTeX 美元符
        ans = re.sub(r"\$+", "", ans)
        return ans
    return None


def parse_direct_solution(fp, year):
    """解析 2022/2023/2024 解析文件（含题干+选项+答案+解析）
    策略：用题号行切分题目区间，在区间内提取题干/选项/答案/解析。
    """
    records = []
    txt = open(fp, encoding="utf-8").read()
    lines = txt.splitlines()

    # 1. 找到所有题号行位置，保存 (line_idx, qno, rest)
    qno_positions = []  # (line_idx, qno, rest)
    for i, line in enumerate(lines):
        res = extract_qno_from_line(line)
        if res:
            qno_positions.append((i, res[0], res[1]))

    # 2. 按题号行切分区间
    for idx, (start, qno, rest) in enumerate(qno_positions):
        end = qno_positions[idx + 1][0] if idx + 1 < len(qno_positions) else len(lines)
        block = lines[start:end]

        # 提取答案：在区间内找答案行
        answer = None
        ans_line_idx = None
        for bi, bl in enumerate(block):
            if is_answer_line(bl):
                answer = extract_answer_from_line(bl)
                ans_line_idx = bi
                break

        # 题干 = 题号行内容(rest) + 后续行，直到答案行（或区间末尾）
        stem_lines = [rest] if rest else []
        limit = ans_line_idx if ans_line_idx is not None else len(block)
        for bi in range(1, limit):
            l = block[bi].strip()
            if l in ("$$", "```"):
                continue
            stem_lines.append(l)
        raw_stem = " ".join(stem_lines)
        content, options = extract_options_from_text(raw_stem)
        content = clean_text(content)
        # 去掉 content 开头的题号前缀 (n) 或 n
        content = re.sub(r"^(?:[（(【]\s*)?\d+(?:\s*[）)】])?\s*[.、．]?\s*", "", content).strip()

        # 解析 = 答案行之后到区间末尾
        analysis_lines = []
        if ans_line_idx is not None:
            for bi in range(ans_line_idx + 1, len(block)):
                l = block[bi].strip()
                if l in ("$$", "```"):
                    analysis_lines.append("")
                    continue
                analysis_lines.append(l)
        analysis = clean_text(" ".join(analysis_lines)) if analysis_lines else None

        # 题型判断
        # 字母答案 (A-D) -> 选择题；但选项提取失败时跳过（避免无选项的"选择题"）
        if answer and re.match(r"^[A-D]$", answer.strip().upper()):
            if options and len(options) >= 3:
                qtype = "single"
            else:
                # 选项提取失败，跳过这道题
                continue
        else:
            # 非字母答案 -> 填空题（表达式答案）
            qtype = "fill"

        # 跳过无答案且无解析的题
        if not answer and not analysis:
            continue
        # 题干过短则跳过
        if len(content) < 5:
            continue
        records.append(_make_record(year, qno, content, options, answer, analysis, qtype))
    return records


def _make_record(year, qno, content, options, answer, analysis, qtype):
    """构造 record dict"""
    # 转换 options 为 canonical dict 格式
    canonical_options = make_options(options) if options else None
    rec = {
        "source": "math-zhenti",
        "subject": "数学",
        "subject_id": 8,
        "content": clean_text(content),
        "options": canonical_options,
        "answer": normalize_answer(answer) if canonical_options else clean_text(answer),
        "analysis": clean_text(analysis) if analysis else None,
        "question_type": qtype,
        "chapter": "考研数学一真题",
        "chapter_id": None,
        "knowledge_point": None,
        "source_label": f"考研数学一真题({year}年)",
        "difficulty": 4,
        "year": year,
        "paper": f"{year}年考研数学一真题",
        "external_id": f"{EXT_PREFIX}_{year}_{qno}",
    }
    return rec


# =========================================================
# 配对导入：1987-2021 题目文件 + 解析文件
# =========================================================
def parse_paired(year):
    """配对导入某一年真题"""
    records = []
    paper_fp = None
    for fp in glob.glob(os.path.join(PAPER_DIR, "*.md")):
        if str(year) in os.path.basename(fp):
            paper_fp = fp
            break
    sol_fp = None
    for fp in glob.glob(os.path.join(SOL_DIR, "*.md")):
        if str(year) in os.path.basename(fp):
            sol_fp = fp
            break
    if not paper_fp or not sol_fp:
        log.warning("缺少 %d 年题目或解析文件", year)
        return records

    paper_txt = open(paper_fp, encoding="utf-8").read()
    sol_txt = open(sol_fp, encoding="utf-8").read()

    # 1. 从题目文件提取每道题: 题号 -> {content, options}
    paper_questions = extract_paper_questions(paper_txt)

    # 2. 从解析文件提取: 题号 -> {answer, analysis}
    sol_answers = extract_solution_answers(sol_txt)

    # 3. 配对
    for qno, pq in paper_questions.items():
        if qno not in sol_answers:
            continue
        sa = sol_answers[qno]
        options = pq.get("options")
        content = pq["content"]
        answer = sa["answer"]
        analysis = sa["analysis"]
        # 题型判断
        if options:
            qtype = "single"
        else:
            # 填空题: 题干以"______"结尾或答案较短 -> fill
            # 否则视为 calc
            if re.search(r"_{2,}|________|（\s*）|\(\s*\)\s*$", content):
                qtype = "fill"
            else:
                qtype = "calc"
        records.append(_make_record(year, qno, content, options, answer, analysis, qtype))
    return records


def parse_paired_by_order(year):
    """顺序配对导入某一年真题的选择题。
    绕开早期试卷「各大题独立编号」导致的题号冲突：
    - 从题目文件按出现顺序提取选择题（题干+选项）
    - 从解析文件按出现顺序提取字母答案（【答案】(X)）
    - 第 i 个选择题 配对 第 i 个字母答案
    """
    records = []
    paper_fp = None
    for fp in glob.glob(os.path.join(PAPER_DIR, "*.md")):
        if str(year) in os.path.basename(fp):
            paper_fp = fp
            break
    sol_fp = None
    for fp in glob.glob(os.path.join(SOL_DIR, "*.md")):
        if str(year) in os.path.basename(fp):
            sol_fp = fp
            break
    if not paper_fp or not sol_fp:
        return records

    paper_txt = open(paper_fp, encoding="utf-8").read()
    sol_txt = open(sol_fp, encoding="utf-8").read()

    # 1. 从题目文件提取选择题（按顺序）
    choice_questions = extract_choice_questions_ordered(paper_txt)

    # 2. 从解析文件提取字母答案（按顺序）
    choice_answers = extract_choice_answers_ordered(sol_txt)

    # 3. 顺序配对
    for i, (qno, content, options) in enumerate(choice_questions):
        if i >= len(choice_answers):
            break
        answer = choice_answers[i]["answer"]
        analysis = choice_answers[i]["analysis"]
        # 选项必须完整且答案在选项中
        if not options or len(options) < 3:
            continue
        records.append(_make_record(year, qno, content, options, answer, analysis, "single"))
    return records


def extract_choice_questions_ordered(txt):
    """从题目文件按出现顺序提取选择题 [(qno, content, options)]"""
    result = []
    lines = txt.splitlines()
    cur_section = None
    cur_qno = None
    cur_content = []
    cur_options = []

    def flush():
        nonlocal cur_qno, cur_content, cur_options
        if cur_qno is not None and cur_section == "choice":
            content = clean_text(" ".join(cur_content))
            opts = make_options(cur_options) if len(cur_options) >= 2 else None
            if content and opts:
                result.append((cur_qno, content, opts))
        cur_qno = None
        cur_content = []
        cur_options = []

    def match_qno(line):
        m = re.match(r"^(?:[（(【]\s*)?(\d+)(?:\s*[）)】])?\s*[.、．]?\s*(.*)", line)
        if m:
            return int(m.group(1)), m.group(2)
        return None

    def match_opt(line):
        m = re.match(r"^(?:[（(]\s*)?([A-D])(?:\s*[）)])?\s*[.、．]?\s*(.*)", line)
        if m:
            return m.group(1), m.group(2)
        return None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if "选择" in line:
                cur_section = "choice"
            elif "填空" in line:
                cur_section = "fill"
            else:
                cur_section = None
            flush()
            continue
        qm = match_qno(line)
        if qm:
            flush()
            cur_qno = qm[0]
            if qm[1]:
                cur_content.append(qm[1])
            continue
        if cur_qno is not None and cur_section == "choice":
            om = match_opt(line)
            if om:
                cur_options.append((om[0], om[1]))
                continue
        if cur_qno is not None:
            cur_content.append(line)
    flush()
    return result


def extract_choice_answers_ordered(txt):
    """从解析文件按出现顺序提取选择题字母答案 [{'answer','analysis'}]"""
    result = []
    lines = txt.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # 匹配 "(n)【答案】(X)" 或 "【答案】(X)" 或 "答案 X."
        m = re.match(r"^(?:[（(]\s*(\d+)\s*[）)]\s*)?【答案】\s*[（(]\s*([A-D])\s*[）)]", line)
        if not m:
            m = re.match(r"^答案\s*[（(]?\s*([A-D])\s*[）)]?\s*\.?", line)
            if m:
                answer = m.group(1)
            else:
                i += 1
                continue
        else:
            answer = m.group(2)
        # 收集解析直到下一个答案行
        ana_lines = []
        j = i + 1
        while j < len(lines):
            l2 = lines[j].strip()
            if re.match(r"^(?:[（(]\s*\d+\s*[）)]\s*)?【答案】\s*[（(]\s*[A-D]\s*[）)]", l2):
                break
            if re.match(r"^答案\s*[（(]?\s*[A-D]", l2):
                break
            if l2 in ("$$", "```"):
                ana_lines.append("")
                j += 1
                continue
            ana_lines.append(l2)
            j += 1
        i = j
        analysis = clean_text(" ".join(ana_lines)) if ana_lines else None
        result.append({"answer": answer, "analysis": analysis})
    return result


def extract_paper_questions(txt):
    """从题目文件提取 {题号: {'content':..., 'options': [...]}}"""
    questions = {}
    lines = txt.splitlines()
    cur_section = None
    cur_qno = None
    cur_content = []
    cur_options = []

    def flush():
        nonlocal cur_qno, cur_content, cur_options
        if cur_qno is not None:
            content = clean_text(" ".join(cur_content))
            opts = make_options(cur_options) if len(cur_options) >= 2 else None
            questions[cur_qno] = {"content": content, "options": opts}
        cur_qno = None
        cur_content = []
        cur_options = []

    def match_qno(line):
        """匹配题号: (1) / 1. / 1、 / 【1】"""
        m = re.match(r"^(?:[（(【]\s*)?(\d+)(?:\s*[）)】])?\s*[.、．]?\s*(.*)", line)
        if m:
            return int(m.group(1)), m.group(2)
        return None

    def match_opt(line):
        """匹配选项行: (A) xxx / A. xxx / A、xxx"""
        m = re.match(r"^(?:[（(]\s*)?([A-D])(?:\s*[）)])?\s*[.、．]?\s*(.*)", line)
        if m:
            return m.group(1), m.group(2)
        return None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 检测分区标题
        if line.startswith("#"):
            if "选择" in line:
                cur_section = "choice"
            elif "填空" in line:
                cur_section = "fill"
            else:
                cur_section = None
            flush()
            continue
        # 检测题号
        qm = match_qno(line)
        if qm:
            flush()
            cur_qno = qm[0]
            rest = qm[1]
            if rest:
                cur_content.append(rest)
            continue
        # 检测选项行（仅在选择题区）
        if cur_qno is not None and cur_section == "choice":
            om = match_opt(line)
            if om:
                cur_options.append((om[0], om[1]))
                continue
        # 其他行追加到题干
        if cur_qno is not None:
            cur_content.append(line)
    flush()
    return questions


def extract_solution_answers(txt):
    """从解析文件提取 {题号: {'answer':..., 'analysis':...}}"""
    answers = {}
    lines = txt.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # 格式A: "(1)【答案】 X"（题号+答案同行）
        m = re.match(r"^[（(]\s*(\d+)\s*[）)]\s*【答案】\s*(.*)", line)
        if m:
            qno = int(m.group(1))
            ans_raw = m.group(2).strip()
            # 提取答案（字母或表达式）
            am = re.search(r"[A-D]", ans_raw)
            answer = am.group(0) if am else re.sub(r"\$+", "", ans_raw)
            # 收集解析直到下一题
            ana_lines = []
            j = i + 1
            while j < len(lines):
                l2 = lines[j].strip()
                if re.match(r"^[（(]\s*\d+\s*[）)]\s*【答案】", l2):
                    break
                if l2.startswith("【答案】"):
                    break
                if l2 in ("$$", "```"):
                    ana_lines.append("")
                    j += 1
                    continue
                ana_lines.append(l2)
                j += 1
            i = j
            analysis = clean_text(" ".join(ana_lines)) if ana_lines else None
            answers[qno] = {"answer": answer, "analysis": analysis}
            continue
        # 格式B: "【答案】(B)" 或 "【答案】-2"（答案行，题号在之前的行）
        m = re.match(r"^【答案】\s*(.*)", line)
        if m:
            ans_raw = m.group(1).strip()
            am = re.search(r"[A-D]", ans_raw)
            answer = am.group(0) if am else re.sub(r"\$+", "", ans_raw)
            # 向前找题号
            qno = None
            for j in range(i - 1, -1, -1):
                qm = re.match(r"^[（(]\s*(\d+)\s*[）)]", lines[j].strip())
                if qm:
                    qno = int(qm.group(1))
                    break
            if qno is None:
                i += 1
                continue
            # 收集解析直到下一题
            ana_lines = []
            j = i + 1
            while j < len(lines):
                l2 = lines[j].strip()
                if re.match(r"^[（(]\s*\d+\s*[）)]\s*【答案】", l2):
                    break
                if l2.startswith("【答案】"):
                    break
                if l2 in ("$$", "```"):
                    ana_lines.append("")
                    j += 1
                    continue
                ana_lines.append(l2)
                j += 1
            i = j
            analysis = clean_text(" ".join(ana_lines)) if ana_lines else None
            answers[qno] = {"answer": answer, "analysis": analysis}
            continue
        # 格式C: "答案 B."（2022）
        m = re.match(r"^答案\s*[（(]?\s*([A-D])\s*[）)]?\s*\.?", line)
        if m:
            answer = m.group(1)
            # 向前找题号
            qno = None
            for j in range(i - 1, -1, -1):
                qm = re.match(r"^(?:[（(]\s*)?(\d+)(?:\s*[）)])?\s*[.、．]?\s*", lines[j].strip())
                if qm and not re.match(r"^答案", lines[j].strip()):
                    qno = int(qm.group(1))
                    break
            if qno is None:
                i += 1
                continue
            ana_lines = []
            j = i + 1
            while j < len(lines):
                l2 = lines[j].strip()
                if re.match(r"^答案\s*[（(]?\s*[A-D]", l2):
                    break
                if l2 in ("$$", "```"):
                    ana_lines.append("")
                    j += 1
                    continue
                ana_lines.append(l2)
                j += 1
            i = j
            analysis = clean_text(" ".join(ana_lines)) if ana_lines else None
            answers[qno] = {"answer": answer, "analysis": analysis}
            continue
        i += 1
    return answers


# =========================================================
# 主流程
# =========================================================
def main():
    all_records = []

    # A. 直接导入 2022/2023/2024（解析文件自带题干+选项）
    #    年份白名单：只保留清晰选择题（2022/2024 部分题 OCR 质量差或子问题误判）
    YEAR_QNO_WHITELIST = {
        2022: {1, 2, 6, 7, 8, 10},
        2023: None,  # 全部保留
        2024: {1, 4, 5, 7, 10},
    }
    for year in (2022, 2023, 2024):
        for fp in glob.glob(os.path.join(SOL_DIR, "*.md")):
            if str(year) in os.path.basename(fp):
                recs = parse_direct_solution(fp, year)
                whitelist = YEAR_QNO_WHITELIST.get(year)
                if whitelist is not None:
                    recs = [r for r in recs if int(r["external_id"].split("_")[-1]) in whitelist]
                log.info("直接解析 %d 年: %d 题", year, len(recs))
                all_records.extend(recs)
                break

    # B. 顺序配对导入 1987-2021 选择题
    for year in range(1987, 2022):
        if year == 1994:
            # 1994 有解析文件但无题目文件
            continue
        recs = parse_paired_by_order(year)
        if recs:
            log.info("顺序配对导入 %d 年: %d 题", year, len(recs))
            all_records.extend(recs)

    log.info("共解析 %d 题，开始写入...", len(all_records))

    conn = psycopg.connect(DB_DSN)
    try:
        inserted = write_records(conn, all_records)
        log.info("成功插入 %d 题", inserted)
    finally:
        conn.close()

    print("\n===== 数学真题导入统计 =====")
    print(f"解析总数: {len(all_records)}")
    print(f"成功插入: {stats['inserted']}")
    print(f"\n按年份:")
    for k in sorted(stats):
        if k.startswith("by_year_"):
            print(f"  {k.replace('by_year_', '')}年: {stats[k]}")
    print(f"\n跳过原因:")
    for k, v in stats.items():
        if k.startswith("skipped") and v:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()