import sqlite3
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')
V = "coalesce(is_junk,0)=0"

print('=== is_available 分布 ===')
for r in con.execute("select is_available, count(*) from quiz_questions group by is_available"):
    print('  ', r)

print()
print('=== quality 分布 ===')
for r in con.execute("select quality, count(*) from quiz_questions group by quality order by 2 desc limit 10"):
    print('  ', r)

print()
print('=== confidence 分布 ===')
for r in con.execute("select case when confidence is null then 'NULL' when confidence>=0.8 then '>=0.8' when confidence>=0.5 then '0.5-0.8' else '<0.5' end, count(*) from quiz_questions group by 1"):
    print('  ', r)

print()
print('=== 有答案题 的题型分布（真正的可刷题）===')
for r in con.execute(f"select question_type, count(*) from quiz_questions where {V} and answer is not null and trim(answer)<>'' group by question_type order by 2 desc"):
    print('  ', r)

print()
print('=== 无答案题 的题型分布 ===')
for r in con.execute(f"select question_type, count(*) from quiz_questions where {V} and (answer is null or trim(answer)='') group by question_type order by 2 desc"):
    print('  ', r)

print()
print('=== 严格可用题（有答案+有题干+非乱码+选择题有选项）按学科 ===')
for r in con.execute(f"""select subject, count(*) from quiz_questions where {V}
 and trim(coalesce(content,''))!='' and length(trim(content))>=15
 and answer is not null and trim(answer)!=''
 and content not glob '*\ufffd*'
 and not (question_type in ('single','multiple','choice') and options is null)
 group by subject order by 2 desc"""):
    print('  ', r)
