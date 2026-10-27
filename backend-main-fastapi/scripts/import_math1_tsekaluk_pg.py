#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入考研数学一真题（TsekaLuk/Kaoyan-Math1-Papers）到 quiz_questions 表 (PostgreSQL)

数据源:
  D:\\平台\\data_sources\\Kaoyan-Math1-Papers\\Kaoyan-Math1-Papers-main\\papers\\*.md     （题目）
  D:\\平台\\data_sources\\Kaoyan-Math1-Papers\\Kaoyan-Math1-Papers-main\\solutions\\<年份>年解析\\*.md （解析）

导入范围:
  A. 2025 卷 papers\\2025年数学一真题.md 自带【答案】+【解析】 -> 直接解析导入（1-22 题）
  B. 2022/2023/2024 解析文件自带完整题干+选项+答案(+解析)      -> 直接解析导入
  C. 2013-2021 配对导入：papers 题目 + solutions 解析 按"分区顺序"配对
     - 选择题 -> single
     - 填空题 -> fill
     - 解答题 -> calc

去重:
  - external_id 唯一约束（math1_tsekaluk_<year>_<no>）保证脚本幂等
  - 按题干内容归一化后与库中 subject_id=8 同年份已有题比对，跳过重复（避免与旧导入重复）

质量门禁:
  - 单选题 answer 必须在选项 key 中
  - 填空/解答题必须有答案或解析
  - content/analysis 保留 LaTeX（$ 数学公式），剔除 OCR 私有区乱码

运行:
  python scripts/import_math1_tsekaluk_pg.py [--dry-run]
"""
import os
import re
import json
import glob
import logging
from collections import Counter, defaultdict

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = r"D:\平台\data_sources\Kaoyan-Math1-Papers\Kaoyan-Math1-Papers-main"
PAPER_DIR = os.path.join(DATA_ROOT, "papers")
SOL_DIR = os.path.join(DATA_ROOT, "solutions")

DB_DSN = "host=127.0.0.1 port=5432 user=kaoyan password=kaoyan_dev_2026 dbname=kaoyan"

EXT_PREFIX = "math1_tsekaluk"
SUBJECT_ID = 8
SUBJECT = "数学"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_math1_tsekaluk")

stats = Counter()

# =========================================================
# 文本清洗
# =========================================================
PUA_RE = re.compile(r"[\ue000-\uf8ff]")  # OCR 私有区乱码

def clean_content(s):
    """清理文本但保留 LaTeX $...$ 标记（用于 content/options/analysis 入库）"""
    if not s:
        return ""
    s = str(s)
    s = "".join(ch for ch in s if ch >= "\u0001" or ch in ("\n", "\t", "\r"))
    s = PUA_RE.sub("", s)
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    s = s.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    s = re.sub(r"<[^>]+>", "", s)
    # 去 markdown 链接但保留链接文字
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    # 合并连续空白为单空格（保留换行为空格）
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_text(s):
    """彻底清洗（用于答案归一化/质量判断）：去除 $、图片、HTML 等"""
    if not s:
        return ""
    s = clean_content(s)
    s = re.sub(r"\$+", "", s)
    s = re.sub(r"!\[.*?\]\(.*?\)", "", s)
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


def join_clean(lines):
    """把若干行拼成一段并清洗（保留 LaTeX）"""
    parts = [l.strip() for l in lines if l and l.strip()]
    if not parts:
        return ""
    return clean_content(" ".join(parts))


def normalize_answer(ans):
    """归一化答案: 去掉括号/空白/标点, 大写（用于校验）"""
    if not ans:
        return ""
    ans = clean_text(ans)
    ans = re.sub(r"[\(\)（）、.\s]", "", ans)
    return ans.upper()


def normalize_for_dedup(s):
    """内容归一化，用于跨源去重：
    去掉 $、LaTeX 命令、图片/链接、所有非字母数字/汉字，转小写"""
    if not s:
        return ""
    s = str(s)
    s = re.sub(r"!\[.*?\]\(.*?\)", "", s)
    s = re.sub(r"\[.*?\]\(.*?\)", "", s)
    s = re.sub(r"\$+", "", s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)  # LaTeX 命令 -> 空格
    s = s.lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s)
    return s


def make_options(opt_list):
    """将 [('A','text'), ...] 转为 canonical JSON 数组（保留 LaTeX）"""
    result = []
    for item in opt_list:
        if isinstance(item, dict):
            key = clean_text(str(item.get("key", ""))).strip().upper()
            text = clean_content(str(item.get("text", item.get("content", ""))))
        else:
            key = clean_text(str(item[0])).strip().upper()
            text = clean_content(str(item[1]))
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
    needs_review, images, question_no
) VALUES (
    %(content)s, %(options)s, %(answer)s, %(analysis)s,
    NULL, NULL, %(question_type)s, 'objective', %(difficulty)s,
    'past_exam', %(source_label)s, %(year)s, %(paper)s, NULL,
    %(external_id)s, %(subject_id)s, %(subject)s, %(chapter_id)s,
    %(chapter)s, %(knowledge_point)s, 'high', 'A', FALSE, TRUE, NULL,
    'source_extract', 0.95, TRUE, FALSE, FALSE, %(figure_missing)s, 'pass', '[]',
    NULL, NOW(), NOW(), 0.95, 'external_import', FALSE, '[]', %(question_no)s
)
ON CONFLICT (external_id) DO NOTHING
"""


