# -*- coding: utf-8 -*-
"""教材-文档关联填充（PostgreSQL 版，强匹配 + 角色推断）。

只做强确定性匹配（文件名含《教材标题》或作者名），并按文件名推断 doc_role：
  - 配套题库/章节题库/模拟试题 → exercise
  - 笔记和课后习题/学习辅导/习题解答/习题全解 → answer
  - 教材正文 PDF（第X版.pdf）→ body
  - 知识点总结/复习提纲/讲义 → slides
doc_role 必须在 ['body','exercise','answer','slides','scan'] 内（DB 检查约束）。

幂等：textbook_id+document_id 唯一冲突跳过。默认 dry-run，--apply 写库。
"""
from __future__ import annotations

import argparse
import sys

import psycopg

DB = dict(host="127.0.0.1", port=5432, dbname="kaoyan", user="kaoyan", password="kaoyan")

TEXTBOOK_RULES = {
    1: (["郑君里"], ["信号与系统"]),
    2: (["吴大正"], ["信号与线性系统"]),
    3: (["管致中"], ["信号与线性系统"]),
    4: ([], ["信号与系统"]),
    5: ([], ["信号与系统"]),
    6: (["樊昌信"], ["通信原理"]),
    7: ([], ["现代通信原理"]),
    8: ([], ["通信原理"]),
    9: ([], ["通信原理"]),
    10: ([], ["通信原理教程"]),
    11: ([], ["通信原理"]),
    12: (["邱关源"], ["电路"]),
    13: (["李瀚荪"], ["电路分析基础"]),
    14: (["康华光", "童诗白"], ["模拟电子技术", "电子技术基础"]),
    15: (["阎石"], ["数字电子技术"]),
    16: ([], ["数字电路与系统"]),
    17: ([], ["数字电路与逻辑设计"]),
    18: ([], ["数字系统原理与设计"]),
    19: (["程佩青"], ["数字信号处理"]),
    20: (["丁玉美"], ["数字信号处理"]),
    21: ([], ["数字信号处理"]),
    22: ([], ["数字信号处理"]),
    23: (["谢处方"], ["电磁场与电磁波"]),
    24: ([], ["电磁场与电磁波"]),
    25: ([], ["电磁场与波"]),
    26: (["谢希仁"], ["计算机网络"]),
}

def infer_role(fname: str) -> str:
    fn = fname or ""
    if any(k in fn for k in ["配套题库", "章节题库", "模拟试题", "题库"]):
        return "exercise"
    if any(k in fn for k in ["笔记和课后习题", "学习辅导", "习题解答", "习题全解", "同步辅导", "详解"]):
        return "answer"
    if any(k in fn for k in ["知识点总结", "复习提纲", "讲义", "笔记", "总结"]):
        return "slides"
    return "body"

def main() -> int:
    parser = argparse.ArgumentParser(description="教材-文档关联填充（强匹配+角色）")
    parser.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = parser.parse_args()

    conn = psycopg.connect(**DB)
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, title, subject_id FROM textbooks ORDER BY id")
        textbooks = cur.fetchall()
        cur.execute(
            "SELECT id, file_name, subject_id FROM documents "
            "WHERE is_junk IS NOT TRUE AND file_name IS NOT NULL ORDER BY id"
        )
        documents = cur.fetchall()
        cur.execute("SELECT textbook_id, document_id FROM textbook_documents")
        existing = {(r[0], r[1]) for r in cur.fetchall()}

        plan = []
        for tbid, title, tsid in textbooks:
            authors, title_kws = TEXTBOOK_RULES.get(tbid, ([], []))
            for doc_id, fname, dsid in documents:
                if dsid != tsid:
                    continue
                fn = (fname or "").strip()
                in_book = any(f"《{kw}》" in fn for kw in title_kws if kw)
                has_author = any(a and a in fn for a in authors)
                if in_book or has_author:
                    if (tbid, doc_id) not in existing:
                        role = infer_role(fn)
                        plan.append((tbid, doc_id, role, fname))
                        existing.add((tbid, doc_id))

        print(f"拟新增强关联 {len(plan)} 条")
        if args.apply:
            for tbid, doc_id, role, fname in plan:
                cur.execute(
                    "INSERT INTO textbook_documents (textbook_id, document_id, doc_role) "
                    "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (tbid, doc_id, role),
                )
            conn.commit()
            print(f"已写库 {len(plan)} 条")
        else:
            for row in plan[:20]:
                print("  ", row)
    finally:
        conn.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
