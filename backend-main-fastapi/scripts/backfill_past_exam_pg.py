#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回填 is_past_exam 与年份（PostgreSQL · 11 文档 §3.4）。

口径说明（与 11 文档 §3.4 的 SQL 有一处有意收紧）：
    11 文档 SQL 是 ``source_label ~ '真题|zhenti|past'`` 直接置 true。但实测
    大量 ``source_label`` 是「名校考研真题＋课后习题＋章节题库＋模拟试题」这类
    **混合题库文档名**，并非每道题都是真题。直接全标会把课后习题/章节题库
    误判为真题，污染 is_past_exam 口径。

    因此本脚本采用「真题来源 + 已有年份」双重条件回填：
        UPDATE quiz_questions
           SET is_past_exam = TRUE
         WHERE is_past_exam IS NOT TRUE
           AND source_label ~ '真题|zhenti|past'
           AND year IS NOT NULL;
    有年份但无真题来源的行不动（保持原值），无年份的真题来源行也不标
    （无法确证是真题，宁可保守）。

流程：默认 dry-run 预览 -> --apply 写库。写库前备份 quiz_questions 为 JSONL，
单事务、失败回滚。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import psycopg

from scripts._conn import dsn

BACKUP_DIR = Path(r"D:\研途\题库建设\backup")
LOG = logging.getLogger("backfill_past_exam")


def backup_quiz_questions(conn, stamp: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"quiz_questions_{stamp}.jsonl"
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM quiz_questions")
        cols = [d.name for d in cur.description]
        with path.open("w", encoding="utf-8") as f:
            while True:
                rows = cur.fetchmany(1000)
                if not rows:
                    break
                for row in rows:
                    f.write(json.dumps(dict(zip(cols, row, strict=False)), ensure_ascii=False, default=str) + "\n")
    return path


def preview(conn) -> tuple[int, list]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, subject, year, source_label FROM quiz_questions "
            "WHERE source_kind = 'external_import' "
            "  AND source_label ~ '真题|zhenti|past' AND year IS NOT NULL "
            "ORDER BY subject, id"
        )
        rows = cur.fetchall()
    return len(rows), rows


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 is_past_exam（真题来源+有年份）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = ap.parse_args()

    conn = psycopg.connect(dsn(), connect_timeout=10)
    try:
        n, rows = preview(conn)
        LOG.info("待回填 source_kind='past_exam'：%d 行", n)
        if not args.apply:
            print("\n===== DRY-RUN 预览 =====")
            print(f"待回填: {n} 行（source_label 含真题、year 非空、source_kind=external_import）")
            for r in rows[:10]:
                print(f"  id={r[0]} {r[1]} year={r[2]} | {str(r[3])[:50]}")
            print("（dry-run，未写库；确认后加 --apply）")
            return 0

        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = backup_quiz_questions(conn, stamp)
        LOG.info("已备份 quiz_questions -> %s", backup)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE quiz_questions SET source_kind = 'past_exam', updated_at = NOW() "
                "WHERE source_kind = 'external_import' "
                "  AND source_label ~ '真题|zhenti|past' AND year IS NOT NULL"
            )
            conn.commit()
            LOG.info("已更新 %d 行（is_past_exam 由生成列自动同步）", cur.rowcount)
            print("\n===== 回填完成 =====")
            print(f"备份: {backup}")
            print(f"成功更新: {cur.rowcount} 行")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())
