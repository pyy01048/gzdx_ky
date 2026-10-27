# -*- coding: utf-8 -*-
"""
本地 Embedding 服务（P0-3 修复：数据不出网，默认离线）。

默认引擎：离线哈希向量（services.offline_embedder），零依赖、零网络、无需下载模型。
可选升级：EMBEDDING_BACKEND=bge 时使用本地 bge-small-zh（fastembed），
          仅当模型已缓存时生效，否则自动回退离线引擎。
在线 API：仅当 generate_embeddings(allow_online=True) 显式开启时才会调用，
          默认路径绝不联网——从根上杜绝「每次 RAG 问答都调在线接口」的数据泄露。
"""

from __future__ import annotations

import os
import time
from typing import List, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session

from services.dbapi_compat import wrap_conn
from models import AIProvider, KnowledgeChunk

# 离线引擎配置
OFFLINE_DIM = 512  # 与 bge-small-zh 对齐

# 在线 API 配置（仅 allow_online=True 时回退用）
DEFAULT_EMBEDDING_MODELS = {
    "doubao": "doubao-embedding-text-240715",
    "qwen": "text-embedding-v2",
    "gpt": "text-embedding-3-small",
    "openai": "text-embedding-3-small",
}
BATCH_SIZE = 32

# 全局本地模型实例（懒加载单例，bge/fastembed）
_local_model = None
_local_model_loaded = False
_local_model_error = None


def _get_local_model():
    """懒加载本地 bge embedding 模型（单例）。

    支持国内镜像站 hf-mirror.com，避免 HuggingFace 连接超时。
    """
    global _local_model, _local_model_loaded, _local_model_error
    if _local_model_loaded:
        return _local_model
    if _local_model_error:
        return None

    try:
        # 设置国内镜像站（避免 HuggingFace 连接超时）
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

        from fastembed import TextEmbedding
        cache_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "embedding_models"
        )
        os.makedirs(cache_dir, exist_ok=True)
        _local_model = TextEmbedding(
            model_name="BAAI/bge-small-zh-v1.5",
            cache_dir=cache_dir,
        )
        _local_model_loaded = True
        return _local_model
    except Exception as e:
        _local_model_error = str(e)
        print(f"[embedding] 本地 bge 模型加载失败: {e}")
        return None


def is_local_model_available() -> bool:
    """检查本地 bge embedding 模型是否可用。"""
    return _get_local_model() is not None


def get_local_model_info() -> dict:
    """获取本地模型信息。"""
    return {
        "model_name": "BAAI/bge-small-zh-v1.5",
        "dim": 512,
        "available": is_local_model_available(),
        "error": _local_model_error,
    }


def generate_local_embeddings(texts: List[str]) -> List[np.ndarray]:
    """使用本地 bge 模型生成 embedding 向量（需模型已缓存）。"""
    model = _get_local_model()
    if model is None:
        raise RuntimeError(f"本地 bge 模型不可用: {_local_model_error}")
    embeddings = list(model.embed(texts))
    return [np.array(emb, dtype=np.float32) for emb in embeddings]


class EmbeddingService:
    """Embedding 生成服务（默认离线，在线 opt-in）。"""

    def __init__(self, db: Session):
        self.db = db

    async def generate_embeddings(
        self, texts: List[str], allow_online: bool = False
    ) -> Tuple[List[np.ndarray], str]:
        """批量生成 embedding 向量。

        引擎选择：
          1) EMBEDDING_BACKEND=bge 且 bge 模型已缓存 -> 本地 bge（质量最高）
          2) 否则 -> 离线哈希引擎（默认，零依赖零网络）✅
          3) 仅当 allow_online=True 且上述都失败 -> 在线 API（数据出网）

        Returns:
            (向量列表, 引擎名 "bge" / "offline" / "online" / "none")
        """
        if not texts:
            return [], "none"

        backend = os.environ.get("EMBEDDING_BACKEND", "bge").lower()

        # 1) 可选：本地 bge（仅在显式开启且模型已缓存时）
        if backend == "bge":
            try:
                embeddings = generate_local_embeddings(texts)
                return embeddings, "bge"
            except Exception as e:
                print(f"[embedding] bge 不可用，回退离线引擎: {e}")

        # 2) 默认：离线哈希引擎（绝不联网）
        try:
            from services.offline_embedder import OfflineEmbedder
            emb = OfflineEmbedder()
            return emb.embed(texts), "offline"
        except Exception as e:
            print(f"[embedding] 离线引擎异常: {e}")

        # 3) 仅显式允许时才联网（数据会出网，谨慎使用）
        if allow_online:
            try:
                embeddings = await self._generate_online_embeddings(texts)
                return embeddings, "online"
            except Exception as e:
                raise RuntimeError(f"本地与在线 embedding 均失败: {e}")

        raise RuntimeError("embedding 生成失败：本地离线引擎不可用")

    async def _generate_online_embeddings(self, texts: List[str]) -> List[np.ndarray]:
        """使用在线 API 生成 embedding（回退路径，allow_online 时启用）。"""
        import httpx

        provider = self._get_embedding_provider()
        if not provider:
            raise RuntimeError("没有可用的在线 embedding 服务商")

        url = self._get_embedding_url(provider)
        model = self._get_model_name(provider)
        headers = self._build_headers(provider)

        all_embeddings = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            payload = {"model": model, "input": batch}
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            batch_embeddings = [
                np.array(item["embedding"], dtype=np.float32)
                for item in data.get("data", [])
            ]
            all_embeddings.extend(batch_embeddings)
        return all_embeddings

    def _get_embedding_provider(self) -> Optional[AIProvider]:
        for ptype in ["doubao", "qwen", "gpt", "openai"]:
            provider = (
                self.db.query(AIProvider)
                .filter(AIProvider.provider_type == ptype, AIProvider.is_enabled == True)
                .first()
            )
            if provider:
                return provider
        return (
            self.db.query(AIProvider)
            .filter(AIProvider.is_enabled == True)
            .order_by(AIProvider.fallback_priority.asc())
            .first()
        )

    def _get_embedding_url(self, provider: AIProvider) -> str:
        base = (provider.base_url or "").rstrip("/")
        if not base:
            base = {
                "doubao": "https://ark.cn-beijing.volces.com/api/v3",
                "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "gpt": "https://api.openai.com/v1",
                "openai": "https://api.openai.com/v1",
            }.get(provider.provider_type or "", "https://api.openai.com/v1")
        return f"{base}/embeddings"

    def _get_model_name(self, provider: AIProvider) -> str:
        return provider.model_name or DEFAULT_EMBEDDING_MODELS.get(
            provider.provider_type or "", "text-embedding-3-small"
        )

    def _build_headers(self, provider: AIProvider) -> dict:
        return {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }


