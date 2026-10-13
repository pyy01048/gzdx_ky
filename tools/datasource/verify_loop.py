"""端到端验证「刷题 → 答题 → 错题 → 挂知识点 → 埋点」闭环。

必须是真实调用：选一道真实题（有答案、有知识点链路），提交错误答案，
然后核对 error_records / error_knowledge_links / study_events 是否真的写入。
"""
import json
import sqlite3
import urllib.request

API = "http://127.0.0.1:8000"
DB = r"D:\平台\database\kaoyan.db"


def post(path, body):
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


con = sqlite3.connect(DB, timeout=60)
con.execute("PRAGMA busy_timeout=60000")


def snap():
    return {
        "errors": con.execute("select count(*) from error_records").fetchone()[0],
        "links": con.execute("select count(*) from error_knowledge_links").fetchone()[0],
        "events": con.execute("select count(*) from study_events").fetchone()[0],
        "answers": con.execute("select count(*) from answer_records").fetchone()[0],
    }


# 选一道：有答案 + 有知识点链路 的题
q = con.execute("""
    select q.id, q.subject, q.question_type, q.answer, length(q.content)
    from quiz_questions q
    join question_knowledge_links l on l.question_id = q.id
    where coalesce(q.is_junk,0)=0 and q.answer is not null and trim(q.answer)<>''
      and q.quality in ('A','B')
    limit 1
""").fetchone()
if not q:
    print("找不到候选题")
    raise SystemExit(1)

qid, subj, qtype, ans, clen = q
print(f"选用题目 #{qid} [{subj}/{qtype}] 正确答案={ans!r} 题干{clen}字")
kp = con.execute("select knowledge_point_id from question_knowledge_links "
                 "where question_id=?", (qid,)).fetchall()
print(f"该题的知识点链路: {kp}")

before = snap()
print("\n提交前:", before)

# 构造一个必然错误的答案
wrong = "___WRONG_FOR_TEST___"
print(f"\n提交错误答案 {wrong!r} ...")
res = post("/api/quiz/submit", {
    "question_id": qid, "my_answer": wrong,
    "mode": "practice", "cost_seconds": 9,
})
print("响应:", json.dumps(res, ensure_ascii=False))

after = snap()
print("\n提交后:", after)
print()
print("=== 差异 ===")
for k in before:
    d = after[k] - before[k]
    mark = "✅" if d > 0 else "—"
    print(f"  {k}: {before[k]} → {after[k]}  (+{d}) {mark}")

# 检查新错题的关联情况
er = con.execute("select id, question_id, error_reason from error_records "
                 "order by id desc limit 1").fetchone()
if er:
    links = con.execute("select knowledge_point_id, relevance, source "
                        "from error_knowledge_links where error_id=?", (er[0],)).fetchall()
    print(f"\n最新错题 #{er[0]} (question#{er[1]}, {er[2]})")
    print(f"  关联知识点: {links if links else '无'}")

ev = con.execute("select id, event_type, subject, is_correct, duration_seconds, occurred_at "
                 "from study_events order by id desc limit 1").fetchone()
print(f"\n最新埋点: {ev}")
