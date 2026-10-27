# -*- coding: utf-8 -*-
"""再测：用真实照片 + JPEG + 不同尺寸，定位视觉塔问题。"""
import base64, json, time, urllib.request, io
from PIL import Image

def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read()), time.time() - t0

# 造一张最简单的图：白底黑字 "HELLO"
img = Image.new("RGB", (400, 200), "white")
from PIL import ImageDraw, ImageFont
d = ImageDraw.Draw(img)
d.text((100, 80), "HELLO", fill="black")
buf = io.BytesIO()
img.save(buf, format="JPEG", quality=85)
b64_jpg = base64.b64encode(buf.getvalue()).decode()

# 造一张彩色方块图
img2 = Image.new("RGB", (300, 300), "red")
d2 = ImageDraw.Draw(img2)
d2.rectangle([50, 50, 250, 250], fill="blue")
buf2 = io.BytesIO()
img2.save(buf2, format="PNG")
b64_png = base64.b64encode(buf2.getvalue()).decode()

for tag, b64, prompt in [
    ("HELLO-jpg", b64_jpg, "What text do you see? Answer in 3 words."),
    ("red-blue-png", b64_png, "What colors do you see? Answer briefly."),
]:
    print(f"\n=== {tag} ===")
    data, dt = post("http://127.0.0.1:11434/api/generate", {
        "model": "qwen2.5vl:7b", "prompt": prompt, "images": [b64],
        "stream": False, "options": {"temperature": 0.0, "num_predict": 60},
    })
    print(f"{dt:.1f}s ->", repr(data.get("response", "")[:300]))
