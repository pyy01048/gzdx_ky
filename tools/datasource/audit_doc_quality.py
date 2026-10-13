"""知识库文档正文质量审计（只读）。

目的：找出"识别度"问题，为改进 OCR/解析质量提供依据。
检查项：
  1. 正文过短（可能解析失败）
  2. 含替换符  (OCR 乱码)
  3. 控制字符残留
  4. 图片引用残留（IMA 抓取内容里的 ![]() ）
  5. 空/近空正文
  6. 大量非中文非英文符号（公式崩坏）
  7. 重复行（PPT 讲义常见）
"""
import re
import sqlite3
from collections import Counter

DB = r"D:\平台\database\kaoyan.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

rows = con.execute(
    "SELECT id, file_name, file_type, subject, subject_source, ocr_used, content "
    "FROM documents"
).fetchall()
print(f"文档总数 {len(rows)}")

stat = Counter()
samples = {}
for did, fn, ft, subj, src, ocr, content in rows:
    c = content or ""
    n = len(c)
    if n < 50:
        stat["1_近空"] += 1
        samples.setdefault("1_近空", []).append((did, fn, n))
    if "\ufffd" in c:
        stat["2_含替换符"] += 1
        samples.setdefault("2_含替换符", []).append((did, fn, c.count("\ufffd")))
    ctrl = sum(1 for ch in c[:5000] if ord(ch) < 32 and ch not in "\n\t\r")
    if ctrl > 5:
        stat["3_控制字符"] += 1
        samples.setdefault("3_控制字符", []).append((did, fn, ctrl))
    imgref = c.count("![")
    if imgref >= 3:
        stat["4_图片引用残留"] += 1
        samples.setdefault("4_图片引用残留", []).append((did, fn, imgref))
    if n >= 50:
        cjk = len(re.findall(r"[\u4e00-\u9fa5]", c))
        ratio = cjk / n
        if ratio < 0.05 and not re.search(r"[a-zA-Z]{20,}", c):
            stat["5_非中英符号为主"] += 1
            samples.setdefault("5_非中英符号为主", []).append((did, fn, round(ratio, 3)))
        # 重复行
        lines = [l.strip() for l in c.split("\n") if len(l.strip()) > 8]
        if len(lines) > 20:
            uniq = len(set(lines))
            if uniq / len(lines) < 0.5:
                stat["6_重复行多"] += 1
                samples.setdefault("6_重复行多", []).append((did, fn, f"{uniq}/{len(lines)}"))

print()
for k in sorted(stat):
    print(f"{k}: {stat[k]}")
    for s in samples.get(k, [])[:4]:
        print("    ", s)

print()
print("=== 按 subject_source 的质量 ===")
for src in ("original", "ima"):
    sub = [r for r in rows if r[4] == src]
    bad = sum(1 for r in sub if len(r[6] or "") < 50)
    fffd = sum(1 for r in sub if "\ufffd" in (r[6] or ""))
    print(f"  {src}: 共{len(sub)} 近空{bad} 含替换符{fffd}")

print()
print("=== ocr_used 分布 × 平均正文字数 ===")
for k, v in Counter(r[5] for r in rows).items():
    lens = [len(r[6] or "") for r in rows if r[5] == k]
    print(f"  ocr_used={k}: {v} 篇, 平均 {sum(lens)//max(len(lens),1)} 字")
