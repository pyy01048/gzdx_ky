"""Insert one page of IMA items into the staging SQLite database.

Usage:
    python insert_page.py <payload.json>

payload.json shape:
    {
      "items": [ {media_id, title, media_type, media_state,
                  file_size, parent_folder_id, introduction,
                  can_fetch_content}, ... ],
      "folder_path": "考研资料数据集V1.0/子目录"   # '' for KB root
    }

Each invocation commits immediately so that full results are never held
in memory across pages. Idempotent via INSERT OR REPLACE on media_id.
"""
import json
import sqlite3
import sys

DB_PATH = r"D:/平台/tools/datasource/ima_inventory.db"


def _to_int(value: object, default: int = 0) -> int:
    """Coerce an API field (int/str/bool/None) to int safely.

    The IMA API returns file_size as a string, can_fetch_content as a
    bool, and media_state/media_type as ints. This keeps the DB columns
    correctly typed regardless of how each field arrives.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: insert_page.py <payload.json>")
        sys.exit(1)

    payload_path = sys.argv[1]
    with open(payload_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    items = payload.get("items", [])
    folder_path = payload.get("folder_path", "")

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        inserted = 0
        for it in items:
            cur.execute(
                """
                INSERT OR REPLACE INTO ima_items
                    (media_id, title, media_type, media_state, file_size,
                     parent_folder_id, folder_path, intro, can_fetch_content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    it.get("media_id"),
                    it.get("title"),
                    _to_int(it.get("media_type")),
                    _to_int(it.get("media_state")),
                    _to_int(it.get("file_size")),
                    it.get("parent_folder_id"),
                    folder_path,
                    it.get("introduction"),
                    _to_int(it.get("can_fetch_content")),
                ),
            )
            inserted += 1
        conn.commit()
        print(
            f"OK folder_path={folder_path!r} inserted/updated={inserted} "
            f"total_rows={count_rows(cur)}"
        )
    finally:
        conn.close()


def count_rows(cur: sqlite3.Cursor) -> int:
    cur.execute("SELECT COUNT(*) FROM ima_items")
    return cur.fetchone()[0]


if __name__ == "__main__":
    main()
