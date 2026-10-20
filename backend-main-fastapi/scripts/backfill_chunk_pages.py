# -*- coding: utf-8 -*-
"""分块页码回填：从 chunk 文本里的 OCR 页码标记提取 page_start/page_end（PG，幂等）。

### 背景（2026-10-20 实测）
- `knowledge_chunks.page_start/page_end` 全 NULL（20,676 条）
- 但 **11,348 条** chunk 文本里嵌着入库时留下的页码标记：`--- 第20页(OCR) ---`
- 答疑链路已能带引用，但因为页码为空只能显示「第 N 段」——回填后自动变「第 X 页」

### 规则
1. 只认**精确标记格式** `--- 第N页(OCR) ---`，不认正文里出现的「第N页」（那是书内引用，不是物理页）
2. 一个 chunk 跨多页 → `page_start=最小页`，`page_end=最大页`
3. 没有标记的 chunk 保持 NULL（docx/doc 本来没有物理页）
4. 幂等：只更新 page_start 为 NULL 的行

用法：
    python scripts/backfill_chunk_pages.py --dry-run
    python scripts/backfill_chunk_pages.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

#: 入库时写入的物理页标记，形如 “--- 第20页(OCR) ---”
RE_PAGE_MARK = re.compile(r"---\s*第\s*([0-9]{1,4})\s*页\s*\(OCR\)\s*---")


def main() -> int:
    ap = argparse.ArgumentParser(description="分块页码回填")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")

    with psycopg.connect(pg_database_url(), autocommit=False) as pg, pg.cursor() as cur:
        cur.execute("""
            SELECT id, text FROM knowledge_chunks
            WHERE page_start IS NULL AND text LIKE '%(OCR) ---%'
        """)
        rows = cur.fetchall()
        print(f"待处理分块（page_start 为空且含标记）：{len(rows)}")

        updates: list[tuple[int, int, int]] = []
        multi = 0
        for cid, text in rows:
            pages = [int(m) for m in RE_PAGE_MARK.findall(text or "")]
            if not pages:
                continue
            lo, hi = min(pages), max(pages)
            if lo != hi:
                multi += 1
            updates.append((lo, hi, cid))

        print(f"可回填：{len(updates)} 个分块（其中跨页 {multi} 个）")

        if args.dry_run:
            for lo, hi, cid in updates[:10]:
                print(f"  chunk {cid} → p{lo}" + (f"-{hi}" if hi != lo else ""))
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        BATCH = 2000
        total = 0
        for i in range(0, len(updates), BATCH):
            chunk = updates[i:i + BATCH]
            cur.executemany(
                "UPDATE knowledge_chunks SET page_start=%s, page_end=%s, updated_at=now()"
                " WHERE id=%s",
                chunk,
            )
            total += len(chunk)
            print(f"  写入 {total}/{len(updates)}")
        pg.commit()

        cur.execute("SELECT count(*) FILTER (WHERE page_start IS NOT NULL), count(*) FROM knowledge_chunks")
        filled, alln = cur.fetchone()
        print(f"\n[OK] 页码覆盖：{filled}/{alln}（{filled/alln:.1%}）")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
