import sqlite3
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')

print('=== 1. seed 伪题（id<=7，AI凭空生成）===')
for r in con.execute("select id,subject,substr(content,1,60),source from quiz_questions where id<=7"):
    print(f'  #{r[0]} [{r[1]}] src={r[3]} | {r[2]}')

print()
print('=== 2. flashcard 污染 ===')
print('  front纯数字:', con.execute("select count(*) from flashcards where front glob '[0-9]*' and length(trim(front))<=3").fetchone()[0])
for r in con.execute("select id,front,back from flashcards where length(trim(front))<=2 limit 5"):
    print(f'    #{r[0]} front={r[1]!r} back={r[2]!r}')

print()
print('=== 3. study_events（埋点）===')
print('  行数:', con.execute("select count(*) from study_events").fetchone()[0])
print('  列:', [r[1] for r in con.execute("PRAGMA table_info(study_events)")])

print()
print('=== 4. papers / paper_questions ===')
print('  papers:', con.execute("select count(*) from papers").fetchone()[0])
print('  paper_questions:', con.execute("select count(*) from paper_questions").fetchone()[0])

print()
print('=== 5. 题目知识点关联 ===')
print('  quiz_questions.knowledge_point 非空:', con.execute("select count(*) from quiz_questions where knowledge_point is not null and trim(knowledge_point)<>''").fetchone()[0])
try:
    print('  question_knowledge_link:', con.execute("select count(*) from question_knowledge_link").fetchone()[0])
except Exception as e:
    print('  question_knowledge_link: 无表')

print()
print('=== 6. 错题表 ===')
try:
    print('  error_records:', con.execute("select count(*) from error_records").fetchone()[0])
    for r in con.execute("select status,count(*) from error_records group by status"):
        print('    ', r)
except Exception as e:
    print('  error_records: 无表', e)

print()
print('=== 7. 单词 deck ===')
try:
    for r in con.execute("select deck_id,count(*) from words group by deck_id"):
        print('    deck', r[0], ':', r[1])
except Exception as e:
    print(e)
