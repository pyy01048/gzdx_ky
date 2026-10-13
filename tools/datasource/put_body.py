# -*- coding: utf-8 -*-
"""从 stdin 读正文并写入指定 doc 的 content（配合 shell heredoc 使用）。

用法：
    type body.txt | python put_body.py 2094
    python put_body.py 2094 < body.txt
"""
from __future__ import annotations

import sqlite3
import sys

REAL_DB = r"D:\平台\database\kaoyan.db"
MAX_CHARS = 30000


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: put_body.py <doc_id>")
        return 1
    doc_id = int(sys.argv[1])
    body = sys.stdin.read().strip()[:MAX_CHARS]
    if len(body) < 50:
        print("body too short")
        return 1
    con = sqlite3.connect(REAL_DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    con.execute("UPDATE documents SET content=? WHERE id=?", (body, doc_id))
    con.commit()
    cur = con.execute("SELECT file_name FROM documents WHERE id=?", (doc_id,)).fetchone()
    con.close()
    print(f"doc {doc_id} ({cur[0] if cur else '?'}) ← {len(body)} 字")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())