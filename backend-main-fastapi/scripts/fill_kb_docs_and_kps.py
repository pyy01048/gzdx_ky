# -*- coding: utf-8 -*-
"""知识库内容扩充：批量生成高质量知识文档 + 知识点卡片（PostgreSQL）。

数据源：scripts/kb_content/ 下的内容模块（人工整理的专业知识）。
- 写入 documents（含 subject_id、chunk_count、knowledge_point_count）
- 写入 knowledge_chunks（保证 RAG 可检索，search_vector 由生成列自动填充）
- 写入 knowledge_points（知识点卡片，extract_source=manual）

幂等：按 file_name 查重 + content_hash 查重。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import sys
from pathlib import Path

import psycopg

BASE_DIR = Path(__file__).resolve().parent.parent
CONTENT_DIR = Path(__file__).resolve().parent / "kb_content"
sys.path.insert(0, str(CONTENT_DIR))

DB_CONFIG = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)

# 内容模块 subject -> (documents.subject, subject_id)
SUBJECT_MAP = {
    "马克思主义基本原理": ("政治", 10),
    "毛泽东思想和中国特色社会主义理论体系": ("政治", 10),
    "中国近现代史纲要": ("政治", 10),
    "思想道德与法治": ("政治", 10),
    "高等数学": ("数学", 8),
    "线性代数": ("数学", 8),
    "概率论与数理统计": ("数学", 8),
    "英语词汇": ("英语", 9),
    "英语语法": ("英语", 9),
    "英语长难句": ("英语", 9),
    "英语作文": ("英语", 9),
    "数据结构": ("数据结构", 24),
    "操作系统": ("操作系统", 25),
    "计算机网络": ("计算机网络", 5),
    "数字电子技术": ("数字电子技术", 6),
    "模拟电子技术": ("模拟电子技术", 7),
    "通信原理": ("通信原理", 1),
    "信号与系统": ("信号与系统", 12),
    "普通物理": ("普通物理", 14),
    "计算机学科专业基础408": ("计算机学科专业基础408", 15),
    "电磁场与电磁波": ("电磁场与电磁波", 4),
    "数字信号处理": ("数字信号处理", 3),
}

MODULES = [
    "politics_mks", "politics_mzt", "politics_history", "politics_sixiu",
    "math_gaoshu", "math_xiandai", "math_prob",
    "english_vocab", "english_grammar", "english_sentences", "english_writing",
    "cs_ds", "cs_os", "cs_network",
    "electronics_digital", "electronics_analog",
    "communications_principles", "signals_systems",
    "general_physics", "cs_408", "electromagnetics", "dsp",
]


def content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def token_count(text: str) -> int:
    """粗略 token 数：汉字算 1，连续字母数字算 1。"""
    n = 0
    word = False
    for ch in text:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            n += 1
            word = False
        elif ch.isalnum() or ch in "_-":
            word = True
        else:
            if word:
                n += 1
                word = False
    if word:
        n += 1
    return max(n, 1)


def chunk_text(text: str, size: int = 600, overlap: int = 80):
    """简单按段落切分，保持每块可读。返回块列表。"""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    buf = ""
    for p in paras:
        if len(buf) + len(p) + 2 <= size or not buf:
            buf = (buf + "\n\n" + p).strip()
        else:
            chunks.append(buf)
            # overlap 取前一块尾部
            tail = buf[-overlap:] if len(buf) > overlap else ""
            buf = (tail + "\n\n" + p).strip()
    if buf:
        chunks.append(buf)
    return chunks or [text]


def main() -> int:
    ap = argparse.ArgumentParser(description="批量生成知识文档与知识点")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写库")
    ap.add_argument("--limit", type=int, default=0, help="最多生成 N 篇（0=全部）")
    args = ap.parse_args()

    # 加载内容
    docs = []
    for m in MODULES:
        mod = importlib.import_module(m)
        docs.extend(mod.DOCS)
    if args.limit:
        docs = docs[: args.limit]

    total_docs = len(docs)
    total_kps = sum(len(d[4]) for d in docs)
    print(f"内容库：{total_docs} 篇文档，{total_kps} 个知识点")

    with psycopg.connect(**DB_CONFIG) as pg, pg.cursor() as cur:
        # 已存在的文件名
        cur.execute("SELECT file_name FROM documents")
        existing_names = {r[0] for r in cur.fetchall()}
        # 已存在的 content_hash
        cur.execute("SELECT content_hash FROM documents WHERE content_hash IS NOT NULL")
        existing_hashes = {r[0] for r in cur.fetchall()}
        print(f"库内已有文档：{len(existing_names)} 篇")

        inserted_docs = 0
        inserted_kps = 0
        skipped = 0
        by_subject: dict[str, dict] = {}

        for title, chapter, category, body, kps in docs:
            subject_full, subject_id = SUBJECT_MAP.get(chapter, (None, None))
            if subject_full is None:
                print(f"  [warn] 未映射章节 {chapter}，跳过 {title}")
                continue

            # 幂等查重
            if title in existing_names:
                skipped += 1
                continue
            h = content_hash(body)
            if h in existing_hashes:
                skipped += 1
                continue

            if args.dry_run:
                inserted_docs += 1
                inserted_kps += len(kps)
                continue

            # 写入 documents
            cur.execute(
                """
                INSERT INTO documents
                    (file_name, content, subject_id, subject, chapter, content_category,
                     doc_type, structure_level, index_status, source_kind,
                     source_format, content_hash, chunk_count, knowledge_point_count,
                     parse_progress, exam_stage, is_junk)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    title, body, subject_id, subject_full, chapter, category,
                    "note", "structured", "indexed", "ai_generated",
                    "md", h, 0, 0, 1.0, "初试", False,
                ),
            )
            doc_id = cur.fetchone()[0]

            # 写入 knowledge_chunks（切块）
            chunks = chunk_text(body)
            for idx, ch in enumerate(chunks):
                cur.execute(
                    """
                    INSERT INTO knowledge_chunks
                        (document_id, doc_name, chunk_index, subject, subject_id, text, token_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (doc_id, title, idx, subject_full, subject_id, ch, token_count(ch)),
                )
            chunk_count = len(chunks)

            # 写入 knowledge_points
            kp_count = 0
            for kp_name, desc, difficulty, frequency in kps:
                cur.execute(
                    """
                    INSERT INTO knowledge_points
                        (name, subject, subject_id, chapter, document_id, description,
                         difficulty, exam_frequency, question_types, extract_source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (kp_name, subject_full, subject_id, chapter, doc_id, desc,
                     difficulty, frequency, "[]", "manual"),
                )
                kp_count += 1

            # 更新文档计数
            cur.execute(
                "UPDATE documents SET chunk_count=%s, knowledge_point_count=%s WHERE id=%s",
                (chunk_count, kp_count, doc_id),
            )

            inserted_docs += 1
            inserted_kps += kp_count
            existing_names.add(title)
            existing_hashes.add(h)

            if subject_full not in by_subject:
                by_subject[subject_full] = {"docs": 0, "kps": 0}
            by_subject[subject_full]["docs"] += 1
            by_subject[subject_full]["kps"] += kp_count

            if inserted_docs % 20 == 0:
                print(f"  已插入 {inserted_docs} 篇...")

        if not args.dry_run:
            pg.commit()

        print(f"\n结果：新增 {inserted_docs} 篇文档，{inserted_kps} 个知识点，跳过 {skipped} 篇")
        if by_subject:
            print("\n各科目分布：")
            for s, v in sorted(by_subject.items()):
                print(f"  {s}: 文档 {v['docs']} 篇, 知识点 {v['kps']} 个")
        if args.dry_run:
            print("\n[DRY-RUN] 未写库；去掉 --dry-run 执行。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
