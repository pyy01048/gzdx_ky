#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入 6wa1t/408-ai-tutor 题库包中「有答案」的题目到 quiz_questions (PostgreSQL)

数据源: data_sources/408-ai-tutor/.../question_banks/*/bank.db
  - 数据结构 803 题（无答案，跳过）
  - 操作系统 752 题（约 385 题有答案）
  - 计算机组成原理 677 题（约 11 题有答案）
  - 计算机网络 640 题（无答案，跳过）

策略:
  - 仅导入 answer 列非空的题目（可自动判分）
  - 科目映射: 数据结构->24, 操作系统->25, 计算机组成原理->计算机基础(23), 计算机网络->5
  - 按题干内容去重（与平台已有 408 题比较），external_id 幂等

运行: python scripts/import_408ai_tutor_pg.py
"""
import io
import json
import os
import re
import sqlite3
import sys

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
BANK_ROOT = os.path.join(PROJECT_ROOT, "..", "data_sources", "408-ai-tutor", "408-ai-tutor-main", "question_banks")

DB_CONFIG = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)

SUBJECT_MAP = {
    "数据结构": (24, "数据结构"),
    "操作系统": (25, "操作系统"),
    "计算机组成原理": (23, "计算机基础"),
    "计算机网络": (5, "计算机网络"),
}


def clean_text(s):
    if not s:
        return ""
    s = str(s)
    s = "".join(ch for ch in s if ch >= "\u0001" or ch in ("\n", "\t", "\r"))
    s = re.sub(r"\$+", "", s)
    s = re.sub(r"!\[.*?\]\(.*?\)", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+\b", " ", s)  # 去掉 LaTeX 命令
    s = re.sub(r"[{}_^]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def make_options(a, b, c, d):
    opts = []
    for key, val in (("A", a), ("B", b), ("C", c), ("D", d)):
        v = (val or "").strip()
        if v:
            opts.append({"key": key, "text": v})
    if len(opts) < 2:
        return None
    return opts


def main():
    if not os.path.isdir(BANK_ROOT):
        print(f"题库目录不存在: {BANK_ROOT}")
        sys.exit(1)

    conn = psycopg.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        # 平台已有 408 相关题目内容集合（用于去重）
        subj_ids = list({v[0] for v in SUBJECT_MAP.values()})
        cur.execute(
            "SELECT content FROM quiz_questions WHERE subject_id = ANY(%s) AND is_junk = FALSE",
            (subj_ids,),
        )
        existing_contents = {clean_text(r[0]) for r in cur.fetchall()}
        print(f"平台已有 408 题: {len(existing_contents)}")

        total_import = 0
        for bank in ["数据结构", "操作系统", "计算机组成原理", "计算机网络"]:
            db_path = os.path.join(BANK_ROOT, bank, "bank.db")
            if not os.path.exists(db_path):
                print(f"跳过不存在: {bank}")
                continue
            subject_id, subject = SUBJECT_MAP[bank]
            sqlite = sqlite3.connect(db_path)
            sqlite.row_factory = sqlite3.Row
            rows = sqlite.execute(
                "SELECT * FROM questions WHERE answer IS NOT NULL AND answer != ''"
            ).fetchall()
            sqlite.close()
            print(f"{bank}: 有答案 {len(rows)} 题")

            inserted = 0
            for row in rows:
                content = clean_text(row["question_text"] or "")
                if not content or len(content) < 5:
                    continue
                if content in existing_contents:
                    continue
                qtype = row["question_type"] or "other"
                options = make_options(row["option_a"], row["option_b"], row["option_c"], row["option_d"])
                answer = (row["answer"] or "").strip()
                analysis = (row["analysis"] or "").strip()
                answer_ref = (row["answer_ref"] or "").strip()
                if answer_ref and not analysis:
                    analysis = f"参考：{answer_ref}"
                if options:
                    question_type = "single"
                else:
                    question_type = "fill" if qtype != "other" else "calc"

                external_id = f"github_openquiz_408ai_{bank}_{row['id']}"
                params = {
                    "content": (row["question_text"] or "").strip(),
                    "options": json.dumps(options, ensure_ascii=False) if options else None,
                    "answer": answer,
                    "analysis": analysis or None,
                    "question_type": question_type,
                    "difficulty": 3,
                    "source_label": f"开源题库:6wa1t/408-ai-tutor({bank})",
                    "year": row["exam_year"] or None,
                    "paper": None,
                    "external_id": external_id,
                    "subject_id": subject_id,
                    "subject": subject,
                    "chapter_id": None,
                    "chapter": row["chapter"] or None,
                    "knowledge_point": row["knowledge_tag"] or None,
                }
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
                try:
                    cur.execute(INSERT_SQL, params)
                    if cur.rowcount > 0:
                        inserted += 1
                        existing_contents.add(content)
                except psycopg.errors.UniqueViolation:
                    conn.rollback()
                except Exception as e:
                    conn.rollback()
                    print(f"  写入失败 {external_id}: {e}")
                    continue
            conn.commit()
            print(f"{bank}: 实际导入 {inserted}")
            total_import += inserted

        print(f"\n合计导入: {total_import}")

    conn.close()
    print("=== 完成 ===")


if __name__ == "__main__":
    main()