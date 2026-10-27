#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量导入考研英语一真题（2017-2023）：题干文件（english1_{year}.md）+ 答案文件 -> quiz_questions

增强点：
  - 支持表格格式（2020/2022 完形填空 <table>）
  - 支持 2019/2023 完形分离格式（A选项带题号，B/C/D 独立行）
  - 支持 "N ." 题号格式（2018）
  - 新题型 41-45：从题干提取 A-G/H 段落作为选项
  - 2020 答案特殊处理：完形答案为单词，映射为选项字母

运行: python scripts/import_english_zhenti_all.py
"""
import os
import re
import json
import logging
from collections import Counter

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
SOL_DIR = os.path.join(PROJECT_ROOT, "scripts", "data", "kaoyan_english_solutions")

DB_DSN = "host=127.0.0.1 port=5432 user=kaoyan password=kaoyan_dev_2026 dbname=kaoyan"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_english_all")

EXT_PREFIX = "eng_zhenti"
stats = Counter()

# =========================================================
# 文本清洗
# =========================================================
def clean_text(s):
    if not s:
        return ""
    s = str(s)
    s = "".join(ch for ch in s if ch >= "\u0001" or ch in ("\n", "\t", "\r"))
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    s = s.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\$+", "", s)
    s = re.sub(r"!\[.*?\]\(.*?\)", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def detect_garbled(s):
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
    if not ans:
        return ""
    ans = clean_text(ans)
    ans = re.sub(r"[\(\)（）、.\s]", "", ans)
    return ans.upper()


def make_options(opt_list):
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


def get_chapter(qno):
    if qno <= 20:
        return "完形填空", 82
    elif qno <= 40:
        return "阅读理解 Part A", 83
    elif qno <= 45:
        return "阅读理解 Part B 新题型", 84
    elif qno <= 50:
        return "翻译", 85
    else:
        return "写作", 87


# =========================================================
# 题干预处理：表格、题号格式归一化
# =========================================================
def normalize_stem_text(text):
    """将题干文本中的特殊格式转换为标准逐行格式。"""
    lines = text.splitlines()
    out = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        stripped = ln.strip()
        if "<table" in stripped:
            # 找到表格块的结束位置（从当前行开始找 </table>）
            j = i
            while j < n and "</table>" not in lines[j]:
                j += 1
            if j < n:
                end = j
            else:
                end = n - 1
            buf = lines[i:end + 1]
            table_text = "\n".join(buf)
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_text, re.S)
            for row in rows:
                if "答案" in row:
                    continue
                tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                opt_parts = []
                qno = None
                for td in tds:
                    td = re.sub(r"<[^>]+>", "", td).strip()
                    m = re.match(r"^\s*(\d{1,2})\s*[\.、．]?\s*\[([A-Z])\]\s*(.*)$", td)
                    if m:
                        if qno is None:
                            qno = int(m.group(1))
                        opt_parts.append((m.group(2), m.group(3)))
                    else:
                        m2 = re.match(r"^\s*\[([A-Z])\]\s*(.*)$", td)
                        if m2:
                            opt_parts.append((m2.group(1), m2.group(2)))
                if qno and len(opt_parts) >= 2:
                    parts = [f"{qno}."]
                    for k, v in opt_parts:
                        parts.append(f"[{k}] {v}".rstrip())
                    out.append(" ".join(parts))
            i = end + 1
            continue
        # "N ." -> "N."
        stripped = re.sub(r"^(\d{1,2})\s+\.", r"\1.", stripped)
        out.append(stripped)
        i += 1
    return "\n".join(out)


# =========================================================
# 从一行文本中提取选项（[X] 标记格式）
# =========================================================
def extract_options_from_text(rest):
    """从 " [A] xxx [B] xxx ..." 中提取选项列表 [(key, text)]"""
    opts = []
    for m in re.finditer(r"\[([A-H])\]\s*([^\[]+)", rest):
        key = m.group(1).strip().upper()
        val = m.group(2).strip()
        if key and val:
            opts.append((key, val))
    return opts


def parse_option_line(line, allow_nosep=False):
    """
    判断一行是否为选项行，若是返回 (key, text)，否则返回 None。
    支持: [A] xxx / A. xxx / A.xxx / A-xxx / A_xxx / A xxx / Axxx(分隔符变体)
    allow_nosep=True 时还支持 "Cbreaking"（字母后无分隔符直接跟小写文本）。
    """
    line = line.strip()
    m = re.match(r"^\[([A-H])\]\s*(.*)$", line)
    if m:
        key = m.group(1).upper()
        val = m.group(2).strip()
        if val:
            return (key, val)
        return None
    # 无方括号格式：A. xxx / A-xxx / A_xxx / A(series
    m = re.match(r"^([A-H])\s*[\.、．/_\-(（]\s*([a-zA-Z].*)$", line)
    if m and m.group(1) in "ABCDEFGH":
        key = m.group(1).upper()
        val = m.group(2).strip()
        if val and len(val) >= 1:
            return (key, val)
    # 无分隔符格式：Cbreaking（仅在完形区启用，避免误判阅读段落）
    if allow_nosep:
        m = re.match(r"^([A-H])([a-z][a-zA-Z].*)$", line)
        if m and m.group(1) in "ABCDEFGH":
            key = m.group(1).upper()
            val = m.group(2)
            if val:
                return (key, val)
    return None


# =========================================================
# 题干解析（多格式）
# =========================================================
def parse_stem_text(text):
    """
    解析选择题 1-45 题（含完形、阅读、新题型）。
    返回 {qno: {content, options, stem, section}}
    """
    text = normalize_stem_text(text)
    lines = text.splitlines()

    questions = {}      # qno -> dict
    region = None       # 'cloze' | 'reading' | 'xtx' | 'writing' | None
    current_q = None
    ctx_buffer = []     # 文章段落缓存

    # 完形分离格式收集
    cloze_a = {}        # qno -> A选项文本
    cloze_b = []        # B选项文本（按出现顺序）
    cloze_c = []
    cloze_d = []
    cloze_ctx = {}      # qno -> 文章上下文

    # 新题型收集
    xtx_opts = []       # 选项段落 A-H

    def reset_cloze():
        return {}, [], [], [], {}

    def make_question(qno, stem, ctx, section):
        return {"stem": stem, "lines": [], "passage_ctx": ctx, "section": section, "direct_options": None}

    for raw_ln in lines:
        ln = raw_ln.strip()
        if not ln:
            continue

        # ---- 区域边界检测 ----
        is_part_a = bool(re.match(r"^#*\s*Part\s*A\b", ln)) or bool(re.match(r"^#*\s*PartA\b", ln))
        is_part_b = bool(re.match(r"^#*\s*Part\s*B\b", ln)) or bool(re.match(r"^#*\s*PartB\b", ln))

        if re.match(r"^#*\s*Section\s*I\b", ln):
            region = "cloze"
            current_q = None
            ctx_buffer = []
            cloze_a, cloze_b, cloze_c, cloze_d, cloze_ctx = reset_cloze()
            continue
        if re.match(r"^#*\s*Part\s*C\b", ln) or re.match(r"^#*\s*Section\s*III\b", ln) or re.match(r"^#*\s*Section\s*IV\b", ln):
            region = "writing"
            current_q = None
            continue
        if region == "writing":
            # 写作区内的 Part A/B 不切换区域
            is_part_a = False
            is_part_b = False
        if is_part_a or re.match(r"^#*\s*Text\s*\d", ln):
            region = "reading"
            current_q = None
            ctx_buffer = []
            continue
        if is_part_b:
            region = "xtx"
            current_q = None
            xtx_opts = []
            ctx_buffer = []
            continue

        # ---- 完形区 ----
        if region == "cloze":
            ln_clean = re.sub(r"^#+\s*", "", ln)
            # 题号行（可能带首选项）
            m = re.match(r"^(\d{1,2})\s*[\.、．]?\s*(.*)$", ln_clean)
            if m:
                qno = int(m.group(1))
                rest = m.group(2).strip()
                if 1 <= qno <= 20:
                    current_q = qno
                    ctx = "\n".join(ctx_buffer[-10:]) if ctx_buffer else ""
                    cloze_ctx[qno] = ctx
                    if qno not in questions:
                        questions[qno] = make_question(qno, "", ctx, "完形填空")
                    # 判断 rest 是否含多个 [X] 标记
                    if re.search(r"\[[A-H]\]", rest):
                        opts = extract_options_from_text(rest)
                        if len(opts) >= 2:
                            # 标准格式，直接设置该题选项
                            questions[qno]["direct_options"] = opts
                            continue
                        elif len(opts) == 1:
                            # 单个 [A] xxx，属于分离格式的A选项
                            cloze_a[qno] = opts[0][1]
                            continue
                    # 无 [X] 标记，可能是 "A displayed" 或 "A. By the way"
                    m_single = re.match(r"^([A-H])\s*[\.、．/-_]?\s*([a-zA-Z].*)$", rest)
                    if m_single:
                        cloze_a[qno] = m_single.group(2).strip()
                        continue
                    # 否则可能是题干（罕见），忽略
                    continue
                else:
                    current_q = None
                    continue
            # 无题号选项行（完形区允许无分隔符格式如 Cbreaking）
            opt = parse_option_line(ln, allow_nosep=True)
            if opt:
                key, val = opt
                if key == "B":
                    cloze_b.append(val)
                elif key == "C":
                    cloze_c.append(val)
                elif key == "D":
                    cloze_d.append(val)
                elif key == "A":
                    # 无题号的 A 选项，归属到当前题
                    if current_q and current_q in questions:
                        questions[current_q]["lines"].append(f"[A] {val}")
                continue
            # 文章段落
            ctx_buffer.append(ln)
            continue

        # ---- 阅读区 ----
        if region == "reading":
            ln_clean = re.sub(r"^#+\s*", "", ln)
            # 题号行（题干）
            m = re.match(r"^(\d{1,2})\s*[\.、．]\s*(.*)$", ln_clean)
            if m:
                qno = int(m.group(1))
                rest = m.group(2).strip()
                if 21 <= qno <= 40:
                    current_q = qno
                    ctx = "\n".join(ctx_buffer[-12:]) if ctx_buffer else ""
                    if qno not in questions:
                        questions[qno] = make_question(qno, rest, ctx, "阅读理解 Part A")
                    else:
                        questions[qno]["stem"] = rest
                    ctx_buffer = []
                    continue
                else:
                    current_q = None
                    continue
            # 选项行
            opt = parse_option_line(ln)
            if opt:
                if current_q and current_q in questions:
                    # 一行含多个 [X] 标记时全部提取
                    multi = extract_options_from_text(ln)
                    if len(multi) >= 2:
                        for k, v in multi:
                            questions[current_q]["lines"].append(f"[{k}] {v}")
                    else:
                        questions[current_q]["lines"].append(f"[{opt[0]}] {opt[1]}")
                continue
            # 文章段落
            ctx_buffer.append(ln)
            continue

        # ---- 新题型区 ----
        if region == "xtx":
            # 提取选项段落 A-H（支持 [A]xxx / A. xxx / A xxx 格式）
            m_opt = re.match(r"^\[([A-H])\]\s*(.{10,})$", ln)
            if not m_opt:
                m_opt = re.match(r"^([A-H])[\.、．]\s*(.{10,})$", ln)
            if not m_opt:
                m_opt = re.match(r"^([A-H])\s+(.{15,})$", ln)
            if m_opt and m_opt.group(1) in "ABCDEFGH":
                key = m_opt.group(1).upper()
                val = m_opt.group(2).strip()
                found = False
                for o in xtx_opts:
                    if o["key"] == key:
                        o["text"] += " " + val
                        found = True
                        break
                if not found:
                    xtx_opts.append({"key": key, "text": val})
                continue
            continue

        # ---- 写作区 ----
        if region == "writing":
            continue

    # ---- 组装完形填空 ----
    # 分离格式对齐：cloze_a 中的题号排序，cloze_b/c/d 按顺序对应
    sep_qnos = sorted(cloze_a.keys())
    for idx, qno in enumerate(sep_qnos):
        if qno not in questions:
            continue
        q = questions[qno]
        a_text = cloze_a.get(qno)
        b_text = cloze_b[idx] if idx < len(cloze_b) else None
        c_text = cloze_c[idx] if idx < len(cloze_c) else None
        d_text = cloze_d[idx] if idx < len(cloze_d) else None
        if a_text and b_text and c_text and d_text:
            opts = make_options([("A", a_text), ("B", b_text), ("C", c_text), ("D", d_text)])
            if opts:
                q["direct_options"] = opts

    # ---- 组装普通题目 ----
    result = {}
    for qno, q in questions.items():
        # 确定选项
        options = None
        if q.get("direct_options"):
            options = make_options(q["direct_options"]) if q["direct_options"] else None
        if not options:
            opt_parts = []
            for lnx in q.get("lines", []):
                m = re.match(r"^\[([A-H])\]\s*(.*)$", lnx)
                if m:
                    opt_parts.append((m.group(1), m.group(2).strip()))
            if len(opt_parts) >= 2:
                options = make_options(opt_parts)
        if not options:
            continue

        # 题干内容
        stem_text = q.get("stem", "")
        ctx = q.get("passage_ctx", "")
        if len(clean_text(stem_text)) < 5:
            if ctx:
                stem_text = f"完形填空（第{qno}题）\n{ctx}"
            else:
                stem_text = f"第{qno}题"
        elif ctx and qno > 20:
            stem_text = f"{ctx}\n{stem_text}"
        content = clean_text(stem_text)
        if len(content) < 5:
            content = f"第{qno}题"
        result[qno] = {
            "content": content,
            "options": options,
            "stem": q.get("stem", ""),
            "section": q.get("section", ""),
        }

    # ---- 组装新题型 41-45 ----
    if xtx_opts:
        # 排序 A-H
        xtx_opts_sorted = sorted(xtx_opts, key=lambda o: o["key"])
        for qno in range(41, 46):
            content = f"新题型（Part B）第{qno}题：请从下列选项中选择正确的一项填入文中第{qno}题。"
            opts = make_options([(o["key"], o["text"][:200]) for o in xtx_opts_sorted if o["text"]])
            if opts:
                result[qno] = {
                    "content": content,
                    "options": opts,
                    "stem": content,
                    "section": "Part B 新题型",
                }

    return result


# =========================================================
# 答案解析（支持 "N. X"、"N.X"、"N. [X]"）
# =========================================================
def parse_answer_file(text):
    answers = {}
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # "N. X" / "N. X xxx"
        m = re.match(r"^(\d{1,2})\s*[\.、．]\s*([A-Z])", ln)
        if m:
            qno = int(m.group(1))
            if 1 <= qno <= 45:
                answers[qno] = {"answer": m.group(2), "analysis": ""}
            continue
        # "N. [X] xxx"
        m = re.match(r"^(\d{1,2})\s*[\.、．]\s*\[([A-Z])\]\s*(.*)$", ln)
        if m:
            qno = int(m.group(1))
            if 1 <= qno <= 45:
                answers[qno] = {"answer": m.group(2), "analysis": m.group(3).strip()}
            continue
        # "N.【答案】[X]"
        m = re.search(r"^(\d{1,2})\s*[\.、．]?\s*【答案】\s*[\[（(]\s*([A-Z])\s*[\]）)]", ln)
        if m:
            qno = int(m.group(1))
            if 1 <= qno <= 45:
                answers[qno] = {"answer": m.group(2), "analysis": ""}
    return answers


# =========================================================
# 2020 答案特殊处理：完形单词 -> 字母
# =========================================================
def parse_answer_2020(raw_text, stem_text):
    answers = {}

    # 1) 提取阅读 21-40 和新题型 41-45 的字母答案（"21.D focus ..."）
    for m in re.finditer(r"(\d{1,2})\.\s*([A-D])\s", raw_text):
        qno = int(m.group(1))
        if 21 <= qno <= 45:
            answers[qno] = m.group(2)

    # 2) 提取完形 1-20 的单词答案
    cloze_part = raw_text
    idx_read = raw_text.find("阅读")
    if idx_read > 0:
        cloze_part = raw_text[:idx_read]
    words = {}
    for m in re.finditer(r"(\d{1,2})\.\s*([a-zA-Z][a-zA-Z\s]*)", cloze_part):
        qno = int(m.group(1))
        word = m.group(2).strip()
        if 1 <= qno <= 20 and word:
            words[qno] = word

    # 3) 用题干选项将完形单词映射为字母
    questions = parse_stem_text(stem_text)
    for qno, word in words.items():
        target = word.lower().strip()
        opts = questions.get(qno, {}).get("options", [])
        letter = None
        for o in opts:
            otext = clean_text(o["text"]).lower().strip()
            if otext == target:
                letter = o["key"]
                break
        if not letter:
            for o in opts:
                otext = clean_text(o["text"]).lower().strip()
                if target in otext or otext in target:
                    letter = o["key"]
                    break
        if letter:
            answers[qno] = letter

    return answers


# =========================================================
# 配对导入
# =========================================================
def import_paired(year, stem_text, ans_dict):
    questions = parse_stem_text(stem_text)
    log.info("年份 %d: 题干解析 %d 题", year, len(questions))

    records = []
    for qno in sorted(questions.keys()):
        q = questions[qno]
        ans_info = ans_dict.get(qno)
        if not ans_info:
            stats[f"no_answer_{year}"] += 1
            continue
        answer = ans_info if isinstance(ans_info, str) else ans_info.get("answer")
        if not answer:
            stats[f"no_answer_{year}"] += 1
            continue
        analysis = ""
        if isinstance(ans_info, dict):
            analysis = ans_info.get("analysis", "")
        chapter, ch_id = get_chapter(qno)
        rec = {
            "source": "kaoyan-english1-zhenti",
            "subject": "英语",
            "subject_id": 9,
            "content": q["content"],
            "options": q["options"],
            "answer": answer,
            "analysis": analysis,
            "question_type": "single",
            "chapter": chapter,
            "chapter_id": ch_id,
            "knowledge_point": None,
            "source_label": f"考研英语一真题({year}年)",
            "difficulty": 3,
            "year": year,
            "paper": f"{year}年考研英语一真题",
            "external_id": f"{EXT_PREFIX}_{year}_{qno}",
        }
        records.append(rec)
        stats[f"parsed_{year}"] += 1

    return records


def build_answer_dict_from_file(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    ans = parse_answer_file(text)
    return {qno: info["answer"] for qno, info in ans.items()}


def main():
    sol_dir = SOL_DIR
    target_years = [2017, 2018, 2019, 2020, 2022, 2023]
    all_records = []

    for year in target_years:
        stem_path = os.path.join(sol_dir, f"english1_{year}.md")
        if not os.path.exists(stem_path):
            log.warning("缺少题干文件: %s", stem_path)
            continue
        with open(stem_path, encoding="utf-8") as f:
            stem_text = f.read()

        if year == 2022:
            ans_path = os.path.join(sol_dir, "english1_2024.md")
            if not os.path.exists(ans_path):
                log.warning("缺少2022答案文件: %s", ans_path)
                continue
            with open(ans_path, encoding="utf-8") as f:
                ans_text = f.read()
            ans_dict = {qno: info["answer"] for qno, info in parse_answer_file(ans_text).items()}
        elif year == 2020:
            raw_path = os.path.join(sol_dir, "answers_2020_raw.txt")
            if not os.path.exists(raw_path):
                log.warning("缺少2020答案原文: %s", raw_path)
                continue
            with open(raw_path, encoding="utf-8") as f:
                raw_text = f.read()
            ans_dict = parse_answer_2020(raw_text, stem_text)
        else:
            ans_path = os.path.join(sol_dir, f"answers_{year}_raw.txt")
            if not os.path.exists(ans_path):
                log.warning("缺少答案文件: %s", ans_path)
                continue
            ans_dict = build_answer_dict_from_file(ans_path)

        records = import_paired(year, stem_text, ans_dict)
        log.info("%d 年: 配对生成 %d 条记录 (答案 %d 条)", year, len(records), len(ans_dict))
        all_records.extend(records)

    if not all_records:
        log.error("没有可导入的记录")
        return

    conn = psycopg.connect(DB_DSN)
    try:
        inserted = write_records(conn, all_records)
        log.info("成功插入 %d 题", inserted)
    finally:
        conn.close()

    log.info("统计: %s", dict(stats))


if __name__ == "__main__":
    main()