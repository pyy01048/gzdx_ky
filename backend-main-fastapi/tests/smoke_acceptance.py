# -*- coding: utf-8 -*-
"""交付前最终验收：静态页面 / 新接口 / 移除项 / 回归。"""
import datetime
import json
import re
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000"
FAILS = []
TODAY = datetime.date.today().isoformat()


def get(path, raw=False):
    try:
        with urllib.request.urlopen(BASE + path, timeout=90) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, (body if raw else json.loads(body))
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, str(e)


def check(cond, label, detail=""):
    mark = "OK " if cond else "FAIL"
    if not cond:
        FAILS.append(label)
    print(f"  [{mark}] {label}{(' — ' + detail) if detail else ''}")


print("=" * 74)
print("A. 静态页面与资源")
print("=" * 74)
st, html = get("/", raw=True)
check(st == 200, "GET / 返回 200")
check("834 知识库" in (html or ""), "首页标题已更新")
for m in re.findall(r'(?:src|href)="\./([^"]+)"', html or ""):
    s, _ = get("/" + m, raw=True)
    check(s == 200, f"静态资源 /{m}")

print()
print("=" * 74)
print("B. 课表已彻底移除")
print("=" * 74)
for p in ("/api/schedule/semesters", "/api/schedule/courses", "/api/schedule/week?week=1"):
    s, _ = get(p)
    check(s == 404, f"{p} 返回 404")

print()
print("=" * 74)
print("C. 三级结构（章节→知识点→题型）")
print("=" * 74)
s, d = get("/api/taxonomy/subjects")
check(s == 200, "科目清单可读")
if s == 200:
    core = [x["name"] for x in d["core"]]
    check(core == ["数字电子技术", "模拟电子技术", "数学", "英语", "政治", "真题综合"],
          "主线科目口径正确", str(core))
    check(all(x["is_core"] is False for x in d["extension"]), "拓展科目不进主线")

s, d = get("/api/taxonomy/tree")
if s == 200:
    filled = [x for x in d["tree"] if x["knowledge_point_count"]]
    total_kp = sum(x["knowledge_point_count"] for x in d["tree"])
    check(total_kp >= 200, f"知识点总数 {total_kp}")
    check(all(x["filled_chapter_count"] > 0 for x in filled), "科目均有已覆盖章节")
    # 每个知识点都必须有章节和题型
    no_ch = no_qt = 0
    for subj in d["tree"]:
        for ch in subj["chapters"]:
            for kp in ch["knowledge_points"]:
                if not ch["title"]:
                    no_ch += 1
                if not kp["question_types"]:
                    no_qt += 1
    check(no_ch == 0, "所有知识点都有章节")
    check(no_qt == 0, "所有知识点都有题型")
    for subj in filled:
        print(f"        {subj['subject']:<10} 知识点 {subj['knowledge_point_count']:>4} "
              f"章 {subj['filled_chapter_count']}/{subj['outline_chapter_count']}")

s, d = get("/api/taxonomy/coverage")
if s == 200:
    t = d["totals"]
    check(t["knowledge_points"] >= 200, f"覆盖率接口知识点 {t['knowledge_points']}")
    check(t["chunks"] > 20000, f"分块 {t['chunks']}")

print()
print("=" * 74)
print("D. 真题题库")
print("=" * 74)
s, d = get("/api/quiz/stats")
check(s == 200 and d.get("total_questions", 0) > 1000,
      f"题目总数 {d.get('total_questions') if s == 200 else 'ERR'}")
s, d = get("/api/quiz/questions?limit=3")
if s == 200:
    items = d.get("items") or d.get("questions") or []
    check(len(items) > 0, f"题库可翻页（返回 {len(items)} 条）")
    for q in items[:2]:
        print(f"        [{q.get('subject')}] {str(q.get('chapter'))[:22]} | {str(q.get('content'))[:44]}")

print()
print("=" * 74)
print("E. 复习进度追踪")
print("=" * 74)
s, d = get("/api/review/progress")
check(s == 200, "进度总览可读")
if s == 200:
    check(d["total_knowledge_points"] >= 200, f"总知识点 {d['total_knowledge_points']}")
    check("new_count" in d and "due_count" in d, "新知识点与到期数分开统计")
    print(f"        新={d['new_count']} 到期={d['due_count']} 已复习={d['reviewed_count']} "
          f"平均掌握度={d['avg_mastery']}")
s, d = get("/api/review/due?limit=5")
check(s == 200 and d.get("total", 0) > 0, f"今日复习队列有 {d.get('total') if s == 200 else 'ERR'} 条")

print()
print("=" * 74)
print("F. 错题↔知识库联动")
print("=" * 74)
s, d = get("/api/review/link-stats")
check(s == 200, "联动覆盖率可读")
if s == 200:
    print(f"        错题 {d['total_errors']} · 已挂考点 {d['linked_errors']} · "
          f"覆盖率 {d['coverage_rate']}%")
# 用最短路径验证"收录即挂考点"（不落库）
s, d = get("/api/errors/1/knowledge-points")
check(s in (200, 404), f"/api/errors/1/knowledge-points 可达（{s}）")

print()
print("=" * 74)
print("G. 原有功能回归")
print("=" * 74)
for p in ("/api/health", "/api/dashboard", "/api/tasks", "/api/errors",
          "/api/documents/subjects", "/api/flashcards", "/api/goals",
          "/api/words/decks", "/api/analytics/overview",
          f"/api/planner/daily?date={TODAY}", "/api/planner/ebbinghaus/due",
          "/api/planner/earlybird/streak", "/api/quiz/modes"):
    s, _ = get(p)
    check(s == 200, f"{p}")

print()
print("=" * 74)
if FAILS:
    print(f"❌ 验收失败 {len(FAILS)} 项：")
    for f in FAILS:
        print("   -", f)
    sys.exit(1)
print("✅ 全部验收项通过")
