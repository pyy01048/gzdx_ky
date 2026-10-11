# -*- coding: utf-8 -*-
"""验证 RAG 检索（jieba 分词生效后）与 OCR 标记字段。"""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000"


def call(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return 0, str(e)


print("=" * 74)
print("1) RAG 检索（jieba 分词 + FTS5）")
print("=" * 74)
for query in ("施密特触发器", "卡诺图化简", "静态工作点", "555定时器", "JK触发器"):
    st, d = call("POST", "/api/ai/rag-search", {"query": query, "limit": 3})
    if st == 200:
        # 契约：响应键是 hits（不是 results）
        items = d.get("hits") or []
        print(f"  [{st}] {query!r} → {len(items)} 条命中")
        for it in items[:2]:
            src = it.get("source") or "?"
            title = (it.get("title") or "")[:38]
            content = (it.get("content") or "")[:52].replace("\n", " ")
            print(f"        [{src}] {title} | {content}")
    else:
        print(f"  [{st}] {query!r} 失败: {d}")

print()
print("=" * 74)
print("2) 文档列表字段（含扫描件标记）")
print("=" * 74)
st, d = call("GET", "/api/documents?page=1&page_size=3")
if st == 200:
    # 契约：GET /api/documents 直接返回 list
    items = d if isinstance(d, list) else (d.get("items") or [])
    print(f"  [{st}] documents 返回 {len(items)} 条（类型 {type(d).__name__}）")
    if items:
        keys = sorted(items[0].keys())
        print(f"        字段: {keys}")
        print(f"        含 doc_type: {'doc_type' in keys} · 含 ocr_used: {'ocr_used' in keys}")

print()
print("=" * 74)
print("3) 搜索索引状态")
print("=" * 74)
st, d = call("GET", "/api/ai/search-status")
print(f"  [{st}] {json.dumps(d, ensure_ascii=False)[:400]}" if st == 200 else f"  [{st}] {d}")
