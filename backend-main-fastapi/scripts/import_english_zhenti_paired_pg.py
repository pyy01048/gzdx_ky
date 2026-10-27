#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入考研英语一真题（配对模式）：题干文件 + 答案文件 -> quiz_questions

适用场景:
  - 题干文件（含文章+选项，无答案）: english1_2022.md
  - 答案文件（含答案+解析）: english1_2024.md（实为 2022 年答案）

运行: python scripts/import_english_zhenti_paired_pg.py
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
SOL_DIR = os.path.join(PROJECT_ROOT, "scripts", "data", "kaoyan_english_solutions")

DB_DSN = "host=127.0.0.1 port=5432 user=kaoyan password=kaoyan_dev_2026 dbname=kaoyan"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_english_paired")

EXT_PREFIX = "eng_zhenti"

stats = Counter()

# =========================================================
# 文本清洗（复用）
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


# =========================================================
# 章节映射
# =========================================================
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
# 从题干文件抽取题干+选项
# =========================================================
def parse_stem_file(text):
    """
    从题干 md 抽取选择题（1-45）。
    题干文件格式（如 english1_2022.md）:
      - 文章段落
      - "N. 题干" 或 "N.题干"
      - 选项行 "[A] ... [B] ..." 或 "A. ... B. ..."
    返回 {qno: {stem, options, passage_ctx}}
    """
    lines = text.splitlines()
    questions = {}
    q_re = re.compile(r"^(\d{1,2})[\.、．]\s*(.+)$")
    current_q = None
    current_section = None
    passage_buffer = []

    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            continue
        sec_m = re.match(r"^#\s*(Section\s+\w+|Part\s+\w+|一、|二、|三、|四、)", ln)
        if sec_m:
            current_section = ln
            passage_buffer = []
            continue
        text_m = re.match(r"^#\s*Text\s+\d+", ln)
        if text_m:
            passage_buffer = []
            continue
        # 跳过翻译/写作区
        if re.match(r"^#\s*(Section III|Section IV|Part C)", ln):
            continue

        m = q_re.match(stripped)
        if m:
            qno = int(m.group(1))
            stem = m.group(2).strip()
            if 1 <= qno <= 45:
                current_q = qno
                ctx = "\n".join(passage_buffer[-12:]) if passage_buffer else ""
                questions[qno] = {
                    "stem": stem,
                    "lines": [stem],
                    "passage_ctx": ctx,
                    "section": current_section or "",
                }
                if qno > 20:
                    passage_buffer = []
            else:
                current_q = None
            continue

        is_option_line = bool(re.match(r"^\s*\[[A-D]\]\s*\S", stripped)) or \
                          bool(re.match(r"^\s*[A-D][\.、]\s*\S", stripped)) or \
                          (stripped.count("[A]") >= 1 and stripped.count("[B]") >= 1)
        if current_q is not None and current_q in questions and is_option_line:
            questions[current_q]["lines"].append(stripped)
        else:
            passage_buffer.append(stripped)

    # 组装选项
    result = {}
    for qno, q in questions.items():
        joined_opts = "\n".join(q["lines"])
        opt_matches = re.findall(r"\[([A-D])\]\s*([^\[]+)", joined_opts)
        opt_parts = []
        if len(opt_matches) >= 2:
            seen = set()
            for k, v in opt_matches:
                key = k.strip().upper()
                val = v.strip()
                val = re.sub(r"\s*\d{1,2}[\.、．].*$", "", val)
                if key not in seen and val:
                    opt_parts.append((key, val))
                    seen.add(key)
        if len(opt_parts) < 2:
            # 尝试 A. xxx B. xxx 格式
            opt_matches2 = re.findall(r"(?:^|\s)([A-D])[\.、]\s*([^A-D\[]+)", joined_opts)
            seen = set()
            opt_parts = []
            for k, v in opt_matches2:
                key = k.strip().upper()
                val = v.strip()
                if key not in seen and val:
                    opt_parts.append((key, val))
                    seen.add(key)
        options = make_options(opt_parts) if len(opt_parts) >= 2 else None
        if not options:
            continue
        # 题干文本
        non_opt_lines = []
        for ln in q["lines"]:
            ln_clean = re.sub(r"\[[A-D]\]\s*[^\[]*", "", ln)
            ln_clean = re.sub(r"(?:^|\s)[A-D][\.、]\s*[^A-D\[]*", "", ln_clean)
            ln_clean = ln_clean.strip()
            if ln_clean:
                non_opt_lines.append(ln_clean)
        stem_text = "\n".join(non_opt_lines)
        ctx = q.get("passage_ctx", "")
        if len(clean_text(stem_text)) < 5 and ctx:
            stem_text = f"完形填空（第{qno}题）\n{ctx}"
        elif ctx and qno > 20:
            stem_text = f"{ctx}\n{stem_text}"
        content = clean_text(stem_text)
        if len(content) < 5:
            continue
        result[qno] = {
            "content": content,
            "options": options,
            "stem": q["stem"],
            "section": q.get("section", ""),
        }
    return result


