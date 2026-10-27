# -*- coding: utf-8 -*-
"""探针：kp.chapter 与 subject_chapters.title 的写法差异 + 分块学科漂移样例。用完即删。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402
from pipeline.config import pg_database_url  # noqa: E402

with psycopg.connect(pg_database_url()) as pg, pg.cursor() as cur:
    cur.execute("""SELECT COALESCE(NULLIF(chapter,''),'(空)'), COUNT(*)
                   FROM knowledge_points GROUP BY 1 ORDER BY 2 DESC LIMIT 25""")
    print("--- kp.chapter 分布 top25 ---")
    for r in cur.fetchall():
        print(f"  {r[1]:4d}  {r[0][:60]}")

    print("--- kp 按 subject 的 chapter 填写率 ---")
    cur.execute("""SELECT subject, COUNT(*) total,
                          COUNT(*) FILTER (WHERE COALESCE(chapter,'')<>'') has_ch
                   FROM knowledge_points GROUP BY 1 ORDER BY 2 DESC LIMIT 12""")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[2]}/{r[1]}")

    print("--- subject_chapters 样例（数电/模电/政治/数学） ---")
    cur.execute("""SELECT s.name, c.code, c.title FROM subject_chapters c
                   JOIN subjects s ON c.subject_id=s.id
                   WHERE s.name IN ('数字电子技术','模拟电子技术','政治','数学','电路')
                   ORDER BY s.name, c.sort_order LIMIT 40""")
    for r in cur.fetchall():
        print(f"  [{r[0]}] {r[1]} {r[2]}")

    print("--- 分块学科漂移样例 10 条 ---")
    cur.execute("""SELECT c.id, c.subject, d.subject, c.subject_id, d.subject_id, LEFT(c.doc_name,40)
                   FROM knowledge_chunks c JOIN documents d ON c.document_id=d.id
                   WHERE COALESCE(c.subject,'')<>'' AND c.subject<>d.subject LIMIT 10""")
    for r in cur.fetchall():
        print(f"  chunk#{r[0]} chunk.subject={r[1]!r} doc.subject={r[2]!r} sid={r[3]}/{r[4]} {r[5]}")

    print("--- 数学 kp.chapter ---")
    cur.execute("""SELECT chapter, COUNT(*) FROM knowledge_points
                   WHERE subject='数学' GROUP BY 1 ORDER BY 2 DESC LIMIT 25""")
    for r in cur.fetchall():
        print(f"  {r[1]:3d}  {r[0][:60]}")

    print("--- 数电/模电 kp.chapter ---")
    cur.execute("""SELECT chapter, COUNT(*) FROM knowledge_points
                   WHERE subject IN ('模拟电子技术','数字电子技术')
                   GROUP BY 1 ORDER BY 2 DESC LIMIT 20""")
    for r in cur.fetchall():
        print(f"  {r[1]:3d}  {r[0][:60]}")