# =========================================================
# 通用工具
# =========================================================
OPT_MARK_RE = re.compile(r"[（(]\s*(?:\\mathrm\{)?\s*([A-D])\s*(?:\})?\s*(?:\\right)?\s*[）)]")

SECTION_RE = re.compile(r"^[#\s]*[一二三]、?\s*(选择题|填空题|解答题)", re.MULTILINE)


def section_name(line):
    if "选择" in line:
        return "choice"
    if "填空" in line:
        return "fill"
    if "解答" in line:
        return "calc"
    return None


def extract_options_from_text(text):
    """从文本中提取选项 (A)(B)(C)(D)。支持：
    - 内联 `\\left(\\mathrm{A}\\right)` 形式
    - 选项顺序错乱（如 A,C,B,D）
    返回 (content, options) 或 (text, None)"""
    matches = list(OPT_MARK_RE.finditer(text))
    if len(matches) < 2:
        return text, None
    # 按首次出现顺序收集不同选项字母
    seen = {}  # key -> first match index
    for idx, m in enumerate(matches):
        k = m.group(1)
        if k in "ABCD" and k not in seen:
            seen[k] = idx
    if len(seen) < 2:
        return text, None
    ordered = sorted(seen.items(), key=lambda x: x[1])  # 按出现顺序
    first_pos = matches[ordered[0][1]].start()
    content = text[:first_pos].strip()

    # 按原文顺序切分：每个 marker 到下一个 marker 之间为其选项文本
    sorted_matches = sorted(matches, key=lambda m: m.start())
    raw_opts = []
    for mi, m in enumerate(sorted_matches):
        k = m.group(1)
        if k not in "ABCD":
            continue
        s = m.end()
        e = sorted_matches[mi + 1].start() if mi + 1 < len(sorted_matches) else len(text)
        raw_opts.append((k, text[s:e].strip()))
    # 去重（同一字母只保留第一次出现）
    opt_list = []
    used = set()
    for k, t in raw_opts:
        if k not in used:
            used.add(k)
            t = re.sub(r"^[.、．:：\s]+", "", t)
            opt_list.append((k, t))
    return content, opt_list


def extract_answer_from_raw(raw):
    """从 (N)【答案】 之后的原始文本提取答案。
    '(D).' -> 'D' ; '$\\frac{\\pi}{4}$ .' -> '\\frac{\\pi}{4}' ; '1.' -> '1'"""
    raw = (raw or "").strip()
    m = re.match(r"[（(]?\s*([A-D])\s*[）)]?\s*\.?$", raw)
    if m:
        return m.group(1)
    raw = re.sub(r"\$+", "", raw)
    raw = raw.rstrip(".。")
    return raw.strip()


def type_by_qno(qno, year):
    if year <= 2020:
        if qno <= 8:
            return "single"
        if qno <= 14:
            return "fill"
        return "calc"
    else:
        if qno <= 10:
            return "single"
        if qno <= 16:
            return "fill"
        return "calc"


