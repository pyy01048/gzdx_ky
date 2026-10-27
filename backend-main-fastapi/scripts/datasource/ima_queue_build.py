"""Build the prioritized IMA full-text ingest queue from the REAL kaoyan.db.

The queue joins `documents` (subject_source='ima', no usable content yet) with
the staging inventory `ima_inventory.db` (table `ima_items`) so that only items
whose `can_fetch_content` is true are scheduled.

Priority (user-defined):
    数模电 > 408 > 公共课-数学 > 信号与系统 > 公共课-政治 > 公共课-英语 > 其他

Within a subject, richer media types go first: PDF(1) > WORD(3) > IMAGE(9),
then larger files, then title, then id for a stable order.

Output: ima_pending_queue.json  (list of {doc_id, media_id, title, subject,
media_type, folder_path, rank}).  Already-processed doc_ids listed in
ima_ingest_done.json are skipped, which makes the script safe to re-run.

Usage:
    python ima_queue_build.py [--limit N] [--subject 数模电]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List

REAL_DB = r"D:\平台\database\kaoyan.db"
INVENTORY_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ima_inventory.db")
QUEUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ima_pending_queue.json")
DONE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ima_ingest_done.json")

# Lower number = higher priority.
SUBJECT_PRIORITY: Dict[str, int] = {
    "数模电": 0,
    "408": 1,
    "公共课-数学": 2,
    "信号与系统": 3,
    "公共课-政治": 4,
    "公共课-英语": 5,
    "其他": 6,
}
DEFAULT_PRIORITY = 7

# Lower number = fetched first inside a subject (PDF/WORD are richer than OCR images).
MEDIA_TYPE_PRIORITY: Dict[int, int] = {1: 0, 3: 1, 9: 2}


def load_done() -> set:
    """Return the set of doc_ids whose content has already been ingested."""
    if not os.path.exists(DONE_PATH):
        return set()
    with open(DONE_PATH, "r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except ValueError:
            return set()
    return {int(x) for x in data.get("done", [])}


def build(limit: int = 0, subject: str = "") -> List[Dict[str, Any]]:
    """Return the prioritized queue, excluding already-done documents."""
    done = load_done()
    conn = sqlite3.connect(INVENTORY_DB, timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("ATTACH DATABASE ? AS realdb", (REAL_DB,))
        rows = conn.execute(
            """
            SELECT d.id, d.ima_media_id, d.file_name, d.subject,
                   i.media_type, i.folder_path, i.file_size
            FROM realdb.documents d
            JOIN main.ima_items i ON i.media_id = d.ima_media_id
            WHERE d.subject_source = 'ima'
              AND (d.content IS NULL OR LENGTH(d.content) < 1000)
              AND i.can_fetch_content = 1
            """,
        ).fetchall()
    finally:
        conn.close()

    items: List[Dict[str, Any]] = []
    for doc_id, media_id, file_name, subj, media_type, folder_path, file_size in rows:
        items.append({
            "doc_id": doc_id,
            "media_id": media_id or "",
            "title": file_name or "",
            "subject": subj or "",
            "media_type": media_type,
            "folder_path": folder_path or "",
            "file_size": file_size or 0,
            "subj_rank": SUBJECT_PRIORITY.get(subj or "", DEFAULT_PRIORITY),
            "media_rank": MEDIA_TYPE_PRIORITY.get(media_type, 9),
        })

    items = [it for it in items if it["doc_id"] not in done]
    if subject:
        items = [it for it in items if it["subject"] == subject]
    items.sort(key=lambda it: (it["subj_rank"], it["media_rank"],
                               -it["file_size"], it["title"], it["doc_id"]))
    if limit:
        items = items[:limit]
    for index, item in enumerate(items):
        item["rank"] = index
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=0, help="keep only the first N items")
    parser.add_argument("--subject", default="", help="restrict to one subject")
    args = parser.parse_args()

    items = build(args.limit, args.subject)
    with open(QUEUE_PATH, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=2)

    by_subject: Dict[str, int] = {}
    for item in items:
        key = "%s(p%d)" % (item["subject"], item["subj_rank"])
        by_subject[key] = by_subject.get(key, 0) + 1
    print("queue -> %s  (%d items)" % (QUEUE_PATH, len(items)))
    for key in sorted(by_subject, key=lambda k: int(k.split("(p")[1].rstrip(")"))):
        print("   %-20s %d" % (key, by_subject[key]))
    for item in items[:15]:
        print("   #%-3d doc=%-6s %-6s %s" % (item["rank"], item["doc_id"],
                                             item["subject"], item["title"][:48]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
