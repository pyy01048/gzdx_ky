# -*- coding: utf-8 -*-
"""回填 PostgreSQL `kaoyan_schools.level`（985 / 211 / 双一流 / 双非）。

数据源：`scripts/school_level_truth.py` 的权威名单（985=39，211=116，双一流补充）。
用法：
    python scripts/backfill_school_level_pg.py --dry-run
    python scripts/backfill_school_level_pg.py --apply

说明：
- 只更新 level 为空或与权威名单不一致的行；已有值不盲目覆盖。
- 名单外的院校统一写「双非」，避免筛选“双非”时又空。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from scripts.school_level_truth import truth_level  # noqa: E402


def db_url() -> str:
    load_dotenv(BASE / ".env")
    host = os.getenv("PG_HOST", "127.0.0.1")
    port = os.getenv("PG_PORT", "5432")
    user = os.getenv("PG_USER", "kaoyan")
    pwd = os.getenv("PG_PASSWORD", "")
    name = os.getenv("PG_DATABASE", "kaoyan")
    return f"host={host} port={port} user={user} password={pwd} dbname={name}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写库；不加只预览")
    args = ap.parse_args()

    with psycopg.connect(db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, level FROM kaoyan_schools ORDER BY id")
            rows = cur.fetchall()

        changes = []
        for sid, name, old in rows:
            new = truth_level(name) or "双非"
            if (old or "") != new:
                changes.append((sid, name, old, new))

        dist = {}
        for _, _, _, new in changes:
            dist[new] = dist.get(new, 0) + 1
        print(f"共 {len(rows)} 所；待修正 {len(changes)} 所；分布 {dist}")
        for row in changes[:15]:
            print("  ", row)

        if not args.apply:
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        with conn.cursor() as cur:
            for sid, _, _, new in changes:
                cur.execute(
                    "UPDATE kaoyan_schools SET level=%s, updated_at=now() WHERE id=%s",
                    (new, sid),
                )
        conn.commit()
        print(f"已更新 {len(changes)} 所。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
