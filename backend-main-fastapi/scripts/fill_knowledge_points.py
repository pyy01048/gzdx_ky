# -*- coding: utf-8 -*-
"""从 knowledge_chunks 生成知识点数据填充 knowledge_points 表（真实数据来源）。

策略：
  - 每个文档取其分块，按 chunk_id 顺序
  - 每个分块取首句作为知识点名（截断 60 字），全文作为 description（截断 500 字）
  - 每个文档最多生成 5 个知识点，避免数量爆炸
  - 幂等：先清空 knowledge_points 再写入（该表当前为空）
"""
import os
import sys
import sqlite3
import datetime

DB = r"D:\MarvisData\User\oAN1i2T40ogJFVM4CCm9d72iRr_I\workspace\conv_6307dce6ea3e494fa029dd89f1bf322a\output\kaoyan-study-platform\backend-main-fastapi\data\kaoyan.db"
DRY_RUN = "--commit" not in sys.argv


def first_sentence(text, maxlen=60):
    """取分块文本的第一句/首行作为知识点名。"""
    t = (text or "").strip().replace("\n", " ")
    if not t:
        return "未命名知识点"
    # 取第一个句号/分号/制表符之前的内容
    import re
    m = re.split(r"[。；;\.]", t, maxsplit=1)[0]
    name = m.strip()
    if not name or len(name) < 2:
        name = t[:30]
    return name[:maxlen]


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    if not DRY_RUN:
        cur.execute("DELETE FROM knowledge_points")
    # 每个文档的分块，按 chunk_id 排序
    cur.execute("""
        SELECT kc.document_id, kc.doc_name, kc.chunk_id, kc.subject, kc.text,
               d.id
        FROM knowledge_chunks kc
        LEFT JOIN documents d ON d.id = kc.document_id
        WHERE kc.document_id IS NOT NULL
        ORDER BY kc.document_id, kc.chunk_id
    """)
    rows = cur.fetchall()

    by_doc = {}
    for document_id, doc_name, chunk_id, subject, text, d_id in rows:
        by_doc.setdefault(document_id, []).append((doc_name, chunk_id, subject, text))

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    per_doc = []
    for document_id, chunks in sorted(by_doc.items()):
        # 每文档最多 5 个知识点（均匀取样覆盖）
        step = max(1, len(chunks) // 5)
        picked = chunks[::step][:5]
        for doc_name, chunk_id, subject, text in picked:
            name = first_sentence(text)
            desc = (text or "").strip()[:500]
            if not DRY_RUN:
                cur.execute(
                    "INSERT INTO knowledge_points (name, subject, chapter, parent_id, mastery, exam_frequency, description, created_at, document_id) "
                    "VALUES (?, ?, ?, NULL, 3, 2, ?, ?, ?)",
                    (name, subject, doc_name or "", desc, now, document_id),
                )
            inserted += 1
            per_doc.append((document_id, doc_name, subject, name))

    if not DRY_RUN:
        con.commit()

    print(f"[{'DRY-RUN 预览' if DRY_RUN else '正式写入'}] 计划生成知识点 {inserted} 条，覆盖文档 {len(by_doc)} 篇")
    print("\n== 样例（前 15 条）==")
    for document_id, doc_name, subject, name in per_doc[:15]:
        print(f"  doc={doc_name} | subject={subject} | name={name}")
    if not DRY_RUN:
        print("\n== 写入后统计 ==")
        for r in cur.execute("SELECT subject, COUNT(*) FROM knowledge_points GROUP BY subject ORDER BY COUNT(*) DESC"):
            print(" ", r[0], r[1])
        total = cur.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
        print("  知识点总数:", total)
    con.close()


if __name__ == "__main__":
    main()
