# -*- coding: utf-8 -*-
"""直接打 Ollama，对比 generate vs chat 接口、不同 prompt 的原始返回。"""
import base64, json, time, urllib.request

def post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read()), time.time() - t0

img_path = r"D:\平台\backend-main-fastapi\tests\fixtures\circuits\01_voltage_divider.png"
with open(img_path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

PROMPT = (
    "这是一张电阻分压电路图。请识别图中的元器件、连接关系和电路功能，"
    "并以 JSON 输出，schema 为："
    '{"circuit_type":"divider",'
    '"components":[{"designator":"R1","type":"resistor","value":"10kΩ","net_nodes":["Vcc","Node1"]}],'
    '"connections":[{"from":"R1.top","to":"Vcc"},{"from":"R1.bottom","to":"Node1"},{"from":"Node1","to":"R2.top"}],'
    '"nodes":["Vcc","GND","Vout"],'
    '"description":"中文简述"}。只输出 JSON，不要其他文字。'
)

# A: /api/generate，无 format=json，num_ctx=8192
print("=== A: /api/generate, no format=json ===")
try:
    data, dt = post("http://127.0.0.1:11434/api/generate", {
        "model": "qwen2.5vl:7b",
        "prompt": PROMPT,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 1024},
    })
    print(f"elapsed {dt:.1f}s, eval_count={data.get('eval_count')}")
    print(data.get("response", "")[:2000])
except Exception as e:
    print("ERR", e)

# B: /api/chat
print("\n=== B: /api/chat ===")
try:
    data, dt = post("http://127.0.0.1:11434/api/chat", {
        "model": "qwen2.5vl:7b",
        "messages": [
            {"role": "system", "content": "你是电路识图专家。只输出 JSON。"},
            {"role": "user", "content": PROMPT, "images": [b64]},
        ],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 1024},
    })
    print(f"elapsed {dt:.1f}s, eval_count={data.get('eval_count')}")
    print(data.get("message", {}).get("content", "")[:2000])
except Exception as e:
    print("ERR", e)
