import sqlite3
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')


def c(q):
    return con.execute(q).fetchone()[0]


V = "coalesce(is_junk,0)=0"
PPT = ("source like '%课件%' or source like '%讲义%' or source like '%教案%' "
       "or source like '%笔记%' or source like '%辅导%' or source like '%培训%' "
       "or source like '%复习%' or source like '%精讲%' or source like '%考点%'")
REAL = ("source like '%真题%' or source like '%试题%' or source like '%题库%' "
        "or source like '%试卷%' or source like '%联考%'")

print('=== 可见题来源性质拆分 ===')
ppt = c(f"select count(*) from quiz_questions where {V} and ({PPT})")
real = c(f"select count(*) from quiz_questions where {V} and ({REAL})")
print('  讲义/课件类:', ppt)
print('  真题/试题类:', real)
print('  其它:', 8852 - ppt - real)

print()
print('=== 讲义类质量 ===')
r = con.execute(f"select count(*), sum(case when answer is not null and trim(answer)<>'' then 1 else 0 end) "
                f"from quiz_questions where {V} and ({PPT})").fetchone()
print(f'  共{r[0]} 有答案{r[1]} ({100 * r[1] // max(r[0], 1)}%)')

print()
print('=== 真题类质量 ===')
r = con.execute(f"select count(*), sum(case when answer is not null and trim(answer)<>'' then 1 else 0 end) "
                f"from quiz_questions where {V} and ({REAL})").fetchone()
print(f'  共{r[0]} 有答案{r[1]} ({100 * r[1] // max(r[0], 1)}%)')

print()
print('=== 讲义类样本（确认是否本就是知识点文本）===')
for row in con.execute(f"select id, subject, substr(content,1,70) from quiz_questions "
                       f"where {V} and ({PPT}) and question_type='essay' order by random() limit 8"):
    print(f'  #{row[0]} [{row[1]}] {row[2]}'.replace('\n', ' '))
