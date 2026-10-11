# -*- coding: utf-8 -*-
"""
离线 Embedding 引擎（P0-3 核心：数据不出网）。

特点：
- 零第三方依赖，仅依赖 numpy；无需联网、无需下载任何模型权重。
- 使用「字符 n-gram + 英文词」的哈希向量（hashing trick）+ TF 子线性加权
  + L2 归一化，得到固定维度的稠密向量。
- 同一引擎在「构建索引」与「查询」时使用，保证向量空间一致，可稳定做余弦相似度。
- 向量维度 512，与 bge-small-zh 一致，便于后续无缝切换到更高质量的本地模型。

该引擎的质量虽不及 bge 等语义模型，但完全离线、秒级构建 5000+ 分块的索引，
并能在 RAG 中作为 FTS5 BM25 的补充召回通道，实现「本地+离线」的精准检索。
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import List

import numpy as np

OFFLINE_DIM = 512  # 与 bge-small-zh-v1.5 对齐，便于后续切换


class OfflineEmbedder:
    """本地哈希向量引擎（离线、确定性、无网络）。"""

    def __init__(self, dim: int = OFFLINE_DIM):
        self.dim = dim

    # ------------------------------------------------------------------ #
    # 分词：英文/数字词 + 中文 1~3 字 n-gram
    # ------------------------------------------------------------------ #
    @staticmethod
    def _tokenize(text: str) -> List[str]:
        if not text:
            return []
        tokens: List[str] = []
        # 英文 / 数字词
        tokens.extend(re.findall(r"[a-zA-Z0-9]+", text.lower()))
        # 中文按字符 n-gram（1/2/3 字）
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
        n = len(cjk)
        for i in range(n):
            tokens.append(cjk[i])                 # 1-gram
            if i + 1 < n:
                tokens.append(cjk[i:i + 2])       # 2-gram
            if i + 2 < n:
                tokens.append(cjk[i:i + 3])       # 3-gram
        return tokens

    def _hash_token(self, tok: str) -> int:
        h = int.from_bytes(hashlib.md5(tok.encode("utf-8")).digest()[:8], "big")
        return h % self.dim

    # ------------------------------------------------------------------ #
    # 单条文本 -> 向量
    # ------------------------------------------------------------------ #
    def embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        toks = self._tokenize(text)
        if not toks:
            return vec
        counts = Counter(toks)
        for tok, c in counts.items():
            idx = self._hash_token(tok)
            # 子线性 TF 加权，降低高频 token 主导
            tf = 1.0 + np.log(float(c))
            vec[idx] += tf
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec

    def embed(self, texts: List[str]) -> List[np.ndarray]:
        return [self.embed_one(t or "") for t in texts]