# =========================================================
# 从答案文件抽取答案+解析
# =========================================================
def parse_answer_file(text):
    """
    从答案文件抽取 {qno: {answer, analysis}}
    支持格式:
      - "# 【答案】" 简表: "1. [A] coined"
      - "N. 【答案】[X]" + "【解析】..."
      - "N. 题干" + "【答案】[X]"（2021 格式）
    """
    lines = text.splitlines()
    answers = {}

    # 方法A: 简表 "N. [A] xxx"
    for ln in lines:
        m = re.match(r"^\s*(\d{1,2})[\.、．]\s*\[([A-D])\]\s*(.*)$", ln)
        if m and "解析" not in ln[:10]:
            qno = int(m.group(1))
            if qno not in answers or not answers[qno].get("answer"):
                answers[qno] = {"answer": m.group(2), "analysis": ""}

    # 方法B: "N. 【答案】[X]"
    for ln in lines:
        m = re.search(r"^\s*(\d{1,2})[\.、．]?\s*【答案】\s*[\[（(]\s*([A-D])\s*[\]）)]", ln)
        if m:
            qno = int(m.group(1))
            answers[qno] = {"answer": m.group(2), "analysis": ""}

    # 方法C: 2021 格式 "N. 题干" + "【答案】[X]"
    numbered_rows = []
    ans_mark_rows = []
    for idx, ln in enumerate(lines):
        m_num = re.match(r"^\s*(\d{1,2})[\.、．]\s*(\[[A-D]\]|[A-D])?", ln)
        if m_num and "【答案】" not in ln and not re.match(r"^\s*\d{1,2}[\.、．]?\s*【答案】", ln):
            numbered_rows.append((idx, int(m_num.group(1))))
        m_ans = re.search(r"【答案】\s*[\[（(]\s*([A-D])\s*[\]）)]", ln)
        if m_ans:
            ans_mark_rows.append((idx, m_ans.group(1), ln.strip()))
    for aidx, letter, full in ans_mark_rows:
        best_qno = None
        for nidx, qno in numbered_rows:
            if nidx < aidx:
                best_qno = qno
            else:
                break
        if best_qno is not None:
            if best_qno not in answers or not answers[best_qno].get("answer"):
                answers[best_qno] = {"answer": letter, "analysis": full}

    # 解析补充：按题号切块，取【解析】后内容
    block_starts = []
    for idx, ln in enumerate(lines):
        m = re.search(r"^\s*(\d{1,2})[\.、．]?\s*【答案】\s*[\[（(]\s*([A-D])\s*[\]）)]", ln)
        if m:
            block_starts.append((idx, int(m.group(1))))
            continue
        m_num = re.match(r"^\s*(\d{1,2})[\.、．]\s*(\[[A-D]\]|[A-D])?", ln)
        if m_num and "【答案】" not in ln:
            block_starts.append((idx, int(m_num.group(1))))

    for bi, (idx, qno) in enumerate(block_starts):
        end_idx = block_starts[bi + 1][0] if bi + 1 < len(block_starts) else len(lines)
        block = "\n".join(lines[idx:end_idx])
        jx_pos = block.find("【解析】")
        if jx_pos >= 0:
            analysis_text = block[jx_pos + len("【解析】"):]
        else:
            analysis_text = ""
        analysis_text = re.sub(r"#+\s*", "", analysis_text)
        analysis_text = clean_text(analysis_text)
        if qno in answers and analysis_text:
            if len(analysis_text) > len(answers[qno].get("analysis", "")):
                answers[qno]["analysis"] = analysis_text

    return answers


# =========================================================
# 配对导入
# =========================================================
def import_paired(year, stem_text, ans_text):
    """配对导入某一年真题"""
    questions = parse_stem_file(stem_text)
    answers = parse_answer_file(ans_text)
    log.info("年份 %d: 题干 %d 题, 答案 %d 题", year, len(questions), len(answers))

    records = []
    for qno in sorted(questions.keys()):
        q = questions[qno]
        ans_info = answers.get(qno)
        if not ans_info or not ans_info.get("answer"):
            stats[f"no_answer_{year}"] += 1
            continue
        answer = ans_info["answer"]
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
            "source_label": f"TsekaLuk/Kaoyan-English1-Papers({year}年考研英语一真题)",
            "difficulty": 3,
            "year": year,
            "paper": f"{year}年考研英语一真题",
            "external_id": f"{EXT_PREFIX}_{year}_{qno}",
        }
        records.append(rec)
        stats[f"parsed_{year}"] += 1

    return records


def main():
    # 2022: 题干在 english1_2022.md, 答案在 english1_2024.md（实为2022）
    sol_dir = SOL_DIR
    stem_path = os.path.join(sol_dir, "english1_2022.md")
    ans_path = os.path.join(sol_dir, "english1_2024.md")
    if not os.path.exists(stem_path) or not os.path.exists(ans_path):
        log.error("缺少文件: %s 或 %s", stem_path, ans_path)
        return
    with open(stem_path, encoding="utf-8") as f:
        stem_text = f.read()
    with open(ans_path, encoding="utf-8") as f:
        ans_text = f.read()

    records = import_paired(2022, stem_text, ans_text)
    log.info("2022 共解析 %d 条记录", len(records))
    if not records:
        log.warning("没有可导入的 2022 记录")
        return

    conn = psycopg.connect(DB_DSN)
    try:
        inserted = write_records(conn, records)
        log.info("成功插入 %d 题", inserted)
    finally:
        conn.close()
    log.info("统计: %s", dict(stats))


if __name__ == "__main__":
    main()