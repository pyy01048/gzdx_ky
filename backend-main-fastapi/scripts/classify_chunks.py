# -*- coding: utf-8 -*-
"""存量 chunk 三层标签回填（docx/14 阶段 B）。

默认只处理**尚未打标**的块（l3_content_type IS NULL），按文档为单位跑
（bge 批量编码 + LLM 成本闸门在 chunk_classifier 内部）。

用法：
    python scripts/classify_chunks.py --limit 20            # 先抽 20 篇试跑
    python scripts/classify_chunks.py --all --force         # 全量两路重打（默认口径）
    python scripts/classify_chunks.py --doc-id 123 --llm    # 单篇带上路3 对比
    python scripts/classify_chunks.py --doc-id 123 --force  # 重打单篇

路3（LLM 兜底）默认关闭：实测 eval_runs #9/#10 在 147 人工标注样本上
Accuracy 0.728→0.707、Macro-F1 0.665→0.639，数电 P 0.77→0.63、408 R 0.92→0.62，
只有数学小幅受益（F1 0.96→0.98）。整体是负增益，只在单篇排障时手动开。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)


def main() -> int:
    # Windows 控制台/重定向默认 GBK，含中文与 emoji 的汇总行会抛 UnicodeEncodeError，
    # 让跑成功的回填以 traceback 收尾（真实回填结果已经落库，却被误判为失败）。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # noqa: BLE001
            pass

    ap = argparse.ArgumentParser(description="存量 chunk 三路融合打标回填")
    ap.add_argument("--doc-id", type=int, nargs="*", help="只处理指定文档")
    ap.add_argument("--limit", type=int, default=None, help="本次最多处理多少篇文档")
    ap.add_argument("--all", action="store_true", help="处理所有文档（含已打标，需配 --force）")
    ap.add_argument("--force", action="store_true", help="已打标的块也重打")
    ap.add_argument("--llm", dest="use_llm", action="store_true", default=False,
                    help="启用路3（默认关：147 人工样本实测 两路 Acc 0.728/MF1 0.665 "
                         "→ 三路 0.707/0.639，负增益）")
    ap.add_argument("--no-llm", dest="use_llm", action="store_false",
                    help="显式关闭路3（与当前默认一致，保留给旧命令与文档示例）")
    args = ap.parse_args()

    from sqlalchemy import func

    from database import SessionLocal
    from models import Document, KnowledgeChunk
    from services import chunk_classifier
    from services.chunk_classifier import encode_texts, load_prototypes

    db = SessionLocal()
    try:
        chunk_classifier.ensure_chunk_label_columns(db)
        protos_ok = bool(load_prototypes(db))
        if not protos_ok:
            print("⚠️ subject_prototypes 为空 —— 路1 不可用，先跑 "
                  "scripts/build_subject_prototypes.py；本次仅关键词(+LLM)两路。")
        elif encode_texts(["ping"]) is None:
            # 原来这条检查挂在 `if args.use_llm` 下：关路3 时 bge 掉了也一声不吭，
            # 整轮回填悄悄退化成"仅关键词"，实测就是这么产出大批低置信 vector 标签的。
            print("⚠️ bge 模型不可用 —— 路1 质心相似度实际不会参与融合，"
                  "本次只剩关键词一路，结果置信度会大面积偏低。")

        q = db.query(Document.id, Document.file_name).filter(
            Document.id.in_(
                db.query(KnowledgeChunk.document_id).distinct()
            )
        )
        if not args.doc_id and not args.force:
            q = q.filter(
                Document.id.in_(
                    db.query(KnowledgeChunk.document_id)
                    .filter(KnowledgeChunk.l3_content_type.is_(None))
                    .distinct()
                )
            )
        if args.doc_id:
            q = q.filter(Document.id.in_(args.doc_id))
        q = q.order_by(Document.id)
        if args.limit:
            q = q.limit(args.limit)
        docs = q.all()
        if not docs:
            print("没有待打标文档")
            return 0

        t0 = time.time()
        done = 0
        for i, (doc_id, name) in enumerate(docs, 1):
            r = chunk_classifier.classify_document(
                db, doc_id, use_llm=args.use_llm,
                only_unlabeled=not args.force)
            done += 1
            agg = r.get("aggregate") or {}
            # llm=成功数 llm_fail=失败数 junk=弃权数：只看成功数无法区分
            # "路3 没触发" 与 "路3 全部失败"，实测就是这么把 NameError 藏了整轮回填。
            print(f"[{i}/{len(docs)}] doc#{doc_id} {str(name)[:36]} → "
                  f"chunks={r.get('chunks')} llm={r.get('llm_calls', 0)} "
                  f"llm_fail={r.get('llm_failed', 0)} junk={r.get('junk_skipped', 0)} "
                  f"main={agg.get('main_subject', '')} mixed={agg.get('mixed')}")
        labeled = db.query(func.count(KnowledgeChunk.id)).filter(
            KnowledgeChunk.l3_content_type.isnot(None)).scalar() or 0
        total = db.query(func.count(KnowledgeChunk.id)).scalar() or 0
        print(f"✅ 本次处理 {done} 篇，耗时 {time.time()-t0:.0f}s；"
              f"库内已打标 {labeled}/{total} 块")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
