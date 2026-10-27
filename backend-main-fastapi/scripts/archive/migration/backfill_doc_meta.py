# -*- coding: utf-8 -*-
"""回填存量资料的「三层结构」与「扫描件」标记。

`services.kb_service.detect_doc_meta` 只在新上传/解析文档时打标记，
但库里 1545 篇历史资料都还没有 `doc_type` / `structure_level` / `ocr_used`，
不补的话前端按层级筛选会全是空。

标记口径（与 kb_service 一致）：
    doc_type        raw 原始层 / note 加工层 / index 索引层
    structure_level structured 已解析出章节 / flat 扁平文本 / ocr 扫描件
    ocr_used        是否为扫描件 OCR 来源

幂等：只补空缺，不覆盖已有值。
执行：
    cd backend-main-fastapi
    python scripts/backfill_doc_meta.py            # 实际执行
    python scripts/backfill_doc_meta.py --dry-run  # 只看统计
"""

from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from database import SessionLocal  # noqa: E402
from models import Document  # noqa: E402
from services import kb_service, structure_parser  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv
IMAGE_TYPES = ("jpg", "jpeg", "png", "bmp", "tiff", "webp")


def main() -> int:
    db = SessionLocal()
    try:
        docs = db.query(Document).all()
        print(f"扫描 {len(docs)} 篇资料" + ("（DRY-RUN）" if DRY_RUN else ""))

        stats = Counter()
        type_dist: Counter = Counter()
        level_dist: Counter = Counter()

        for doc in docs:
            changed = False
            content = doc.content or ""
            file_type = (doc.file_type or "").lower()

            # 1. 资料层级
            if not doc.doc_type:
                doc.doc_type = kb_service.classify_doc_type(doc.file_name, doc.file_type)
                stats["doc_type"] += 1
                changed = True
            type_dist[doc.doc_type] += 1

            # 2. 扫描件判定：图片型文件，或正文里带 OCR 页标记
            ocr_like = file_type in IMAGE_TYPES or "页(OCR)" in content
            if ocr_like and not doc.ocr_used:
                doc.ocr_used = True
                stats["ocr_used"] += 1
                changed = True

            # 3. 结构化程度
            if not doc.structure_level and content:
                parsed = structure_parser.parse_structure(content, doc.subject)
                doc.structure_level = "ocr" if ocr_like else parsed["level"]
                stats["structure_level"] += 1
                if not ocr_like and parsed["level"] == "structured":
                    stats["parsed_structured"] += 1
                changed = True
            level_dist[doc.structure_level or "未标记"] += 1

            if changed and not DRY_RUN:
                db.add(doc)

        if not DRY_RUN:
            db.commit()

        print("\n=== 回填结果 ===")
        print(f"  doc_type 补齐：{stats['doc_type']}")
        print(f"  structure_level 补齐：{stats['structure_level']}")
        print(f"    其中解析出章节结构：{stats['parsed_structured']}")
        print(f"  ocr_used 标记：{stats['ocr_used']}")

        print("\n=== 资料层级分布 ===")
        labels = {"raw": "原始层", "note": "加工层", "index": "索引层"}
        for k, v in type_dist.most_common():
            print(f"  {str(k):<8} {labels.get(k, ''):<6} {v:>5} 篇")

        print("\n=== 结构化程度分布 ===")
        for k, v in level_dist.most_common():
            print(f"  {k:<12} {v:>5}")

        if DRY_RUN:
            print("\n[!] DRY-RUN 模式，未写入数据库")
        else:
            print("\n[✓] 回填完成")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
