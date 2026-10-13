"""Upsert one page/shard of IMA knowledge items into the staging SQLite DB.

Usage:
    python ima_upsert.py <payload.json> [...]   # one or more payload files
    python ima_upsert.py -                      # read a payload from stdin

Payload shape (compact keys keep the crawl's context cost low):
    {
      "folder_path": "考研资料数据集V1.0/数电资料",   # '' for KB root
      "scope": "ROOT" | "<folder_id>",               # for the page ledger
      "offset": 0,                                   # for the page ledger
      "parent_default": "001aa4b2d3800376",           # parent_folder_id fallback
      "id_prefix": "pdf_cls1_b6e72461..._",           # media_id = prefix+uid+suffix
      "id_suffix": "001aa4b2d3800376",
      "items": [ {"uid": "<32hex>", "t": title, "mt": media_type, "fs": file_size,
                   "i": introduction, "mid": optional_full_media_id,
                   "pf": optional_parent, "ms": optional_state,
                   "cf": optional_can_fetch}, ... ]
    }

Guarantees:
  * INSERT OR REPLACE on media_id -> idempotent, safe to re-run.
  * Exactly one COMMIT per payload file (per page), so nothing is ever held
    in memory across pages.
  * WAL + busy_timeout so parallel/serial shards never corrupt each other.
  * Completed pages are recorded in ima_page_log so a later session can
    resume exactly where this one stopped.
  * Touches ONLY the staging DB - never D:/平台/database/kaoyan.db.
"""
import json
import os
import sqlite3
import sys
import time

DB_PATH = r"D:/平台/tools/datasource/ima_inventory.db"
BUSY_TIMEOUT_MS = 60000


def _to_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=%d" % BUSY_TIMEOUT_MS)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ima_items (
            media_id          TEXT PRIMARY KEY,
            title             TEXT,
            media_type        INTEGER,
            media_state       INTEGER,
            file_size         INTEGER,
            parent_folder_id  TEXT,
            folder_path       TEXT,
            intro             TEXT,
            can_fetch_content INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ima_page_log (
            scope     TEXT,
            offset    INTEGER,
            n_items   INTEGER,
            ts        INTEGER,
            PRIMARY KEY (scope, offset)
        )
        """
    )
    return conn


def _row(item: dict, payload: dict) -> tuple:
    prefix = payload.get("id_prefix", "")
    suffix = payload.get("id_suffix", "")
    media_id = item.get("mid") or (prefix + item.get("uid", "") + suffix)
    media_type = _to_int(item.get("mt"))
    return (
        media_id,
        item.get("t"),
        media_type,
        _to_int(item.get("ms"), _to_int(payload.get("media_state_default"), 2)),
        _to_int(item.get("fs")),
        item.get("pf") or payload.get("parent_default", ""),
        item.get("fp") or payload.get("folder_path", ""),
        item.get("i", ""),
        _to_int(item.get("cf"), 0 if media_type == 99 else 1),
    )


def upsert_file(payload: dict, conn: sqlite3.Connection) -> tuple:
    items = payload.get("items", []) or []
    cur = conn.cursor()
    for it in items:
        cur.execute(
            """
            INSERT OR REPLACE INTO ima_items
                (media_id, title, media_type, media_state, file_size,
                 parent_folder_id, folder_path, intro, can_fetch_content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _row(it, payload),
        )
    scope = payload.get("scope")
    offset = payload.get("offset")
    if scope is not None and offset is not None:
        cur.execute(
            "INSERT OR REPLACE INTO ima_page_log (scope, offset, n_items, ts) VALUES (?,?,?,?)",
            (scope, _to_int(offset), len(items), int(time.time())),
        )
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM ima_items")
    return len(items), cur.fetchone()[0]


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: ima_upsert.py <payload.json|-> [payload2.json ...]")
        sys.exit(1)
    conn = _connect()
    try:
        for src in sys.argv[1:]:
            payload = json.load(sys.stdin) if src == "-" else json.load(
                open(src, "r", encoding="utf-8")
            )
            written, total = upsert_file(payload, conn)
            print(
                "OK scope=%s offset=%s path=%r items=%d db_total=%d"
                % (
                    payload.get("scope"),
                    payload.get("offset"),
                    payload.get("folder_path", ""),
                    written,
                    total,
                )
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
