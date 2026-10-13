import sqlite3
import re
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')
V = "coalesce(is_junk,0)=0"
rows = con.execute(f"select id, content, answer, source, question_type, options from quiz_questions where {V}").fetchall()

# 答案体特征：以 答：/解：/答案/参考 开头，或含"故/因此/所以...选"
ANS_START = ('答：', '解：', '答案', '参考答', '解析', '解:', '答:')
ANS_MID = ('故选', '故答案', '因此答案', '所以答案', '答案为', '答案：')

n_ans_start = 0
n_ans_mid = 0
n_choice_noopt = 0
samples = []
for i, c, a, s, t, o in rows:
    c = c or ''
    cs = c.strip()
    if any(k in cs[:8] for k in ANS_START):
        n_ans_start += 1
        if len(samples) < 12:
            samples.append((i, cs[:90].replace('\n', ' ')))
    if any(k in c for k in ANS_MID):
        n_ans_mid += 1
    if t in ('single', 'multiple', 'choice') and not o:
        n_choice_noopt += 1

print('题干以 答/解/答案 开头（答案体）:', n_ans_start)
print('题干含"故选/答案为"等答案信号:', n_ans_mid)
print('选择题但无选项:', n_choice_noopt)
print()
print('=== 答案体样本 ===')
for s in samples:
    print(f'  #{s[0]} | {s[1]}')

print()
print('=== 重复题检测（content 前60字相同）===')
dup = con.execute(f"""select substr(content,1,60) as c, count(*) n from quiz_questions
 where {V} group by c having n>1 order by n desc limit 10""").fetchall()
tot_dup = con.execute(f"""select sum(n) from (select count(*) n from quiz_questions
 where {V} group by substr(content,1,60) having n>1)""").fetchone()[0]
print('  重复组数:', len(dup), ' 涉及题目总数:', tot_dup)
for d in dup[:5]:
    print(f'    ×{d[1]} | {d[0][:60]}'.replace('\n', ' '))
