# -*- coding: utf-8 -*-
"""临时诊断：逐题原始余弦 / 边距 / 融合置信，用于校准向量置信。"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from services.quiz_classifier_v2 import (
    _load_vector_assets,
    _keyword_decision,
    _fuse_subject,
)


def _raw_cos(emb, centroids):
    q = emb / max(np.linalg.norm(emb), 1e-9)
    out = {}
    for s, c in centroids.items():
        c = c / max(np.linalg.norm(c), 1e-9)
        out[s] = float(np.dot(q, c))
    return out


def main():
    db = SessionLocal()
    try:
        gold = json.load(open("scripts/data/quiz_classify_silver.json", encoding="utf-8"))
        embed_func, centroids = _load_vector_assets(db)
        print(f"{'gold':<10}{'pred':<12}{'correct':>7}{'fused_conf':>11}{'top1_cos':>9}{'margin':>8}{'vec_softmax':>12}")
        for g in gold:
            txt = g["content"]
            kw = _keyword_decision(txt)
            embs = embed_func([txt])
            cos = _raw_cos(embs[0], centroids)
            ranked = sorted(cos.items(), key=lambda kv: -kv[1])
            top1, top1c = ranked[0]
            top2c = ranked[1][1] if len(ranked) > 1 else 0.0
            margin = top1c - top2c
            # softmax 与 classify 内部一致
            vals = np.array([v for v in cos.values()], dtype=np.float64)
            w = np.exp(vals * 6.0); w /= w.sum()
            sm = dict(zip(cos.keys(), w))
            vec = {"value": top1, "conf": sm[top1], "source": "vector"}
            from services.quiz_classifier_v2 import FieldDecision
            fvec = FieldDecision(top1, round(float(sm[top1]), 4), "vector")
            fused = _fuse_subject(kw, fvec, use_llm=False, text=txt, db=db)
            correct = "✓" if fused.value == g["subject"] else "✗"
            print(f"{g['subject']:<10}{fused.value:<12}{correct:>7}{fused.confidence:>11.3f}{top1c:>9.3f}{margin:>8.3f}{sm[top1]:>12.3f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
