import sqlite3
import re
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')

print('=== 【草稿】污染分布 ===')
print('answer 含【草稿】:', con.execute("select count(*) from quiz_questions where answer like '%【草稿】%'").fetchone()[0])
print('analysis 含【草稿】:', con.execute("select count(*) from quiz_questions where analysis like '%【草稿】%'").fetchone()[0])
print('content 含【草稿】:', con.execute("select count(*) from quiz_questions where content like '%【草稿】%'").fetchone()[0])
print('任意字段含【草稿】:', con.execute("select count(*) from quiz_questions where answer like '%【草稿】%' or analysis like '%【草稿】%' or content like '%【草稿】%'").fetchone()[0])

print()
print('=== answer 形态分析 ===')
rows = con.execute("select id, answer from quiz_questions where answer like '%【草稿】%' limit 3000").fetchall()
pats = {}
for i, a in rows:
    a = a or ''
    if '查看答案' in a:
        pats['含"查看答案"'] = pats.get('含"查看答案"', 0) + 1
    m = re.match(r'^【草稿】\s*([A-D]+)', a)
    if m:
        pats['【草稿】+字母'] = pats.get('【草稿】+字母', 0) + 1
for k, v in pats.items():
    print(' ', k, v)

print()
print('=== 样本（answer 清洗前 → 清洗后）===')
for i, a in rows[:15]:
    cleaned = re.sub(r'^【草稿】(解析)?\s*', '', a or '')
    cleaned = cleaned.replace('查看答案', '')
    print(f'  #{i}')
    print(f'     before: {a[:90]!r}')
    print(f'     after : {cleaned[:90]!r}')

print()
print('=== analysis 含【草稿解析】样本 ===')
for i, a in con.execute("select id, analysis from quiz_questions where analysis like '%【草稿】%' limit 3"):
    print(f'  #{i}: {str(a)[:150]}')
