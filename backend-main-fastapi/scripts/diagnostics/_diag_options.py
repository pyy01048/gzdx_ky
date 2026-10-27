import sqlite3
import re
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')
q = ("question_type in ('single','multiple','choice') and (options is null "
     "or options='null' or options='[]' or trim(coalesce(options,''))='')")
rows = con.execute(f"select id, content, question_type, quality from quiz_questions where {q}").fetchall()
print('待处理', len(rows))

# 内联选项模式：A. xxx B. xxx C. xxx D. xxx  （A/B/C/D 后跟内容）
INLINE = re.compile(r"[（(]?\s*[Aa][\.、:：\)）]?\s*\S+.*?[Bb][\.、:：\)）]\s*\S+.*?[Cc][\.、:：\)）]\s*\S+.*?[Dd][\.、:：\)）]\s*\S+")

n_inline = 0
n_fill = 0
n_other = 0
samples_inline = []
samples_fill = []
for i, c, t, ql in rows:
    c = c or ''
    if INLINE.search(c):
        n_inline += 1
        if len(samples_inline) < 5:
            samples_inline.append((i, c[:110].replace('\n', ' ')))
    elif ('____' in c or '（ ）' in c or '( )' in c or '（  ）' in c):
        n_fill += 1
        if len(samples_fill) < 5:
            samples_fill.append((i, c[:110].replace('\n', ' ')))
    else:
        n_other += 1

print(f'含内联A/B/C/D选项: {n_inline}')
print(f'实为填空题(有空格/括号): {n_fill}')
print(f'其它: {n_other}')
print()
print('=== 内联选项样本 ===')
for s in samples_inline:
    print(f'  #{s[0]} | {s[1]}')
print()
print('=== 填空样本 ===')
for s in samples_fill:
    print(f'  #{s[0]} | {s[1]}')
