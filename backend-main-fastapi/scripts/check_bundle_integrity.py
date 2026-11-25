#!/usr/bin/env python3
"""构建完整性校验：所有被引用的 chunk 是否都真实存在于产物目录。
用法：python check_bundle_integrity.py <static_dir>
"""

import os
import re
import sys

root = sys.argv[1] if len(sys.argv) > 1 else os.path.join("backend-main-fastapi", "static")
js_dir = os.path.join(root, "assets", "js")
css_dir = os.path.join(root, "assets", "css")

existing = set(os.listdir(js_dir)) if os.path.isdir(js_dir) else set()
existing_css = set(os.listdir(css_dir)) if os.path.isdir(css_dir) else set()

ref_re = re.compile(r"assets/js/([A-Za-z0-9_.\-]+\.js)")
css_re = re.compile(r"assets/css/([A-Za-z0-9_.\-]+\.css)")
missing = {}
missing_css = {}
checked = 0
for name in sorted(existing):
    p = os.path.join(js_dir, name)
    try:
        txt = open(p, encoding="utf-8", errors="ignore").read()
    except OSError:
        continue
    checked += 1
    for ref in set(ref_re.findall(txt)):
        if ref not in existing:
            missing.setdefault(ref, []).append(name)
    for ref in set(css_re.findall(txt)):
        if ref not in existing_css:
            missing_css.setdefault(ref, []).append(name)

print(f"js files: {len(existing)}, scanned: {checked}")
print(f"css files: {len(existing_css)}")
print(f"missing js refs: {len(missing)}")
for k, v in list(missing.items())[:20]:
    print("  MISSING", k, "<-", v[:3])
print(f"missing css refs: {len(missing_css)}")
for k, v in list(missing_css.items())[:20]:
    print("  MISSING", k, "<-", v[:3])

# index.html 引用
idx = os.path.join(root, "index.html")
if os.path.exists(idx):
    html = open(idx, encoding="utf-8").read()
    refs = set(ref_re.findall(html)) | set(css_re.findall(html))
    bad = [r for r in refs if r not in existing and r not in existing_css]
    print(f"index.html refs: {len(refs)}, missing: {len(bad)} {bad}")

# 未被任何 chunk 引用的孤儿文件
all_js = set(existing)
referenced = set()
for name in existing:
    p = os.path.join(js_dir, name)
    txt = open(p, encoding="utf-8", errors="ignore").read()
    referenced |= set(ref_re.findall(txt))
# entry 由 index.html 引用
entry = ref_re.findall(html) if os.path.exists(idx) else []
referenced |= set(entry)
orphans = [n for n in all_js if n not in referenced and not n.startswith(("index-", "react-vendor", "state-vendor"))]
print(f"orphan chunks (not referenced anywhere): {len(orphans)}")
for n in orphans[:15]:
    print("  ORPHAN", n, os.path.getsize(os.path.join(js_dir, n)) // 1024, "KB")
