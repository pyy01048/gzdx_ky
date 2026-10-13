"""Clean junk knowledge points out of the REAL kaoyan.db `knowledge_points` table.

Background
----------
The local Ollama model used by `document_analyzer.py` produces low-quality JSON;
roughly one third of the extracted knowledge-point names are garbage such as
``(1)+17``, ``表2-11(a)``, ``0``, ``13``, ``转换时``.  Those pollute the knowledge
map, so they must be removed (or at least flagged) before the map is consumed.

Design
------
* Read-only by default (``--dry-run`` is the default mode).
* Matching is rule based; every hit is labelled with the rule that fired so the
  operator can audit precision before deleting anything.
* The rules were tightened after a first dry-run falsely flagged real knowledge
  points: ``栈`` (single CJK char), ``主从``, ``标准与或``, ``定积分应用``
  (nouns that merely end in a function word) and the long but legitimate
  ``555定时器构成的单稳态触发器、施密特触发器、多谐振荡器方法``.  A name is only
  treated as a pasted question stem when it also carries sentence punctuation or
  formula markers, not because of length alone.
* Deletion is idempotent: a second run finds nothing to delete.
* Every deleted row is written to an audit JSON so it can be restored.
* Rows that are still referenced by link tables (flashcards, error records,
  question_knowledge_links, ...) are NEVER deleted; they are reported instead.

Rules (evaluated in order, first match wins)
--------------------------------------------
R1 blank                : empty / whitespace only
R2 pure_number_symbol   : no CJK and no Latin letter at all  -> "0", "13", "-3", "(1)+17"
R3 numbered_item        : "(<n>)" followed by optional sign + number, no CJK -> "(1)+17"
R4 figure_table_ref     : whole name is a bare 表/图/题/式/例 + number reference
R5 trailing_particle    : ends with a dangling 时/的/了 (never ends a real term)
R6 too_short            : fewer than 2 characters AND no CJK char
R7 pasted_sentence      : >= 25 chars AND carries sentence punctuation or formula
                          markers (question stems such as "...(  )。A．空穴B...")
R8 dash_duplicate       : leading "-"/"*"/"·" and the bare name already exists

Deliberately NOT flagged (verified against real knowledge points):
``卡诺图`` (3 CJK chars), ``PN结`` (letters + CJK), ``十进制``, ``存储容量``,
``Ugs`` (pure Latin but a real parameter name).

Usage
-----
    python clean_kp_noise.py                      # dry-run, prints report
    python clean_kp_noise.py --apply              # backup + delete flagged rows
    python clean_kp_noise.py --apply --no-backup  # skip the sqlite backup
    python clean_kp_noise.py --scope ima          # only IMA-derived rows
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

REAL_DB = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\database\backups"
AUDIT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kp_noise_audit.json")

# Tables (column) that may reference knowledge_points.id.
REF_TABLES: List[Tuple[str, str]] = [
    ("error_records", "knowledge_point_id"),
    ("flashcards", "knowledge_point_id"),
    ("error_knowledge_links", "knowledge_point_id"),
    ("question_knowledge_links", "knowledge_point_id"),
    ("study_events", "knowledge_point_id"),
    ("misconceptions", "knowledge_point_id"),
]

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
TRIM_PUNCT = " \t\r\n,、。，;；:：.。!！?？)）]】}》\"'_-—–~～/\\|"
NUMBERED_ITEM_RE = re.compile(r"^\(?\d+\)?\s*[+\-−±]?\s*\d+\s*$")
FIGURE_REF_RE = re.compile(r"^(表|图|题|式|例|公式|习题)\s*\d[\d\-–—.()a-zA-Z]{0,12}$")
DANGLING_SUFFIX = ("时", "的", "了")
SENTENCE_MARKERS = ("。", "；", "，", ";", "．", "？", "?", "！", "!", "：")
FORMULA_MARKERS = ("^", "{", "}", "_", "____")
SENTENCE_MIN_LEN = 25
REF_PREFIX = "-*·•"
# Borderline names that look like bare numbers but name a real concept
# ("555" = the 555 timer IC, already covered by id=24). Keep them.
KEEP_ALLOWLIST = {"555"}


def _norm(name: str) -> str:
    """Strip surrounding whitespace and punctuation from a knowledge-point name."""
    return (name or "").strip().strip(TRIM_PUNCT).strip()


def classify(name: str) -> Optional[str]:
    """Return the rule id that marks `name` as noise, or None when it is clean."""
    raw = name or ""
    norm = _norm(raw)
    if not norm:
        return "R1_blank"
    if norm in KEEP_ALLOWLIST:
        return None
    # R2 / R3: nothing but digits and symbols (or a "(n)±m" enumeration item).
    if not CJK_RE.search(norm):
        if not LATIN_RE.search(norm):
            return "R2_pure_number_symbol"
        if NUMBERED_ITEM_RE.match(norm):
            return "R3_numbered_item"
    # R4: a bare cross-reference such as 表2-11(a) or 图2-10.
    if FIGURE_REF_RE.match(norm):
        return "R4_figure_table_ref"
    # R6: shorter than two characters and not even a CJK term ("栈" is kept).
    if len(norm) < 2 and not CJK_RE.search(norm):
        return "R6_too_short"
    # R7: question stems / whole formulas pasted in as a "knowledge point".
    # Length alone is not enough (id=24 is a long but legitimate 555-timer name),
    # so sentence punctuation or formula markers are required as well.
    if len(norm) >= SENTENCE_MIN_LEN:
        if any(m in norm for m in SENTENCE_MARKERS) or any(m in norm for m in FORMULA_MARKERS):
            return "R7_pasted_sentence"
        if re.search(r"[（(]\s*[)）]", norm):
            return "R7_pasted_sentence"
    # R5: dangling function word at the end ("转换时" ...).
    if norm.endswith(DANGLING_SUFFIX):
        return "R5_trailing_particle"
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def load_rows(conn: sqlite3.Connection, scope: str) -> List[Tuple[Any, ...]]:
    """Return (id, name, subject, chapter, document_id) for the requested scope."""
    sql = ("SELECT kp.id, kp.name, kp.subject, kp.chapter, kp.document_id "
           "FROM knowledge_points kp")
    if scope == "ima":
        sql += (" JOIN documents d ON d.id = kp.document_id "
                "WHERE d.subject_source = 'ima'")
    sql += " ORDER BY kp.id"
    return conn.execute(sql).fetchall()


def referenced_ids(conn: sqlite3.Connection, ids: List[int]) -> Dict[int, List[str]]:
    """Map knowledge-point id -> list of tables that still reference it."""
    refs: Dict[int, List[str]] = {}
    if not ids:
        return refs
    for table, column in REF_TABLES:
        if not _table_exists(conn, table):
            continue
        # Chunk to keep the IN clause small.
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                "SELECT %s FROM %s WHERE %s IN (%s)" % (column, table, column, marks),
                chunk,
            ).fetchall()
            for (value,) in rows:
                if value in refs:
                    refs[value].append(table)
                else:
                    refs[value] = [table]
    return refs


def backup(conn: sqlite3.Connection) -> str:
    """Create a consistent copy of the DB using the sqlite3 backup API."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = os.path.join(BACKUP_DIR, "kaoyan.db.bak_kp_clean_%s" % stamp)
    dest = sqlite3.connect(target)
    try:
        with dest:
            conn.backup(dest)
    finally:
        dest.close()
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="actually delete flagged rows (default is dry-run)")
    parser.add_argument("--no-backup", action="store_true",
                        help="skip the sqlite backup that precedes --apply")
    parser.add_argument("--scope", choices=("all", "ima"), default="all",
                        help="all knowledge points (default) or only IMA-derived ones")
    parser.add_argument("--samples", type=int, default=12,
                        help="how many sample rows to print per rule")
    args = parser.parse_args()

    conn = sqlite3.connect(REAL_DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        rows = load_rows(conn, args.scope)
        # Names of rows that do NOT carry a leading bullet, used by R8.
        clean_names = {_norm(r[1]).lstrip(REF_PREFIX) for r in rows}
        hits: List[Dict[str, Any]] = []
        for kp_id, name, subject, chapter, document_id in rows:
            rule = classify(name)
            if rule is None and (name or "").strip()[:1] in tuple(REF_PREFIX):
                # "-直流电源" style artefact: only junk when the bare name exists too.
                if _norm(name).lstrip(REF_PREFIX) in clean_names:
                    rule = "R8_dash_duplicate"
            if rule:
                hits.append({
                    "id": kp_id,
                    "name": name,
                    "subject": subject,
                    "chapter": chapter,
                    "document_id": document_id,
                    "rule": rule,
                })

        by_rule: Dict[str, List[Dict[str, Any]]] = {}
        for hit in hits:
            by_rule.setdefault(hit["rule"], []).append(hit)

        total = len(rows)
        print("=" * 72)
        print("scope=%s  scanned=%d  flagged=%d (%.1f%%)  mode=%s"
              % (args.scope, total, len(hits), 100.0 * len(hits) / max(total, 1),
                 "APPLY" if args.apply else "DRY-RUN"))
        print("=" * 72)
        for rule in sorted(by_rule):
            print("\n[%s] %d hits" % (rule, len(by_rule[rule])))
            for hit in by_rule[rule][:args.samples]:
                shown = hit["name"] if len(hit["name"]) <= 60 else hit["name"][:57] + "..."
                print("   - id=%-5s doc=%-5s %s" % (hit["id"], hit["document_id"], shown))
            if len(by_rule[rule]) > args.samples:
                print("   ... %d more" % (len(by_rule[rule]) - args.samples))

        # False-positive inspection: short-but-kept names, and names with digits.
        kept_short = [r for r in rows if 0 < len(_norm(r[1])) < 5
                      and classify(r[1]) is None]
        print("\n[KEPT] short names (<5 chars, not flagged) -> %d, samples:" % len(kept_short))
        for r in kept_short[:args.samples]:
            print("   + id=%-5s %s" % (r[0], r[1]))
        kept_digit = [r for r in rows if re.search(r"\d", r[1] or "")
                      and classify(r[1]) is None]
        print("\n[KEPT] names containing digits (not flagged) -> %d, samples:" % len(kept_digit))
        for r in kept_digit[:args.samples]:
            shown = r[1] if len(r[1]) <= 60 else r[1][:57] + "..."
            print("   + id=%-5s %s" % (r[0], shown))

        if not args.apply:
            print("\nDRY-RUN: nothing was modified. Re-run with --apply to delete.")
            return 0

        # Reference safety: never delete a row that other tables point at.
        ids = [h["id"] for h in hits]
        refs = referenced_ids(conn, ids)
        deletable = [h for h in hits if h["id"] not in refs]
        skipped = [h for h in hits if h["id"] in refs]
        backup_path = "" if args.no_backup else backup(conn)
        if backup_path:
            print("\nbackup -> %s" % backup_path)
        if skipped:
            print("\n[SKIP] %d flagged rows are referenced elsewhere and were kept:"
                  % len(skipped))
            for hit in skipped[:args.samples]:
                print("   ! id=%-5s %s <- %s" % (hit["id"], hit["name"][:40],
                                                 ",".join(refs[hit["id"]])))
        if deletable:
            conn.executemany(
                "DELETE FROM knowledge_points WHERE id=?",
                [(h["id"],) for h in deletable],
            )
            conn.commit()
        print("\nDELETED %d rows%s" % (len(deletable),
                                       "" if not skipped else
                                       " (skipped %d referenced)" % len(skipped)))
        remaining = conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
        print("knowledge_points total now = %d" % remaining)

        audit = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scope": args.scope,
            "backup": backup_path,
            "deleted": deletable,
            "skipped_referenced": skipped,
        }
        with open(AUDIT_PATH, "w", encoding="utf-8") as fh:
            json.dump(audit, fh, ensure_ascii=False, indent=2)
        print("audit -> %s" % AUDIT_PATH)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