def find_file(directory, year, recursive=False):
    """在目录（含子目录）中找包含 year 的 .md 文件"""
    pattern = os.path.join(directory, "**", "*.md") if recursive else os.path.join(directory, "*.md")
    for fp in glob.glob(pattern, recursive=recursive):
        base = os.path.basename(fp)
        if str(year) in base:
            return fp
    return None


def make_record(year, qno, content, options, answer, analysis, qtype):
    canonical_options = make_options(options) if options else None
    has_img = bool(re.search(r"!\[.*?\]\(.*?\)", content or "")) or bool(
        re.search(r"!\[.*?\]\(.*?\)", analysis or ""))
    rec = {
        "subject": SUBJECT,
        "subject_id": SUBJECT_ID,
        "content": content,
        "options": canonical_options,
        "answer": normalize_answer(answer) if canonical_options else clean_text(answer),
        "analysis": clean_content(analysis) if analysis else None,
        "question_type": qtype,
        "chapter": "考研数学一真题",
        "chapter_id": None,
        "knowledge_point": None,
        "source_label": f"考研数学一真题-TsekaLuk({year}年)",
        "difficulty": 4,
        "year": year,
        "paper": f"{year}年考研数学一真题",
        "external_id": f"{EXT_PREFIX}_{year}_{qno}",
        "figure_missing": 1 if has_img else 0,
        "question_no": qno,
    }
    return rec


# =========================================================
# A. 2025 卷直接解析
# =========================================================
def parse_2025_paper(fp):
    lines = open(fp, encoding="utf-8").read().splitlines()
    # 源文件中个别题【答案】行为空（如 2025 第 8 题），依据官方答案补齐
    HARDCODED_ANSWERS = {8: "C"}
    qstarts = []  # (line_idx, qno, rest)
    for i, l in enumerate(lines):
        l = l.strip()
        if not l:
            continue
        if re.match(r"^\d+\s*[.．、]?\s*解[:：]", l):
            continue  # 排除 "17．解：" 这类解析行
        m = re.match(r"^#?\s*(\d+)[.．、]\s*(.*)$", l)
        if m:
            qno = int(m.group(1))
            if 1 <= qno <= 22:
                qstarts.append((i, qno, m.group(2)))

    records = []
    for idx, (start, qno, rest) in enumerate(qstarts):
        end = qstarts[idx + 1][0] if idx + 1 < len(qstarts) else len(lines)
        block = [l.strip() for l in lines[start + 1:end] if l.strip()]
        block_lines = ([rest] if rest else []) + block

        # 找答案行
        answer = None
        ans_idx = None
        for bi, l in enumerate(block_lines):
            if l.startswith("【答案】"):
                answer = extract_answer_from_raw(l[len("【答案】"):])
                ans_idx = bi
                break
        if not answer and qno in HARDCODED_ANSWERS:
            answer = HARDCODED_ANSWERS[qno]

        # 找解析行
        ana_idx = None
        for bi, l in enumerate(block_lines):
            if l.startswith("【解析】") or l.startswith("【解】") or re.match(r"^\d*\s*[.．、]?\s*解[:：]", l):
                ana_idx = bi
                break

        qtype = type_by_qno(qno, 2025)
        content = ""
        options = None
        analysis = None

        # 题干/选项区：答案/解析之前的所有行
        pre_lines = []
        for bi, l in enumerate(block_lines):
            if bi == ans_idx or bi == ana_idx:
                break
            pre_lines.append(l)

        if qtype == "single":
            content_parts = []
            opt_pairs = []
            started = False
            for l in pre_lines:
                om = re.match(r"^([A-D])[.．、]\s*(.*)$", l)
                if om:
                    started = True
                    opt_pairs.append((om.group(1), om.group(2)))
                else:
                    if not started:
                        content_parts.append(l)
            # 仅当 4 个选项都有前缀时才走常规路径
            options = make_options(opt_pairs) if len(opt_pairs) == 4 else None
            content = ""
            if options is None:
                # 回退：OCR 丢失选项前缀时，题干后前 4 个"类选项"行按顺序赋 A-D
                first_opt = None
                for bi, l in enumerate(pre_lines):
                    if re.match(r"^[A-D][.．、]", l) or re.match(r"^[\\$]", l) or OPT_MARK_RE.search(l):
                        first_opt = bi
                        break
                if first_opt is not None:
                    content = join_clean(pre_lines[:first_opt])
                    non_blank = [l for l in pre_lines[first_opt:] if l.strip()]
                    if len(non_blank) == 4:
                        opt_pairs = []
                        for j, l in enumerate(non_blank):
                            key = chr(ord("A") + j)
                            txt = re.sub(r"^[A-D][.．、]\s*", "", l.strip())
                            opt_pairs.append((key, txt))
                        options = make_options(opt_pairs)
            if not content:
                content = join_clean(pre_lines)
        else:
            content = join_clean(pre_lines)

        # 解析
        if ana_idx is not None:
            # 解析从 ana_idx 行（含标记）之后开始；若标记行本身带内容则也纳入
            ana_parts = []
            marker = block_lines[ana_idx]
            if marker.startswith("【解析】"):
                tail = marker[len("【解析】"):].strip()
                if tail:
                    ana_parts.append(tail)
            elif marker.startswith("【解】"):
                tail = marker[len("【解】"):].strip()
                if tail:
                    ana_parts.append(tail)
            else:
                m = re.match(r"^\d*\s*[.．、]?\s*解[:：]\s*(.*)$", marker)
                if m and m.group(1):
                    ana_parts.append(m.group(1))
            ana_parts.extend(block_lines[ana_idx + 1:])
            analysis = join_clean(ana_parts)

        if not content:
            continue
        records.append(make_record(2025, qno, content, options, answer, analysis, qtype))
    return records


