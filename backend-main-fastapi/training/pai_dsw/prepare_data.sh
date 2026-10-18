#!/usr/bin/env bash
# 准备训练数据：数据来源按优先级
#   1. 环境变量 TRAIN_DATA_DIR 指定的目录
#   2. git 仓库自带的 data/lora_finetune_v2（276 条答疑数据集，随代码分发）
#   3. /mnt/data/考研资料数据集/lora_finetune_v2（用户上传到 OSS 的）
# 输出固定到 /mnt/workspace/train_data（本地盘，训练时读取快）
set -euo pipefail

WORKSPACE="${WORKSPACE:-/mnt/workspace}"
REPO="${REPO:-$WORKSPACE/gzdx_ky}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="${DEST:-$WORKSPACE/train_data}"

SRC="${TRAIN_DATA_DIR:-}"
if [ -z "$SRC" ]; then
  for cand in \
      "$SCRIPT_DIR/data/lora_finetune_v3" \
      "$SCRIPT_DIR/data/lora_finetune_v2" \
      "$REPO/data/lora_finetune_v3" \
      "$REPO/data/lora_finetune_v2" \
      "/mnt/data/考研资料数据集/lora_finetune_v3" \
      "/mnt/data/考研资料数据集/lora_finetune_v2" \
      "/mnt/data/考研资料数据集/lora_data"; do
    if [ -f "$cand/train.jsonl" ] && [ -f "$cand/val.jsonl" ]; then
      SRC="$cand"
      break
    fi
  done
fi

if [ -z "$SRC" ]; then
  echo "✗ 找不到训练数据（train.jsonl + val.jsonl）"
  echo "  检查过: \$TRAIN_DATA_DIR / 仓库 data/lora_finetune_v2 / OSS lora_finetune_v2 / OSS lora_data"
  exit 1
fi

echo "数据源: $SRC"
rm -rf "$DEST"
mkdir -p "$DEST"
cp "$SRC/train.jsonl" "$SRC/val.jsonl" "$DEST/"

echo "---- 数据校验 ----"
for f in train val; do
  n=$(wc -l < "$DEST/$f.jsonl")
  echo "  $f.jsonl: $n 条"
  # 第一条 JSON 合法性快检
  head -1 "$DEST/$f.jsonl" | python3 -c "import json,sys; json.load(sys.stdin); print('  JSON 格式 OK')" \
    || { echo "✗ $f.jsonl 首行不是合法 JSON"; exit 1; }
done
echo "✓ 数据就绪: $DEST"
