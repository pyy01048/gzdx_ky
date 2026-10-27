import sqlite3
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')
V = "coalesce(is_junk,0)=0"

# 验证：无答案题的下一条记录是否是"解："答案体
rows = con.execute(f"""select id, content, answer, source from quiz_questions
 where {V} order by id""").fetchall()
by_id = {r[0]: r for r in rows}
ids = sorted(by_id)

ANS_START = ('解：', '答：', '答案', '解析', '解:', '答:')
noans_ids = [i for i in ids if not (by_id[i][2] and by_id[i][2].strip())]
print('无答案题:', len(noans_ids))

# 统计：无答案题的 id+1..+3 是答案体的比例
pair_1 = pair_3 = 0
for i in noans_ids:
    for k in (1, 2, 3):
        nxt = by_id.get(i + k)
        if nxt and any(nxt[1].strip().startswith(p) for p in ANS_START):
            if k == 1:
                pair_1 += 1
            pair_3 += 1
            break
print('紧邻下1条是答案体:', pair_1)
print('下1-3条内有答案体:', pair_3)

# 看一个具体例子
print()
print('=== 示例：id 415-432 连续记录 ===')
for i in range(415, 433):
    r = by_id.get(i)
    if r:
        ans = 'Y' if (r[2] and r[2].strip()) else 'n'
        print(f'  #{i} ans={ans} | {r[1][:75]}'.replace('\n', ' '))
