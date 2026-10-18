#!/usr/bin/env bash
# 把训练产物回传 OSS（/mnt/data 挂载点即 OSS，cp 即可，无需 ossutil/AK）。
# 用法: bash push_checkpoint.sh [源目录]
#   默认源目录: /mnt/workspace/lora_out/checkpoints/final
set -euo pipefail

SRC="${1:-/mnt/workspace/lora_out/checkpoints/final}"
OSS_OUT="${OSS_OUT:-/mnt/data/考研资料数据集/lora_out}"

if [ ! -d "$SRC" ]; then
  echo "✗ 源目录不存在: $SRC"
  exit 1
fi

echo "源: $SRC"
echo "目标: $OSS_OUT/final"
mkdir -p "$OSS_OUT"
rm -rf "$OSS_OUT/final"
cp -r "$SRC" "$OSS_OUT/final"

echo "---- 校验 ----"
ls -la "$OSS_OUT/final"
SIZE=$(du -sm "$OSS_OUT/final" | cut -f1)
echo "✓ 已回传 OSS，共 ${SIZE} MB"
echo
echo "本地机器下载方式（任选一）："
echo "  A. PAI 控制台 → 工作空间 → 默认存储 → 浏览 oss-pai-087n0xbfgdz56tjfyu-cn-shanghai/考研资料数据集/lora_out/final"
echo "  B. 本地装 ossutil 后: ossutil cp -r oss://oss-pai-087n0xbfgdz56tjfyu-cn-shanghai/考研资料数据集/lora_out/final ./final"
