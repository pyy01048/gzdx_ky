#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""warn 题治理（PostgreSQL · 11 文档 §3.1）。

现状：validation_status='warn' 共 216 行，错误码统一为
``single_options_less_than_four``（单选题选项不足 4 个）。这些行大多来自
扫描/OCR 切题，选项被截断；在没有原卷源可补全的情况下，按 11 文档
§3.1 决策树走「无法修复 → is_available=false 下架（保留数据，可回滚）」。

流程：
  1. 导出 warn 明细 CSV（题目/选项/答案/解析/错误码）——可审计；
  2. 默认 dry-run 预览；
  3. --apply 写库：备份 quiz_questions 为 JSONL，单事务把 warn 行置
     is_available=false，生成回滚 SQL（恢复 is_available 即可）。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import psycopg

from scripts._conn import dsn

REPORT_DIR = Path(r"D:\研途\gzdx_ky\docs\reports")
BACKUP_DIR = Path(r"D:\研途\题库建设\backup")
LOG = logging.getLogger("govern_warn_quiz")

WARN_COLS = (
    "id, subject, chapter, question_type, content, options, answer, "
    "analysis, validation_errors, source_kind, source_label, year"
)


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


def export_warn_csv(conn, path: Path) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {WARN_COLS} FROM quiz_questions WHERE validation_status = 'warn' ORDER BY subject, id")
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(
                [
                    "" if v is None else (json.dumps(v, ensure_ascii=False) if isinstance(v, dict | list) else v)
                    for v in r
                ]
            )
    return len(rows)


def preview(conn) -> tuple[int, list]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, subject, question_type, validation_errors FROM quiz_questions "
            "WHERE validation_status = 'warn' ORDER BY subject, id"
        )
        return cur.rowcount, cur.fetchall()


def main() -> int:
    ap = argparse.ArgumentParser(description="warn 题治理（软下架 + 回滚 SQL）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    csv_path = REPORT_DIR / f"warn-questions-{time.strftime('%Y%m%d')}.csv"
    md_path = REPORT_DIR / f"warn-governance-{time.strftime('%Y%m%d')}.md"

    conn = psycopg.connect(dsn(), connect_timeout=10)
    try:
        n_csv = export_warn_csv(conn, csv_path)
        n, rows = preview(conn)
        LOG.info("warn 明细 CSV 已导出 %s（%d 行）", csv_path, n_csv)
        LOG.info("待软下架 warn 行：%d", n)
        if not args.apply:
            print("\n===== DRY-RUN 预览 =====")
            print(f"待软下架: {n} 行（validation_status='warn'）")
            for r in rows[:10]:
                errs = r[3]
                if isinstance(errs, str):
                    errs = json.loads(errs)
                print(f"  id={r[0]} {r[1]} {r[2]} | {errs}")
            print("（dry-run，未写库；确认后加 --apply）")
            return 0

        backup = backup_quiz_questions(conn, stamp)
        LOG.info("已备份 quiz_questions -> %s", backup)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE quiz_questions SET is_available = FALSE, updated_at = NOW() WHERE validation_status = 'warn'"
            )
            affected = cur.rowcount
            conn.commit()
        LOG.info("已软下架 %d 行", affected)

        # 回滚 SQL
        sql = f"""-- warn 题治理回滚（{datetime.now().isoformat(timespec="seconds")}）
-- 恢复被软下架的 warn 题目为可作答状态
UPDATE quiz_questions SET is_available = TRUE, updated_at = NOW()
 WHERE validation_status = 'warn';
"""
        sql_path = REPORT_DIR / f"warn-governance-rollback-{time.strftime('%Y%m%d')}.sql"
        sql_path.write_text(sql, encoding="utf-8")

        # 治理报告
        by_subject: dict[str, int] = {}
        for r in rows:
            by_subject[r[1] or "NULL"] = by_subject.get(r[1] or "NULL", 0) + 1
        lines = [
            f"# warn 题治理报告（{time.strftime('%Y-%m-%d')}）",
            "",
            f"- 明细 CSV：`{csv_path}`",
            f"- 备份：`{backup}`",
            f"- 回滚 SQL：`{sql_path}`",
            f"- 处置：`validation_status='warn'` 的 {affected} 行置 `is_available=false`（软下架，保留数据）",
            "",
            "## 按科目",
            "",
            "| 科目 | warn 数 |",
            "|---|---|",
        ]
        for s, c in sorted(by_subject.items(), key=lambda x: -x[1]):
            lines.append(f"| {s} | {c} |")
        lines += ["", "## 回滚", "", "见上方回滚 SQL：将 `validation_status='warn'` 的行恢复 `is_available=true`。"]
        md_path.write_text("\n".join(lines), encoding="utf-8")

        print("\n===== 治理完成 =====")
        print(f"CSV: {csv_path}")
        print(f"备份: {backup}")
        print(f"回滚 SQL: {sql_path}")
        print(f"报告: {md_path}")
        print(f"成功软下架: {affected} 行")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())