# =========================================================
# B. 2022/2023/2024 解析文件（自带题干）
# =========================================================
def parse_2023_solution(fp, year):
    """2023: (1) 题干 ... 【答案】(B) 【解析】..."""
    qno_re = re.compile(r"^[（(]\s*(\d+)\s*[）)]\s*(.*)$")
    return parse_embedded_lines(fp, year, qno_re)


def parse_2024_solution(fp, year):
    """2024: 【1】题干 ... 【答案】（C）。注意 OCR 可能导致 【N】 前有杂字符（如 a【6】）"""
    qno_re = re.compile(r"【\s*(\d+)\s*】\s*(.*)$")
    return parse_embedded_lines(fp, year, qno_re, use_search=True)


def expected_qnos(section, year):
    """返回某分区内合法的题目编号集合（用于避免把小题号/OCR 误识别当作新题）"""
    if year <= 2020:
        if section == "choice":
            return set(range(1, 9))
        if section == "fill":
            return set(range(9, 15))
        if section == "calc":
            return set(range(15, 24))
    else:
        if section == "choice":
            return set(range(1, 11))
        if section == "fill":
            return set(range(11, 17))
        if section == "calc":
            return set(range(17, 23))
    return set()


def parse_embedded_lines(fp, year, qno_re, use_search=False):
    lines = open(fp, encoding="utf-8").read().splitlines()
    records = []
    cur_qno = None
    cur_lines = []
    cur_answer = None
    cur_analysis = None
    cur_section = None
    seen_qnos = set()

    def flush():
        nonlocal cur_qno, cur_lines, cur_answer, cur_analysis
        if cur_qno is None:
            return
        # 找答案/解析位置
        ans_idx = None
        ana_idx = None
        for bi, l in enumerate(cur_lines):
            if l.startswith("【答案】"):
                ans_idx = bi
            if l.startswith("【解析】") or l.startswith("【解】"):
                ana_idx = bi
                break
        if ans_idx is not None and cur_answer is None:
            cur_answer = extract_answer_from_raw(cur_lines[ans_idx][len("【答案】"):])

        # 题干区 = 解析标记之前的所有行，并去掉答案行
        if ana_idx is not None:
            content_lines = [l for l in cur_lines[:ana_idx] if not l.startswith("【答案】")]
        else:
            content_lines = [l for l in cur_lines if not l.startswith("【答案】")]
        content_text = "\n".join(content_lines)
        content, options = extract_options_from_text(content_text)
        content = clean_content(content)

        # 解析区
        analysis = None
        if ana_idx is not None:
            ana_parts = []
            marker = cur_lines[ana_idx]
            if marker.startswith("【解析】"):
                tail = marker[len("【解析】"):].strip()
                if tail:
                    ana_parts.append(tail)
            elif marker.startswith("【解】"):
                tail = marker[len("【解】"):].strip()
                if tail:
                    ana_parts.append(tail)
            ana_parts.extend(cur_lines[ana_idx + 1:])
            analysis = join_clean(ana_parts)

        qtype = type_by_qno(cur_qno, year)

        # 单选题选项回退：OCR 把 (B) 识别成 (3) 等导致选项不全时，题干后的 4 个类选项行按顺序赋 A-D
        if qtype == "single" and (not options or len(options) < 3):
            pre_lines = content_lines  # 已不含答案/解析
            first_opt = None
            for bi, l in enumerate(pre_lines):
                if OPT_MARK_RE.search(l) or re.match(r"^[（(]\s*[A-D]?", l) or l.startswith("$") or l.startswith("\\"):
                    first_opt = bi
                    break
            if first_opt is not None:
                candidates = [l for l in pre_lines[first_opt:] if l.strip()]
                if len(candidates) == 4:
                    content = join_clean(pre_lines[:first_opt])
                    opt_pairs = []
                    for j, l in enumerate(candidates):
                        key = chr(ord("A") + j)
                        txt = re.sub(r"^[（(][^）)]*[）)]\s*", "", l.strip())
                        txt = re.sub(r"^[（(][^）)]*[）)]\s*", "", txt)
                        opt_pairs.append((key, txt))
                    options = make_options(opt_pairs)

        if qtype == "single" and not options:
            cur_qno = None
            cur_lines = []
            cur_answer = None
            cur_analysis = None
            return
        if content:
            records.append(make_record(year, cur_qno, content, options, cur_answer, analysis, qtype))
        cur_qno = None
        cur_lines = []
        cur_answer = None
        cur_analysis = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        sm = SECTION_RE.match(line)
        if sm:
            flush()
            cur_section = section_name(line)
            seen_qnos.clear()
            continue
        qm = qno_re.search(line) if use_search else qno_re.match(line)
        if qm:
            qno = int(qm.group(1))
            if qno in expected_qnos(cur_section, year) and qno not in seen_qnos:
                flush()
                cur_qno = qno
                seen_qnos.add(qno)
                cur_lines.append(qm.group(2))
                continue
        if cur_qno is not None:
            cur_lines.append(line)
    flush()
    return records


