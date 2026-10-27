#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai-for-unidata 院校数据补全 (PostgreSQL)

1. kaoyan_schools.official_url 回填（148 所双一流，schools.csv）
2. 新建 kaoyan_national_lines 表并导入国家线 A/B 区（national-lines.csv，2022-2026 全学科门类）

运行: python scripts/import_school_data_aiunidata_pg.py
"""
import csv
import io
import os
import sys

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "..", "data_sources", "ai-for-unidata", "backend", "src", "main", "resources")

DB_CONFIG = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)


def load_csv(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"文件不存在: {path}")
        sys.exit(1)
    with io.open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def update_school_urls(conn):
    schools = load_csv("schools.csv")
    updated = 0
    not_found = []
    with conn.cursor() as cur:
        for s in schools:
            name = s["name"].strip()
            url = (s.get("admissionUrl") or "").strip()
            level = (s.get("level") or "").strip()
            if not url:
                continue
            cur.execute(
                "UPDATE kaoyan_schools SET official_url=%s, updated_at=NOW() "
                "WHERE name=%s AND (official_url IS NULL OR official_url='')",
                (url, name),
            )
            updated += cur.rowcount
            if cur.rowcount == 0:
                # 检查学校是否存在（无 URL 空位时是否因已填好）
                cur.execute("SELECT count(*) FROM kaoyan_schools WHERE name=%s", (name,))
                if cur.fetchone()[0] == 0:
                    not_found.append(name)
    conn.commit()
    print(f"[schools] 回填 official_url: {updated}")
    if not_found:
        print(f"[schools] 平台缺失学校（未匹配）: {len(not_found)}，如: {not_found[:10]}")


def create_national_table(conn):
    DDL = """
    CREATE TABLE IF NOT EXISTS kaoyan_national_lines (
        id bigserial PRIMARY KEY,
        year integer NOT NULL,
        discipline varchar(100) NOT NULL,
        subjects varchar(500),
        total_a integer,
        politics_a integer,
        math_a integer,
        total_b integer,
        politics_b integer,
        math_b integer,
        note text,
        source varchar(100),
        created_at timestamptz NOT NULL DEFAULT NOW(),
        UNIQUE (year, discipline, subjects)
    )
    """
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    print("[national] 表 kaoyan_national_lines 已就绪")


def import_national_lines(conn):
    lines = load_csv("national-lines.csv")
    inserted = 0
    skipped = 0
    with conn.cursor() as cur:
        for r in lines:
            year = int(r["year"]) if r.get("year") else None
            discipline = (r.get("discipline") or "").strip()
            subjects = (r.get("subjects") or "").strip() or None
            def to_int(v):
                v = (v or "").strip()
                return int(v) if v else None
            total_a = to_int(r.get("totalA"))
            politics_a = to_int(r.get("oneA"))
            math_a = to_int(r.get("overA"))
            total_b = to_int(r.get("totalB"))
            politics_b = to_int(r.get("oneB"))
            math_b = to_int(r.get("overB"))
            note = (r.get("note") or "").strip() or None
            if year is None or not discipline:
                skipped += 1
                continue
            cur.execute(
                """
                INSERT INTO kaoyan_national_lines (
                    year, discipline, subjects, total_a, politics_a, math_a,
                    total_b, politics_b, math_b, note, source
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ai-for-unidata/national-lines.csv')
                ON CONFLICT (year, discipline, subjects) DO UPDATE SET
                    total_a=EXCLUDED.total_a, politics_a=EXCLUDED.politics_a, math_a=EXCLUDED.math_a,
                    total_b=EXCLUDED.total_b, politics_b=EXCLUDED.politics_b, math_b=EXCLUDED.math_b,
                    note=EXCLUDED.note
                """,
                (year, discipline, subjects, total_a, politics_a, math_a,
                 total_b, politics_b, math_b, note),
            )
            inserted += cur.rowcount
    conn.commit()
    print(f"[national] 导入国家线: {inserted}, 跳过: {skipped}")


def main():
    conn = psycopg.connect(**DB_CONFIG)
    try:
        update_school_urls(conn)
        create_national_table(conn)
        import_national_lines(conn)
    finally:
        conn.close()
    print("=== 完成 ===")


if __name__ == "__main__":
    main()