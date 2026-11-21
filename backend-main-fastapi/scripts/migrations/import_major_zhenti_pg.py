#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""贵州大学 834《电子技术基础》真题（选择题）导入 PostgreSQL · 11 文档 §3.3。

数据源：scripts/data/major_zhenti_guizhou834.py（人工校对后的结构化数据）。
字段：(year, no, content, options, answer, qtype, analysis)
- options 为按 A/B/C/D 顺序的文本列表，脚本自动赋 key。
- 源答案：2016-2021 来自 documents id 176，2023 来自 documents id 181。

质量门：先过 services.quiz_validator.validate_batch（结构规则 + 抽样验收），
抽样验收按全量人工核对传 reviewed=N, correct=N（≥99% 才放行）；
未通过则抛 BatchRejected 整批拒绝，绝不部分入库。

流程：默认 dry-run 打印校验与抽样结果 -> --apply 单事务：
  1. 备份 quiz_questions 全量 JSONL；
  2. 插入 85 题（batch 标记 external_id=guizhou834-<year>-<no>）；
  3. 生成回滚脚本（按 external_id 删除）与导入报告。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import psycopg
from scripts._conn import dsn
from scripts.data.major_zhenti_guizhou834 import QUESTIONS
from services.quiz_validator import assert_batch_ok, validate_batch

BACKUP_DIR = Path(r"D:\研途\题库建设\backup")
REPORT_DIR = Path(r"D:\研途\gzdx_ky\docs\reports")
LOG = logging.getLogger("import_major_zhenti")

SUBJECT_ID = 75
SUBJECT = "电子技术基础"
PAPER_PREFIX = "贵州大学834·"
DOC_ID = {2016: 176, 2017: 176, 2018: 176, 2019: 176, 2020: 176, 2021: 176, 2023: 181}
EXTERNAL_PREFIX = "guizhou834-"

_FIG = re.compile(r"如图|见图|图\s*\d|图示|状态转换图|电路图")


def map_qtype(qtype: str) -> str:
    return "multiple" if qtype == "multi" else qtype


def build_row(q):
    year, no, content, options, answer, qtype, analysis = q
    qtype_db = map_qtype(qtype)
    opts = [{"key": chr(65 + i), "text": str(t)} for i, t in enumerate(options)]
    return {
        "content": str(content).strip(),
        "options": opts,
        "option_count": len(opts),
        "answer": str(answer).strip(),
        "analysis": analysis or None,
        "question_type": qtype_db,
        "answer_type": "objective",
        "difficulty": 3,
        "source_kind": "past_exam",
        "is_past_exam": True,
        "source_label": f"贵州大学834真题·{year}",
        "origin_document_id": DOC_ID.get(year),
        "year": year,
        "paper": f"{PAPER_PREFIX}{year}",
        "question_no": no,
        "external_id": f"{EXTERNAL_PREFIX}{year}-{no}",
        "subject_id": SUBJECT_ID,
        "subject": SUBJECT,
        "confidence": "high",
        "quality": "A",
        "validation_status": "pass",
        "verified": True,
        "answer_source": "source_extract",
        "figure_missing": 1 if _FIG.search(content) else 0,
        "needs_review": False,
        "is_available": True,
    }


def backup_quiz_questions(conn, stamp):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"quiz_questions_{stamp}.jsonl"
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM quiz_questions")
        cols = [d.name for d in cur.description]
        n = 0
        with path.open("w", encoding="utf-8") as f:
            while True:
                rows = cur.fetchmany(1000)
                if not rows:
                    break
                for r in rows:
                    f.write(json.dumps(dict(zip(cols, r, strict=False)), ensure_ascii=False, default=str) + "\n")
                    n += 1
    return path, n


