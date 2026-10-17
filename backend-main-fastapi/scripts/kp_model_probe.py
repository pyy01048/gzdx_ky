# -*- coding: utf-8 -*-
"""知识点抽取模型实测探针（只读探测，不落库）。

用途：在真实 chunk 上对比候选模型的**耗时**与**产出质量**，用于决定分批回填
用哪个模型、能跑多少篇。

用法：
    python scripts/kp_model_probe.py [--models qwen2.5-coder:7b,...] [--doc-id 11] [--chunks 1]

说明：
* 只调 `services.kp_extract._extract_from_chunk`（单块抽取 + 质量门禁），
  **不写库**，因此可以随时安全重跑。
* 模型通过环境变量 `SMART_INGEST_KP_MODEL` 覆盖（kp_extract 第 107 行读取），
  这里直接改模块属性 `kp_extract.KP_MODEL`，避免重复 import。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402

PG_URL = "postgresql+psycopg://kaoyan:kaoyan_dev_2026@127.0.0.1:5432/kaoyan"


def _prose_score(s: str) -> float:
    """正文度：中文占比 × 句子标点密度 —— 用来避开目录页/纯标题块。

    目录页（「第七章 微分方程 习题7-1 …」）几乎没有句号，模型正确地返回 []，
    但拿它测耗时会严重低估真实开销，因此探针默认挑正文度最高的块。
    """
    import re

    s = s or ""
    if not s:
        return 0.0
    cjk = len(re.findall(r"[\u4e00-\u9fa5]", s))
    sent = len(re.findall(r"[。；！？]", s))
    return (cjk / len(s)) * (sent + 1)


def load_chunk(doc_id: int, idx: int = 0, pick: str = "best"):
    """从库里取一篇文档，按 kp_extract 的同一套分块逻辑切块。

    Args:
        pick: `best` = 正文度最高的块（默认，避开目录页）；`idx` = 按下标取。
    """
    from services.document_analyzer import smart_chunk_text

    eng = create_engine(PG_URL)
    with eng.connect() as c:
        row = c.execute(
            text("SELECT id, file_name, subject, content FROM documents WHERE id=:d"),
            {"d": doc_id},
        ).fetchone()
    if not row:
        raise SystemExit(f"doc#{doc_id} 不存在")
    body = (row[3] or "").strip()
    chunks = smart_chunk_text(body, max_chunk_size=3000, overlap=200)
    if not chunks:
        raise SystemExit(f"doc#{doc_id} 分块为空（正文 {len(body)} 字）")
    if pick == "best":
        scored = sorted(
            range(len(chunks)),
            key=lambda i: _prose_score(chunks[i].get("text") or ""),
            reverse=True,
        )
        idx = scored[0]
    ch = chunks[idx % len(chunks)]
    ch["index"] = idx
    return {
        "doc_id": row[0],
        "file_name": row[1],
        "subject": row[2],
        "total_chunks": len(chunks),
        "body_chars": len(body),
        "chunk": ch,
    }


def probe(model: str, payload: dict, timeout: float):
    """用指定模型对同一块跑一次抽取，返回统计。"""
    import services.kp_extract as kp

    kp.KP_MODEL = model
    kp.KP_TIMEOUT = timeout
    t0 = time.time()
    st = kp._extract_from_chunk(
        payload["chunk"],
        file_name=payload["file_name"],
        doc_subject=payload["subject"] or "",
        doc_chapter="",
        doc_id=payload["doc_id"],
        chunk_row_id=None,
    )
    secs = round(time.time() - t0, 1)
    items = st.get("items") or []
    return {
        "model": model,
        "seconds": secs,
        "kept": len(items),
        "dropped": st.get("dropped", 0),
        "failed": st.get("failed", 0),
        "error": st.get("error", ""),
        "items": [
            {"name": it["name"], "subject": it["subject"],
             "subject_source": it["subject_source"],
             "desc": it["description"][:120]}
            for it in items[:6]
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc-id", type=int, default=11)
    ap.add_argument("--chunk-idx", type=int, default=0)
    ap.add_argument("--pick", choices=("best", "idx"), default="best",
                    help="best=正文度最高的块（默认，避开目录页）；idx=按 --chunk-idx 取")
    ap.add_argument("--timeout", type=float, default=420.0)
    ap.add_argument("--models", default="qwen2.5-coder:7b")
    ap.add_argument("--out", default="scripts/_logs/kp_model_probe.json")
    args = ap.parse_args()

    payload = load_chunk(args.doc_id, args.chunk_idx, args.pick)
    print(f"[doc#{payload['doc_id']}] {payload['file_name']} "
          f"subject={payload['subject']} 正文={payload['body_chars']}字 "
          f"块数={payload['total_chunks']}", flush=True)
    print(f"[chunk#{args.chunk_idx}] 字数="
          f"{len(payload['chunk'].get('text') or '')} "
          f"heading={payload['chunk'].get('heading')!r}", flush=True)
    print(f"[preview] {(payload['chunk'].get('text') or '')[:200]!r}\n", flush=True)

    results = []
    for m in [x.strip() for x in args.models.split(",") if x.strip()]:
        print(f"--- probing {m} ...", flush=True)
        try:
            r = probe(m, payload, args.timeout)
        except Exception as e:  # noqa: BLE001
            r = {"model": m, "seconds": -1, "kept": 0, "error":
                 f"{type(e).__name__}: {e}"[:300], "items": []}
        results.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=2), flush=True)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"doc": {k: v for k, v in payload.items() if k != "chunk"},
                   "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\n[saved] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
