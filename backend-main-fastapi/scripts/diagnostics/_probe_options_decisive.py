# -*- coding: utf-8 -*-
"""决定性复测：options 单元格的 sqlite 类型 + 形状分布（把两次矛盾的数字钉死）。"""
import json
import os
import sqlite3
from collections import Counter

DB = os.path.join("D:", os.sep, "平台", "database", "kaoyan.db")
before = os.stat(DB)
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

print("列声明类型:", [(r[1], r[2]) for r in cur.execute("PRAGMA table_info(quiz_questions)") if r[1] == "options"])
rows = cur.execute("SELECT id, options FROM quiz_questions").fetchall()
print("总行数:", len(rows))

typecnt = Counter()
shape = Counter()
bad = []
for qid, opts in rows:
    typecnt[type(opts).__name__] += 1
    if opts is None:
        shape["NULL"] += 1
        continue
    if isinstance(opts, (bytes, bytearray)):
        try:
            opts = opts.decode("utf-8")
            shape["bytes→解码后参与统计"] += 0
        except Exception:
            shape["bytes 解不开"] += 1
            continue
    if isinstance(opts, str) and not opts.strip():
        shape["空串"] += 1
        continue
    try:
        p = json.loads(opts)
    except Exception as e:
        shape["非法JSON"] += 1
        if len(bad) < 5:
            bad.append((qid, str(opts)[:80], str(e)[:60]))
        continue
    if isinstance(p, list):
        shape[f"list(len={len(p)})"] += 1
    elif isinstance(p, dict):
        shape["dict"] += 1
    else:
        shape[f"标量 {type(p).__name__}"] += 1

print("\ncell python 类型分布:", dict(typecnt))
print("\n形状分布:")
for k, v in shape.most_common(16):
    print(f"  {k:<20} {v:>6}")
n_list = sum(v for k, v in shape.items() if k.startswith("list("))
print(f"\n合计 list 形态 {n_list} / {len(rows)}")
if bad:
    print("非法 JSON 样例:", bad)

# 抽样看 list(1)/list(2) 到底是数据坏还是切分坏
print("\n=== len=1 的样例（判断题？还是切分丢选项？）===")
for qid, opts in rows[:4000]:
    try:
        p = json.loads(opts) if isinstance(opts, str) else None
    except Exception:
        continue
    if isinstance(p, list) and len(p) == 1:
        print("  id", qid, "->", repr(p[0])[:110])
        break
print("=== len=2 的样例 ===")
for qid, opts in rows:
    try:
        p = json.loads(opts) if isinstance(opts, str) else None
    except Exception:
        continue
    if isinstance(p, list) and len(p) == 2:
        print("  id", qid, "->", [str(x)[:40] for x in p])
        break

after = os.stat(DB)
assert (after.st_mtime, after.st_size) == (before.st_mtime, before.st_size), "探针动了生产库！"
print("\n[guard] 生产库未变:", before.st_size)