# ---------- 2022 特殊解析 ----------
# 2022 解析文件中第 3/4/5 题的题干行丢失了题号，这里硬编码其起始行号（1-based）。
# 该数据源文件为静态文件，行号稳定；解析器仍会自动寻找答案行与选项。
UNNUMBERED_2022 = {3: 73, 4: 109, 5: 135}


def parse_2022_solution(fp, year):
    lines = open(fp, encoding="utf-8").read().splitlines()
    # 截断到"答案速查"之前
    end = len(lines)
    for i, l in enumerate(lines):
        if "答案速查" in l:
            end = i
            break
    lines = lines[:end]

    # 分区
    section_at = {}
    cur_section = None
    for i, l in enumerate(lines):
        sm = SECTION_RE.match(l.strip())
        if sm:
            cur_section = section_name(l)
        section_at[i] = cur_section

    blocks = []  # (start_idx, qno)
    # 1) 带题号的行
    for i, l in enumerate(lines):
        l = l.strip()
        if not l:
            continue
        m = re.match(r"^(\d{1,2})\s+(\S.*)$", l)
        if m and section_at.get(i) is not None:
            qno = int(m.group(1))
            if 1 <= qno <= 22:
                blocks.append([i, qno])
    # 2) 无题号的 3/4/5 题
    existing = {qno for _, qno in blocks}
    for qno, line_no in UNNUMBERED_2022.items():
        if qno not in existing and 1 <= line_no <= len(lines):
            blocks.append([line_no - 1, qno])
    blocks.sort(key=lambda x: x[0])

    records = []
    for idx, (start, qno) in enumerate(blocks):
        b_end = blocks[idx + 1][0] if idx + 1 < len(blocks) else len(lines)
        block_lines = [l.strip() for l in lines[start:b_end] if l.strip()]
        if not block_lines:
            continue
        # 去掉首行题号前缀（如果是带题号的行）
        first = block_lines[0]
        m = re.match(r"^(\d{1,2})\s+(.*)$", first)
        if m:
            block_lines[0] = m.group(2)

        # 找答案行：`答案 X.` / `答案 应填...`
        answer = None
        ans_idx = None
        for bi, l in enumerate(block_lines):
            m = re.match(r"^答案\s*(.*)$", l)
            if m:
                answer = extract_answer_from_raw(m.group(1))
                ans_idx = bi
                break

        # 找解析起点：`分析` / `解`（在答案行之后）
        ana_idx = None
        for bi, l in enumerate(block_lines):
            if l.startswith("分析") or l.startswith("解") or l.startswith("【解】") or l.startswith("【解析】"):
                ana_idx = bi
                break

        # 题干文本 = 答案行之前（若答案行存在），否则到解析行之前
        content_text_lines = block_lines
        if ans_idx is not None:
            content_text_lines = block_lines[:ans_idx]
        elif ana_idx is not None:
            content_text_lines = block_lines[:ana_idx]
        content_text = "\n".join(content_text_lines)
        content, options = extract_options_from_text(content_text)
        content = clean_content(content)

        analysis = None
        if ans_idx is not None:
            # 分析 = 答案行之后（去掉"分析/解"标记本身由 join_clean 保留）
            ana_lines = block_lines[ans_idx + 1:]
            if ana_lines:
                # 去掉开头的 "分析" / "解" 标记行内容里的标记词，保留正文
                cleaned_ana = []
                for l in ana_lines:
                    l2 = re.sub(r"^(分析|解|【解】|【解析】)\s*", "", l)
                    cleaned_ana.append(l2)
                analysis = join_clean(cleaned_ana)
        elif ana_idx is not None:
            ana_lines = block_lines[ana_idx + 1:]
            cleaned_ana = []
            marker = block_lines[ana_idx]
            marker_tail = re.sub(r"^(分析|解|【解】|【解析】)\s*", "", marker)
            if marker_tail:
                cleaned_ana.append(marker_tail)
            for l in ana_lines:
                l2 = re.sub(r"^(分析|解|【解】|【解析】)\s*", "", l)
                cleaned_ana.append(l2)
            analysis = join_clean(cleaned_ana)

        qtype = type_by_qno(qno, year)
        if qtype == "single" and not options:
            continue
        if content:
            records.append(make_record(year, qno, content, options, answer, analysis, qtype))
    return records


