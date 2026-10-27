# -*- coding: utf-8 -*-
"""只读探针：题库假数据来源 + 各写入路径的实际产出。绝不写库（mode=ro）。"""
import os
import sqlite3
import sys

DB = os.path.join("D:", os.sep, "平台", "database", "kaoyan.db")
before = os.stat(DB)
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.text_factory = str
cur = conn.cursor()


def q(sql, args=()):
    try:
        return cur.execute(sql, args).fetchall()
    except Exception as e:  # 表名/列名不对时直接报出来，不静默
        return [("ERR", str(e))]


print("=== goals 表（判定 _init_sample_data 是否已触发过）===")
print("表名:", q("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%goal%'"))
print("行数/内容:", q("SELECT id, exam_date, university, total_score_target FROM goals ORDER BY id LIMIT 10"))

print()
print("=== 假题目是否已经在生产库里（按 main.py 里的题干原文查）===")
stems = [
    "设函数 f(x) 在 x=0 处连续",
    "The word 'ubiquitous' in the passage",
    "马克思主义哲学区别于旧哲学的最显著特征",
    "下列关于线性表的说法正确的是",
]
for s in stems:
    print(f"  {s[:24]!r}:", q("SELECT count(*) FROM quiz_questions WHERE content LIKE ?", (f"{s}%",)))

print("  假任务:", q("SELECT count(*) FROM tasks WHERE title LIKE '%数学高等数学第一章复习%'"))
print("  假错题:", q("SELECT count(*) FROM error_records WHERE my_answer IN ('A','C') AND content LIKE '%ubiquitous%'"))
print("  AI 供应商模板:", q("SELECT count(*), group_concat(name) FROM ai_providers"))

print()
print("=== quiz_questions 总量口径（重新实测，别引用旧数）===")
print("  total:", q("SELECT count(*) FROM quiz_questions"))
print("  is_junk=1:", q("SELECT count(*) FROM quiz_questions WHERE is_junk=1"))
print("  answer 空:", q("SELECT count(*) FROM quiz_questions WHERE answer IS NULL OR trim(answer)=''"))
print("  verified=1:", q("SELECT count(*) FROM quiz_questions WHERE verified=1"))
print("  is_deleted=1:", q("SELECT count(*) FROM quiz_questions WHERE is_deleted=1"))
print("  可用池(非junk且有答案):", q(
    "SELECT count(*) FROM quiz_questions WHERE (is_junk IS NULL OR is_junk=0) "
    "AND answer IS NOT NULL AND trim(answer)<>'' AND (is_deleted IS NULL OR is_deleted=0)"))

print()
print("=== 按 source 前缀分组：谁在往题库里写垃圾 ===")
rows = q("""
SELECT CASE
  WHEN source LIKE '文档生成%' THEN 'A:generate_quiz(无闸门)'
  WHEN source LIKE '知识库:%' THEN 'B:kb_import/confirm(有闸门)'
  WHEN source LIKE '文档提取%' THEN 'C:confirm_questions(有闸门)'
  WHEN source LIKE '真题%' THEN 'D:真题导入'
  WHEN source IS NULL OR trim(source)='' THEN 'E:source 为空'
  ELSE 'F:其他'
END AS lane,
count(*) AS n,
sum(CASE WHEN is_junk=1 THEN 1 ELSE 0 END) AS junk,
sum(CASE WHEN answer IS NULL OR trim(answer)='' THEN 1 ELSE 0 END) AS no_ans,
sum(CASE WHEN length(content)<10 THEN 1 ELSE 0 END) AS short_stem,
sum(CASE WHEN options IS NULL OR trim(options)='' OR trim(options)='[]' THEN 1 ELSE 0 END) AS no_opt
FROM quiz_questions GROUP BY lane ORDER BY n DESC
""")
print(f"  {'lane':<34}{'n':>7}{'junk':>7}{'no_ans':>8}{'short':>7}{'no_opt':>8}")
for r in rows:
    print(f"  {str(r[0]):<34}{r[1]:>7}{r[2] or 0:>7}{r[3] or 0:>8}{r[4] or 0:>7}{r[5] or 0:>8}")

print()
print("=== F:其他 里到底写了什么（前 20 种 source）===")
for r in q("""SELECT source, count(*) n FROM quiz_questions
  WHERE source IS NOT NULL AND source NOT LIKE '文档生成%' AND source NOT LIKE '知识库:%'
    AND source NOT LIKE '文档提取%' AND source NOT LIKE '真题%'
  GROUP BY source ORDER BY n DESC LIMIT 20"""):
    print("   ", r[1], "|", (r[0] or "")[:60])

print()
print("=== A 通道（generate_quiz）产出的样例：闸门缺失的代价 ===")
for r in q("""SELECT id, substr(replace(content, char(10), ' '),1,60), ifnull(answer,''), ifnull(length(options),0),
                     is_junk, index_status
              FROM quiz_questions WHERE source LIKE '文档生成%' ORDER BY id DESC LIMIT 15"""):
    print("   ", r)

print()
print("=== 最短的题干（闸门该拦而未拦的）===")
for r in q("""SELECT id, length(content), substr(content,1,40), source FROM quiz_questions
              ORDER BY length(content) ASC LIMIT 12"""):
    print("   ", r)

after = os.stat(DB)
assert (after.st_mtime, after.st_size) == (before.st_mtime, before.st_size), "只读探针动了生产库！"
print("\n[guard] 生产库 (mtime,size) 未变:", before.st_size)
conn.close()
