# -*- coding: utf-8 -*-
"""临时诊断：数字/模拟 sibling 余弦间隙，用于设置兄弟科自动入库守卫阈值。"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from services.quiz_classifier_v2 import _load_vector_assets


def _raw_cos(emb, centroids):
    q = emb / max(np.linalg.norm(emb), 1e-9)
    out = {}
    for s, c in centroids.items():
        c = c / max(np.linalg.norm(c), 1e-9)
        out[s] = float(np.dot(q, c))
    return out


SIB = {"数字电子技术", "模拟电子技术"}


def main():
    db = SessionLocal()
    try:
        gold = json.load(open("scripts/data/quiz_classify_silver.json", encoding="utf-8"))
        embed_func, centroids = _load_vector_assets(db)
        print(f"{'gold':<12}{'pred':<12}{'corr':>5}{'c_pred':>7}{'c_sib':>7}{'gap':>7}")
        for g in gold:
            if g["subject"] not in SIB:
                continue
            txt = g["content"]
            embs = embed_func([txt])
            cos = _raw_cos(embs[0], centroids)
            pred = max(cos, key=cos.get)
            c_pred = cos[pred]
            # sibling = the other of the pair
            sib = (SIB - {pred}).pop() if pred in SIB else None
            c_sib = cos.get(sib, 0.0) if sib else 0.0
            gap = c_pred - c_sib
            corr = "✓" if pred == g["subject"] else "✗"
            print(f"{g['subject']:<12}{pred:<12}{corr:>5}{c_pred:>7.3f}{c_sib:>7.3f}{gap:>7.3f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
