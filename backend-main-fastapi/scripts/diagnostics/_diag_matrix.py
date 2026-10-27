import sqlite3
con = sqlite3.connect(r'D:\平台\database\kaoyan.db')
V = "coalesce(is_junk,0)=0"

# 来源分类
PPT_SRC = ("source like '%课件%' or source like '%讲义%' or source like '%教案%' "
           "or source like '%培训%' or source like '%辅导%' or source like '%精讲%'")
REAL_SRC = ("source like '%真题%' or source like '%试题%' or source like '%试卷%' "
            "or source like '%联考%' or source like '%题库%'")
Q_MARK = ["？", "?", "____", "（ ）", "( )", "求：", "试：", "简述", "设计",
          "计算", "画出", "写出", "说明", "选择", "判断", "填空", "已知", "分析"]

qcond = " or ".join([f"content like '%{k}%'" for k in Q_MARK])
ans = "answer is not null and trim(answer)<>''"

print('=== 交叉矩阵（可见题）===')
for label, cond in [
    ('讲义类 + 有答案', f"{V} and ({PPT_SRC}) and {ans}"),
    ('讲义类 + 无答案 + 像题', f"{V} and ({PPT_SRC}) and not ({ans}) and ({qcond})"),
    ('讲义类 + 无答案 + 不像题', f"{V} and ({PPT_SRC}) and not ({ans}) and not ({qcond})"),
    ('真题类 + 有答案', f"{V} and ({REAL_SRC}) and {ans}"),
    ('真题类 + 无答案', f"{V} and ({REAL_SRC}) and not ({ans})"),
]:
    n = con.execute(f"select count(*) from quiz_questions where {cond}").fetchone()[0]
    print(f'  {label}: {n}')

print()
print('=== 讲义类 + 无答案 + 不像题 的样本（这些是知识点正文）===')
for r in con.execute(f"""select id, substr(content,1,80), source from quiz_questions
 where {V} and ({PPT_SRC}) and not ({ans}) and not ({qcond}) limit 10"""):
    print(f'  #{r[0]} | {r[1]}'.replace('\n', ' '))
