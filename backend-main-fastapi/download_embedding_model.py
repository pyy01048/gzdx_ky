# -*- coding: utf-8 -*-
"""
本地 Embedding 模型下载工具

解决 HuggingFace 连接超时问题，使用国内镜像站 hf-mirror.com 下载。
模型：BAAI/bge-small-zh-v1.5（约100MB，512维）

使用方法：
    python download_embedding_model.py

如果自动下载仍失败，可手动下载：
1. 访问 https://hf-mirror.com/BAAI/bge-small-zh-v1.5
2. 下载以下文件到 data/embedding_models/models--BAAI--bge-small-zh-v1.5/snapshots/<hash>/
   - config.json
   - model.onnx
   - tokenizer.json
   - special_tokens_map.json
   - vocab.txt
3. 重新运行本脚本验证
"""

import os
import sys
import time

# 设置国内镜像站（必须在导入 fastembed 之前设置）
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "embedding_models")


def download_model():
    """下载模型。"""
    print("=" * 60)
    print("  本地 Embedding 模型下载工具")
    print("  模型: BAAI/bge-small-zh-v1.5 (约100MB, 512维)")
    print("  镜像站: https://hf-mirror.com")
    print("=" * 60)

    os.makedirs(CACHE_DIR, exist_ok=True)
    print(f"\n缓存目录: {CACHE_DIR}")

    # 检查是否已下载
    model_dir = os.path.join(CACHE_DIR, "models--BAAI--bge-small-zh-v1.5")
    if os.path.exists(model_dir):
        print(f"\n✓ 模型目录已存在: {model_dir}")
        # 检查模型文件
        onnx_files = []
        for root, dirs, files in os.walk(model_dir):
            for f in files:
                if f.endswith(".onnx"):
                    onnx_files.append(os.path.join(root, f))
        if onnx_files:
            print(f"✓ 找到模型文件: {onnx_files[0]}")
            print("\n模型已下载，无需重复下载。")
            return True
        else:
            print("⚠ 模型目录存在但未找到.onnx文件，重新下载...")

    print("\n开始下载模型（首次约100MB，请耐心等待）...")
    print("如果下载速度慢或失败，请检查网络或使用代理。")
    print("-" * 60)

    start = time.time()
    try:
        from fastembed import TextEmbedding
        model = TextEmbedding(model_name=MODEL_NAME, cache_dir=CACHE_DIR)

        # 测试生成向量
        test_text = "数字电子技术基础"
        embeddings = list(model.embed([test_text]))
        elapsed = time.time() - start

        print("-" * 60)
        print(f"✓ 模型下载成功！耗时 {elapsed:.1f}秒")
        print(f"✓ 向量维度: {len(embeddings[0])}")
        print(f"✓ 测试文本: {test_text}")
        print(f"✓ 前5个向量值: {embeddings[0][:5]}")
        print("\n" + "=" * 60)
        print("  模型下载完成！现在可以使用本地 Embedding 了。")
        print("  数据完全本地处理，不出网。")
        print("=" * 60)
        return True

    except Exception as e:
        elapsed = time.time() - start
        print("-" * 60)
        print(f"✗ 下载失败（耗时 {elapsed:.1f}秒）: {e}")
        print("\n" + "=" * 60)
        print("  手动下载方案：")
        print("  1. 访问 https://hf-mirror.com/BAAI/bge-small-zh-v1.5")
        print("  2. 下载以下文件：")
        print("     - config.json")
        print("     - model.onnx")
        print("     - tokenizer.json")
        print("     - special_tokens_map.json")
        print("     - vocab.txt")
        print(f"  3. 放到: {CACHE_DIR}\\models--BAAI--bge-small-zh-v1.5\\snapshots\\<hash>\\")
        print("  4. 重新运行本脚本验证")
        print("=" * 60)
        return False


if __name__ == "__main__":
    success = download_model()
    sys.exit(0 if success else 1)
