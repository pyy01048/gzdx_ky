# -*- coding: utf-8 -*-
"""只读：产出两份 CSV 清单（seed 假数据行 / 被过度隔离的真实题），并核对网盘 connected 假状态。"""
import csv
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join("D:", os.sep, "平台", "database", "kaoyan.db")
OUTDIR = os.path.join("D:", os.sep, "平台", "docx", "_audit")
before = os.stat(DB)
sys.path.insert(0, os.path.join(BASE, "scripts"))
from quiz_quality_gate import classify  # noqa: E402

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

# ---------- 1) seed 假数据行 ----------
# main.py::_init_sample_data 写入的固定题干/标题，按原文匹配，不做模糊推断。
SEED_TITLES = [
    "数学高等数学第一章复习", "英语阅读理解精读 2 篇", "政治马原原理梳理",
    "数据结构链表练习", "数学线性代数复习", "英语单词背诵 200 个", "政治毛中特框架整理",
]
SEED_STEMS = [
    "设函数 f(x) 在 x=0 处连续", "The word 'ubiquitous' in the passage",
    "马克思主义哲学区别于旧哲学的最显著特征", "下列关于线性表的说法正确的是",
]
rows = []
for t in SEED_TITLES:
    for r in cur.execute("SELECT id, title, subject, status, completed_at, created_at FROM tasks WHERE title=?", (t,)):
        rows.append(["tasks", r[0], r[1], r[2], f"status={r[3]} completed_at={r[4]}", r[5] or ""])
for s in SEED_STEMS:
    for r in cur.execute("SELECT id, substr(content,1,60), subject, source, created_at FROM quiz_questions WHERE content LIKE ?", (s + "%",)):
        rows.append(["quiz_questions", r[0], r[1], r[2], f"source={r[3]}", r[4] or ""])
er_cols = [c[1] for c in cur.execute("PRAGMA table_info(error_records)")]
try:
    for r in cur.execute("SELECT id, content, subject, error_reason, created_at FROM error_records "
                         "WHERE content LIKE '%ubiquitous%' OR content LIKE '%设函数 f(x)%'"):
        rows.append(["error_records", r[0], r[1][:60], r[2], f"reason={r[3]}", r[4] or ""])
except Exception as exc:
    print("  error_records 查询跳过:", exc, "| 列:", er_cols)
for r in cur.execute("SELECT id, exam_date, university, remark, created_at FROM goals"):
    rows.append(["goals", r[0], f"exam_date={r[1]}", r[2], f"remark={r[3]}", r[4] or ""])

p1 = os.path.join(OUTDIR, "seed_demo_rows_live_20261013.csv")
with open(p1, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["table", "id", "content/title", "subject", "other", "created_at", "处置建议"])
    for x in rows:
        w.writerow(x + ["待用户逐条确认；不自动删除"])
print(f"[1] seed 假数据行 {len(rows)} 条 → {p1}")
for x in rows:
    print("   ", x[0], x[1], str(x[2])[:44])

# ---------- 2) 被过度隔离、但今天闸门判非 JUNK 的行 ----------
allq = cur.execute("SELECT id, content, answer, source, question_type, options, is_junk, "
                   "is_available, subject FROM quiz_questions").fetchall()
over = []
for r in allq:
    if r[6] == 1:
        g, why = classify(r[:6])
        if g != "JUNK":
            over.append([r[0], g, why, r[8], (r[1] or "")[:80], r[3], r[7]])
p2 = os.path.join(OUTDIR, "quiz_overquarantined_20261013.csv")
with open(p2, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["id", "当前判定", "原因", "subject", "题干前80字", "source", "is_available", "处置建议"])
    w.writerows(over)
print(f"\n[2] 过度隔离（is_junk=1 但闸门判 {('A','B','C')}）共 {len(over)} 条 → {p2}")
from collections import Counter
print("    等级分布:", Counter(o[1] for o in over))
print("    学科分布:", Counter(o[3] for o in over).most_common(8))
print("    样例:")
for o in over[:6]:
    print("     ", o[0], o[1], o[3], "|", o[4][:46])

# ---------- 3) 网盘 connected 假状态 ----------
print("\n[3] platform_configs 的连接状态（凭证为空却 connected=True 即为假状态）")
for r in cur.execute("SELECT platform_name, sync_enabled, extra FROM platform_configs"):
    import json
    try:
        e = json.loads(r[2] or "{}")
    except Exception:
        e = {"_raw": (r[2] or "")[:40]}
    print(f"   {r[0]:<18} sync_enabled={r[1]} connected={e.get('connected')} "
          f"app_key_len={len(e.get('app_key') or '')}")
ap_cols = [c[1] for c in cur.execute("PRAGMA table_info(ai_providers)")]
key_col = "api_key" if "api_key" in ap_cols else None
print("   ai_providers 列:", ap_cols)
if key_col:
    print("   ai_providers 里带 key 的行数:",
          cur.execute(f"SELECT count(*) FROM ai_providers WHERE {key_col} IS NOT NULL AND trim({key_col})<>''").fetchall())

after = os.stat(DB)
assert (after.st_mtime, after.st_size) == (before.st_mtime, before.st_size), "探针动了生产库！"
print("\n[guard] 生产库未变:", before.st_size)
conn.close()
