import sqlite3
import sys
sys.path.insert(0, r'D:\平台\backend-main-fastapi\scripts')
from quiz_quality_gate import classify

con = sqlite3.connect(r'D:\平台\database\kaoyan.db')
rows = con.execute("select id, content, answer, source, question_type, options from quiz_questions").fetchall()

groups = {'A': [], 'B': [], 'C': [], 'JUNK': []}
for r in rows:
    g, why = classify(r)
    groups[g].append((r, why))

import random
random.seed(7)
for g in ('A', 'B', 'C', 'JUNK'):
    print(f'=== {g} 类抽样（{len(groups[g])}）===')
    for r, why in random.sample(groups[g], min(6, len(groups[g]))):
        c = (r[1] or '').replace('\n', ' ')[:95]
        ans = 'Y' if (r[2] and str(r[2]).strip()) else 'n'
        print(f'  #{r[0]} ans={ans} [{why}] {c}')
    print()
