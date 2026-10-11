# -*- coding: utf-8 -*-
"""⚠️ 已被 `rebuild_knowledge_base.py` 取代，请勿单独运行。

保留原因：本脚本记录了早期"只补空缺、不重建"的思路，作历史参考。

为什么被取代：实测存量那 898 条 knowledge_points 里 **631 条是自动抽取噪声**
（幻灯片标题拼接、OCR 断句残片、页面导航文字），`chapter` 字段里存的也是文件名和考卷名。
"补空缺"救不了这种数据 —— 只能重建。现在请用：

    python migrate.py                      # 统一入口，按顺序执行
    python scripts/rebuild_knowledge_base.py --dry-run   # 单独预览重建

以下为原始说明（内容已过期，功能仍可用）：
---------------------------------------------------------------
存量数据回填：把扁平数据补齐成「章节 → 知识点 → 题型」三级结构。

处理内容：
  1. 科目归一化（8 类 → 主线 6 类 + 拓展 5 类，修掉"电子技术基础"等别名）
  2. documents.doc_type      → 原始层 / 加工层 / 索引层
  3. documents.structure_level → structured / flat / ocr，并标记 ocr_used
  4. knowledge_points.chapter → 从来源文档正文里解析出的章节树回填
  5. knowledge_points.question_types → 按知识点名 / 科目题型表回填
  6. knowledge_points.next_review → 给未排期的知识点排首次复习（明天）

幂等：重复执行只补空缺，不覆盖已填好的值。
执行：
    cd backend-main-fastapi
    python scripts/migrate_structure.py            # 实际执行
    python scripts/migrate_structure.py --dry-run  # 只看统计不改库
"""

from __future__ import annotations

import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from database import SessionLocal  # noqa: E402
from models import Document, KnowledgePoint  # noqa: E402
from services import taxonomy, structure_parser  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv

# --------------------------------------------------------------------------- #
# 文件名 → 资料层级
# --------------------------------------------------------------------------- #
_NOTE_KW = ["笔记", "总结", "整理", "错题", "手写", "摘要", "划重点"]
_INDEX_KW = ["思维导图", "考点清单", "大纲", "目录", "速查", "索引"]
_RAW_KW = ["教材", "课本", "真题", "试卷", "试题", "题库", "习题", "讲义", "课件", "模拟"]


def classify_doc_type(file_name: str, file_type: str) -> str:
    n = file_name or ""
    if any(k in n for k in _INDEX_KW):
        return "index"
    if any(k in n for k in _NOTE_KW):
        return "note"
    if any(k in n for k in _RAW_KW):
        return "raw"
    # 图片/扫描件一律算原始层
    if file_type in ("jpg", "jpeg", "png", "bmp", "tiff", "webp"):
        return "raw"
    return "raw"


