# -*- coding: utf-8 -*-
"""临时诊断：向量路是否真的生效（英语/政治为何全空）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from services.quiz_classifier_v2 import (
    _load_vector_assets,
    _keyword_decision,
)


def main():
    db = SessionLocal()
    try:
        embed_func, centroids = _load_vector_assets(db)
        print("embed_func:", "OK" if embed_func else "NONE")
        print("centroids subjects:", list(centroids.keys()) if centroids else None)
        if centroids:
            for k, v in centroids.items():
                print(f"  centroid {k}: dim={v.size}")

        samples = [
            ("英语", "Read the following passage and choose the best answer. The main idea of the text is about..."),
            ("政治", "马克思主义哲学认为，物质是标志客观实在的哲学范畴，这种客观实在是人通过感觉感知的。"),
            ("计算机学科专业基础408", "在一个二叉树的遍历中，已知前序序列和中序序列，如何唯一确定该二叉树的结构？"),
            ("数学", "求极限 lim(x->0) sin(x)/x 的值，并使用洛必达法则验证。"),
        ]
        for gold_subj, txt in samples:
            kw = _keyword_decision(txt)
            print(f"\n[{gold_subj}] text={txt[:40]!r}")
            print(f"  kw -> {kw.value}({kw.confidence},{kw.source})")
            if embed_func is not None and centroids:
                from services.quiz_classifier_v2 import _vector_decision_from_embedding
                from services.chunk_classifier import encode_texts, vector_scores
                embs = embed_func([txt])
                print("  embed None?", embs is None)
                if embs is not None:
                    vs = vector_scores(embs[0], centroids)
                    print("  top vec scores:", sorted(vs.items(), key=lambda kv: -kv[1])[:3])
                    vd = _vector_decision_from_embedding(embs[0], centroids)
                    print(f"  vec decision -> {vd.value}({vd.confidence})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
