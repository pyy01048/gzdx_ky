#!/usr/bin/env bash
# DSW 依赖护栏：只补缺失，绝不盲目升级核心包。
#
# 为什么需要（2026-10-18 实测）：镜像自带 torch 2.3.1 / transformers 4.55.4 /
# peft 0.18.1 / datasets 3.6.0 / accelerate 1.12.0 / bitsandbytes 0.49.1 /
# modelscope 1.40.1 —— 训练所需其实一样不缺。而 `pip install -U <核心包>` 会把
# torch 换成 554MB 的新 wheel：驱动是 550.163.01（CUDA 12.4 上限），新 wheel 若
# 面向更高 CUDA，torch.cuda.is_available() 直接 False，train_dsw.py 以 exit(2) 退出。
#
# 用法：
#   bash env_setup.sh            # 体检：CUDA 可用就一个包都不装，只补真正缺的
#   bash env_setup.sh --restore  # 回滚到镜像基线（被 -U 弄坏后用）
set -uo pipefail

MIRROR="${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple}"

# 镜像基线版本（上面实测值）。trl 故意不在列：train_dsw.py 不 import 它，
# 装它只会引入额外依赖解析风险。
BASE_PINS=(
  "torch==2.3.1"
  "transformers==4.55.4"
  "peft==0.18.1"
  "datasets==3.6.0"
  "accelerate==1.12.0"
  "bitsandbytes==0.49.1"
  "modelscope==1.40.1"
)

cuda_ok() {
  python3 - <<'PY' >/dev/null 2>&1
import torch
raise SystemExit(0 if torch.cuda.is_available() else 1)
PY
}

# 模块能否 import（装了但坏掉也算不行）
importable() {
  python3 -c "import importlib,sys; importlib.import_module(sys.argv[1])" "$1" >/dev/null 2>&1
}

pin_of() { echo "${1#*==}"; }

restore() {
  echo "== 回滚到镜像基线 =="
  # torch 单独装：它是 CUDA 运行时的载体，必须最先落位
  for spec in "${BASE_PINS[@]}"; do
    pkg="${spec%%==*}"
    echo "-- pip install --force-reinstall --no-deps $spec"
    python3 -m pip install --no-cache-dir --index-url "$MIRROR" \
      --force-reinstall --no-deps "$spec" || { echo "✗ $spec 安装失败"; return 1; }
  done
  # --no-deps 逐个钉版本后，再让 pip 补齐这些包自身声明的依赖
  python3 -m pip install --index-url "$MIRROR" "${BASE_PINS[@]}" || return 0
  return 0
}

check() {
  echo "== 1/3 CUDA 可用性 =="
  if cuda_ok; then
    python3 - <<'PY'
import torch
p = torch.cuda.get_device_properties(0)
print(f"  [OK] torch {torch.__version__} CUDA {torch.version.cuda} -> "
      f"{p.name} {p.total_memory/1024**3:.1f}GB")
PY
  else
    echo "  [!!] torch.cuda 不可用 —— 当前 torch 已被换掉或装成 CPU 版。"
    echo "       执行：bash env_setup.sh --restore"
    return 2
  fi

  echo "== 2/3 依赖齐备性（缺什么装什么，不升级已有的）=="
  local missing=0
  for spec in "${BASE_PINS[@]}"; do
    pkg="${spec%%==*}"
    if importable "$pkg"; then
      ver=$(python3 -c "import importlib.metadata as m; print(m.version('$pkg'))" 2>/dev/null || echo 未知)
      printf "  [OK]   %-14s %s\n" "$pkg" "$ver"
    else
      printf "  [缺]   %-14s 将安装 %s\n" "$pkg" "$spec"
      missing=1
    fi
  done

  if [ "$missing" = 1 ]; then
    # 只装缺失项，且不带 -U：已有版本一律不动
    local specs=()
    for spec in "${BASE_PINS[@]}"; do
      importable "${spec%%==*}" || specs+=("$spec")
    done
    python3 -m pip install --index-url "$MIRROR" "${specs[@]}" || {
      echo "  ✗ 安装失败，检查网络或改用 PIP_INDEX 环境变量换源"; return 1; }
  fi

  echo "== 3/3 结论 =="
  cuda_ok && importable bitsandbytes && importable modelscope \
    && echo "  ✓ 环境就绪，可以跑 preflight.py / train_dsw.py" \
    || { echo "  ✗ 仍不就绪，见上面 [!!] / [缺] 行"; return 1; }
}

case "${1:-check}" in
  --restore|restore) restore; cuda_ok && echo "✓ CUDA 恢复" || echo "✗ CUDA 仍不可用" ;;
  *) check ;;
esac
