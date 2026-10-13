# -*- coding: utf-8 -*-
"""清理后完整性校验：确认没误伤真题/题库/词汇书，且核心数据仍在。"""
import sqlite3, os, sys, re
sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
KB = r"D:\平台\knowledge_base"
c = sqlite3.connect(DB).cursor()

print("=== 核心规模（清理后）===")
for t in ["documents", "knowledge_chunks", "quiz_questions", "knowledge_points",
          "words", "flashcards"]:
    print(f"  {t:20} {c.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0]}")

print("\n=== 残留低价值文档（应为 0 或极少）===")
BAD = ["答题卡", "答题纸", "打卡", "课程表", "计划表", "封面及目录"]
left = []
for w in BAD:
    n = c.execute("SELECT COUNT(*) FROM documents WHERE file_name LIKE ?",
                  (f"%{w}%",)).fetchone()[0]
    if n:
        rows = c.execute("SELECT id,file_name FROM documents WHERE file_name LIKE ?",
                         (f"%{w}%",)).fetchall()
        left.extend(rows)
    print(f"  {w:10} {n}")
for r in left:
    print("     ->", r)

print("\n=== 误伤校验：高价值资产仍在？ ===")
for kw, label in [("红宝书", "红宝书"), ("词汇闪过", "词汇闪过"),
                  ("真题", "真题类"), ("题库", "题库类"), ("教材", "教材类")]:
    n = c.execute("SELECT COUNT(*) FROM documents WHERE file_name LIKE ?",
                  (f"%{kw}%",)).fetchone()[0]
    d = c.execute(
        "SELECT COUNT(*) FROM documents WHERE file_path LIKE ?",
        (f"%{kw}%",)).fetchone()[0]
    print(f"  {label:10} 文件名命中 {n:4}  路径命中 {d:4}")

print("\n=== 关键真题文档抽样确认 ===")
rows = c.execute(
    "SELECT id, file_name, length(content) FROM documents "
    "WHERE file_name LIKE '%真题%' AND length(content) > 10000 "
    "ORDER BY length(content) DESC LIMIT 8").fetchall()
for r in rows:
    print(f"  #{r[0]:<6} {r[1][:60]}  正文={r[2]}")

print("\n=== 磁盘隔离区 ===")
tr = os.path.join(KB, "_trash", "20261012")
if os.path.isdir(tr):
    n = sum(len(f) for _, _, f in os.walk(tr))
    sz = sum(os.path.getsize(os.path.join(p, f))
             for p, _, fs in os.walk(tr) for f in fs
             if os.path.exists(os.path.join(p, f)))
    print(f"  {tr}: {n} 个文件, {sz/1048576:.1f} MB（可回溯）")
else:
    print("  未创建")

print("\n=== 磁盘真题/词汇书仍在？ ===")
for pat in ["红宝书", "词汇闪过", "真题"]:
    cnt = 0
    for root, dirs, files in os.walk(KB):
        if "_trash" in root:
            continue
        cnt += sum(1 for f in files if pat in f)
    print(f"  含'{pat}'文件数: {cnt}")
