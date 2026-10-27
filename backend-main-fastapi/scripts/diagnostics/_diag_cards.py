import sqlite3
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')

print('=== flashcards 总览 ===')
print('总数:', con.execute("select count(*) from flashcards").fetchone()[0])

print()
print('=== 污染类型 ===')
print('front 过短(<=2字):', con.execute("select count(*) from flashcards where length(trim(coalesce(front,'')))<=2").fetchone()[0])
print('front 纯数字:', con.execute("select count(*) from flashcards where front glob '[0-9]*' and trim(front) not glob '*[^0-9]*'").fetchone()[0])
print('front 含【考纲要求】:', con.execute("select count(*) from flashcards where front like '%考纲要求%'").fetchone()[0])
print('back 含【考纲要求】:', con.execute("select count(*) from flashcards where back like '%考纲要求%'").fetchone()[0])
print('front==back:', con.execute("select count(*) from flashcards where trim(coalesce(front,''))=trim(coalesce(back,''))").fetchone()[0])
print('无 knowledge_point_id:', con.execute("select count(*) from flashcards where knowledge_point_id is null").fetchone()[0])

print()
print('=== 劣质样本 ===')
for r in con.execute("select id, front, back, knowledge_point_id from flashcards where length(trim(coalesce(front,'')))<=2 limit 10"):
    print(f'  #{r[0]} front={r[1]!r} back={r[2]!r} kp={r[3]}')

print()
print('=== 含【考纲要求】样本（back 是元数据不是释义）===')
for r in con.execute("select id, front, back from flashcards where back like '%考纲要求%' limit 8"):
    print(f'  #{r[0]} front={r[1]!r}')
    print(f'      back={r[2][:100]!r}')

print()
print('=== 正常样本 ===')
for r in con.execute("select id, front, back from flashcards where length(trim(coalesce(front,'')))>4 and back not like '%考纲要求%' limit 5"):
    print(f'  #{r[0]} front={r[1][:50]!r}')
    print(f'      back={r[2][:80]!r}')
