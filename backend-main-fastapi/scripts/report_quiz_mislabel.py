# -*- coding: utf-8 -*-
"""生成「疑似错标」报告：高置信自动分类结果与库内标签冲突的题。

用途：库内标签存在噪声（如数字电子的题被标成模拟电子），这些冲突题既是
自动入库精度被"看低"的原因，也提示库内标签本身需要订正。输出 JSON 供人工复核。

用法：
    python scripts/report_quiz_mislabel.py                 # 数字/模拟全量扫描
    python scripts/report_quiz_mislabel.py --limit 5000 --min-conf 0.90
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="生成题库疑似错标报告")
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--min-conf", type=float, default=0.92)
    ap.add_argument("--out", default="scripts/data/quiz_mislabel_report.json")
    args = ap.parse_args()

    from database import SessionLocal
    from models import QuizQuestion
    from sqlalchemy import func
    from services.quiz_classifier_v2 import classify_batch_v2

    db = SessionLocal()
    try:
        rows = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.subject.in_(["数字电子技术", "模拟电子技术"]))
            .filter(QuizQuestion.is_junk.is_(False) | QuizQuestion.is_junk.is_(None))
            .filter(func.length(QuizQuestion.content) >= 20)
            .order_by(func.random())
            .limit(args.limit)
            .all()
        )
        qs = [{"content": r.content, "options": r.options if isinstance(r.options, list) else None}
              for r in rows]
        decs = classify_batch_v2(qs, db=db, use_llm=False)
        report = []
        for r, d in zip(rows, decs):
            if (d.subject.confidence >= args.min_conf
                    and d.subject.value and d.subject.value != r.subject):
                report.append({
                    "id": r.id,
                    "library_subject": r.subject,
                    "predicted_subject": d.subject.value,
                    "confidence": round(d.subject.confidence, 4),
                    "source": d.subject.source,
                    "document_id": getattr(r, "document_id", None),
                    "source_name": getattr(r, "source", None),
                    "content": (r.content or "")[:120],
                })
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f"扫描 {len(rows)} 题，疑似错标 {len(report)} 题 → {args.out}")
        for it in report[:12]:
            print(f"  库内={it['library_subject']} 预测={it['predicted_subject']}"
                  f"({it['confidence']:.2f}) id={it['id']} | {it['content'][:46]}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
