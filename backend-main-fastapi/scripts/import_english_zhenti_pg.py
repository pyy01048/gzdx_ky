#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入考研英语一真题（2017-2024）到 quiz_questions 表 (PostgreSQL)

数据源:
  scripts/data/kaoyan_english_solutions/english1_*.md
  （TsekaLuk/Kaoyan-English1-Papers 仓库 solutions 目录）

导入策略:
  A. 2021/2024 解析文件自带题干+选项+【答案】+【解析】 -> 完整导入(single)
  B. 2017-2020/2022/2023 仅题目+选项，无答案 -> 只导入题干+选项
     （答案待后续从答案册补全）

题型: 完形填空 / 阅读理解 / 新题型 均为单选题
运行: python scripts/import_english_zhenti_pg.py
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
log = logging.getLogger("import_english_zhenti")

EXT_PREFIX = "eng_zhenti"

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
    """
    基础质量过滤。record 为 dict:
      content, options(list[dict]|None), answer, analysis, question_type
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
# 章节映射
# =========================================================
def get_chapter(qno):
    """根据题号映射章节"""
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
# 解析 2021/2024 格式（题干+选项在前，答案+解析在后）
# =========================================================
def parse_full_year(text, year):
    """
    从完整解析文件抽取题目。
    2021 格式:
      前部: 文章 + "N. 题干" + 选项行（选项可能在题干行内或下一行）
      后部: "# 参考答案及详细解析" 之后，每题为:
            "N. [A] ... [B] ..." 题干选项
            "【答案】[X] ..."
            "【解析】..."
    2024 格式:
      "# 【答案】" 区列出 1-20 答案（简表）
      "# 【解析】" 区每题为 "N. 【答案】[X]" + "【解析】..."
    """
    records = []

    # ---- 1. 从文章区抽取题目题干与选项 ----
    lines = text.splitlines()

    # 定位答案区起点
    ans_start = None
    for i, ln in enumerate(lines):
        if re.search(r"#\s*(参考答案及详细解析|答案与解析|答案：|答案:|试题解析)", ln):
            ans_start = i
            break

    # ---- 抽取题干区 ----
    # 题号 -> {stem_lines, opt_raw}
    questions = {}

    # 正则匹配题号行: "21. xxx" / "21、xxx" / "21 xxx"
    q_re = re.compile(r"^(\d{1,2})[\.、．]\s*(.+)$")

    # 存储当前题目上下文
    current_q = None
    current_section = None
    in_answer_zone = False
    # 收集当前 Section 的文章段落（非题号、非选项行）
    passage_buffer = []

    for i, ln in enumerate(lines):
        if ans_start is not None and i >= ans_start:
            in_answer_zone = True

        # 识别 Section 标题（用于排除翻译/写作）
        sec_m = re.match(r"^#\s*(Section\s+\w+|Part\s+\w+|一、|二、|三、|四、)", ln)
        if sec_m:
            current_section = ln
            passage_buffer = []
            continue

        # 识别 Text 标题（阅读每篇独立文章）
        text_m = re.match(r"^#\s*Text\s+\d+", ln)
        if text_m:
            passage_buffer = []
            continue

        # 跳过答案区
        if in_answer_zone:
            continue

        stripped = ln.strip()
        if not stripped:
            continue

        # 匹配题号
        m = q_re.match(stripped)
        if m:
            qno = int(m.group(1))
            stem = m.group(2).strip()
            # 仅处理 1-50 题（完形/阅读/新题型/翻译）
            if 1 <= qno <= 50:
                current_q = qno
                # 题干上下文：文章段落（限制长度）
                ctx = "\n".join(passage_buffer[-12:]) if passage_buffer else ""
                questions[qno] = {
                    "stem": stem,
                    "lines": [stem],
                    "section": current_section or "",
                    "passage_ctx": ctx,
                }
                # 完形题共享同一篇文章，不清空缓冲区
                # 阅读/新题型每题独立，清空缓冲区
                if qno > 20:
                    passage_buffer = []
            else:
                current_q = None
            continue

        # 非题号行
        # 判断是否为纯选项行（整行由 [A]/[B]/[C]/[D] 选项组成）
        is_option_line = bool(re.match(r"^\s*\[[A-D]\]\s*\S", stripped)) or \
                          bool(re.match(r"^\s*[A-D][\.、]\s*\S", stripped)) or \
                          (stripped.count("[A]") >= 1 and stripped.count("[B]") >= 1)
        if current_q is not None and current_q in questions and is_option_line:
            questions[current_q]["lines"].append(stripped)
        else:
            # 文章段落：收集到缓冲区
            passage_buffer.append(stripped)

    # ---- 2. 从答案区抽取答案与解析 ----
    answers = {}
    if ans_start is not None:
        ans_lines = lines[ans_start:]

        # 方法A: 2024 格式 "N. 【答案】[X]" / "N、【答案】（X）"
        for ln in ans_lines:
            m = re.search(r"^\s*(\d{1,2})[\.、．]?\s*【答案】\s*[\[（(]\s*([A-D])\s*[\]）)]", ln)
            if m:
                qno = int(m.group(1))
                if qno not in answers or not answers[qno].get("answer"):
                    answers[qno] = {"answer": m.group(2), "analysis": ""}

        # 方法B: 2021 格式 —— 题号行 "N. 题干" + "[A]...[B]..."
        #        后跟 "【答案】[X] ..."，按出现顺序配对
        # 先收集答案区中的题号行顺序和 【答案】 顺序
        numbered_rows = []  # (line_idx, qno)
        ans_mark_rows = []  # (line_idx, answer_letter, full_line)
        for idx, ln in enumerate(ans_lines):
            m_num = re.match(r"^\s*(\d{1,2})[\.、．]\s*(\[[A-D]\]|[A-D])?", ln)
            # 题号行: 行首是 "N." 且不是 "【答案】" 行
            if m_num and "【答案】" not in ln and not re.match(r"^\s*\d{1,2}[\.、．]?\s*【答案】", ln):
                numbered_rows.append((idx, int(m_num.group(1))))
            m_ans = re.search(r"【答案】\s*[\[（(]\s*([A-D])\s*[\]）)]", ln)
            if m_ans:
                ans_mark_rows.append((idx, m_ans.group(1), ln.strip()))

        # 按顺序配对: 每个题号行之后最近的 【答案】 属于该题
        if numbered_rows and ans_mark_rows:
            # 双指针
            ni = 0
            for ai, (aidx, letter, full) in enumerate(ans_mark_rows):
                # 找到最后一个 <= aidx 的题号行
                best_qno = None
                for (nidx, qno) in numbered_rows:
                    if nidx < aidx:
                        best_qno = qno
                    else:
                        break
                if best_qno is not None:
                    if best_qno not in answers or not answers[best_qno].get("answer"):
                        answers[best_qno] = {"answer": letter, "analysis": full}

        # ---- 解析补充: 按题号切块收集解析文本 ----
        # 对每个题号块，从 【解析】 标记处截取作为 analysis
        block_starts = []  # (line_idx, qno)
        for idx, ln in enumerate(ans_lines):
            m = re.search(r"^\s*(\d{1,2})[\.、．]?\s*【答案】\s*[\[（(]\s*([A-D])\s*[\]）)]", ln)
            if m:
                block_starts.append((idx, int(m.group(1))))
                continue
            # 题号行（2021 答案区）
            m_num = re.match(r"^\s*(\d{1,2})[\.、．]\s*(\[[A-D]\]|[A-D])?", ln)
            if m_num and "【答案】" not in ln:
                block_starts.append((idx, int(m_num.group(1))))

        for bi, (idx, qno) in enumerate(block_starts):
            end_idx = block_starts[bi + 1][0] if bi + 1 < len(block_starts) else len(ans_lines)
            block = "\n".join(ans_lines[idx:end_idx])
            # 只保留 【解析】 之后的内容
            jx_pos = block.find("【解析】")
            if jx_pos >= 0:
                analysis_text = block[jx_pos + len("【解析】"):]
            else:
                # 没有【解析】标记：可能是 2024 简表答案区，跳过
                analysis_text = ""
            analysis_text = re.sub(r"#+\s*", "", analysis_text)
            analysis_text = clean_text(analysis_text)
            if qno in answers:
                # 仅当解析文本非空且比现有 analysis 更长时替换
                if analysis_text and len(analysis_text) > len(answers[qno].get("analysis", "")):
                    answers[qno]["analysis"] = analysis_text

    # ---- 3. 组装记录 ----
    for qno in sorted(questions.keys()):
        q = questions[qno]
        if qno > 50:
            continue
        # 排除翻译题(46-50 实际是翻译句子，没有选项) 和写作
        stem_lines = q["lines"]
        passage_ctx = q.get("passage_ctx", "")
        options = None
        stem_text = ""
        opt_parts = []

        # 选项行提取: 从 lines 中收集 [A]...[B]...[C]...[D] 选项
        joined_opts = "\n".join(stem_lines)
        # 提取 [A]...[B]...[C]...[D] 选项
        opt_matches = re.findall(r"\[([A-D])\]\s*([^\[]+)", joined_opts)
        if len(opt_matches) >= 2:
            seen_keys = set()
            for k, v in opt_matches:
                key = k.strip().upper()
                val = v.strip()
                # 去除尾部的下一个题号干扰
                val = re.sub(r"\s*\d{1,2}[\.、．].*$", "", val)
                if key not in seen_keys and val:
                    opt_parts.append((key, val))
                    seen_keys.add(key)
            if len(opt_parts) >= 2:
                options = make_options(opt_parts)

        if not options:
            # 尝试匹配 "A. xxx  B. xxx  C. xxx  D. xxx" 行内选项
            opt_matches2 = re.findall(r"(?:^|\s)([A-D])[\.、]\s*([^A-D\[]+)", joined_opts)
            if len(opt_matches2) >= 2:
                seen_keys = set()
                for k, v in opt_matches2:
                    key = k.strip().upper()
                    val = v.strip()
                    if key not in seen_keys and val:
                        opt_parts.append((key, val))
                        seen_keys.add(key)
                if len(opt_parts) >= 2:
                    options = make_options(opt_parts)

        # 若没有选项，说明是翻译/写作题，跳过
        if not options:
            continue

        # 题干文本 = 文章上下文 + 问题
        # 完形题：题干 = 文章段落 + 题号行文本（去掉选项）
        # 阅读题：题干 = 文章段落 + 问题文本
        # 从 stem_lines 中移除选项行，保留题干文字
        non_opt_lines = []
        for ln in stem_lines:
            # 去掉行内的 [A]... 选项部分
            ln_clean = re.sub(r"\[[A-D]\]\s*[^\[]*", "", ln)
            ln_clean = re.sub(r"(?:^|\s)[A-D][\.、]\s*[^A-D\[]*", "", ln_clean)
            ln_clean = ln_clean.strip()
            if ln_clean:
                non_opt_lines.append(ln_clean)
        stem_text = "\n".join(non_opt_lines)
        # 若是完形（题干只有选项行），用文章上下文作为题干
        if len(clean_text(stem_text)) < 5 and passage_ctx:
            stem_text = f"完形填空（第{qno}题）\n{passage_ctx}"
        elif passage_ctx and qno > 20:
            # 阅读/新题型：附加文章上下文（限制长度）
            stem_text = f"{passage_ctx}\n{stem_text}"

        content = clean_text(stem_text)
        if len(content) < 5:
            continue

        # 答案与解析
        ans_info = answers.get(qno, {})
        answer = ans_info.get("answer", "")
        analysis = ans_info.get("analysis", "")

        # 无答案的题目：选择题必须 answer_in_options 才能过质量门禁
        if not answer:
            stats[f"no_answer_{year}"] += 1
            continue

        chapter, ch_id = get_chapter(qno)
        source_label = f"TsekaLuk/Kaoyan-English1-Papers({year}年考研英语一真题)"
        rec = {
            "source": "kaoyan-english1-zhenti",
            "subject": "英语",
            "subject_id": 9,
            "content": content,
            "options": options,
            "answer": answer,
            "analysis": analysis,
            "question_type": "single",
            "chapter": chapter,
            "chapter_id": ch_id,
            "knowledge_point": None,
            "source_label": source_label,
            "difficulty": 3,
            "year": year,
            "paper": f"{year}年考研英语一真题",
            "external_id": f"{EXT_PREFIX}_{year}_{qno}",
        }
        records.append(rec)
        stats[f"parsed_{year}"] += 1

    return records


# =========================================================
# 主流程
# =========================================================
def main():
    files = sorted(glob.glob(os.path.join(SOL_DIR, "english1_*.md")))
    if not files:
        log.error("未找到英语解析文件: %s", SOL_DIR)
        return

    all_records = []
    for fp in files:
        year_m = re.search(r"english1_(\d{4})\.md", os.path.basename(fp))
        if not year_m:
            continue
        year = int(year_m.group(1))
        with open(fp, "r", encoding="utf-8") as f:
            text = f.read()
        # 先统计答案标记数量，决定是否走完整导入
        ans_mark_count = len(re.findall(r"【答案】", text))
        if ans_mark_count > 0:
            log.info("处理 %d 年（含答案标记 %d 个）...", year, ans_mark_count)
            records = parse_full_year(text, year)
        else:
            log.info("处理 %d 年（无答案标记，跳过）...", year)
            continue
        all_records.extend(records)

    log.info("共解析 %d 条记录", len(all_records))
    if not all_records:
        log.warning("没有可导入的记录")
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