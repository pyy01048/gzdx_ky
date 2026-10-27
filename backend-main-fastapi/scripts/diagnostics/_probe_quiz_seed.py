# -*- coding: utf-8 -*-
"""只读探针：低 id 行与 goals 行的来历 + 闸门判定的存量交叉表。绝不写库。"""
import os
import sqlite3

DB = os.path.join("D:", os.sep, "平台", "database", "kaoyan.db")
before = os.stat(DB)
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

print("=== goals 全行（判定倒计时是不是假日期）===")
cols = [c[1] for c in cur.execute("PRAGMA table_info(goals)")]
print("  columns:", cols)
for r in cur.execute("SELECT * FROM goals"):
    print("  ", dict(zip(cols, r)))

print()
print("=== quiz_questions id<=12（seed 伪题是否还在）===")
for r in cur.execute("SELECT id, substr(replace(content,char(10),' '),1,50), source, subject, is_junk, "
                     "quality, is_available, created_at FROM quiz_questions ORDER BY id LIMIT 12"):
    print("  ", r)

print()
print("=== tasks 里像 seed 的行 ===")
tcols = [c[1] for c in cur.execute("PRAGMA table_info(tasks)")]
print("  columns:", tcols)
for r in cur.execute("SELECT id, title, subject, status, created_at FROM tasks ORDER BY id LIMIT 12"):
    print("  ", r)

print()
print("=== JUNK 交叉表：现存 is_junk 与当前闸门判定是否一致 ===")
import sys
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))
from quiz_quality_gate import classify  # noqa: E402

rows = cur.execute("SELECT id, content, answer, source, question_type, options, is_junk "
                   "FROM quiz_questions").fetchall()
tab = {}
newly_junk, stale_junk = [], []
for r in rows:
    g, why = classify(r[:6])
    cur_junk = 1 if r[6] == 1 else 0
    tab[(cur_junk, g)] = tab.get((cur_junk, g), 0) + 1
    if g == "JUNK" and not cur_junk:
        newly_junk.append(r[0])
    if cur_junk and g != "JUNK":
        stale_junk.append((r[0], g, why))

print(f"  {'现存is_junk':<14}{'当前判定':<10}{'行数':>7}")
for (cj, g), n in sorted(tab.items()):
    print(f"  {('JUNK' if cj else 'not-junk'):<14}{g:<10}{n:>7}")
print(f"\n  闸门今天会新判 JUNK、但库里 is_junk=0 的行数: {len(newly_junk)}")
print(f"  库里 is_junk=1、但闸门今天判非 JUNK（过度标记）: {len(stale_junk)}")
if stale_junk[:8]:
    print("  样例:", stale_junk[:8])

print()
print("=== 空题干 / 无选项但声称选择题 ===")
print("  content 为空或<6:", cur.execute(
    "SELECT count(*) FROM quiz_questions WHERE content IS NULL OR length(trim(content))<6").fetchall())
print("  纯 seed 长度=6 且无答案:", cur.execute(
    "SELECT count(*) FROM quiz_questions WHERE length(content)=6 AND (answer IS NULL OR trim(answer)='')").fetchall())

after = os.stat(DB)
assert (after.st_mtime, after.st_size) == (before.st_mtime, before.st_size), "探针动了生产库！"
print("\n[guard] 生产库未变:", before.st_size)
conn.close()
