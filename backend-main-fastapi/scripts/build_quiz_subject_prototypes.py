# -*- coding: utf-8 -*-
"""构建「题目科目质心」到 quiz_subject_centroids 表（bge 向量）。

为什么自建表：历史 subject_prototypes 表的 ORM（models.py）与库结构
（subject_id / prototype bytea / prototype_vec）对不上，导致向量信号长期静默失效、
科目分类退化为纯关键词。本脚本与 quiz_classifier_v2 共用 quiz_subject_centroids，
完全用原始 SQL 管理，绕开 ORM/DB 不同步的坑。

种子：quiz_questions 中「库内标签 + 题干独立 ≥2 关键词」双重确认的高精语料。

用法：
    python scripts/build_quiz_subject_prototypes.py --per-subject 120
    python scripts/build_quiz_subject_prototypes.py --force
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def collect_seeds(db, per_subject: int) -> dict:
    """种子 = 该科「库内标签」下、长度达标、非 junk 的题（信任库内标签）。

    早期版本用「题干 ≥2 关键词命中」筛种子，导致 数学/英语/政治 等小科目只攒出
    9~26 条种子，质心近乎噪声、向量信号长期失效。这里改为**信任库内标签**，直接
    用该科全部「非 junk」库内题建质心——质心是平均向量，少量错标会被平均掉。
    仅剔除 junk（真垃圾）与长度不足；is_available=False 仅表示"尚未处理"而非劣质，
    故不排除，以让小科目攒够样本。
    """
    from models import QuizQuestion
    from services.quiz_autoclassify import _SUBJECT_RULES
    from sqlalchemy import func

    seeds: dict = {}
    for subject, _kws in _SUBJECT_RULES:
        rows = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.subject == subject)
            .filter(QuizQuestion.is_junk.is_(False) | QuizQuestion.is_junk.is_(None))
            .filter(func.length(QuizQuestion.content) >= 20)
            .limit(per_subject * 4)
            .all()
        )
        pool = []
        for r in rows:
            content = (r.content or "").strip()
            if len(content) < 20:
                continue
            pool.append(content)
            if len(pool) >= per_subject:
                break
        if pool:
            seeds[subject] = pool
    return seeds


def ensure_table(db) -> None:
    from sqlalchemy import text
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS quiz_subject_centroids ("
        "  subject VARCHAR(50) PRIMARY KEY,"
        "  engine VARCHAR(20) NOT NULL DEFAULT 'bge',"
        "  dim INTEGER NOT NULL,"
        "  vector BYTEA NOT NULL,"
        "  n_samples INTEGER NOT NULL DEFAULT 0,"
        "  built_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
    db.commit()


def upsert(db, subject: str, centroid: np.ndarray, n: int) -> None:
    from sqlalchemy import text
    db.execute(text(
        "INSERT INTO quiz_subject_centroids (subject, engine, dim, vector, n_samples, built_at) "
        "VALUES (:s, 'bge', :d, :v, :n, now()) "
        "ON CONFLICT (subject) DO UPDATE SET "
        "engine=EXCLUDED.engine, dim=EXCLUDED.dim, vector=EXCLUDED.vector, "
        "n_samples=EXCLUDED.n_samples, built_at=now()"),
        {"s": subject, "d": int(centroid.size),
         "v": centroid.astype(np.float32).tobytes(), "n": n})
    db.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description="构建题目科目质心（bge）")
    ap.add_argument("--per-subject", type=int, default=120)
    ap.add_argument("--force", action="store_true", help="覆盖已有质心")
    args = ap.parse_args()

    from services.chunk_classifier import encode_texts
    if encode_texts(["健康检查"]) is None:
        print("❌ bge 不可用，拒绝构建。先缓存 bge 模型。")
        return 1

    from database import SessionLocal

    db = SessionLocal()
    try:
        ensure_table(db)
        seeds = collect_seeds(db, args.per_subject)
        print(f"{'学科':<16} 种子数")
        for s in sorted(seeds):
            print(f"{s:<16} {len(seeds[s])}")
        if not seeds:
            print("⚠️ 无种子（题目库缺科目标注？）")
            return 1
        built = 0
        for subj, texts in sorted(seeds.items()):
            if not args.force:
                existing = db.execute(
                    __import__("sqlalchemy").text(
                        "SELECT 1 FROM quiz_subject_centroids WHERE subject=:s"),
                    {"s": subj}).fetchone()
                if existing:
                    continue
            vecs = encode_texts(texts)
            if vecs is None:
                print(f"❌ {subj} 编码失败")
                continue
            normed = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
            centroid = normed.mean(axis=0)
            centroid = centroid / max(float(np.linalg.norm(centroid)), 1e-9)
            upsert(db, subj, centroid, len(texts))
            built += 1
        print(f"✅ 质心写入 {built} 科 → quiz_subject_centroids")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
