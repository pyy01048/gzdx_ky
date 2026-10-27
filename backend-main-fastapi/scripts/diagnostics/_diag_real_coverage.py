# -*- coding: utf-8 -*-
"""真实库覆盖/精度：在 quiz_questions 上跑 v2，用库内标签为 数字/模拟 的题做真值。"""
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
        # 抽样：库内标签为 数字/模拟（占库绝大多数），用其标签做真值
        rows = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.subject.in_(["数字电子技术", "模拟电子技术"]))
            .filter(QuizQuestion.is_junk.is_(False) | QuizQuestion.is_junk.is_(None))
            .filter(func.length(QuizQuestion.content) >= 20)
            .order_by(func.random())
            .limit(2000)
            .all()
        )
        qs = [{"content": r.content, "options": r.options if isinstance(r.options, list) else None}
              for r in rows]
        truth = [r.subject for r in rows]
        decs = classify_batch_v2(qs, db=db, use_llm=False)
        auto = auto_ok = tot = 0
        for t, d in zip(truth, decs):
            tot += 1
            if d.auto_accept:
                auto += 1
                if d.subject.value == t:
                    auto_ok += 1
        print(f"样本(数字/模拟) {tot} 题")
        print(f"自动入库覆盖率: {auto/tot:.3f} ({auto}/{tot})")
        print(f"★ 自动入库精度: {auto_ok/auto:.3f} ({auto_ok}/{auto})  [以库内标签为真值]")
        leaks = [(t, d.subject.value, d.subject.confidence, d.subject.source, (qs[i]["content"] or "")[:50])
                 for i, (t, d) in enumerate(zip(truth, decs))
                 if d.auto_accept and d.subject.value != t]
        if leaks:
            print(f"\n[精度漏网] 自动入库但科目判错 {len(leaks)} 例：")
            for t, p, c, s, txt in leaks:
                print(f"  gold={t} pred={p}({c:.2f},{s}) | {txt}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