# =========================================================
# C. 2013-2021 配对导入
# =========================================================
def parse_paper_questions(year):
    """解析 papers 文件 -> 按分区顺序的题目列表"""
    fp = find_file(PAPER_DIR, year)
    if not fp:
        return []
    lines = open(fp, encoding="utf-8").read().splitlines()
    questions = []  # {section, qno, content, options}
    cur_section = None
    cur_qno = None
    cur_lines = []

    def flush():
        nonlocal cur_qno, cur_lines
        if cur_qno is not None and cur_section is not None:
            text = "\n".join(cur_lines)
            content, options = extract_options_from_text(text)
            content = clean_content(content)
            questions.append({
                "section": cur_section,
                "qno": cur_qno,
                "content": content,
                "options": options,
            })
        cur_qno = None
        cur_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        sm = SECTION_RE.match(line)
        if sm:
            flush()
            cur_section = section_name(line)
            continue
        # 选项行不应被当作题号
        if re.match(r"^[（(]\s*[A-D]\s*[）)]", line):
            if cur_qno is not None:
                cur_lines.append(line)
            continue
        qm = re.match(r"^\s*[（(【]?\s*(\d+)\s*[）)】]?\s*[.、．]?\s*(.*)$", line)
        if qm:
            qno = int(qm.group(1))
            flush()
            cur_qno = qno
            if qm.group(2):
                cur_lines.append(qm.group(2))
            continue
        if cur_qno is not None:
            cur_lines.append(line)
    flush()
    return questions


