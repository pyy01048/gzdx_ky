# -*- coding: utf-8 -*-
"""合并 LoRA 权重到基础模型，并导出为完整模型。

使用本地 ModelScope 缓存的基础模型，避免 HuggingFace 网络问题。
"""

import os
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 路径配置
BASE_MODEL = r"C:\Users\33884\.cache\modelscope\hub\models\Qwen--Qwen2.5-3B-Instruct\snapshots\master"
LORA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lora_finetune", "checkpoints", "final")
MERGED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lora_finetune", "merged")


def merge_lora():
    """合并 LoRA 权重。"""
    print("=" * 60)
    print("合并 LoRA 权重到基础模型")
    print("=" * 60)
    print(f"开始时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 检查路径
    if not os.path.exists(BASE_MODEL):
        print(f"✗ 基础模型不存在: {BASE_MODEL}")
        return None
    if not os.path.exists(LORA_PATH):
        print(f"✗ LoRA 模型不存在: {LORA_PATH}")
        return None

    print(f"基础模型: {BASE_MODEL}")
    print(f"LoRA 权重: {LORA_PATH}")
    print(f"输出目录: {MERGED_DIR}")
    print()

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
    except ImportError as e:
        print(f"✗ 缺少依赖库: {e}")
        print("请先安装：pip install torch transformers peft")
        return None

    # 加载基础模型（CPU，因为合并不需要GPU）
    print("加载基础模型（CPU模式）...")
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16,
        device_map="cpu",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    print("✓ 基础模型加载完成")

    # 加载 LoRA 权重
    print(f"\n加载 LoRA 权重: {LORA_PATH}")
    model = PeftModel.from_pretrained(base_model, LORA_PATH)
    print("✓ LoRA 权重加载完成")

    # 合并权重
    print("\n合并权重中...")
    merged_model = model.merge_and_unload()
    print("✓ 权重合并完成")

    # 保存合并后的模型
    os.makedirs(MERGED_DIR, exist_ok=True)
    print(f"\n保存合并模型到: {MERGED_DIR}")
    merged_model.save_pretrained(MERGED_DIR, safe_serialization=True)
    tokenizer.save_pretrained(MERGED_DIR)
    print("✓ 模型保存完成")

    # 统计文件大小
    total_size = 0
    print("\n合并模型文件:")
    for f in os.listdir(MERGED_DIR):
        fpath = os.path.join(MERGED_DIR, f)
        if os.path.isfile(fpath):
            size_mb = os.path.getsize(fpath) / (1024 * 1024)
            total_size += size_mb
            print(f"  - {f}: {size_mb:.1f} MB")
    print(f"\n总大小: {total_size:.1f} MB")

    print(f"\n完成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("✓ 模型合并完成！")
    return MERGED_DIR


if __name__ == "__main__":
    merge_lora()
