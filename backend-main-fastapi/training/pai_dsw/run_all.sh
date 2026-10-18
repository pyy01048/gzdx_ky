#!/usr/bin/env bash
# PAI-DSW 一键训练：探测 → 备数据 → 训练 → 回传 OSS
# 每步都可用环境变量跳过，方便分步排查：
#   SKIP_PROBE=1 SKIP_PREPARE=1 SKIP_TRAIN=1 SKIP_PUSH=1 bash run_all.sh
set -euo pipefail
cd "$(dirname "$0")"

STEP=1
say() { echo; echo "======== [$STEP/4] $1 ========"; STEP=$((STEP+1)); }

if [ "${SKIP_PROBE:-0}" != "1" ]; then
  say "环境探测"
  bash probe_env.sh
else
  say "环境探测（已跳过）"; STEP=$((STEP+1))
fi

if [ "${SKIP_PREPARE:-0}" != "1" ]; then
  say "准备训练数据"
  bash prepare_data.sh
else
  say "准备训练数据（已跳过）"; STEP=$((STEP+1))
fi

if [ "${SKIP_TRAIN:-0}" != "1" ]; then
  say "LoRA 训练（Qwen2.5-7B + QLoRA 4bit）"
  DATA_DIR="${DEST:-/mnt/workspace/train_data}"
  OUT_DIR="${OUT_DIR:-/mnt/workspace/lora_out}"
  python3 train_dsw.py --data-dir "$DATA_DIR" --output-dir "$OUT_DIR"
else
  say "LoRA 训练（已跳过）"; STEP=$((STEP+1))
fi

if [ "${SKIP_PUSH:-0}" != "1" ]; then
  say "回传 OSS"
  bash push_checkpoint.sh
else
  say "回传 OSS（已跳过）"
fi

echo
echo "✓ 全流程完成。本地拿到 adapter 后："
echo "  1. 下载 OSS: 考研资料数据集/lora_out/final（~500MB）"
echo "  2. 合并:   python training/lora_finetune.py --stage merge --data-dir <放adapter的目录> --base-model <7B本地路径>"
echo "  3. 导入:   ollama create kaoyan-assistant-v5 -f Modelfile"
echo "  4. 评测:   python scripts/eval_qa_model.py --models qwen2.5:1.5b,kaoyan-assistant,kaoyan-assistant-v5 --n 150"
