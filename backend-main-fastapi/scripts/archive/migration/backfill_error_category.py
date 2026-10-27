#!/usr/bin/env python
"""错因回填（S2）：给 error_category 为空的错题按可观测信号补一个错因。

用法：
    python scripts/backfill_error_category.py            # dry-run
    python scripts/backfill_error_category.py --apply

判定走 ``services.error_analyzer.infer_error_category``（信号驱动，零 LLM）：
    未作答+耗时短→时间不足 / 未作答→方法没想到 / 计算作图→计算错误 /
    简答填空→记忆缺失 / 选择判断秒选→审题失误 / 其余→概念混淆

幂等：只处理 error_category IS NULL 或空串的行，重跑无副作用。
**不覆盖**已有值（用户手填或 AI 归因的结果一律尊重）。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from services.error_analyzer import infer_error_category  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行（默认 dry-run）")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT e.id, e.my_answer, e.correct_answer, e.subject,
                   q.question_type, q.options
              FROM error_records e
              LEFT JOIN quiz_questions q ON q.id = e.question_id
             WHERE e.error_category IS NULL OR btrim(e.error_category) = ''
             ORDER BY e.id
        """)).fetchall()

        print(f"待回填错题：{len(rows)} 条")
        stats = Counter()
        for rid, my_ans, correct, subject, qtype, options in rows:
            opt_n = None
            if options:
                try:
                    opt_n = len(options) if isinstance(options, list) else None
                except Exception:  # noqa: BLE001
                    opt_n = None
            cat = infer_error_category(
                question_type=qtype, my_answer=my_ans, correct_answer=correct,
                option_count=opt_n, subject=subject,
            )
            stats[cat] += 1
            if args.apply:
                db.execute(text(
                    "UPDATE error_records SET error_category = :c, updated_at = now() WHERE id = :i"),
                    {"c": cat, "i": rid})
        if args.apply:
            db.commit()

        print("\n=== 判定分布（%s）===" % ("APPLIED" if args.apply else "DRY-RUN"))
        for k, v in stats.most_common():
            print(f"  {k:<10} {v}")

        total = db.execute(text("SELECT count(*) FROM error_records")).scalar()
        filled = db.execute(text(
            "SELECT count(*) FROM error_records WHERE error_category IS NOT NULL AND btrim(error_category) <> ''")).scalar()
        print(f"\n错因覆盖率：{filled}/{total} = {filled / max(total, 1) * 100:.1f}%")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
