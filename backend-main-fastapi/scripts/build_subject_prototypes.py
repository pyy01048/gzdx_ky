# -*- coding: utf-8 -*-
"""学科原型质心构建（docx/14 阶段 A）。

为 `subject_prototypes` 表构建各学科 bge 质心：种子块要求
**文档级标签与 chunk 级关键词判定一致**（保守口径），且过乱码/碎片门禁 ——
质心被脏种子带偏比没有质心更糟。

bge 模型不可用时**直接拒绝构建**：`knowledge_chunks_vec` 里哈希向量与 bge
同为 512 维，混进去就是静默崩盘（见 chunk_classifier 头部口径红线）。

用法：
    python scripts/build_subject_prototypes.py                # 默认每科 60 块
    python scripts/build_subject_prototypes.py --per-subject 100 --force
    python scripts/build_subject_prototypes.py --dry-run      # 只看种子分布
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from collections import defaultdict

import numpy as np

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

SEED = 42
MIN_CHUNK_CHARS = 200      # 短块（OCR 碎片/目录行）不做种子
MAX_CHUNK_CHARS = 4000     # 超长块截断编码，质心取前段语义


MANUAL_SEEDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "data", "manual_seeds.json")
MANUAL_MIN_CHARS = 120   # 人工教材段质量有保证，不受库内 200 字噪声门禁约束


def _load_manual_seeds() -> dict[str, list[str]]:
    """人工撰写的教材式种子段（冷门科目库里没语料时唯一可靠来源）。"""
    if not os.path.exists(MANUAL_SEEDS_PATH):
        return {}
    import json
    with open(MANUAL_SEEDS_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: [t for t in v if len(t) >= MANUAL_MIN_CHARS] for k, v in raw.items()}


def collect_seeds(db, per_subject: int) -> dict[str, list[str]]:
    """按学科收集种子块文本。

    优先级：人工教材段（manual_seeds.json）> 严格双一致 > 文档级宽松填充。
    实测信号与系统/通信原理/普通物理在库里只有几条 ~1000 字"网络补充"txt，
    不配人工种子这几科就永远没有质心。

    两级库内口径：
      严格 = 文档标签 × chunk 关键词判定**双一致**且高置信（首选，最干净）；
      宽松 = 仅文档级标签一致 + 过乱码/碎片门禁（严格不足 MIN_STRICT 的科用它填充）。
    """
    from models import Document, KnowledgeChunk
    from services.chunk_classifier import _normalize_subject, subject_candidates
    from services.kb_service import classify_subject_confidence, is_parse_failure

    MIN_STRICT = 10
    manual = _load_manual_seeds()
    cands = set(subject_candidates())
    docs = db.query(Document).filter(Document.subject.isnot(None)).all()
    strict: dict[str, list] = defaultdict(list)
    loose: dict[str, list] = defaultdict(list)
    rng = random.Random(SEED)

    for doc in docs:
        doc_subj = _normalize_subject(doc.subject or "")
        if not doc_subj or doc_subj not in cands:
            continue
        chunks = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.document_id == doc.id)
            .all()
        )
        texts = [c.text or "" for c in chunks if len(c.text or "") >= MIN_CHUNK_CHARS]
        if not texts:
            continue
        rng.shuffle(texts)
        for t in texts[:20]:            # 单文档最多吃 20 块，防一份大教材垄断质心
            if is_parse_failure(t):
                continue
            try:
                from services.kp_extract import text_is_mojibake

                if text_is_mojibake(t):
                    continue
            except Exception:  # noqa: BLE001
                pass
            t = t[:MAX_CHUNK_CHARS]
            kw_subj, confident = classify_subject_confidence(doc.file_name, t)
            if confident and _normalize_subject(kw_subj) == doc_subj:
                strict[doc_subj].append(t)
            else:
                loose[doc_subj].append(t)

    seeds: dict[str, list[str]] = {}
    for subj in set(strict) | set(loose) | set(manual):
        if subj not in cands:      # 非候选学科不建质心（softmax 会摊薄有效科的分数）
            continue
        pool = list(manual.get(subj, []))          # 人工教材段优先且不受 20/篇上限
        pool.extend(strict.get(subj, []))
        if len(pool) < MIN_STRICT:
            extra = loose.get(subj, [])
            rng.shuffle(extra)
            pool.extend(extra)
        seeds[subj] = pool[:per_subject]
    return seeds


def main() -> int:
    ap = argparse.ArgumentParser(description="构建学科原型质心（仅 bge 真模型）")
    ap.add_argument("--per-subject", type=int, default=60, help="每科种子块上限")
    ap.add_argument("--force", action="store_true", help="覆盖已有质心")
    ap.add_argument("--subjects", default="",
                    help="只重建这些学科（逗号分隔）。改判文档学科后只有对应质心被污染，"
                         "全量 --force 会顺带动到域内科的既有基准，故按科重建。")
    ap.add_argument("--dry-run", action="store_true", help="只统计种子分布，不写库")
    args = ap.parse_args()

    from services.chunk_classifier import encode_texts, ensure_chunk_label_columns

    if encode_texts(["健康检查"]) is None:
        print("❌ bge 模型不可用，拒绝构建（哈希向量做质心=噪声）。")
        print("   先运行 python download_embedding_model.py 或设置 EMBEDDING_BACKEND=bge 并缓存模型。")
        return 1

    from database import SessionLocal
    from models import SubjectPrototype

    # 新表可能还没被服务器启动 create_all 过，幂等补建
    from database import Base, engine
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        ensure_chunk_label_columns(db)
        seeds = collect_seeds(db, args.per_subject)
        only = {s.strip() for s in args.subjects.split(",") if s.strip()}
        if only:
            missing = only - set(seeds)
            if missing:
                print(f"⚠️ 请求重建但没种子块的学科: {sorted(missing)}")
            seeds = {k: v for k, v in seeds.items() if k in only}
        print(f"{'学科':<14} 种子块数")
        for s in sorted(seeds):
            print(f"{s:<14} {len(seeds[s])}")
        weak = [s for s, v in seeds.items() if len(v) < 10]
        if weak:
            print(f"⚠️ 种子不足 10 块，质心不稳定，本次跳过: {weak}")
        if args.dry_run:
            return 0

        built = 0
        for subj, texts in sorted(seeds.items()):
            if len(texts) < 10:
                continue
            existing = (
                db.query(SubjectPrototype)
                .filter(SubjectPrototype.subject == subj, SubjectPrototype.engine == "bge")
                .first()
            )
            if existing and not args.force:
                continue
            vecs = encode_texts(texts)
            if vecs is None:
                print("❌ 编码中断（bge 失效），已写入的不回滚，重跑即可")
                return 1
            normed = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
            centroid = normed.mean(axis=0)
            centroid = centroid / max(float(np.linalg.norm(centroid)), 1e-9)
            row = existing or SubjectPrototype(subject=subj, engine="bge")
            row.dim = int(centroid.size)
            row.vector = centroid.astype(np.float32).tobytes()
            row.n_samples = len(texts)
            import datetime
            row.built_at = datetime.datetime.now(datetime.timezone.utc)
            if existing is None:
                db.add(row)
            db.commit()
            built += 1
        print(f"✅ 质心写入 {built} 科（engine=bge）")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