async def build_all_embeddings(
    db: Session, force: bool = False, batch_size: int = 100, progress_callback=None
) -> dict:
    """为 knowledge_chunks 构建向量索引（默认完全离线）。

    Args:
        force: 是否清空旧向量并整体重建（保证维度/引擎一致）
        batch_size: 批大小
        progress_callback: 进度回调 (done, total)
    """
    from services.search_service import ensure_vec_table

    conn = wrap_conn(db.connection().connection)
    ensure_vec_table(conn)

    # ---- PostgreSQL：转交权威向量路径 ----
    #
    # 下面的分支写的是 SQLite 时代的镜像表 `knowledge_chunks_vec`，而 PG 侧：
    #   1. 该表**不存在** —— `ensure_vec_table` 对 PG 直接 return
    #      （权威表是 core/sql/020 建好的 `chunk_vectors` + pgvector HNSW）；
    #   2. 用的是 `INSERT OR REPLACE`，PG 无法识别，适配层也改不了
    #      （缺冲突键信息，只能原样透传 → 语法错误）。
    #
    # 结果：用户在界面上点"重建向量"**必定失败**（表不存在 + 语法错误）。
    # 这里转交 services/vector_builder.py —— 与 CLI 灌库脚本同一份实现，
    # 避免两条路径再次漂移。
    from services.dbapi_compat import is_sqlite

    if not is_sqlite(conn):
        from services.vector_builder import build_pg_vectors

        raw = db.connection().connection  # 裸 psycopg 连接
        res = build_pg_vectors(
            raw,
            generate_local_embeddings,
            rebuild=force,
            batch=batch_size,
            on_progress=progress_callback,
        )
        return {
            "total": res["total"],
            "built": res["inserted"],
            "skipped": res["skipped"],
            "failed": res["failed"],
            "rate_per_sec": round(res["rate"], 2),
            "elapsed_sec": round(res["elapsed"], 1),
            "engine": "pgvector:bge",
            "local_model": get_local_model_info(),
            "table": "chunk_vectors",
        }

    # 清空旧向量，避免混用不同引擎/维度导致召回噪声
    if force:
        conn.execute("DELETE FROM knowledge_chunks_vec")
        conn.commit()

    # 查询待构建向量（缺失）的分块
    rows = conn.execute("""
        SELECT kc.id, kc.document_id, kc.subject, kc.text
        FROM knowledge_chunks kc
        LEFT JOIN knowledge_chunks_vec kv ON kc.id = kv.chunk_id
        WHERE kv.chunk_id IS NULL AND kc.text IS NOT NULL AND kc.text != ''
    """).fetchall()

    total = len(rows)
    if total == 0:
        return {"total": 0, "built": 0, "skipped": 0, "engine": "none", "message": "所有分块已有向量"}

    svc = EmbeddingService(db)
    built = 0
    failed = 0
    engine_used = "unknown"

    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        texts = [r[3] or "" for r in batch]
        try:
            embeddings, engine_used = await svc.generate_embeddings(texts)
            for j, row in enumerate(batch):
                if j < len(embeddings):
                    vec_bytes = embeddings[j].tobytes()
                    dim = len(embeddings[j])
                    conn.execute(
                        """INSERT OR REPLACE INTO knowledge_chunks_vec
                           (chunk_id, document_id, subject, embedding, dim)
                           VALUES (?, ?, ?, ?, ?)""",
                        (row[0], row[1], row[2], vec_bytes, dim),
                    )
                    built += 1
                else:
                    failed += 1
            conn.commit()
            if progress_callback:
                progress_callback(min(i + batch_size, total), total)
        except Exception as e:
            print(f"[embedding] 批量构建失败 (batch {i}): {e}")
            failed += len(batch)

    return {
        "total": total,
        "built": built,
        "failed": failed,
        "engine": engine_used,
        "local_model": get_local_model_info(),
    }
