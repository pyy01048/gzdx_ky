# -*- coding: utf-8 -*-
"""Import the audited 2027 engineering catalog without guessing school ownership."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

if __package__ in (None, ""):
    backend_root = str(Path(__file__).resolve().parents[2])
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

from scripts._conn import _env, pg_connect

ASSET_DIR = Path("D:/研途/gzdx_ky/data-assets/08工学数据包/index")
COLLEGE_FILE = ASSET_DIR / "college_list.csv"
MAJOR_FILE = ASSET_DIR / "school08_majors.csv"
SCHOOL_FILE = ASSET_DIR / "school_dict.csv"
COLLEGE_SUFFIXES = (
    "学院",
    "学系",
    "系",
    "研究院",
    "研究所",
    "研究生院",
    "学部",
    "书院",
    "教学部",
    "教研部",
)
REVIEW_TERMS = (
    "校区",
    "实验室",
    "联合培养",
    "联合学院",
    "分校",
    "分院",
    "中心",
)
NAV_NAMES = {"帮助中心", "用户中心", "教育部学生服务与素质发展中心", "重点实验室"}


def clean_college_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def college_decision(value: str, ref_type: str) -> tuple[str, str]:
    name = clean_college_name(value)
    if not name:
        return "review", "empty_name"
    if len(name) > 80:
        return "review", "too_long"
    if re.search(r"<[^>]+>|https?://|&(?:amp|nbsp|ldquo|rdquo|quot);|[\x00-\x1f\x7f]", name, re.I):
        return "review", "markup_or_control"
    if re.match(r"^\s*(?:\d+[.、)]|[（(]\d+[)）])\s*", name):
        return "review", "list_prefix"
    if name in NAV_NAMES:
        return "review", "navigation_or_lab"
    if not name.endswith(COLLEGE_SUFFIXES):
        return "review", "unsupported_name_shape"
    if any(term in name for term in REVIEW_TERMS):
        return "review", "campus_or_special_unit"
    if "（" in name or "(" in name:
        return "review", "parenthetical_alias"
    if ref_type == "研招网院系设置":
        return "review", "catalog_source_only"
    if ref_type not in {"参照校级", "自有办法"}:
        return "review", "unknown_source_type"
    return "insert", "eligible"


def read_csv(path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    raw = path.read_bytes()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows, {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "rows": len(rows)}


def build_plan(
    college_rows: Iterable[dict[str, str]],
    major_rows: Iterable[dict[str, str]],
    schools: Iterable[dict[str, Any]],
    source_school_names: set[str],
    colleges: Iterable[dict[str, Any]],
    majors: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    school_index = {
        str(row["name"]): int(row["id"])
        for row in schools
        if row.get("enabled", True) and row.get("deleted_at") is None
    }
    college_index = {(int(row["school_id"]), row["name"]): int(row["id"]) for row in colleges}
    existing_majors: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in majors:
        if row.get("code"):
            existing_majors[(int(row["school_id"]), row["code"], row["name"])].append(row)

    unmatched_schools: set[str] = set()
    college_plan: list[dict[str, Any]] = []
    seen_colleges: dict[tuple[int, str], int] = {}
    for line, row in enumerate(college_rows, 2):
        school_name = row["school"]
        if school_name not in source_school_names:
            continue
        school_id = school_index.get(school_name)
        if school_id is None:
            unmatched_schools.add(school_name)
            continue
        name = clean_college_name(row["college"])
        key = (school_id, name)
        decision, reason = college_decision(name, row["ref_type"].strip())
        source = {
            "line": line,
            "unit_code": row["unit_code"],
            "ref_type": row["ref_type"],
            "source_url": row["source_url"],
        }
        if key in seen_colleges:
            previous = college_plan[seen_colleges[key]]
            priority = {"自有办法": 3, "参照校级": 2, "研招网院系设置": 1}
            if previous["decision"] != "skip" and priority.get(row["ref_type"], 0) > priority.get(
                previous["ref_type"], 0
            ):
                college_plan[seen_colleges[key]] = {
                    "school_id": school_id,
                    "name": name,
                    **source,
                    "decision": decision,
                    "reason": reason,
                }
            continue
        seen_colleges[key] = len(college_plan)
        if key in college_index:
            decision, reason = "skip", "already_exists"
        college_plan.append({"school_id": school_id, "name": name, **source, "decision": decision, "reason": reason})

    major_groups: dict[tuple[int, str, str], list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for line, row in enumerate(major_rows, 2):
        source_school = row["school"]
        if source_school not in source_school_names:
            continue
        school_id = school_index.get(source_school)
        if school_id is None:
            unmatched_schools.add(source_school)
            continue
        code, name, degree = row["zydm"].strip(), row["zymc"].strip(), row["xwlx"].strip()
        if degree not in {"学术学位", "专业学位"}:
            continue
        major_groups[(school_id, code, name)].append((line, row))

    catalog_subjects: dict[tuple[int, str], set[str]] = defaultdict(set)
    catalog_sources: dict[tuple[int, str], list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for line, row in enumerate(major_rows, 2):
        school_id = school_index.get(row["school"])
        code = row["zydm"].strip()
        subject_code = row["yjxkdm"].strip()
        if school_id is None or not code or not subject_code:
            continue
        key = (school_id, code)
        catalog_subjects[key].add(subject_code)
        catalog_sources[key].append((line, row))

    subject_code_fill_plan: list[dict[str, Any]] = []
    for row in majors:
        if not row.get("enabled", True) or row.get("deleted_at") is not None:
            continue
        if row.get("subject_code"):
            continue
        key = (int(row["school_id"]), row["code"])
        candidates = catalog_subjects.get(key, set())
        if len(candidates) != 1:
            continue
        entries = catalog_sources[key]
        source = entries[0][1]
        subject_code_fill_plan.append(
            {
                "target_id": int(row["id"]),
                "school_id": int(row["school_id"]),
                "code": row["code"],
                "name": row["name"],
                "subject_code": next(iter(candidates)),
                "source_lines": sorted(line for line, _ in entries),
                "catalog_year": source["catalog_year"],
                "unit_code": source["unit_code"],
                "match_method": "school_code_unique_subject",
            }
        )

    major_plan: list[dict[str, Any]] = []
    for (school_id, code, name), entries in major_groups.items():
        source = entries[0][1]
        base = {
            "school_id": school_id,
            "college_id": None,
            "code": code,
            "name": name,
            "subject_code": source["yjxkdm"].strip() or None,
            "degree_type": "academic" if source["xwlx"].strip() == "学术学位" else "professional",
            "line": entries[0][0],
            "unit_code": source["unit_code"],
            "catalog_year": source["catalog_year"],
        }
        if len(entries) > 1:
            major_plan.append(
                {
                    **base,
                    "decision": "review",
                    "reason": "duplicate_degree_rows",
                    "source_lines": [line for line, _ in entries],
                }
            )
            continue
        existing = existing_majors.get((school_id, code, name), [])
        if len(existing) > 1:
            major_plan.append(
                {
                    **base,
                    "decision": "review",
                    "reason": "multiple_existing_rows",
                    "target_ids": [row["id"] for row in existing],
                }
            )
        elif not existing:
            major_plan.append({**base, "decision": "insert", "reason": "new_unassigned_major"})
        else:
            target = existing[0]
            expected_degree = base["degree_type"]
            if target.get("degree_type") not in {"unknown", expected_degree}:
                major_plan.append(
                    {**base, "decision": "review", "reason": "degree_conflict", "target_ids": [target["id"]]}
                )
            elif not target.get("subject_code") and base["subject_code"]:
                major_plan.append(
                    {**base, "decision": "fill", "reason": "missing_subject_code", "target_ids": [target["id"]]}
                )
            else:
                major_plan.append(
                    {**base, "decision": "skip", "reason": "already_covered", "target_ids": [target["id"]]}
                )

    return {
        "run_id": uuid.uuid4().hex,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_schools": len(source_school_names),
        "matched_source_schools": len(source_school_names - unmatched_schools),
        "unmatched_schools": sorted(unmatched_schools),
        "college_plan": college_plan,
        "major_plan": major_plan,
        "subject_code_fill_plan": subject_code_fill_plan,
        "statistics": {
            "colleges": dict(Counter(row["decision"] for row in college_plan)),
            "majors": dict(Counter(row["decision"] for row in major_plan)),
            "major_unassigned_inserts": sum(row["decision"] == "insert" for row in major_plan),
            "subject_code_fills": len(subject_code_fill_plan),
        },
    }


def pg_dump_backup(database: str) -> Path:
    executable = os.environ.get("PG_DUMP_BIN") or "D:/pgsql/pgenv/Library/bin/pg_dump.exe"
    backup_dir = Path("D:/研途/backups") / f"engineering_catalog_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    target = backup_dir / f"{database}_engineering_catalog.dump"
    command = [
        executable,
        "--format=custom",
        "--no-owner",
        "--file",
        str(target),
        "--host",
        _env("PG_HOST", "127.0.0.1"),
        "--port",
        _env("PG_PORT", "5432"),
        "--username",
        _env("PG_USER", "kaoyan"),
        "--dbname",
        database,
        "--table",
        "kaoyan_schools",
        "--table",
        "kaoyan_colleges",
        "--table",
        "kaoyan_majors",
        "--table",
        "school_aliases",
    ]
    env = {**os.environ, "PGPASSWORD": _env("PG_PASSWORD", "")}
    subprocess.run(command, env=env, check=True, capture_output=True, text=True, encoding="utf-8")
    return target


def apply_plan(conn: Any, plan: dict[str, Any]) -> dict[str, Any]:
    inserted_colleges = 0
    for row in plan["college_plan"]:
        if row["decision"] != "insert":
            continue
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO kaoyan_colleges (school_id, name) VALUES (%s, %s) "
                "ON CONFLICT (school_id, name) DO NOTHING RETURNING id",
                (row["school_id"], row["name"]),
            )
            result = cur.fetchone()
        inserted_colleges += int(result is not None)
        row["target_id"] = result[0] if result else None

    inserted_majors = filled = fallback_filled = 0
    filled_ids: set[int] = set()
    for row in plan["major_plan"]:
        with conn.cursor() as cur:
            if row["decision"] == "insert":
                cur.execute(
                    "INSERT INTO kaoyan_majors (school_id, college_id, code, name, subject_code, degree_type) "
                    "SELECT %s, NULL, %s, %s, %s, %s::degree_type "
                    "WHERE NOT EXISTS (SELECT 1 FROM kaoyan_majors WHERE school_id=%s AND code=%s AND name=%s) "
                    "RETURNING id",
                    (
                        row["school_id"],
                        row["code"],
                        row["name"],
                        row["subject_code"],
                        row["degree_type"],
                        row["school_id"],
                        row["code"],
                        row["name"],
                    ),
                )
                result = cur.fetchone()
                inserted_majors += int(result is not None)
                row["target_id"] = result[0] if result else None
            elif row["decision"] == "fill":
                cur.execute(
                    "UPDATE kaoyan_majors SET subject_code=%s "
                    "WHERE id=%s AND (subject_code IS NULL OR btrim(subject_code)='')",
                    (row["subject_code"], row["target_ids"][0]),
                )
                filled += cur.rowcount
                filled_ids.add(row["target_ids"][0])
                row["target_id"] = row["target_ids"][0]
    for row in plan.get("subject_code_fill_plan", []):
        target_id = row["target_id"]
        if target_id in filled_ids:
            continue
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE kaoyan_majors SET subject_code=%s "
                "WHERE id=%s AND (subject_code IS NULL OR btrim(subject_code)='')",
                (row["subject_code"], target_id),
            )
            fallback_filled += cur.rowcount
    return {
        "inserted_colleges": inserted_colleges,
        "inserted_majors": inserted_majors,
        "filled_subject_codes": filled,
        "fallback_filled_subject_codes": fallback_filled,
    }


def run(*, apply: bool, database_name: str | None, output: Path | None) -> dict[str, Any]:
    database = _env("PG_DATABASE", "kaoyan")
    if apply and (not database_name or database_name != database):
        raise RuntimeError("--apply requires --database-name to exactly match PG_DATABASE")
    college_rows, college_source = read_csv(COLLEGE_FILE)
    major_rows, major_source = read_csv(MAJOR_FILE)
    school_rows, school_source = read_csv(SCHOOL_FILE)
    source_school_names = {row["name"] for row in school_rows if row["has_08"] == "1"}
    conn = pg_connect(database, autocommit=False)
    backup = None
    try:
        if not apply:
            conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, enabled, deleted_at FROM kaoyan_schools")
            schools = [dict(zip(("id", "name", "enabled", "deleted_at"), row, strict=False)) for row in cur.fetchall()]
            cur.execute("SELECT id, school_id, name FROM kaoyan_colleges")
            colleges = [dict(zip(("id", "school_id", "name"), row, strict=False)) for row in cur.fetchall()]
            cur.execute(
                "SELECT id, school_id, code, name, subject_code, degree_type, enabled, deleted_at "
                "FROM kaoyan_majors WHERE deleted_at IS NULL AND enabled"
            )
            majors = [
                dict(
                    zip(
                        ("id", "school_id", "code", "name", "subject_code", "degree_type", "enabled", "deleted_at"),
                        row,
                        strict=False,
                    )
                )
                for row in cur.fetchall()
            ]
        plan = build_plan(college_rows, major_rows, schools, source_school_names, colleges, majors)
        plan.update(
            {
                "mode": "apply" if apply else "dry_run",
                "database": database,
                "read_only": not apply,
                "sources": [school_source, college_source, major_source],
            }
        )
        if apply:
            backup = pg_dump_backup(database)
            plan["backup"] = str(backup)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('import_08_engineering_catalog_pg'))")
                cur.execute("SET LOCAL lock_timeout = '10s'")
            plan["write"] = apply_plan(conn, plan)
        conn.commit()
    except Exception:
        conn.rollback()
        plan = {**locals().get("plan", {}), "write": {"attempted": bool(apply), "rolled_back": True}}
        raise
    finally:
        conn.close()
    if output:
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database-name")
    parser.add_argument("--output", type=Path, help="write the complete row-level audit report")
    args = parser.parse_args(argv)
    plan = run(apply=args.apply, database_name=args.database_name, output=args.output)
    print(
        json.dumps(
            {
                key: value
                for key, value in plan.items()
                if key not in {"college_plan", "major_plan", "subject_code_fill_plan"}
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
