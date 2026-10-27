# -*- coding: utf-8 -*-
"""用 3 张 fixture 电路图真实跑一遍 VLM，打印结构化结果。"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.circuit_vision import CircuitVisionService

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "tests", "fixtures", "circuits")
FIX = os.path.abspath(FIX)

svc = CircuitVisionService(use_ocr=False)  # OCR 微服务未启动，先走纯 VLM

expected = {
    "01_voltage_divider.png": {
        "circuit_type": "divider",
        "must_contain": ["R1", "R2", "Vcc", "GND", "Vout"],
    },
    "02_common_emitter.png": {
        "circuit_type": "amplifier",
        "must_contain": ["Q1", "NPN", "Rc", "Re", "C1", "C2", "Vin", "Vout", "Vcc"],
    },
    "03_bridge_rectifier.png": {
        "circuit_type": "rectifier",
        "must_contain": ["D1", "D2", "D3", "D4", "C1", "Rload", "GND"],
    },
}

results = {}
for fname in sorted(os.listdir(FIX)):
    if not fname.endswith(".png"):
        continue
    p = os.path.join(FIX, fname)
    print("=" * 70)
    print(f"[FILE] {fname}")
    t0 = time.time()
    res = svc.analyze(p, question_text=None, use_ocr=False)
    dt = time.time() - t0
    print(f"[elapsed] {dt:.1f}s  ok={res['ok']}  engines={res['engines']}")
    print(f"[circuit_type] {res.get('circuit_type')} / {res.get('circuit_type_cn')}")
    print(f"[components]")
    for c in res.get("components", []):
        print(f"  - {c.get('designator'):8s} {c.get('type'):14s} value={c.get('value'):10s} nets={c.get('net_nodes')} conf={c.get('confidence')}")
    print(f"[connections] ({len(res.get('connections', []))})")
    for c in res.get("connections", [])[:15]:
        print(f"  - {c.get('from')} -> {c.get('to')}")
    print(f"[nodes] {res.get('nodes')}")
    print(f"[description] {res.get('description')}")
    print(f"[uncertainties] {res.get('uncertainties')}")
    if res.get("errors"):
        print(f"[errors] {res['errors']}")
    results[fname] = res

# 保存完整 JSON 供交付报告引用
out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "tests", "fixtures", "circuits", "_vlm_results.json")
out = os.path.abspath(out)
with open(out, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("=" * 70)
print(f"saved -> {out}")
