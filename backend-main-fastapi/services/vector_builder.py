"""向量灌库核心（knowledge_chunks → chunk_vectors，pgvector）。

## 为什么抽成 service

原先这段逻辑只存在于 `pipeline/build_vectors.py`（CLI 脚本），而
`services/embedding_service.build_all_embeddings`（挂在
`POST /api/ai/build-embeddings` 上）维护了**另一套**实现，写的是
SQLite 时代的镜像表 `knowledge_chunks_vec`：

  * 该表在 PG 侧**不存在**（`search_service.ensure_vec_table` 对 PG 直接 return，
    权威表是 core/sql/020 建好的 `chunk_vectors`）；
  * 用的 `INSERT OR REPLACE` 是 SQLite 方言，PG 下是语法错误，
    适配层也无法自动改写（缺冲突键信息）。

结果：**用户在界面上点"重建向量"必定失败**（表不存在 + 语法错误）。
抽到这里让 CLI 与 API 走同一条已验证的路径，避免再次漂移。

## 表结构要点（实测踩坑）

`chunk_vectors` 有两个向量承载列：
  * `embedding`      BYTEA      —— 退化列，无 pgvector 时可用；
  * `embedding_f32`  vector(512) —— **HNSW 索引建在这一列**，检索走它。
两列必须**同时写**，否则要么检索用不上索引、要么维度校验不过。

向量必须做 ArgMin 归一化（bge 推荐）：不归一化时余弦距离虽仍可用，
但 `<=>` 的数值分布会漂，HNSW 的邻居图质量下降。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Optional, Sequence

import numpy as np

#: 与 pipeline/build_vectors.py 保持一致的常量（那里改这里就要改）
MODEL_VERSION = "bge-small-zh-v1.5"
DIM = 512
#: bge-small-zh 的 max_length 是 512 token；按中文 ≈1.5 token/字 估算，
#: 截到 400 字符可稳妥落在窗口内，超长部分对语义贡献也很低。
MAX_CHARS = 400
BATCH = 64


def clean_text(text: str) -> str:
    """向量化前的文本清洗：去控制字符、压缩空白、截断。

    换行会打断 bge 的注意力，压成单空格更稳。
    """
    if not text:
        return ""
    t = text.replace("\x00", " ")
    t = " ".join(t.split())
    return t[:MAX_CHARS]


def argmin_normalize(v: np.ndarray) -> np.ndarray:
    """ArgMin 归一化（bge 官方推荐）：把向量投影到单位球面。

    除以最小值而非 L2 范数 —— 对小模长向量的区分度更好。
    """
    arr = np.asarray(v, dtype=np.float32)
    if arr.ndim == 1:
        mn = float(arr.min())
        if mn == 0:
            return arr
        return arr - mn
    mn = arr.min(axis=1, keepdims=True)
    mn[mn == 0] = 1.0
    return arr - mn


def vec_literal(v: np.ndarray) -> str:
    """转成 pgvector 的字面量 `[0.1,0.2,...]`。

    走文本而非二进制：psycopg 没装 pgvector 适配器时也能用，
    代价是字符串略长（512 维约 6KB/行，可接受）。
    """
    return "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"


def fetch_pending(
    conn,
    *,
    rebuild: bool = False,
    subject: str | None = None,
    limit: int | None = None,
) -> list[tuple]:
    """取待处理分块 (chunk_id, document_id, subject_id, text)。

    增量模式只取 `chunk_vectors` 里没有的；rebuild 则全量。
    """
    where = ["kc.text IS NOT NULL", "kc.text != ''"]
    params: list[Any] = []
    if subject:
        where.append("kc.subject = %s")
        params.append(subject)

    if rebuild:
        sql = (
            "SELECT kc.id, kc.document_id, kc.subject_id, kc.text "
            "FROM knowledge_chunks kc "
            f"WHERE {' AND '.join(where)} ORDER BY kc.id"
        )
    else:
        sql = (
            "SELECT kc.id, kc.document_id, kc.subject_id, kc.text "
            "FROM knowledge_chunks kc "
            "LEFT JOIN chunk_vectors cv ON cv.chunk_id = kc.id "
            f"WHERE cv.chunk_id IS NULL AND {' AND '.join(where)} ORDER BY kc.id"
        )
    if limit:
        sql += f" LIMIT {int(limit)}"

    with conn.cursor() as cur:
        cur.execute(sql, params or None)
        return cur.fetchall()


_UPSERT = """
INSERT INTO chunk_vectors
    (chunk_id, document_id, subject_id, engine, dim,
     embedding, embedding_f32, model_version)
