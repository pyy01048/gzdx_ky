# -*- coding: utf-8 -*-
"""OCR 质量评估：量化扫描件识别噪声，决定要不要做清洗。

背景：扫描件重启 OCR 后，检索结果里出现了明显噪声 ——
    "三极管P = SO, U88 =- 0.2V"   应为  "三极管β=50, U_BE=-0.2V"
    "共射放大电路巾"              应为  "共射放大电路中"
    "f司"                        应为  "问"

噪声直接影响 RAG 检索质量与 AI 理解，所以先量化再决定处理方式。
"""
import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")
db = sqlite3.connect(r"data\kaoyan.db")

# 常见 OCR 形近字误识（中文）
CJK_CONFUSION = {
    "巾": "中", "司": "问", "曰": "日", "己": "已", "未": "末",
    "人": "入", "力": "刀", "干": "千", "土": "士", "天": "夭",
}
# 拉丁/希腊字母误识（工程符号）
LATIN_CONFUSION = [
    (r"\bSO\b", "50"), (r"\bS0\b", "50"), (r"\bO\b(?=\s*[=＝])", "0"),
    (r"U88", "U_BE"), (r"U8B", "U_BE"), (r"Ucc(?![a-z])", "U_CC"),
    (r"\bP\s*=\s*(?=\d)", "β="),
]
# 明显乱码标记
GARBLE = re.compile(r"[�□◻]|\\u[0-9a-fA-F]{4}|[^\x00-\x7f\u3000-\u9fff\uff00-\uffef"
                    r"\u2000-\u206f\u2190-\u21ff\u2200-\u22ff\s]")

rows = db.execute(
    "select id, file_name, content from documents where ocr_used=1"
).fetchall()

print(f"OCR 文档 {len(rows)} 篇\n")

total_len = 0
garble_chars = 0
latin_suspect = 0
samples = []

for did, name, content in rows:
    if not content:
        continue
    total_len += len(content)
    g = len(GARBLE.findall(content))
    garble_chars += g
    lat = 0
    for pat, _ in LATIN_CONFUSION:
        lat += len(re.findall(pat, content))
    latin_suspect += lat
    ratio = g / max(len(content), 1)
    if ratio > 0.001 or lat > 3:
        samples.append((ratio, lat, did, name, content))

print(f"  总字符数          {total_len:,}")
print(f"  乱码/异体字符      {garble_chars:,}  ({garble_chars/max(total_len,1)*100:.3f}%)")
print(f"  工程符号疑似误识    {latin_suspect:,}")
print()

samples.sort(reverse=True)
print(f"  噪声最重的 {min(8, len(samples))} 篇：")
for ratio, lat, did, name, content in samples[:8]:
    print(f"    id={did:<5} 乱码率 {ratio*100:.2f}%  符号误识 {lat:<3} {str(name)[:44]}")

print()
print("=== 典型噪声片段 ===")
for ratio, lat, did, name, content in samples[:3]:
    # 找出含噪声的句子
    for sent in re.split(r"[。\n]", content):
        if GARBLE.search(sent) or any(re.search(p, sent) for p, _ in LATIN_CONFUSION):
            s = sent.strip()[:110]
            if s:
                print(f"    · {s}")
                break

db.close()
