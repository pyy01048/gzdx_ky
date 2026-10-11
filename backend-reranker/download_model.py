"""Download BAAI/bge-reranker-v2-m3 via hf-mirror.com."""
import os
import sys

# Use hf-mirror as HF endpoint (must be set before importing huggingface_hub)
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
# hf-mirror 不支持 xet/CAS 协议，必须禁用
os.environ["HF_HUB_DISABLE_XET"] = "1"

from huggingface_hub import snapshot_download

LOCAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "models", "bge-reranker-v2-m3")

print(f"Downloading BAAI/bge-reranker-v2-m3 to: {LOCAL_DIR}")
print(f"HF_ENDPOINT: {os.environ['HF_ENDPOINT']}")

path = snapshot_download(
    repo_id="BAAI/bge-reranker-v2-m3",
    local_dir=LOCAL_DIR,
    # Only need model weight + config + tokenizer, no ONNX/flax/etc.
    allow_patterns=[
        "*.json",
        "*.txt",
        "*.model",
        "*.safetensors",
        "*.bin",
        "tokenizer*",
        "vocab*",
        "merges*",
        "special_tokens_map*",
    ],
)

print(f"Download complete. Files at: {path}")

# Calculate total size
total_size = 0
for root, dirs, files in os.walk(path):
    for f in files:
        fp = os.path.join(root, f)
        total_size += os.path.getsize(fp)

print(f"Total size: {total_size / 1024 / 1024:.1f} MB ({total_size / 1024 / 1024 / 1024:.2f} GB)")
