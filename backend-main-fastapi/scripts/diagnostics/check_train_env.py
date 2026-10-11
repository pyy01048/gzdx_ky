# -*- coding: utf-8 -*-
"""训练环境体检：GPU / 依赖 / 已有产物 / Ollama 模型。"""
import importlib
import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = os.path.dirname(os.path.abspath(__file__))
LORA = os.path.join(BASE, "data", "lora_finetune")

print("=" * 72)
print("1) GPU")
print("=" * 72)
try:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version",
         "--format=csv,noheader"],
        capture_output=True, text=True, timeout=30,
    )
    print("  " + (out.stdout.strip() or out.stderr.strip()))
except Exception as e:
    print("  nvidia-smi 不可用:", e)

print()
print("=" * 72)
print("2) 训练依赖")
print("=" * 72)
for m in ("torch", "transformers", "peft", "trl", "datasets", "accelerate",
          "bitsandbytes", "modelscope", "ollama", "sentencepiece"):
    try:
        mod = importlib.import_module(m)
        ver = getattr(mod, "__version__", "")
        print(f"  [OK]   {m:<16} {ver}")
    except Exception as e:
        print(f"  [MISS] {m:<16} {type(e).__name__}")

# torch CUDA 单独探测（避免 OMP 冲突直接崩）
print()
print("  --- torch CUDA 可用性 ---")
code = (
    "import os;os.environ.setdefault('KMP_DUPLICATE_LIB_OK','TRUE');"
    "import torch;print('torch',torch.__version__);"
    "print('cuda_available',torch.cuda.is_available());"
    "print('device',torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu');"
    "print('vram_GB',round(torch.cuda.get_device_properties(0).total_memory/1024**3,1) if torch.cuda.is_available() else 0)"
)
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180,
                   env={**os.environ, "KMP_DUPLICATE_LIB_OK": "TRUE"})
print("  " + (r.stdout.strip().replace("\n", "\n  ") or r.stderr.strip()[-400:]))

print()
print("=" * 72)
print("3) 已有训练产物")
print("=" * 72)
for sub in ("checkpoints", "merged"):
    p = os.path.join(LORA, sub)
    if not os.path.isdir(p):
        print(f"  {sub}: 不存在")
        continue
    print(f"  {sub}/")
    for name in sorted(os.listdir(p)):
        fp = os.path.join(p, name)
        if os.path.isdir(fp):
            n = sum(1 for _ in os.scandir(fp))
            print(f"     {name}/  ({n} 个文件)")
        else:
            print(f"     {name}  {os.path.getsize(fp)/1024/1024:.1f} MB")

# merged 是否完整（能被 transformers 加载）
merged = os.path.join(LORA, "merged")
if os.path.isdir(merged):
    print()
    print("  --- merged 完整性 ---")
    for f in ("config.json", "model.safetensors", "tokenizer.json",
              "tokenizer_config.json", "chat_template.jinja"):
        fp = os.path.join(merged, f)
        print(f"     {'OK ' if os.path.exists(fp) else '缺失'} {f}")
    try:
        with open(os.path.join(merged, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        print(f"     架构={cfg.get('architectures')} 层数={cfg.get('num_hidden_layers')} "
              f"hidden={cfg.get('hidden_size')}")
    except Exception as e:
        print("     读 config 失败:", e)

print()
print("=" * 72)
print("4) Ollama")
print("=" * 72)
exe = shutil.which("ollama")
print(f"  ollama 可执行: {exe or '未找到'}")
if exe:
    r = subprocess.run([exe, "list"], capture_output=True, text=True, timeout=60)
    print("  " + (r.stdout.strip() or r.stderr.strip())[:1200])
