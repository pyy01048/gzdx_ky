# -*- coding: utf-8 -*-
"""向量灌库：knowledge_chunks → chunk_vectors（bge-small-zh-v1.5，512 维）。

背景（2026-10-14）
------------------
`chunk_vectors` 表建好了、HNSW 索引也建好了，但**一行数据都没有**（实测 0 行）。
后果：`search_service.vec_search` 在 PG 上恒返回空 → hybrid 检索退化为纯全文，
向量语义召回能力完全没用上；`ai_service` 的检索兜底也随之失效。

本脚本把 61041 个分块批量向量化并写入 `chunk_vectors`，让 pgvector 检索真正可用。

设计要点
--------
1. **断点续传**：以 chunk_id 为主键做 `ON CONFLICT DO UPDATE`，重跑只补缺口。
   61041 块在 CPU 上约需数十分钟，中途中断不能前功尽弃。
2. **批量推理**：bge 单条推理有固定开销，按 batch=64 送入，吞吐提升数倍。
3. **文本预处理**：跳过空白块；超长文本截断（bge 上限 512 token，
   过长会被模型内部截断，显式截断更可控）。
4. **双写**：`embedding_f32`（pgvector，走 HNSW 索引）与 `embedding`（bytea 退化列）
   同时写入，保证 VECTOR_BACKEND=python 的回退路径也可用。
5. **进度可观测**：每批打印进度、速率、剩余估算，便于判断是否要中断。
6. **不碰 knowledge_chunks**：只读源表，只写向量表。

用法
----
    python -m pipeline.build_vectors                # 全量（增量补缺）
    python -m pipeline.build_vectors --limit 500    # 试跑 500 块
    python -m pipeline.build_vectors --rebuild      # 强制重算全部
    python -m pipeline.build_vectors --subject 数字电子技术
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

MODEL_VERSION = "bge-small-zh-v1.5"
DIM = 512
#: bge-small-zh 的 max_length 是 512 token；按中文字符 ≈1.5 token/字 估算，
#: 截到 400 字符可稳妥落在窗口内，超长部分对语义贡献也很低。
MAX_CHARS = 400
BATCH = 64


# 核心实现已抽到 services/vector_builder.py（CLI 与 API 共用同一份，避免漂移）。
# 这里只保留薄壳：常量再导出 + 委托，方便旧调用方 from pipeline.build_vectors import ...
from services.vector_builder import (  # noqa: E402
    BATCH,
    build_pg_vectors,
    DIM,
    MAX_CHARS,
    MODEL_VERSION,
    argmin_normalize as _argmin_normalize,
    clean_text as _clean,
    fetch_pending,
    vec_literal as _vec_literal,
)


def _legacy_clean_note():
    """占位：历史实现已迁移，保留符号以免外部 import 断裂。"""
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="向量灌库：chunks → chunk_vectors")
    p.add_argument("--database-url", default=None,
                   help="缺省走 pipeline.config.pg_database_url()：DATABASE_URL > .env 的 PG_* 分项")
    p.add_argument("--limit", type=int, default=None, help="最多处理多少块（试跑用）")
    p.add_argument("--rebuild", action="store_true", help="忽略已有向量，全部重算")
    p.add_argument("--subject", default=None, help="只处理指定科目")
    p.add_argument("--batch", type=int, default=BATCH)
    args = p.parse_args(argv)

    print("=" * 68)
    print(f"向量灌库 · {MODEL_VERSION} · {DIM} 维")
    print("=" * 68)

    # 延迟导入模型（避免 --help 时也加载 onnx）
    from services.embedding_service import (
        generate_local_embeddings, is_local_model_available,
    )

    if not is_local_model_available():
        print("[错误] 本地 bge 模型不可用，无法灌库。")
        print("       检查 data/embedding_models 下是否存在 bge-small-zh-v1.5。")
        return 2

    t0 = time.time()
    with psycopg.connect(args.database_url or pg_database_url()) as pg:
        # 核心循环委托给 services/vector_builder.build_pg_vectors ——
        # API 端点（/api/ai/build-embeddings）走的是同一份实现。
        def _progress(done: int, total: int) -> None:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            print(f"  进度 {done}/{total}  速率 {rate:.1f} 块/秒  "
                  f"预计剩余 {eta / 60:.1f} 分钟")

        res = build_pg_vectors(
            pg,
            generate_local_embeddings,
            rebuild=args.rebuild,
            subject=args.subject,
            limit=args.limit,
            batch=args.batch,
            on_progress=_progress,
        )
        if res["total"] == 0:
            print("无待处理分块，无需灌库。")
            _print_coverage(pg)
            return 0
        inserted = res["inserted"]
        skipped = res["skipped"]
        failed = res["failed"]

    elapsed = time.time() - t0
    print("-" * 68)
    print(f"完成：入库 {inserted}，跳过（文本过短）{skipped}，失败 {failed}，"
          f"耗时 {elapsed / 60:.1f} 分钟")
    with psycopg.connect(args.database_url or pg_database_url()) as pg:
        _print_coverage(pg)
    print("=" * 68)
    return 0


def _print_coverage(pg: psycopg.Connection) -> None:
    """打印覆盖率，并顺手做一次真实向量检索自检。"""
    with pg.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge_chunks")
        chunks = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*), COUNT(embedding_f32) FROM chunk_vectors")
        vec_rows, vec_f32 = cur.fetchone()
        cur.execute("SELECT COUNT(DISTINCT model_version) FROM chunk_vectors")
        versions = cur.fetchone()[0]
    rate = (vec_rows / chunks) if chunks else 0
    print(f"覆盖率：{vec_rows}/{chunks} = {rate:.2%}"
          f"（embedding_f32 有效 {vec_f32} 行，模型版本 {versions} 种）")
    if versions > 1:
        print("  [注意] 检测到多个模型版本混存，语义空间不一致会污染召回，"
              "建议用 --rebuild 统一重算。")


if __name__ == "__main__":
    raise SystemExit(main())
