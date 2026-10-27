import sqlite3
import re
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')
V = "coalesce(is_junk,0)=0"

rows = con.execute(f"select id, content, answer, source, question_type from quiz_questions where {V}").fetchall()
print('可见题', len(rows))

# PPT/讲义残留特征
PPT_ART = ['返回', '下页', '上页', '内容盛要', '内容提要', '本节', '目录', '第 页', '共 页',
           '点击', '放映', '幻灯片', '第页']
# 真题目特征
Q_MARK = ['？', '?', '____', '（ ）', '( )', '求：', '试：', '简述', '设计', '分析',
          '计算', '画', '写出', '说明', '选择', '判断', '填空', '已知']


def has_ppt(c):
    return sum(1 for k in PPT_ART if k in c) >= 1


def q_score(c):
    return sum(1 for k in Q_MARK if k in c)


has_ans = lambda a: a is not None and a.strip() != ''

n_ppt = n_noans = n_both = 0
samples_ppt_q = []
for i, c, a, s, t in rows:
    c = c or ''
    p = has_ppt(c)
    q = q_score(c) > 0
    if p:
        n_ppt += 1
        if q and len(samples_ppt_q) < 8:
            samples_ppt_q.append((i, c[:80].replace('\n', ' '), s))
    if not has_ans(a):
        n_noans += 1

print('含PPT残留:', n_ppt)
print('无答案:', n_noans)
print()
print('=== 含PPT残留但同时像题的（需谨慎判断）===')
for s in samples_ppt_q:
    print(f'  #{s[0]} | {s[1]}')

print()
print('=== 无答案 且 含PPT残留 ===')
n = con.execute(f"""select count(*) from quiz_questions where {V}
 and (answer is null or trim(answer)='')
 and (content like '%返回%' or content like '%下页%' or content like '%上页%' or content like '%内容盛要%')""").fetchone()[0]
print('  ', n)

print()
print('=== 真题来源 但无答案（真题目缺答案，应保留但标注）===')
n2 = con.execute(f"""select count(*) from quiz_questions where {V}
 and (answer is null or trim(answer)='')
 and (source like '%真题%' or source like '%试题%' or source like '%试卷%' or source like '%联考%')""").fetchone()[0]
print('  ', n2)