def parse_solution_items(year):
    """解析 solutions 文件 -> 按分区顺序的 (qno, answer, analysis) 列表"""
    fp = find_file(SOL_DIR, year, recursive=True)
    if not fp:
        return []
    text = open(fp, encoding="utf-8").read()

    def section_by_qno(qno):
        if year <= 2020:
            if qno <= 8:
                return "choice"
            if qno <= 14:
                return "fill"
            return "calc"
        else:
            if qno <= 10:
                return "choice"
            if qno <= 16:
                return "fill"
            return "calc"

    marker_re = re.compile(
        r"[（(]\s*(\d+)\s*[）)]\s*(?:[（(]?\s*[IⅠⅡⅢⅣ]+\s*[）)]?\s*)?(【答案】|【解】|【证明】)")
    markers = list(marker_re.finditer(text))
    items = []
    for idx, m in enumerate(markers):
        qno = int(m.group(1))
        kind = m.group(2)
        seg_start = m.end()
        seg_end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
        # 若段内有分区头，截断
        for hm in re.finditer(r"^[#\s]*[一二三]、?\s*(选择题|填空题|解答题)", text, re.MULTILINE):
            hp = hm.start()
            if seg_start < hp < seg_end:
                seg_end = hp
                break
        segment = text[seg_start:seg_end]
        answer = None
        analysis = None
        if kind == "【答案】":
            nl = segment.find("\n")
            if nl == -1:
                ans_raw = segment
                rest = ""
            else:
                ans_raw = segment[:nl]
                rest = segment[nl + 1:]
            answer = extract_answer_from_raw(ans_raw)
            jie = rest.find("【解】")
            if jie != -1:
                analysis = rest[jie + len("【解】"):]
            else:
                analysis = rest
        else:
            analysis = segment
        items.append({
            "section": section_by_qno(qno),
            "qno": qno,
            "answer": answer,
            "analysis": clean_content(analysis) if analysis else None,
        })
    return items


# 某些题目源文件 OCR 丢失了选项前缀，但选项文本仍在文件中。
# 这里按 (year, qno) 手动补齐缺失选项（内容来自源文件本身，未改动）。
HARDCODED_EXTRA_OPTIONS = {
    (2014, 3): [("D", r"$\int_0^{\frac{\pi}{2}}\mathrm{d}\theta \int_0^{\frac{1}{\cos\theta + \sin\theta}}f(r\cos \theta ,r\sin \theta)r\mathrm{d}r + \int_{\frac{\pi}{2}}^{\pi}\mathrm{d}\theta \int_0^1 f(r\cos \theta ,r\sin \theta)r\mathrm{d}r.$")],
}


def parse_paired(year):
    """2013-2021：papers 题目 + solutions 解析，按分区顺序配对"""
    pqs = parse_paper_questions(year)
    sas = parse_solution_items(year)
    if not pqs or not sas:
        return []
    paper_by_sec = defaultdict(list)
    for q in pqs:
        paper_by_sec[q["section"]].append(q)
    sol_by_sec = defaultdict(list)
    for s in sas:
        sol_by_sec[s["section"]].append(s)

    records = []
    for sec in ("choice", "fill", "calc"):
        plist = paper_by_sec.get(sec, [])
        slist = sol_by_sec.get(sec, [])
        for i, pq in enumerate(plist):
            if i >= len(slist):
                break
            sa = slist[i]
            qtype = {"choice": "single", "fill": "fill", "calc": "calc"}[sec]
            if qtype == "single" and not pq.get("options"):
                continue
            # 补齐 OCR 丢失前缀的选项
            if qtype == "single" and pq.get("options"):
                extra = HARDCODED_EXTRA_OPTIONS.get((year, pq["qno"]))
                if extra:
                    existing_keys = {k for k, _ in pq["options"]}
                    for k, t in extra:
                        if k not in existing_keys:
                            pq = {**pq, "options": pq["options"] + [(k, t)]}
            # 以解析文件中的题号为准（2021 填空题干题号 OCR 破损）
            qno = sa.get("qno") or pq["qno"]
            records.append(make_record(
                year, qno, pq["content"], pq.get("options"),
                sa.get("answer"), sa.get("analysis"), qtype))
    return records


