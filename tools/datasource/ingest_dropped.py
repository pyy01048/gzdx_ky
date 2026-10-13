# -*- coding: utf-8 -*-
"""把 IMA fetch_media_content 落盘文件写入 documents.content。

用法：
    python ingest_dropped.py <落盘txt路径> <doc_id>
    python ingest_dropped.py --scan     # 扫描 tool-results 目录，报告可用文件

落盘文件是 MCP 超长结果被自动保存的 JSON：{"content": "<markdown 正文>"}
本脚本解析 JSON 取 content，截断到 3 万字后幂等写入 documents.content。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

REAL_DB = r"D:\平台\database\kaoyan.db"
MAX_CHARS = 30000
DROPPED_DIR = (
    r"C:\Users\33884\.workbuddy\projects\c-Users-33884-WorkBuddy-2026-10-11-23-38-15"
    r"\73677e9c-25bd-4ac1-a4bf-aad9e25e2bec\tool-results"
)


def parse(path: str) -> str:
    raw = open(path, encoding="utf-8", errors="ignore").read()
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "content" in data:
            return str(data["content"])
    except json.JSONDecodeError:
        pass
    return raw


def main() -> int:
    if "--scan" in sys.argv:
        if not os.path.isdir(DROPPED_DIR):
            print("no dropped dir")
            return 1
        for n in sorted(os.listdir(DROPPED_DIR)):
            if "fetch_media_content" in n:
                print(n)
        return 0

    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    path = sys.argv[1]
    doc_id = int(sys.argv[2])
    body = parse(path).strip()
    body = body[:MAX_CHARS]

    con = sqlite3.connect(REAL_DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    row = con.execute(
        "SELECT file_name, length(coalesce(content,'')) FROM documents WHERE id=?",
        (doc_id,),
    ).fetchone()
    if not row:
        print(f"doc {doc_id} not found")
        con.close()
        return 1
    if row[1] and row[1] >= len(body):
        print(f"skip doc {doc_id}（已有 {row[1]} 字，不更短）")
        con.close()
        return 0
    con.execute("UPDATE documents SET content=? WHERE id=?", (body, doc_id))
    con.commit()
    print(f"doc {doc_id} ({row[0]}) 写入 {len(body)} 字")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())