# -*- coding: utf-8 -*-
"""知识点挂接回填 + 分块学科名对齐（幂等，可重复执行）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402
from pipeline.config import pg_database_url  # noqa: E402

with psycopg.connect(pg_database_url(), autocommit=False) as pg, pg.cursor() as cur:
    # ---- 前置核查（只读） ----
    cur.execute("""
        SELECT COUNT(*) FILTER (WHERE k.chapter_id IS NULL AND c.chapter_id IS NOT NULL) AS fixable,
               COUNT(*) FILTER (WHERE k.chapter_id IS NULL)                              AS total_null,
               COUNT(*) FILTER (WHERE k.chapter_id IS NOT NULL)                          AS already_linked
        FROM knowledge_points k
        LEFT JOIN knowledge_chunks c ON k.source_chunk_id = c.id""")
    fixable, total_null, already = cur.fetchone()
    print(f"知识点挂接：未挂 {total_null}，其中可通过 source_chunk 回填 {fixable}，已挂 {already}")

    cur.execute("SELECT COUNT(*) FILTER (WHERE chapter_id IS NOT NULL), COUNT(*) FROM knowledge_chunks")
    ch_linked, ch_total = cur.fetchone()
    print(f"分块章节覆盖：{ch_linked}/{ch_total}")

    if fixable:
        # ---- 回填知识点 → 章节（取分块的章节；名称同步章节表 title） ----
        cur.execute("""
            UPDATE knowledge_points k
            SET chapter_id = c.chapter_id,
                chapter    = COALESCE(ch.title, c.chapter, k.chapter)
            FROM knowledge_chunks c
            LEFT JOIN subject_chapters ch ON ch.id = c.chapter_id
            WHERE k.source_chunk_id = c.id
              AND k.chapter_id IS NULL
              AND c.chapter_id IS NOT NULL""")
        print(f"回填知识点 chapter_id：{cur.rowcount} 条")
    else:
        print("无可回填知识点")

    # ---- 分块学科名对齐（按 subject_id 刷冗余 name 字段） ----
    cur.execute("""
        UPDATE knowledge_chunks c
        SET subject = d.subject
        FROM documents d
        WHERE c.document_id = d.id
          AND c.subject_id = d.subject_id
          AND COALESCE(c.subject, '') <> ''
          AND c.subject <> d.subject""")
    print(f"对齐分块学科名：{cur.rowcount} 条")

    pg.commit()
    print("已提交。")
