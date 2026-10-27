# -*- coding: utf-8 -*-
"""纯章号知识点 → subject_chapters 挂接（PG，幂等）。

场景：knowledge_points.chapter 只有「第1章」「第一章」「1.2.3」这类章号，
link_kp_chapters.py 不敢挂；本脚本只在**同科目内唯一命中**时挂接。

用法：
    python scripts/link_pure_chapters.py --dry-run
    python scripts/link_pure_chapters.py --apply
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

CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def chapter_no(text: str | None) -> int | None:
    t = (text or "").strip()
    if not t:
        return None
    m = re.match(r"^(?:第\s*)?([0-9一二三四五六七八九十]+)\s*章$", t)
    if not m:
        m = re.match(r"^(\d+)(?:\.\d+)*$", t)
    if not m:
        return None
    raw = m.group(1)
    return int(raw) if raw.isdigit() else CN.get(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    with psycopg.connect(pg_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, subject_id, chapter
                FROM knowledge_points
                WHERE chapter_id IS NULL AND chapter IS NOT NULL AND btrim(chapter) <> ''
            """)
            rows = cur.fetchall()

            updates = []
            for kid, sid, ch in rows:
                no = chapter_no(ch)
                if no is None:
                    continue
                cur.execute("""
                    SELECT id, title FROM subject_chapters
                     WHERE subject_id = %s AND title LIKE %s
                """, (sid, f"第{no}章%"))
                matches = cur.fetchall()
                if len(matches) == 1:
                    updates.append((kid, matches[0][0], matches[0][1]))

        print(f"可唯一挂接 {len(updates)} / {len(rows)} 个纯章号知识点")
        for row in updates[:15]:
            print("  ", row)
        if not apply:
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        with conn.cursor() as cur:
            for kid, cid, title in updates:
                cur.execute("""
                    UPDATE knowledge_points
                       SET chapter_id = %s, chapter = %s
                     WHERE id = %s AND chapter_id IS NULL
                """, (cid, title, kid))
        conn.commit()
        print(f"已挂接 {len(updates)} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
