# -*- coding: utf-8 -*-
"""分块章节挂接：按「章号标记传播法」给 knowledge_chunks 补 chapter_id（PG，幂等）。

### 背景（2026-10-20 实测）
- `documents.chapter_id` / `documents.chapter` 全空（0/705）
- `knowledge_chunks.chapter_id` 全空（0/20,676）
- `knowledge_chunks.l2_chapter` 全 NULL
即整条章节链路都没有元数据，无法靠继承挂接。

### 办法：章号标记传播
教材正文里每章开头一般有「第 3 章」「第三章」「3.1」这类标记。按
(document_id, chunk_index) 顺序扫描：
  1. 命中章号标记 → 记为本文档的 current_chapter
  2. 后续 chunk 一律归入 current_chapter，直到下一个章号
  3. 只在本文档内传播，不跨文档
比"只给含章号的 chunk 挂接"覆盖率高一个量级（章号通常只出现在章首一两块）。

### 匹配规则
章号 N → `subject_chapters.code = 'ch{N:02d}'` 且 `subject_id` 相同。
找不到对应章节就不挂（宁缺勿错）。

用法：
    python scripts/link_chunks_chapter_propagate.py --dry-run
    python scripts/link_chunks_chapter_propagate.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

CN_DIGIT = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
            "十一": 11, "十二": 12, "十三": 13, "十四": 14,
            "十五": 15, "十六": 16, "十七": 17, "十八": 18,
            "十九": 19, "二十": 20}

#: 章号标记：第3章 / 第三章 / 第 3 章 / 第3章：xxx / CHAPTER 3
RE_CHAPTER = re.compile(
    r"(?:第\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*章)"
    r"|(?:CHAPTER\s*([0-9]{1,2}))",
    re.IGNORECASE,
)
#: 小节号（3.1 / 3.1.2）——只有在同一章内出现时才用于校验，不单独跨章
RE_SECTION = re.compile(r"(?<![\d.])([0-9]{1,2})\.([0-9]{1,2})(?:\.[0-9]{1,2})?(?![\d.])")

HEAD_LEN = 400   # 只看块首若干字，避免正文里的「第3章」引用造成误判


def parse_chapter_no(text: str) -> int | None:
    """从文本里取第一个章号；没有返回 None。"""
    m = RE_CHAPTER.search(text or "")
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    return CN_DIGIT.get(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description="分块章节挂接（章号标记传播）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--head-len", type=int, default=HEAD_LEN)
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")

    with psycopg.connect(pg_database_url(), autocommit=False) as pg, pg.cursor() as cur:
        # 章节索引：subject_id -> {章号: chapter_id}
        cur.execute("SELECT id, subject_id, code FROM subject_chapters WHERE is_active IS NOT FALSE")
        chap_map: dict[tuple[int, int], int] = {}
        for cid, sid, code in cur.fetchall():
            m = re.fullmatch(r"ch0*([0-9]{1,2})", (code or "").strip(), re.IGNORECASE)
            if m:
                chap_map[(sid, int(m.group(1)))] = cid
        print(f"章节索引：{len(chap_map)} 条（subject_id, 章号）→ chapter_id")

        # 逐文档顺序扫描
        cur.execute("""
            SELECT id, document_id, chunk_index, subject_id, left(coalesce(text,''), %s)
            FROM knowledge_chunks
            WHERE chapter_id IS NULL
            ORDER BY document_id, chunk_index
        """, (args.head_len,))
        rows = cur.fetchall()
        print(f"待挂接分块：{len(rows)}")

        updates: list[tuple[int, int]] = []
        stats = {"doc_with_marker": 0, "unmatched_chapter": 0}
        cur_doc = None
        current: int | None = None
        seen_doc: set[int] = set()
        for cid, doc_id, idx, sid, head in rows:
            if doc_id != cur_doc:
                cur_doc, current = doc_id, None
            no = parse_chapter_no(head)
            if no is not None:
                current = no
                if doc_id not in seen_doc:
                    stats["doc_with_marker"] += 1
                    seen_doc.add(doc_id)
            if current is None:
                continue
            if sid is None:
                continue
            chapter_id = chap_map.get((sid, current))
            if chapter_id is None:
                stats["unmatched_chapter"] += 1
                continue
            updates.append((chapter_id, cid))

        print(f"可挂接：{len(updates)} 个分块"
              f"（覆盖 {len(updates)/max(1,len(rows)):.1%}）")
        print(f"有章号标记的文档：{stats['doc_with_marker']}；"
              f"章号在章节表里找不到：{stats['unmatched_chapter']} 块")

        if args.dry_run:
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        # 分批 UPDATE，避免单次参数过多
        BATCH = 2000
        total = 0
        for i in range(0, len(updates), BATCH):
            chunk = updates[i:i + BATCH]
            cur.executemany(
                "UPDATE knowledge_chunks SET chapter_id=%s, updated_at=now() WHERE id=%s",
                chunk,
            )
            total += len(chunk)
            print(f"  写入 {total}/{len(updates)}")

        pg.commit()
        cur.execute("SELECT count(*) FILTER (WHERE chapter_id IS NOT NULL), count(*) FROM knowledge_chunks")
        linked, alln = cur.fetchone()
        print(f"\n[OK] 分块章节覆盖：{linked}/{alln}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
