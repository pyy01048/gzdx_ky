# -*- coding: utf-8 -*-
"""只读盘点：低价值文档（答题卡/打卡/计划表等）现状。不做任何删除。"""
import os, sys, sqlite3, json

DB = r"D:\平台\database\kaoyan.db"
KB = r"D:\平台\knowledge_base"

LOW_KW = ["答题卡", "答题纸", "打卡", "签到", "课程表", "进度表", "计划表",
          "倒计时", "打印店", "打印", "空白模板", "填涂", "机读卡", "封面", "目录"]

db = sqlite3.connect(DB)
c = db.cursor()
out = {}

# 1. documents 表里的低价值文档
cols = [r[1] for r in c.execute("PRAGMA table_info(documents)")]
out["documents_columns"] = cols
mcol = next((x for x in ("char_count", "char_total", "content_length") if x in cols), "id")
rows = c.execute(
    f"SELECT id, file_name, {mcol} FROM documents WHERE " +
    " OR ".join(["file_name LIKE ?"] * len(LOW_KW)),
    [f"%{k}%" for k in LOW_KW]).fetchall()
out["low_value_documents"] = rows

# 2. 磁盘上的低价值文件
low_files = []
for root, dirs, files in os.walk(KB):
    for fn in files:
        if any(k in fn for k in LOW_KW):
            p = os.path.join(root, fn)
            try:
                sz = os.path.getsize(p)
            except OSError:
                sz = 0
            low_files.append({"path": os.path.relpath(p, KB), "size": sz})
out["low_value_files"] = low_files
out["low_value_files_total_size"] = sum(f["size"] for f in low_files)

# 3. 空表 / 打卡类表
tabs = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
suspicious = {}
for t in tabs:
    if any(k in t.lower() for k in ["checkin", "check_in", "sign", "early_bird",
                                     "punch", "clock", "streak", "milestone",
                                     "plan", "todo", "task"]):
        try:
            cnt = c.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        except Exception as e:
            cnt = f"ERR {e}"
        suspicious[t] = cnt
out["checkin_like_tables"] = suspicious

# 4. 真库核心规模（用于清理前后对比）
core = {}
for t in ["documents", "knowledge_chunks", "quiz_questions", "knowledge_points", "words", "flashcards"]:
    if t in tabs:
        core[t] = c.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
out["core_counts"] = core

print(json.dumps(out, ensure_ascii=False, indent=2))
