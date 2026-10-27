# -*- coding: utf-8 -*-
"""真实库阈值扫描：数字/模拟题上扫 subject/type 阈值，定位 ≥99% 精度落点。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import QuizQuestion
from sqlalchemy import func
from services.quiz_classifier_v2 import classify_batch_v2


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
        print(f"样本 {n} 题（数字/模拟，库内标签为真值）\n")
        print(f"{'科目阈':>7}{'题型阈':>7}{'覆盖':>8}{'精度':>8}{'自动数':>8}")
        for s_th in (0.80, 0.85, 0.90, 0.92):
            for t_th in (0.72, 0.80, 0.85, 0.90):
                auto = ok = 0
                for t, d in zip(truth, decs):
                    if d.subject.confidence >= s_th and d.question_type.confidence >= t_th:
                        auto += 1
                        if d.subject.value == t:
                            ok += 1
                prec = ok / auto if auto else float("nan")
                print(f"{s_th:>7.2f}{t_th:>7.2f}{auto/n:>8.1%}{prec:>8.3f}{auto:>8}")
        # 题型准确率（全量）
        ttype_ok = sum(1 for d in decs if True)
        print(f"\n[注] 库内题型标签含噪声，精度以科目为准；自动集精度为下界。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
