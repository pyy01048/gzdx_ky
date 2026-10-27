# -*- coding: utf-8 -*-
"""真实库置信-精度曲线：数字/模拟题按 subject 置信分桶，看各档精度与覆盖。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import QuizQuestion
from sqlalchemy import func
from services.quiz_classifier_v2 import classify_batch_v2

BUCKETS = [(0.92, 1.01), (0.88, 0.92), (0.84, 0.88), (0.80, 0.84),
           (0.70, 0.80), (0.60, 0.70), (0.0, 0.60)]


def main():
    db = SessionLocal()
    try:
        rows = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.subject.in_(["数字电子技术", "模拟电子技术"]))
            .filter(QuizQuestion.is_junk.is_(False) | QuizQuestion.is_junk.is_(None))
            .filter(func.length(QuizQuestion.content) >= 20)
            .order_by(func.random())
            .limit(3000)
            .all()
        )
        qs = [{"content": r.content, "options": r.options if isinstance(r.options, list) else None}
              for r in rows]
        truth = [r.subject for r in rows]
        decs = classify_batch_v2(qs, db=db, use_llm=False)
        n = len(rows)
        print(f"样本 {n} 题")
        print(f"{'置信区间':>14}{'题数':>7}{'占比':>8}{'精度':>8}{'≥阈值覆盖':>10}{'≥阈值精度':>10}")
        # 累积（≥阈值）视角
        for lo, hi in BUCKETS:
            sel = [(t, d) for t, d in zip(truth, decs) if lo <= d.subject.confidence < hi]
            if not sel:
                continue
            okk = sum(1 for t, d in sel if d.subject.value == t)
            print(f"{f'[{lo:.2f},{min(hi,1.0):.2f})':>14}{len(sel):>7}{len(sel)/n:>8.1%}{okk/len(sel):>8.3f}")
        print()
        for th in (0.80, 0.84, 0.88, 0.90, 0.92):
            sel = [(t, d) for t, d in zip(truth, decs) if d.subject.confidence >= th]
            if not sel:
                print(f"  阈值 {th:.2f}: 覆盖 0%")
                continue
            okk = sum(1 for t, d in sel if d.subject.value == t)
            print(f"  阈值 {th:.2f}: 覆盖 {len(sel)/n:>6.1%}  精度 {okk/len(sel):>6.3f}  ({okk}/{len(sel)})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
