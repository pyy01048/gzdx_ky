# -*- coding: utf-8 -*-
"""只读实测：① 水印/广告污染在库里的真实占比 ② 题目选项数量分布 ③ 题图残留。"""
import os
import re
import sqlite3
from collections import Counter

DB = os.path.join("D:", os.sep, "平台", "database", "kaoyan.db")
before = os.stat(DB)
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = conn.cursor()

# 来自外部方案的 WATERMARK_RULES，逐条实测命中量
RULES = {
    "淘宝/店铺/代购/打印": r"淘宝.{0,6}(店铺|店|代购|打印)",
    "考研工作室": r"光速考研工作室",
    "更多考研资料": r"更多考研资料",
    "QQ号": r"[qQ][qQ]?\s*[:：]?\s*\d{5,12}",
    "微信公众号": r"公众号[:：]?\s*\S{2,20}",
    "关注【】": r"关注【[^】]*】",
    "加群/扣扣": r"加[扣扣]?\s*\d{5,12}",
    "网址": r"(www\.|https?://)\S{6,}",
    "文库站名": r"(道客巴巴|百度文库|豆丁|原创力|小木虫)",
}
COMPILED = {k: re.compile(v) for k, v in RULES.items()}

print("=== ① documents.content 里的水印行 ===")
docs = cur.execute("SELECT id, subject, content FROM documents WHERE content IS NOT NULL").fetchall()
doc_hits = Counter()
line_hits = Counter()
dirty_docs = 0
total_lines = 0
for _id, _s, c in docs:
    hit_any = False
    for line in c.splitlines():
        if not line.strip():
            continue
        total_lines += 1
        for name, rx in COMPILED.items():
            if rx.search(line):
                line_hits[name] += 1
                doc_hits[name] += 0
                hit_any = True
    if hit_any:
        dirty_docs += 1
        for name, rx in COMPILED.items():
            if any(rx.search(l) for l in c.splitlines()):
                doc_hits[name] += 1
print(f"  扫描文档 {len(docs)} 篇，正文行数 {total_lines}")
print(f"  含至少一条水印/广告行的文档: {dirty_docs} 篇（{dirty_docs / max(1, len(docs)):.1%}）")
for name, n in line_hits.most_common():
    print(f"    {name:<18} 命中行 {n:>6}  涉及文档 {doc_hits[name]:>5} 篇")

print()
print("=== ② knowledge_chunks.text 里的水印行（检索侧真正会命中的）===")
ch = cur.execute("SELECT text FROM knowledge_chunks WHERE text IS NOT NULL").fetchall()
chunk_dirty = 0
chunk_line = Counter()
for (t,) in ch:
    hit = False
    for line in t.splitlines():
        for name, rx in COMPILED.items():
            if rx.search(line):
                chunk_line[name] += 1
                hit = True
    if hit:
        chunk_dirty += 1
print(f"  扫描块 {len(ch)}，含水印行的块 {chunk_dirty} 个（{chunk_dirty / max(1, len(ch)):.2%}）")
print("  行级分布:", dict(chunk_line.most_common(6)))

print()
print("=== ③ 题目选项数量分布（'怎么会有两三个 abcd 选项'）===")
import json
rows = cur.execute("SELECT id, options, question_type, content FROM quiz_questions").fetchall()
dist = Counter()
weird = []
for qid, opts, qt, content in rows:
    if not opts:
        dist["options 为空"] += 1
        continue
    try:
        parsed = json.loads(opts) if isinstance(opts, str) else opts
    except Exception:
        dist["非 JSON 存不下"] += 1
        continue
    if not isinstance(parsed, list):
        dist["不是数组"] += 1
        continue
    dist[f"{len(parsed)} 个选项"] += 1
    if isinstance(parsed, list) and len(parsed) < 4 and (content and re.search(r"[A-DＡ-Ｄ]\s*[\.、．]", content)):
        weird.append((qid, len(parsed), qt, (content or "")[:60]))
for k, v in sorted(dist.items(), key=lambda x: -x[1]):
    print(f"  {k:<16} {v:>6}")
print(f"  可疑：选项<4 但题干里出现 A./B./C./D. 的题 {len(weird)} 条，样例:")
for w in weird[:6]:
    print("   ", w)

print()
print("=== ④ 题干里混进图片的题（'题目识别的图'）===")
for pat, label in [(r"!\[[^\]]*\]\([^)]*\)", "markdown 图"), (r"<img", "html img"),
                   (r"微信图片_|Screenshot_|image_\d{4}", "截图文件名"), (r"data:image/", "base64 内嵌")]:
    rx = re.compile(pat)
    n = sum(1 for (c,) in cur.execute("SELECT content FROM quiz_questions") if c and rx.search(c))
    n2 = sum(1 for (c,) in cur.execute("SELECT content FROM documents WHERE content IS NOT NULL") if c and rx.search(c))
    print(f"  {label:<14} 题目 {n:>5} 条 / 文档 {n2:>5} 篇")
for tbl, col, pk in [("documents", "content", "id"), ("knowledge_chunks", "text", "id")]:
    rx = re.compile(r"!\[[^\]]*\]\([^)]*\)")
    n = cur.execute(f"SELECT count(*) FROM {tbl} WHERE {col} IS NOT NULL").fetchone()[0]
    hits = sum(1 for (c,) in cur.execute(f"SELECT {col} FROM {tbl} WHERE {col} IS NOT NULL") if c and rx.search(c))
    print(f"  markdown 图片语法（全量）: {tbl}.{col} {hits}/{n}")

after = os.stat(DB)
assert (after.st_mtime, after.st_size) == (before.st_mtime, before.st_size), "探针动了生产库！"
print("\n[guard] 生产库未变:", before.st_size)
conn.close()
