"""Create the IMA inventory staging SQLite database and its table.

Only creates the staging DB under D:/平台/tools/datasource/.
Does NOT touch any project business code or D:/平台/database/kaoyan.db.
"""
import os
import sqlite3

DB_PATH = r"D:/平台/tools/datasource/ima_inventory.db"


def main() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ima_items (
                media_id          TEXT PRIMARY KEY,
                title             TEXT,
                media_type        INTEGER,
                media_state       INTEGER,
                file_size         INTEGER,
                parent_folder_id TEXT,
                folder_path       TEXT,
                intro             TEXT,
                can_fetch_content INTEGER
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    print("DB ready at", DB_PATH)


if __name__ == "__main__":
    main()
