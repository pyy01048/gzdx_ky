# -*- coding: utf-8 -*-
"""自动扫描 tool-results 目录，把所有 IMA fetch_media_content 落盘文件入库。

原理：MCP 抓取超长正文时会自动把结果写成
``mcp-ima-mcp-fetch_media_content-<ts>-<hash>.txt``（JSON，键为 content）。
落盘文件名里含 media_id 片段，可据此回填到对应 documents 行。

幂等：已存在且不更短则跳过。
用法：python auto_ingest_dropped.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3

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
    if not os.path.isdir(DROPPED_DIR):
        print("no dropped dir")
        return 0
    files = sorted(
        glob.glob(os.path.join(DROPPED_DIR, "mcp-ima-mcp-fetch_media_content-*.txt"))
    )
    if not files:
        print("no dropped files")
        return 0

    con = sqlite3.connect(REAL_DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    # media_id → doc_id
    mapping = {
        mid: did
        for did, mid in con.execute(
            "SELECT id, ima_media_id FROM documents "
            "WHERE ima_media_id IS NOT NULL"
        )
    }

    ok = skipped = unmatched = 0
    for fp in files:
        body = parse(fp).strip()[:MAX_CHARS]
        if len(body) < 50:
            continue
        # 正文里含 media_id（图路径里），用它反查 doc
        ids = set(re.findall(r"((?:pdf|word|image|img)_[0-9a-z_]+)", body))
        # 也从文件名找 hash 无用，改用行内容匹配：取最长命中
        matched = [mapping[i] for i in ids if i in mapping]
        if not matched:
            unmatched += 1
            continue
        doc_id = matched[0]
        cur_len = con.execute(
            "SELECT length(coalesce(content,'')) FROM documents WHERE id=?", (doc_id,)
        ).fetchone()[0]
        if cur_len and cur_len >= len(body):
            skipped += 1
            continue
        con.execute("UPDATE documents SET content=? WHERE id=?", (body, doc_id))
        ok += 1
        print(f"  ✓ doc {doc_id} ← {os.path.basename(fp)[:60]} ({len(body)}字)")
    con.commit()
    con.close()
    print(f"入库 {ok}，跳过 {skipped}，无法匹配 {unmatched}（共 {len(files)} 个落盘文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())