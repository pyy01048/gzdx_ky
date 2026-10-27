"""Ingest one IMA full-text result file into the REAL kaoyan.db documents table.

Usage:
    python ima_content_ingest.py <tool_result_file> <doc_id> [max_chars]

The MCP tool `fetch_media_content` returns a very long payload; when it exceeds
the model context limit the harness spills it to a file. This script reads that
file directly (never loading it into the model context), extracts the `content`
field, truncates it to `max_chars` (default 30000) and writes it into
`documents.content` keyed by `documents.id`.

Only `documents.content` and `documents.updated_at` are touched.
"""
import json
import os
import sqlite3
import sys
import time

REAL_DB = r"D:\平台\database\kaoyan.db"
DEFAULT_MAX_CHARS = 30000


def _read_raw_text(path: str) -> str:
    """Read the payload file and return its raw text (UTF-8, BOM tolerant)."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def parse_content(raw: str) -> str:
    """Extract the document body from an IMA fetch_media_content payload.

    The payload is usually JSON: {"content": "..."} . Some harness versions
    wrap it further; fall back to the raw text when JSON parsing fails.
    """
    text = raw.strip()
    # Strip a leading UTF-8 BOM if present.
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(data, dict):
        # Prefer the canonical content field, fall back to any single string.
        for key in ("content", "text", "markdown", "body"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        for value in data.values():
            if isinstance(value, str) and len(value) > 100:
                return value
        return json.dumps(data, ensure_ascii=False)
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False)


def _clean(text: str) -> str:
    """Normalise whitespace a little without destroying paragraph structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def ingest(path: str, doc_id: int, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    raw = _read_raw_text(path)
    content = _clean(parse_content(raw))
    original_len = len(content)
    truncated = original_len > max_chars
    stored = content[:max_chars] if truncated else content

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(REAL_DB, timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        row = conn.execute(
            "SELECT id, file_name, subject, ima_media_id FROM documents WHERE id=?",
            (doc_id,),
        ).fetchone()
        if not row:
            raise SystemExit("documents.id=%s not found" % doc_id)
        _, file_name, subject, media_id = row
        old_len = conn.execute(
            "SELECT COALESCE(LENGTH(content),0) FROM documents WHERE id=?", (doc_id,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE documents SET content=?, updated_at=? WHERE id=?",
            (stored, now, doc_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "doc_id": doc_id,
        "file_name": file_name,
        "subject": subject,
        "ima_media_id": media_id,
        "fetched_chars": original_len,
        "stored_chars": len(stored),
        "old_content_chars": old_len,
        "truncated": truncated,
        "updated_at": now,
    }


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    path = sys.argv[1]
    doc_id = int(sys.argv[2])
    max_chars = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_MAX_CHARS
    result = ingest(path, doc_id, max_chars)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