VALUES (%s,%s,%s,'bge'::vector_engine,%s,%s,%s::vector,%s)
ON CONFLICT (chunk_id) DO UPDATE
   SET embedding = EXCLUDED.embedding,
       embedding_f32 = EXCLUDED.embedding_f32,
       engine = EXCLUDED.engine,
       dim = EXCLUDED.dim,
       model_version = EXCLUDED.model_version
"""


def build_pg_vectors(
    conn,
    embed_fn: Callable[[Sequence[str]], Iterable[np.ndarray]],
    *,
    rebuild: bool = False,
    subject: str | None = None,
    limit: int | None = None,
    batch: int = BATCH,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """把待处理分块的文本向量化并 upsert 进 `chunk_vectors`。

    Args:
        conn: **psycopg** 连接（原生，不是 SQLAlchemy Session）。
        embed_fn: 接收一批文本、返回同长度向量列表的可调用对象（同步）。
            由调用方注入，避免本模块硬依赖某个模型后端。
        rebuild: 忽略已有向量，全量重算。
        subject: 只处理指定科目。
        limit: 最多处理多少块（试跑）。
        batch: 批大小。
        on_progress: (done, total) 回调。

    Returns:
        ``{"total","inserted","skipped","failed","rate","elapsed"}``
    """
    t0 = time.time()
    rows = fetch_pending(conn, rebuild=rebuild, subject=subject, limit=limit)
    total = len(rows)
    if not total:
        return {"total": 0, "inserted": 0, "skipped": 0, "failed": 0,
                "rate": 0.0, "elapsed": 0.0}

    bs = max(1, int(batch))
    inserted = skipped = failed = 0

    for i in range(0, total, bs):
        chunk = rows[i:i + bs]
        # 过短文本（纯符号/页码残留）不值得占用向量空间，直接跳过
        keep = [(r[0], r[1], r[2], clean_text(r[3] or "")) for r in chunk]
        keep = [k for k in keep if len(k[3]) >= 5]
        skipped += len(chunk) - len(keep)
        if not keep:
            if on_progress:
                on_progress(min(i + bs, total), total)
            continue

        texts = [k[3] for k in keep]
        try:
            vecs = list(embed_fn(texts))
        except Exception as exc:  # noqa: BLE001
            # 不静默：单批推理失败会静默少灌一批，覆盖率对不上却查不到原因
            import logging

            logging.getLogger(__name__).warning(
                "向量推理失败 batch=%s: %s", i // bs, str(exc)[:200]
            )
            failed += len(keep)
            continue

        if len(vecs) != len(keep):
            import logging

            logging.getLogger(__name__).warning(
                "向量数量不匹配 batch=%s: 期望 %s 实得 %s",
                i // bs, len(keep), len(vecs),
            )
            failed += len(keep)
            continue

        payload = []
        for (cid, did, sid, _t), v in zip(keep, vecs):
            v = argmin_normalize(np.asarray(v, dtype=np.float32))
            payload.append((cid, did, sid, DIM, v.tobytes(), vec_literal(v),
                            MODEL_VERSION))

        try:
            with conn.cursor() as cur:
                cur.executemany(_UPSERT, payload)
            conn.commit()
            inserted += len(payload)
        except Exception as exc:  # noqa: BLE001
            # 关键：必须 rollback —— PG 里失败会把事务打成 aborted，
            # 不 rollback 后续批次全部连锁失败（项目反复踩过的坑）
            conn.rollback()
            failed += len(payload)
            import logging

            logging.getLogger(__name__).warning(
                "向量写库失败 batch=%s: %s", i // bs, str(exc)[:200]
            )

        if on_progress:
            on_progress(min(i + bs, total), total)

    elapsed = time.time() - t0
    return {
        "total": total,
        "inserted": inserted,
        "skipped": skipped,
        "failed": failed,
        "rate": (inserted / elapsed) if elapsed else 0.0,
        "elapsed": elapsed,
    }
