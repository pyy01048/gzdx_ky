# -*- coding: utf-8 -*-
"""临时诊断：数字/模拟 各题 classify_subject_v2 输出（value/conf/source）vs 真值。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from services.quiz_classifier_v2 import classify_subject_v2, _load_vector_assets


def main():
    db = SessionLocal()
    try:
        gold = json.load(open("scripts/data/quiz_classify_silver.json", encoding="utf-8"))
        embed_func, centroids = _load_vector_assets(db)
        print(f"{'gold':<12}{'pred':<12}{'corr':>5}{'conf':>7}{'src':<10}")
        for g in gold:
            if g["subject"] not in ("数字电子技术", "模拟电子技术"):
                continue
            d = classify_subject_v2(g["content"], embed_func=embed_func, protos=centroids, db=db, use_llm=False)
            corr = "✓" if d.value == g["subject"] else "✗"
            print(f"{g['subject']:<12}{d.value:<12}{corr:>5}{d.confidence:>7.3f}{d.source:<10}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