def main() -> int:
    db = SessionLocal()
    try:
        stats = {
            "subject_normalized": 0,
            "doc_type_filled": 0,
            "structure_parsed": 0,
            "chapter_filled": 0,
            "chapter_reused": 0,
            "types_filled": 0,
            "review_scheduled": 0,
        }

        # ---------------- 1. 科目归一化 ---------------- #
        print("=== 1. 科目归一化 ===")
        for model, label in ((Document, "documents"), (KnowledgePoint, "knowledge_points")):
            for row in db.query(model).all():
                std = taxonomy.normalize_subject(row.subject)
                if std != row.subject:
                    stats["subject_normalized"] += 1
                    if not DRY_RUN:
                        row.subject = std
        if not DRY_RUN:
            db.commit()
        print(f"  归一化 {stats['subject_normalized']} 条记录的科目")

        # ---------------- 2. 文档层级 + 结构化解析 ---------------- #
        print("\n=== 2. 文档层级与结构解析 ===")
        docs = db.query(Document).all()
        struct_cache: dict[int, dict] = {}

        for doc in docs:
            changed = False
            # 资料层级
            if not doc.doc_type:
                doc.doc_type = classify_doc_type(doc.file_name, doc.file_type)
                stats["doc_type_filled"] += 1
                changed = True

            # 扫描件标记：文件名/内容里带 OCR 痕迹
            ocr_like = ("OCR" in (doc.content or "")[:3000]) or (
                (doc.file_type or "").lower() in ("jpg", "jpeg", "png", "bmp", "tiff", "webp")
            )
            if ocr_like and not doc.ocr_used:
                doc.ocr_used = True
                changed = True

            # 结构解析
            if not doc.structure_level and doc.content and len(doc.content) > 200:
                parsed = structure_parser.parse_structure(doc.content, doc.subject)
                struct_cache[doc.id] = parsed
                doc.structure_level = "ocr" if ocr_like else parsed["level"]
                if parsed["level"] == "structured":
                    stats["structure_parsed"] += 1
                changed = True
            elif doc.content:
                parsed = structure_parser.parse_structure(doc.content, doc.subject)
                struct_cache[doc.id] = parsed

            if changed and not DRY_RUN:
                db.add(doc)

        if not DRY_RUN:
            db.commit()
        print(f"  填充 doc_type {stats['doc_type_filled']} 篇；"
              f"解析出章节结构 {stats['structure_parsed']} 篇（共扫描 {len(docs)} 篇）")

        # ---------------- 3. 知识点补章节 ---------------- #
        print("\n=== 3. 知识点补章节 ===")
        kps = db.query(KnowledgePoint).all()
        # 只为"被知识点引用的文档"解析章节树，避免解析 1500+ 篇无关键
        needed_doc_ids = {kp.document_id for kp in kps if kp.document_id}
        struct_cache = {
            doc_id: parsed for doc_id, parsed in struct_cache.items()
            if doc_id in needed_doc_ids
        }
        missing = [d for d in needed_doc_ids if d not in struct_cache]
        if missing:
            print(f"  补充解析 {len(missing)} 篇被引用的文档…")
            for doc in db.query(Document).filter(Document.id.in_(missing)).all():
                if doc.content:
                    struct_cache[doc.id] = structure_parser.parse_structure(doc.content, doc.subject)
        # 按科目收集"文档 → 章节名集合"，用于名称匹配
        for kp in kps:
            changed = False

            # 3a. 通过来源文档的章节树 + 知识点名匹配
            chapter = None
            if kp.document_id and kp.document_id in struct_cache:
                parsed = struct_cache[kp.document_id]
                chapter = _match_chapter(kp.name, parsed)
                if chapter:
                    stats["chapter_reused"] += 1

            # 3b. 回退：同科目下已有同名/近名知识点的章节
            if not chapter and kp.chapter:
                chapter = kp.chapter

            if chapter and not kp.chapter:
                kp.chapter = chapter
                stats["chapter_filled"] += 1
                changed = True

            # 3c. 题型回填
            if not kp.question_types:
                hinted = taxonomy.guess_question_type(kp.name or "", kp.subject)
                types = [hinted] if hinted else []
                for t in taxonomy.question_types_of(kp.subject):
                    if t not in types:
                        types.append(t)
                    if len(types) >= 4:
                        break
                kp.question_types = types
                stats["types_filled"] += 1
                changed = True

            # 3d. 首次复习排期（明天开始进队列）
            if kp.next_review is None and not kp.last_review:
                kp.next_review = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)
                stats["review_scheduled"] += 1
                changed = True

            if changed and not DRY_RUN:
                db.add(kp)

        if not DRY_RUN:
            db.commit()

        print(f"  补章节 {stats['chapter_filled']} 个（其中按文档章节匹配 {stats['chapter_reused']} 个）")
        print(f"  补题型 {stats['types_filled']} 个")
        print(f"  排首次复习 {stats['review_scheduled']} 个")

        # ---------------- 4. 汇总 ---------------- #
        print("\n=== 4. 迁移结果 ===")
        from sqlalchemy import func
        rows = (
            db.query(KnowledgePoint.subject, func.count(KnowledgePoint.id))
            .group_by(KnowledgePoint.subject).all()
        )
        for subject, cnt in sorted(rows, key=lambda x: -x[1]):
            with_ch = db.query(func.count(KnowledgePoint.id)).filter(
                KnowledgePoint.subject == subject,
                KnowledgePoint.chapter.isnot(None),
                KnowledgePoint.chapter != "",
            ).scalar() or 0
            print(f"  {subject:<12} 知识点 {cnt:>5}  已标章节 {with_ch:>5}  "
                  f"({round(with_ch / cnt * 100, 1) if cnt else 0}%)")

        if DRY_RUN:
            print("\n[!] --dry-run 模式，未写入数据库")
        else:
            print("\n[✓] 回填完成")
        return 0
    finally:
        db.close()


def _match_chapter(kp_name: str, parsed: dict) -> str | None:
    """在章节树里找包含该知识点名的章节。"""
    name = (kp_name or "").strip()
    if not name or len(name) < 2:
        return None
    for ch in parsed.get("chapters", []):
        for sec in ch.get("sections", []):
            sec_title = (sec.get("title") or "").strip()
            if not sec_title:
                continue
            # 去掉小节编号前缀再比较
            body = sec_title
            for prefix in ("第",):
                if body.startswith(prefix):
                    body = body.split("节", 1)[-1].strip() if "节" in body else body
            body = body.lstrip("0123456789.、 ")
            if not body:
                continue
            # 双向包含：知识点名 ⊂ 小节名，或小节名 ⊂ 知识点名
            if name in body or body in name:
                return ch["title"]
        if name and name in ch.get("title", ""):
            return ch["title"]
    return None


if __name__ == "__main__":
    raise SystemExit(main())
