#!/usr/bin/env bash
# PAI-DSW 环境探测：训练前先跑这个，把输出贴回来即可判断要不要补装依赖。
set -uo pipefail

echo "================ 系统 ================"
python3 -V
echo "---- GPU ----"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null \
  || echo "!! nvidia-smi 不可用（无 GPU 或驱动异常）"
echo "---- 磁盘 ----"
df -h /mnt/workspace /mnt/data 2>/dev/null | awk 'NR==1 || /\/mnt\//'

echo "================ OSS 挂载 ================"
if [ -d /mnt/data ]; then
  echo "/mnt/data 存在，顶层内容："
  ls -la /mnt/data/ | head -20
  KB="/mnt/data/考研资料数据集"
  if [ -d "$KB" ]; then
    echo "---- $KB 内容抽样 ----"
    ls "$KB" | head -10
    echo "文件总数（含子目录，可能较慢）:"
    find "$KB" -type f 2>/dev/null | wc -l
  else
    echo "!! 未找到 $KB，请确认 OSS 挂载路径"
  fi
else
  echo "!! /mnt/data 不存在——OSS 未挂载，检查工作空间配置的默认存储路径"
fi

echo "================ Python 依赖 ================"
python3 - <<'EOF'
import importlib
mods = [
    ("torch", "torch"), ("transformers", "transformers"), ("peft", "peft"),
    ("datasets", "datasets"), ("accelerate", "accelerate"),
    ("bitsandbytes", "bitsandbytes"), ("modelscope", "modelscope"),
]
for name, mod in mods:
    try:
        m = importlib.import_module(mod)
        ver = getattr(m, "__version__", "未知")
        extra = ""
        if mod == "torch":
            extra = f", CUDA={torch_cuda}" if (torch_cuda := getattr(m, 'version', None) and m.version.cuda) else ""
        print(f"  {name:16s} {ver}{extra}")
    except ImportError:
        print(f"  {name:16s} !! 未安装")

import torch
if not torch.cuda.is_available():
    print("!! torch.cuda 不可用——当前 torch 可能是 CPU 版，需重装 CUDA 版")
EOF

echo "================ 结论指引 ================"
cat <<'TIP'
缺什么装什么（DSW 默认 python3 即训练用解释器，root 身份直接装）：
  torch        装 CUDA 12.4 版：pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
  transformers  pip install "transformers>=4.41,<6"     # 4.41+ 才有 eval_strategy
  peft          pip install "peft>=0.13"
  datasets      pip install datasets
  accelerate    pip install accelerate
  bitsandbytes  pip install bitsandbytes                # QLoRA 4bit 必需
  modelscope    pip install modelscope                  # 拉基座用，镜像通常已带
TIP
