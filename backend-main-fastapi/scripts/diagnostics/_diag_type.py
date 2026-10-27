# -*- coding: utf-8 -*-
"""临时诊断：题型分类 预测 vs 库内标签 混淆 + 库内类型分布。"""
import json
import os
import sys
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import QuizQuestion
from sqlalchemy import func
from services.quiz_classifier_v2 import classify_type_v2


def main():
    db = SessionLocal()
    try:
        # 库内类型分布
        rows = db.query(QuizQuestion.question_type, func.count(QuizQuestion.id)) \
            .group_by(QuizQuestion.question_type).all()
        print("库内 question_type 分布：")
        for t, c in sorted(rows, key=lambda x: -x[1]):
            print(f"  {repr(t):<14} {c}")
        print()

        gold = json.load(open("scripts/data/quiz_classify_silver.json", encoding="utf-8"))
        conf = collections.Counter()
        mism = []
        for g in gold:
            d = classify_type_v2(g["content"], g.get("options"))
            gt = g.get("question_type") or "single"
            conf[(gt, d.value)] += 1
            if d.value != gt:
                mism.append((gt, d.value, d.confidence, (g["content"] or "")[:44]))
        print("混淆（库内→预测）：")
        for (gt, pv), c in conf.most_common():
            mark = "" if gt == pv else "  ✗"
            print(f"  {gt:<10}-> {pv:<10} {c}{mark}")
        print(f"\n不符样例（前 15）：")
        for gt, pv, cf, txt in mism[:15]:
            print(f"  库内={gt} 预测={pv}({cf:.2f}) | {txt}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
