# -*- coding: utf-8 -*-
"""检查两个'打卡'命中的高价值文件是否已入库，决定是否从删除清单剔除。"""
from pathlib import Path
import sqlite3, sys, os
sys.stdout.reconfigure(encoding="utf-8")

# 路径按本文件位置推导（P0-B2：拆除机器专属绝对路径绑定）
_REPO = Path(__file__).resolve().parents[2]
DB = str(_REPO / "database" / "kaoyan.db")
TARGETS = ["红宝书", "艾宾浩斯", "词汇闪过", "六级高频词打卡海报"]

c = sqlite3.connect(DB).cursor()

for t in TARGETS:
    rows = c.execute(
        "SELECT id, file_name, length(content), subject FROM documents "
        "WHERE file_name LIKE ?", (f"%{t}%",)).fetchall()
    print(f"=== {t} ===")
    if not rows:
        print("  未入库")
    for r in rows:
        print(f"  #{r[0]} {r[1]} | 正文字符={r[2]} | 学科={r[3]}")
    print()

# 词汇来源统计：单词表的知识来自哪
try:
    cols = [x[1] for x in c.execute("PRAGMA table_info(words)").fetchall()]
    print("words 表字段:", cols)
except Exception as e:
    print("words 表读取失败:", e)

# 反查：有没有 chunk 来自这些文件
for t in ["红宝书", "艾宾浩斯", "词汇闪过"]:
    n = c.execute(
        "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id IN "
        "(SELECT id FROM documents WHERE file_name LIKE ?)", (f"%{t}%",)).fetchone()[0]
    print(f"chunk 来自 {t}: {n}")
