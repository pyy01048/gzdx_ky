# -*- coding: utf-8 -*-
"""使用ModelScope下载模型并启动LoRA微调训练。"""

import os
import sys
import time

# 设置ModelScope（国内访问稳定）
os.environ["MODELSCOPE_CACHE"] = os.path.expanduser("~/.cache/modelscope/hub")

def download_model(model_name="Qwen/Qwen2.5-4B-Instruct"):
    """使用ModelScope下载模型。"""
    print("=" * 60)
    print(f"使用ModelScope下载模型: {model_name}")
    print("=" * 60)

    try:
        from modelscope import snapshot_download
        print("开始下载模型（约8GB，可能需要10-30分钟）...")
        start_time = time.time()

        model_dir = snapshot_download(
            model_name,
            cache_dir=os.environ["MODELSCOPE_CACHE"],
        )

        elapsed = time.time() - start_time
        print(f"\n✓ 模型下载完成！")
        print(f"  模型路径: {model_dir}")
        print(f"  下载耗时: {elapsed/60:.1f} 分钟")

        # 列出模型文件
        print("\n模型文件:")
        for f in os.listdir(model_dir):
            fpath = os.path.join(model_dir, f)
            if os.path.isfile(fpath):
                size_mb = os.path.getsize(fpath) / (1024 * 1024)
                print(f"  - {f}: {size_mb:.1f} MB")

        return model_dir

    except Exception as e:
        print(f"✗ 模型下载失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def start_training(model_dir):
    """使用下载的模型启动LoRA微调训练。"""
    print("\n" + "=" * 60)
    print("启动LoRA微调训练")
    print("=" * 60)

    # 设置环境变量
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    # 导入训练模块
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from lora_finetune import train_lora, DATA_DIR, OUTPUT_DIR

    # 临时修改模型名称为本地路径
    import lora_finetune
    original_model_name = lora_finetune.MODEL_NAME
    lora_finetune.MODEL_NAME = model_dir

    try:
        result = train_lora()
        return result
    finally:
        lora_finetune.MODEL_NAME = original_model_name


def main():
    print("考研学习平台 - 本地模型LoRA微调训练（ModelScope版）")
    print(f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 步骤1：下载模型（使用3B模型，8GB显存更适合）
    model_dir = download_model("Qwen/Qwen2.5-3B-Instruct")

    if not model_dir:
        print("\n✗ 模型下载失败，无法继续训练")
        sys.exit(1)

    # 步骤2：启动训练
    result = start_training(model_dir)

    print("\n" + "=" * 60)
    print("训练完成！")
    print("=" * 60)
    print(f"结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"模型保存路径: {result or 'data/lora_finetune/checkpoints/final/'}")
    print()
    print("下一步:")
    print("  1. 合并模型: python lora_finetune.py --stage merge")
    print("  2. 导入Ollama: python lora_finetune.py --stage ollama")
    print("  3. 在平台设置中将本地模型名称改为 kaoyan-assistant")


if __name__ == "__main__":
    main()
