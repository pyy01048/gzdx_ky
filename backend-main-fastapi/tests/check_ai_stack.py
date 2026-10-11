# -*- coding: utf-8 -*-
"""AI 接入层现状核查：本地模型 / 云端 API / 嵌入 / 路由 是否齐备可用。"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000"


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=90) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return 0, str(e)


def post(path, body=None):
    data = json.dumps(body or {}, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return 0, str(e)


print("=" * 74)
print("1) 已配置的 AI 服务商（云端 API）")
print("=" * 74)
st, d = get("/api/ai/providers")
if st == 200:
    items = d if isinstance(d, list) else (d.get("items") or [])
    print(f"  共 {len(items)} 个")
    for p in items:
        key = (p.get("api_key") or "")
        masked = (key[:6] + "****" + key[-4:]) if len(key) > 12 else ("已配置" if key else "未配置")
        print(f"    · {p.get('name') or p.get('provider')} | model={p.get('model')} "
              f"| {masked} | 默认={p.get('is_default') or p.get('is_active')}")
else:
    print(f"  [{st}] {d}")

print()
print("=" * 74)
print("2) 本地模型（Ollama）状态")
print("=" * 74)
st, d = get("/api/ai/local/status")
print(f"  [{st}] local/status -> {json.dumps(d, ensure_ascii=False)[:400]}" if st == 200 else f"  [{st}] {d}")
st, d = get("/api/ai/local/models")
print(f"  [{st}] local/models -> {json.dumps(d, ensure_ascii=False)[:300]}" if st == 200 else f"  [{st}] {d}")

print()
print("=" * 74)
print("3) 检索索引与嵌入")
print("=" * 74)
st, d = get("/api/ai/search-status")
print(f"  [{st}] search-status -> {json.dumps(d, ensure_ascii=False)}" if st == 200 else f"  [{st}] {d}")

print()
print("=" * 74)
print("4) RAG 检索（本地知识库）")
print("=" * 74)
st, d = post("/api/ai/rag-search", {"query": "卡诺图化简", "limit": 2})
if st == 200:
    hits = d.get("hits") or []
    print(f"  [{st}] 命中 {len(hits)} 条")
    for h in hits[:2]:
        print(f"    · [{h.get('source')}] {(h.get('title') or '')[:40]}")
else:
    print(f"  [{st}] {d}")

print()
print("=" * 74)
print("5) 智能路由（本地优先 + 云端兜底）")
print("=" * 74)
st, d = post("/api/ai/chat/router", {"message": "什么是卡诺图？", "use_rag": False})
print(f"  [{st}] chat/router -> {json.dumps(d, ensure_ascii=False)[:400]}" if st == 200 else f"  [{st}] {str(d)[:300]}")
