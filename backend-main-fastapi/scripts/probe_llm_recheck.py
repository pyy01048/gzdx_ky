# -*- coding: utf-8 -*-
"""独立验证：本地 LLM 是否真的不可用（quiz-answer-gap 的 6 次超时结论复核）。

他的探测可能有问题：大计算题 + 180s 超时。我们这里：
1. 先测最简请求（健康检查）
2. 再测短文本抽取（判断"答案本就在题里"的切分任务）
"""
import json, sys, time, urllib.request
sys.stdout.reconfigure(encoding="utf-8")

OLLAMA = "http://127.0.0.1:11434"

def post(path, payload, timeout=60):
    req = urllib.request.Request(
        OLLAMA + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return time.time() - t0, json.loads(r.read())
    except Exception as e:
        return time.time() - t0, {"__error__": str(e)}


print("=== 1. Ollama 服务健康检查 ===")
try:
    with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=10) as r:
        models = [m["name"] for m in json.loads(r.read())["models"]]
    print(f"  在线，{len(models)} 个模型:", models[:8])
except Exception as e:
    print("  不可达:", e)
    raise SystemExit(1)

print("\n=== 2. 最小生成请求（健康检查，30s 超时）===")
dt, r = post("/api/generate",
             {"model": "qwen3:4b", "prompt": "说一个字：好",
              "stream": False, "options": {"num_predict": 8}},
             timeout=30)
if "__error__" in r:
    print(f"  [{dt:.1f}s] 失败:", r["__error__"][:120])
else:
    print(f"  [{dt:.1f}s] OK -> {r.get('response','')[:40]!r}")

print("\n=== 3. 真实任务：把题+答案切成两段（这类任务很轻）===")
CASES = [
    ("kaoyan-assistant:latest",
     "从下面文本中切分出【题目】和【答案】两部分，只输出 JSON。\n"
     "文本：2 能否将 1.5V 的干电池以正向接法接到二极管两端？为什么？ 解：不能。"),
    ("qwen3:8b",
     "从下面文本中切分出【题目】和【答案】两部分，只输出 JSON。\n"
     "文本：2 能否将 1.5V 的干电池以正向接法接到二极管两端？为什么？ 解：不能。"),
]
for model, prompt in CASES:
    dt, r = post("/api/generate",
                 {"model": model, "prompt": prompt, "stream": False,
                  "options": {"num_predict": 200}}, timeout=90)
    if "__error__" in r:
        print(f"  {model:<28} [{dt:5.1f}s] 失败: {r['__error__'][:90]}")
    else:
        out = r.get("response", "").replace("\n", " ")[:100]
        print(f"  {model:<28} [{dt:5.1f}s] OK -> {out!r}")

print("\n=== 4. 真实任务：短知识点释义（判断 S5 转知识点质量）===")
dt, r = post("/api/generate",
             {"model": "qwen3:8b", "stream": False,
              "prompt": "用一句话解释什么叫互补复位器件，只输出解释，不要多余文字。",
              "options": {"num_predict": 150}}, timeout=90)
print(f"  [{dt:.1f}s] " + ("失败: " + r["__error__"][:90] if "__error__" in r
                            else repr(r.get("response", "")[:140])))
