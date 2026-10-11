# -*- coding: utf-8 -*-
"""诊断 qwen2.5vl:7b：纯文本 / 简单视觉 / 中文视觉。"""
import base64, json, time, urllib.request

def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read()), time.time() - t0

img_path = r"D:\平台\backend-main-fastapi\tests\fixtures\circuits\01_voltage_divider.png"
with open(img_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

# 1) 纯文本：让模型算 2+3
print("=== 1) text-only: 2+3=? ===")
data, dt = post("http://127.0.0.1:11434/api/generate", {
    "model": "qwen2.5vl:7b", "prompt": "2+3=? 只回答数字。",
    "stream": False, "options": {"temperature": 0.0, "num_predict": 20},
})
print(f"{dt:.1f}s ->", repr(data.get("response", "")[:200]))

# 2) 简单视觉：用英文问图里有什么
print("\n=== 2) vision simple English: what do you see? ===")
data, dt = post("http://127.0.0.1:11434/api/generate", {
    "model": "qwen2.5vl:7b",
    "prompt": "Describe this image in one short sentence.",
    "images": [b64],
    "stream": False,
    "options": {"temperature": 0.0, "num_predict": 80},
})
print(f"{dt:.1f}s ->", repr(data.get("response", "")[:500]))

# 3) 简单视觉中文
print("\n=== 3) vision Chinese: 图里有什么元件？ ===")
data, dt = post("http://127.0.0.1:11434/api/generate", {
    "model": "qwen2.5vl:7b",
    "prompt": "这张图里画了什么？用一句话回答。",
    "images": [b64],
    "stream": False,
    "options": {"temperature": 0.0, "num_predict": 80},
})
print(f"{dt:.1f}s ->", repr(data.get("response", "")[:500]))
