"""对比 knowledge_base 磁盘文件 与 documents 表，找出未入库的文件。

只读，不修改任何数据。
"""
import os
import sqlite3
from collections import Counter

KB = r"D:\平台\knowledge_base"
DB = r"D:\平台\database\kaoyan.db"
DOC_EXT = {".pdf", ".docx", ".doc", ".ppt", ".pptx", ".md", ".txt", ".png", ".jpg", ".jpeg"}

# 1) 磁盘文件
disk = []
for root, dirs, files in os.walk(KB):
    # 跳过已归档目录与缓存
    rel = os.path.relpath(root, KB)
    if rel.startswith("documents") or rel.startswith("chunks"):
        continue
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext in DOC_EXT:
            disk.append(os.path.join(root, f))
print(f"磁盘文档类文件: {len(disk)}")

# 2) DB 中的路径
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db_paths = set()
db_names = set()
for fp, fn in con.execute("SELECT file_path, file_name FROM documents"):
    if fp:
        db_paths.add(os.path.normcase(os.path.abspath(fp)))
    if fn:
        db_names.add(os.path.normcase(fn.strip()))
print(f"DB 文档行: {con.execute('SELECT COUNT(*) FROM documents').fetchone()[0]}")
print(f"DB 有 file_path 的: {len(db_paths)}；有 file_name 的: {len(db_names)}")

# 3) 差集：按路径 + 按文件名
missing_by_path = [p for p in disk if os.path.normcase(os.path.abspath(p)) not in db_paths]
missing_by_name = [p for p in disk if os.path.normcase(os.path.basename(p)) not in db_names]
print()
print(f"路径未匹配: {len(missing_by_path)}")
print(f"文件名未匹配: {len(missing_by_name)}")

# 4) 未入库文件按目录分布
cnt = Counter()
for p in missing_by_name:
    rel = os.path.relpath(os.path.dirname(p), KB)
    top = rel.split(os.sep)[0]
    cnt[top] += 1
print()
print("未入库文件（按顶层目录）:")
for k, v in cnt.most_common(20):
    print(f"  {k}: {v}")

print()
print("未入库样本:")
for p in missing_by_name[:12]:
    print("  ", os.path.relpath(p, KB))
