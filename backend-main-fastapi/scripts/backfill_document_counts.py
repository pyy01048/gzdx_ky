# -*- coding: utf-8 -*-
"""回填 documents 的两列计数：chunk_count / knowledge_point_count（PG，幂等）。

### 背景（2026-10-21 体检 D2）
- `documents.chunk_count` 列存在，但旧版 `models.py::Document` 没有映射它，
  `smart_ingest` 里的 `doc.chunk_count = n` 只是挂了个 Python 属性，从未落库
  —— 705 篇文档该列全是 0。
- `routers/imports.py` 曾把分块数误写进 `knowledge_point_count`，导致这一列
  名不副实（数字是 chunk 数而不是知识点数）。

### 规则
- `chunk_count` = `knowledge_chunks` 中该文档的实际行数
- `knowledge_point_count` = `knowledge_points` 中该文档的实际行数
- 幂等：只更新与实测值不一致的行

用法：
    python scripts/backfill_document_counts.py --dry-run
    python scripts/backfill_document_counts.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

_DRIFT_SQL = """
SELECT d.id,
       d.file_name,
       d.chunk_count            AS old_chunks,
       COALESCE(c.n, 0)         AS new_chunks,
       d.knowledge_point_count  AS old_kps,
       COALESCE(k.n, 0)         AS new_kps
FROM documents d
LEFT JOIN (SELECT document_id, count(*) AS n FROM knowledge_chunks GROUP BY document_id) c
       ON c.document_id = d.id
LEFT JOIN (SELECT document_id, count(*) AS n FROM knowledge_points GROUP BY document_id) k
       ON k.document_id = d.id
WHERE d.chunk_count IS DISTINCT FROM COALESCE(c.n, 0)
   OR d.knowledge_point_count IS DISTINCT FROM COALESCE(k.n, 0)
ORDER BY d.id
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 documents 的 chunk_count / knowledge_point_count")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")

    with psycopg.connect(pg_database_url(), autocommit=False) as pg, pg.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents")
        total_docs = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM knowledge_chunks")
        total_chunks = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM knowledge_points")
        total_kps = cur.fetchone()[0]

        cur.execute(_DRIFT_SQL)
        rows = cur.fetchall()

        chunk_drift = sum(1 for r in rows if r[2] != r[3])
        kp_drift = sum(1 for r in rows if r[4] != r[5])

        print(f"documents: {total_docs} 篇 | knowledge_chunks: {total_chunks} | knowledge_points: {total_kps}")
        print(f"需回填: chunk_count {chunk_drift} 篇, knowledge_point_count {kp_drift} 篇（合计 {len(rows)} 篇有偏差）")
        for r in rows[:15]:
            print(f"  doc {r[0]} {r[1]!r}: chunks {r[2]}→{r[3]}, kps {r[4]}→{r[5]}")

        if args.dry_run:
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        cur.executemany(
            "UPDATE documents SET chunk_count=%s, knowledge_point_count=%s, updated_at=now()"
            " WHERE id=%s",
            [(r[3], r[5], r[0]) for r in rows],
        )
        pg.commit()
        print(f"\n[APPLY] 已更新 {len(rows)} 篇。")

        cur.execute(_DRIFT_SQL)
        remain = cur.fetchall()
        print(f"[VERIFY] 回填后仍有偏差: {len(remain)} 篇")
        return 0 if not remain else 1


if __name__ == "__main__":
    raise SystemExit(main())