# =========================================================
# 去重 & 写入
# =========================================================
def load_existing_content(conn):
    """加载 subject_id=8 且 year>=2013 的已有题目内容（用于去重）"""
    existing = defaultdict(set)  # year -> set(normalized content)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT year, content FROM quiz_questions
            WHERE subject_id = %s AND year IS NOT NULL AND year >= 2013
        """, (SUBJECT_ID,))
        for year, content in cur.fetchall():
            norm = normalize_for_dedup(content)
            if norm:
                existing[year].add(norm)
    return existing


def write_records(conn, records, existing_content):
    inserted = 0
    with conn.cursor() as cur:
        for rec in records:
            ok, reason = quality_gate(rec)
            if not ok:
                stats[f"skipped_{reason}"] += 1
                log.warning("质量门禁跳过 external_id=%s year=%s qno=%s reason=%s",
                            rec.get("external_id"), rec.get("year"), rec.get("question_no"), reason)
                continue
            # 内容去重
            year = rec["year"]
            norm = normalize_for_dedup(rec["content"])
            if norm and norm in existing_content.get(year, set()):
                stats["skipped_content_dup"] += 1
                stats[f"dup_year_{year}"] += 1
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
                "figure_missing": rec["figure_missing"],
                "question_no": rec["question_no"],
            }
            try:
                cur.execute(INSERT_SQL, params)
                if cur.rowcount > 0:
                    inserted += 1
                    stats["inserted"] += 1
                    stats[f"by_year_{year}"] += 1
                    existing_content.setdefault(year, set()).add(norm)
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                stats["skipped_duplicate_external"] += 1
                continue
            except Exception as e:
                conn.rollback()
                log.warning("写入失败 external_id=%s: %s", rec.get("external_id"), e)
                stats["skipped_other"] += 1
                continue
        conn.commit()
    return inserted


# =========================================================
# 主流程
# =========================================================
def build_all_records():
    all_records = []

    # A. 2025 全套
    fp25 = os.path.join(PAPER_DIR, "2025年数学一真题.md")
    if os.path.exists(fp25):
        recs = parse_2025_paper(fp25)
        log.info("2025 解析: %d 题", len(recs))
        all_records.extend(recs)

    # B. 2022/2023/2024 解析文件直接导入
    sol_files = {
        2022: os.path.join(SOL_DIR, "2022年解析", "2022年解析.md"),
        2023: os.path.join(SOL_DIR, "2023年解析", "2023年解析.md"),
        2024: os.path.join(SOL_DIR, "2024年解析", "2024.md"),
    }
    for year, fp in sol_files.items():
        if not os.path.exists(fp):
            log.warning("缺少 %d 解析文件: %s", year, fp)
            continue
        if year == 2022:
            recs = parse_2022_solution(fp, year)
        elif year == 2023:
            recs = parse_2023_solution(fp, year)
        else:
            recs = parse_2024_solution(fp, year)
        log.info("%d 解析: %d 题", year, len(recs))
        all_records.extend(recs)

    # C. 2013-2021 配对导入
    for year in range(2013, 2022):
        recs = parse_paired(year)
        if recs:
            log.info("%d 配对: %d 题", year, len(recs))
            all_records.extend(recs)

    return all_records


def print_stats():
    print("\n===== 数学一真题(TsekaLuk)导入统计 =====")
    print(f"成功插入: {stats['inserted']}")
    print("\n按年份新增:")
    for k in sorted(stats):
        if k.startswith("by_year_"):
            print(f"  {k.replace('by_year_', '')}年: {stats[k]}")
    print("\n跳过原因:")
    skip_keys = [k for k in stats if k.startswith("skipped")]
    if not skip_keys:
        print("  (无)")
    for k in sorted(skip_keys):
        print(f"  {k}: {stats[k]}")


def main():
    import sys
    dry_run = "--dry-run" in sys.argv
    all_records = build_all_records()

    # 按年份统计解析数
    by_year = Counter(r["year"] for r in all_records)
    print("\n===== 解析结果（按年份） =====")
    for y in sorted(by_year):
        print(f"  {y}年: {by_year[y]} 题")

    if dry_run:
        print("\n[dry-run] 不写入数据库。")
        return

    conn = psycopg.connect(DB_DSN)
    try:
        existing = load_existing_content(conn)
        log.info("库中已有 subject_id=8 且 year>=2013 的题目数: %d",
                 sum(len(v) for v in existing.values()))
        inserted = write_records(conn, all_records, existing)
        log.info("成功插入 %d 题", inserted)
    finally:
        conn.close()
    print_stats()


if __name__ == "__main__":
    main()