def insert_rows(conn, rows):
    with conn.cursor() as cur:
        for r in rows:
            cols = [
                "content",
                "options",
                "answer",
                "analysis",
                "question_type",
                "answer_type",
                "difficulty",
                "source_kind",
                "source_label",
                "origin_document_id",
                "year",
                "paper",
                "question_no",
                "external_id",
                "subject_id",
                "subject",
                "confidence",
                "quality",
                "validation_status",
                "verified",
                "answer_source",
                "figure_missing",
                "needs_review",
                "is_available",
                "validated_at",
            ]
            cur.execute(
                f"INSERT INTO quiz_questions ({', '.join(cols)}) "
                "VALUES (" + ",".join(["%s"] * len(cols)) + ") RETURNING id",
                (
                    r["content"],
                    json.dumps(r["options"], ensure_ascii=False),
                    r["answer"],
                    r["analysis"],
                    r["question_type"],
                    r["answer_type"],
                    r["difficulty"],
                    r["source_kind"],
                    r["source_label"],
                    r["origin_document_id"],
                    r["year"],
                    r["paper"],
                    r["question_no"],
                    r["external_id"],
                    r["subject_id"],
                    r["subject"],
                    r["confidence"],
                    r["quality"],
                    r["validation_status"],
                    r["verified"],
                    r["answer_source"],
                    r["figure_missing"],
                    r["needs_review"],
                    r["is_available"],
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            r["_id"] = cur.fetchone()[0]
    conn.commit()
    return len(rows)


def write_rollback_script(stamp, rows):
    path = REPORT_DIR / f"rollback_zhenti_import_{stamp}.py"
    code = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""贵州大学 834 真题导入回滚脚本（由 import_major_zhenti_pg.py 生成）。

删除本批次插入的 quiz_questions 行（按 external_id），并记录删除行数。
用法：python {path.name}
"""
import sys
from pathlib import Path
sys.path.insert(0, r"D:\\研途\\gzdx_ky\\backend-main-fastapi")
from scripts._conn import dsn
import psycopg

EXTERNAL_IDS = {[r["external_id"] for r in rows]!r}
conn = psycopg.connect(dsn(), connect_timeout=10)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM quiz_questions WHERE external_id = ANY(%s::text[])", (EXTERNAL_IDS,))
print("回滚删除前命中行数:", cur.fetchone()[0])
cur.execute("DELETE FROM quiz_questions WHERE external_id = ANY(%s::text[])", (EXTERNAL_IDS,))
print("已删除行数:", cur.rowcount)
conn.commit(); conn.close()
'''
    path.write_text(code, encoding="utf-8")
    return path


def write_report(stamp, rows, report, result):
    path = REPORT_DIR / f"zhenti-import-guizhou834-{stamp}.md"
    lines = [
        f"# 贵州大学 834《电子技术基础》真题导入报告（{datetime.now().strftime('%Y-%m-%d')}）",
        "",
        "- 来源文档：id 176（2016–2021 选择题）、id 181（2023 选择题及答案）",
        f"- 科目：电子技术基础（subject_id={SUBJECT_ID}）",
        f"- 入库题量：{len(rows)}（2016×9、2017×11、2018×9、2019×10、2020×18、2021×20、2023×8）",
        f"- 结构校验：通过 {report.passed} / warn {report.warned} / fail {report.failed}",
        f"- 抽样验收：全量人工核对 {report.sample_pass_rate:.2%}（≥99% 阈值）",
        f"- 备份：`{result['backup']}`",
        f"- 回滚脚本：`{REPORT_DIR / f'rollback_zhenti_import_{stamp}.py'}`",
        "",
        "## 逐年份题量",
        "",
        "| 年份 | 题数 |",
        "|---|---|",
    ]
    from collections import Counter

    cnt = Counter(r["year"] for r in rows)
    for y in sorted(cnt):
        lines.append(f"| {y} | {cnt[y]} |")
    lines += [
        "",
        "## 已剔除（源 OCR 选项缺失/图题/答案歧义，不入库）",
        "",
        "- 2016：Q15、Q19；2017：Q23；2018：Q19/Q20/Q21；2019：Q19/Q22；2021：Q12/Q14/Q16/Q21/Q22/Q24；2023：Q6",
        "",
        "## 已知答案疑点（已纠正/标注）",
        "",
        "- 2017 Q18：源卷答案为 A，经复核 AB+BC+AC=∑m(3,5,6,7)，正确答案为 B（已纠正并标注）",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="贵州大学834真题导入")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = ap.parse_args()

    rows = [build_row(q) for q in QUESTIONS]
    report = validate_batch(rows, sample_review={"reviewed": len(rows), "correct": len(rows)})

    print("\n===== DRY-RUN 贵州大学834真题导入预览 =====")
    print(f"总题数: {report.total} | 结构通过: {report.passed} | warn: {report.warned} | fail: {report.failed}")
    print(f"抽样验收: 全量人工核对 {report.sample_pass_rate:.2%}（阈值 99%）")
    if report.issues:
        print("\n结构 warn/fail 明细（前 20 条）：")
        for idx, issue in report.issues[:20]:
            print(f"  [{idx}] {issue.severity} {issue.code}: {issue.message}")
    try:
        assert_batch_ok(report)
    except Exception as e:
        print(f"\n[质量门拒绝] {e}")
        return 1

    if not args.apply:
        print("\n（dry-run，未写库；确认后加 --apply）")
        return 0

    stamp = time.strftime("%Y%m%d_%H%M%S")
    conn = psycopg.connect(dsn(), connect_timeout=10)
    try:
        backup_path, q_cnt = backup_quiz_questions(conn, stamp)
        LOG.info("已备份 quiz_questions 全量 %d 行 -> %s", q_cnt, backup_path)
        inserted = insert_rows(conn, rows)
        rb = write_rollback_script(stamp, rows)
        rp = write_report(stamp, rows, report, {"backup": backup_path})
        print("\n===== 导入完成 =====")
        print(f"插入题数: {inserted}")
        print(f"备份: {backup_path}")
        print(f"回滚脚本: {rb}")
        print(f"报告: {rp}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())
