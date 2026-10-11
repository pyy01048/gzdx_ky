# -*- coding: utf-8 -*-
"""知识库重建：把"能检索但不能用"的数据，重建成「章节→知识点→题型」三级结构。

### 为什么必须重建（实测证据）

| 问题 | 实测 |
|------|------|
| 知识点是垃圾 | 898 条里 631 条是幻灯片标题拼接 / OCR 断句残片 / 页面导航文字 |
| chapter 字段存错东西 | 185 个数电章节名里只有 4 个是标准章名，其余是文件名、考卷名 |
| 题目几乎没有 | 1545 篇资料只有 7 道题，而真题正文就一直躺在 documents.content 里 |
| 掌握度是死的 | mastery 字段无任何写入路径 |

### 本脚本做什么

1. 归档旧知识点（导出 JSON，不删除，保留可追溯性）
2. 从真题正文抽取**真实题目** → quiz_questions（带 科目/章节/知识点/题型）
3. 从权威来源重建考点：834 考纲 → 章节化资料 → 真题考点
4. 把题目关联到知识点（回写 question_count / exam_frequency）
5. 输出体检对照表

执行：
    cd backend-main-fastapi
    python scripts/rebuild_knowledge_base.py --dry-run   # 先看统计
    python scripts/rebuild_knowledge_base.py             # 实际执行
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from database import SessionLocal  # noqa: E402
from models import Document, KnowledgePoint, QuizQuestion  # noqa: E402
from services import taxonomy, qbank_builder, kp_builder, kp_cleaner  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv
ARCHIVE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "archive"
)

# 真题/题库来源（按文件名识别）
_EXAM_PATTERNS = [
    "真题", "考试卷", "试题", "题库", "试卷", "模拟试题", "章节题库", "练习题",
]
# 排除：明显不是题目的（答案册、笔记、讲义）
_EXAM_EXCLUDE = ["答案部分", "笔记", "讲义", "知识点", "总结", "大纲", "考纲"]


def _is_exam_doc(file_name: str) -> bool:
    n = file_name or ""
    if any(x in n for x in _EXAM_EXCLUDE):
        return False
    return any(p in n for p in _EXAM_PATTERNS)


def _readable_ratio(text: str) -> float:
    """正文可读率：中文/ASCII 可打印字符占比，多点采样（乱码头尾都能抓到）。"""
    c = text or ""
    if not c:
        return 0.0
    n = len(c)
    spans = [(0, 3000), (max(0, n // 2 - 1500), n // 2 + 1500), (max(0, n - 3000), n)]
    ok = tot = 0
    for a, b in spans:
        seg = c[a:b]
        tot += len(seg)
        ok += sum(
            1 for ch in seg
            if ch.isprintable() and (ch.isascii() or "\u4e00" <= ch <= "\u9fa5")
        )
    return ok / max(tot, 1)


# 旧版 .doc 二进制被当文本解码后的确定性特征：
# 正常真题正文不会同时出现 "Root Entry"、"Microsoft Office Word"、
# 控制字符、以及 WordSummary 之类的内部流名。
_JUNK_MARKERS = [
    "Root Entry", "WordDocument", "Microsoft Office Word",
    "SummaryInformation", "ProductBuildVer", "WpsCustomData",
    "ObjectPool", "CompObj", "Times New Roman(",
]


def _junk_score(text: str) -> int:
    """命中多少个二进制垃圾特征。"""
    c = (text or "")[:20000]
    score = sum(1 for m in _JUNK_MARKERS if m in c)
    # 控制字符（除 \n \t \r）出现次数，二进制解码后必然很多
    ctrl = sum(1 for ch in c if ord(ch) < 32 and ch not in "\n\t\r")
    if ctrl > 50:
        score += 3
    elif ctrl > 10:
        score += 1
    return score


def _is_junk_text(text: str) -> bool:
    return _junk_score(text) >= 2


def _looks_like_outline(text: str) -> bool:
    """正文必须真的像考纲：含"考试科目"且含"电路部分"这类分节标记。"""
    c = text or ""
    return ("考试科目" in c) and ("部分" in c) and ("掌握" in c or "了解" in c)


def main() -> int:
    db = SessionLocal()
    try:
        print("=" * 74)
        print("知识库重建" + ("（DRY-RUN 预览）" if DRY_RUN else ""))
        print("=" * 74)

        # ================= 1. 归档旧知识点 ================= #
        old_kps = db.query(KnowledgePoint).all()
        print(f"\n[1] 旧知识点 {len(old_kps)} 条")
        junk = valid = 0
        for k in old_kps:
            if kp_cleaner.assess_knowledge_point(k.name, k.subject)["is_valid"]:
                valid += 1
            else:
                junk += 1
        print(f"    质量判定：可用 {valid} / 垃圾 {junk}"
              f"（{round(junk/max(len(old_kps),1)*100,1)}% 为自动抽取噪声）")

        # 先把"其他"科目的条目捞出来 —— 它们其实是数电/模电章名，
        # 但必须在下面 DELETE 之前读取（删了就查不到了）。
        other_kp_rows = [
            {"id": k.id, "name": k.name, "description": k.description}
            for k in old_kps if (k.subject or "") == "其他"
        ]

        if not DRY_RUN and old_kps:
            os.makedirs(ARCHIVE_DIR, exist_ok=True)
            path = os.path.join(ARCHIVE_DIR, "knowledge_points_legacy.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    [{
                        "id": k.id, "name": k.name, "subject": k.subject,
                        "chapter": k.chapter, "mastery": k.mastery,
                        "document_id": k.document_id, "description": k.description,
                    } for k in old_kps],
                    f, ensure_ascii=False, indent=1,
                )
            print(f"    已归档 → {path}")

        # ================= 2. 抽取真实题目 ================= #
        print("\n[2] 从真题正文抽取题目")
        # 只取判定所需的列，避免把 1500+ 篇全文一次性读进内存
        from sqlalchemy import select

        doc_rows = db.execute(
            select(Document.id, Document.file_name, Document.subject, Document.content)
        ).all()
        exam_docs = [d for d in doc_rows if _is_exam_doc(d.file_name or "")]
        print(f"    命中真题/题库类文档 {len(exam_docs)} 篇")

        # 已有题目内容指纹，用于去重
        existing_hashes = set()
        for q in db.query(QuizQuestion).all():
            existing_hashes.add(qbank_builder.content_hash(q.content or ""))

        extracted: list[dict] = []
        per_doc: list[tuple[str, int]] = []
        skipped_binary = 0
        for doc in exam_docs:
            content = doc.content or ""
            if len(content) < 200:
                continue
            # 旧版 .doc 二进制正文是乱码，抽出来全是垃圾题
            if _is_junk_text(content):
                skipped_binary += 1
                continue
            try:
                qs = qbank_builder.extract_questions(content)
            except Exception as e:
                print(f"    [!] {doc.file_name[:40]} 抽取失败: {e}")
                continue
            kept = 0
            for q in qs:
                h = qbank_builder.content_hash(q["content"])
                if h in existing_hashes:
                    continue
                cls = qbank_builder.classify_question(
                    q["content"],
                    subject_hint=doc.subject,
                    section_type=q["section_type"],
                )
                # 只收编能定位到 数电/模电 的题（834 口径）
                if cls["subject"] not in ("数字电子技术", "模拟电子技术"):
                    continue
                existing_hashes.add(h)
                q.update(cls)
                q["document_id"] = doc.id
                q["doc_name"] = doc.file_name
                extracted.append(q)
                kept += 1
            if kept:
                per_doc.append((doc.file_name, kept))

        print(f"    抽出有效题目 {len(extracted)} 道（去重后）"
              + (f"，跳过二进制乱码文档 {skipped_binary} 篇" if skipped_binary else ""))
        for name, cnt in sorted(per_doc, key=lambda x: -x[1])[:12]:
            print(f"      {cnt:>4} 道  {name[:56]}")

        subj_dist: dict[str, int] = {}
        chap_dist: dict[str, int] = {}
        type_dist: dict[str, int] = {}
        for q in extracted:
            subj_dist[q["subject"]] = subj_dist.get(q["subject"], 0) + 1
            type_dist[q["section_type"] or "未识别"] = type_dist.get(q["section_type"] or "未识别", 0) + 1
            if q.get("chapter"):
                chap_dist[q["chapter"]] = chap_dist.get(q["chapter"], 0) + 1
        print(f"    科目分布：{subj_dist}")
        print(f"    题型分布：{type_dist}")
        print(f"    章节归位：{len(chap_dist)} 个章节有题")

        if not DRY_RUN and extracted:
            for q in extracted:
                db.add(QuizQuestion(
                    content=q["content"],
                    options=q.get("options") or None,
                    answer=q.get("answer"),
                    analysis=q.get("analysis"),
                    subject=q["subject"],
                    chapter=q.get("chapter"),
                    knowledge_point=q.get("knowledge_point") or "",
                    difficulty=q.get("difficulty") or 3,
                    source=f"真题:{q.get('doc_name','')[:80]}",
                    question_type=q.get("question_type") or "single",
                ))
            db.commit()
            print(f"    [✓] 已写入 quiz_questions {len(extracted)} 道")

        # ================= 3. 重建考点 ================= #
        print("\n[3] 重建考点（章节 → 知识点 → 题型）")

        # 3a. 834 考纲
        # 注意：不能只用 "834" 匹配文件名 —— "贵大2022年834真题" 也会命中。
        # 必须文件名同时含 834 且含 考纲/大纲；且正文可读率足够高
        # （.doc 旧版二进制解析出来是乱码，必须排除）。
        outline_items: list[dict] = []
        outline_text = ""
        outline_doc = None
        candidates = db.query(Document).filter(
            Document.file_name.like("%834%"),
            (Document.file_name.like("%考纲%")) | (Document.file_name.like("%大纲%")),
        ).all()
        readable = [
            d for d in candidates
            if not _is_junk_text(d.content)
            and _looks_like_outline(d.content)
            and len(d.content or "") > 300
        ]
        # 同内容优先选 .txt（解析干净的），再按长度
        readable.sort(key=lambda d: (".txt" not in (d.file_name or ""), -len(d.content or "")))
        if readable:
            outline_doc = readable[0]
            outline_text = outline_doc.content
            print(f"    考纲来源：{outline_doc.file_name}（{len(outline_text)} 字，"
                  f"可读率 {_readable_ratio(outline_text):.0%}）")
        else:
            print("    [!] 未找到可读的 834 考纲文档，跳过考纲考点")

        for item in kp_builder.parse_834_outline(outline_text):
            subj = _module_subject(item["module"])
            chapter = kp_cleaner.map_chapter(
                item["name"], None, subj, item["requirement"]
            )
            outline_items.append({
                "name": item["name"],
                "subject": subj,
                "chapter": chapter or f"834考纲·{item['module'] or '总则'}",
                "description": f"【考纲要求·{item['verb']}】{item['requirement']}",
                "difficulty": kp_builder.outline_difficulty(item["verb"]),
                "question_types": taxonomy.question_types_of(subj),
                "source": "outline",
            })
        print(f"    834 考纲 → {len(outline_items)} 条考点")
        for it in outline_items[:8]:
            print(f"      · [{it['subject']}] {it['name'][:34]}  →  {it['chapter']}")

        # 3b. 章节化资料（doc_rows 已在上方按列取出，避免重复载入全文）
        chapter_items = kp_builder.knowledge_points_from_chapter_files(doc_rows)
        print(f"    章节化资料 → {len(chapter_items)} 条")

        # 3c. 真题考点
        # 关键：考点必须从**题库全量**推导，而不是只从本次新抽出的题目推导。
        # 否则脚本第二次运行（题目已入库、extracted 为空）会把真题考点清零。
        qb_rows = db.query(QuizQuestion).all()
        # 补齐历史题里没抽出考点的（首次抽取时可能没命中术语表）
        backfilled = 0
        for q in qb_rows:
            if q.subject in ("数字电子技术", "模拟电子技术") and not q.knowledge_point:
                cls = qbank_builder.classify_question(
                    q.content or "", subject_hint=q.subject,
                    section_type=_label_of_type(q.question_type),
                )
                if cls["knowledge_point"]:
                    q.knowledge_point = cls["knowledge_point"]
                    backfilled += 1
                if not q.chapter and cls["chapter"]:
                    q.chapter = cls["chapter"]
        if backfilled:
            db.flush()
            print(f"    补齐 {backfilled} 道题的考点标注")

        qb_for_kp = [
            {"knowledge_point": q.knowledge_point, "subject": q.subject,
             "chapter": q.chapter, "question_type": q.question_type}
            for q in qb_rows
            if (q.subject in ("数字电子技术", "模拟电子技术"))
        ]
        question_items = kp_builder.knowledge_points_from_questions(qb_for_kp)
        # 按出现次数给考频
        for it in question_items:
            it["exam_frequency"] = min(5, max(1, it.get("question_count", 0)))
        print(f"    真题考点 → {len(question_items)} 条（来自题库 {len(qb_for_kp)} 道题）")

        all_items = outline_items + chapter_items + question_items

        # 3d. 归位"其他"科目（在其他数据源里其实是数电/模电章名）
        reclassified = 0
        for row in other_kp_rows:
            name = (row["name"] or "").replace("数－模", "数模").replace("模－数", "模数").lstrip("-").strip()
            guessed = qbank_builder._guess_subject(name) or qbank_builder._guess_subject(row["description"] or "")
            if not guessed:
                continue
            chapter = kp_cleaner.map_chapter(name, None, guessed, row["description"] or "")
            all_items.append({
                "name": name,
                "subject": guessed,
                "chapter": chapter,
                "description": row["description"],
                "source": "reclassify",
            })
            reclassified += 1
        print(f"    '其他'科目归位 → {reclassified}/{len(other_kp_rows)} 条")

        print(f"    合计待写入 {len(all_items)} 条")
        if DRY_RUN:
            print("    （DRY-RUN 未写入）")
        else:
            # 安全闸：一旦有错题/复习记录挂在这些知识点上，说明系统已在真实使用，
            # 直接 DELETE 会把 error_knowledge_links / review_records 变成悬空引用。
            # 此时拒绝执行，要求走增量补齐（不加 --force）。
            from sqlalchemy import func

            from models import ErrorKnowledgeLink, ReviewRecord

            link_refs = db.query(func.count(ErrorKnowledgeLink.id)).filter(
                ErrorKnowledgeLink.knowledge_point_id.isnot(None)
            ).scalar() or 0
            review_refs = db.query(func.count(ReviewRecord.id)).filter(
                ReviewRecord.item_type == "knowledge"
            ).scalar() or 0

            if (link_refs or review_refs) and "--force" not in sys.argv:
                print(f"\n[!] 检测到知识点已被引用：错题关联 {link_refs} 条、复习记录 {review_refs} 条。")
                print("    重建会清空知识点表并让这些引用悬空，已中止。")
                print("    如确认要重建，请显式加 --force（并自行承担关联丢失）。")
                return 2

            # 清掉旧的噪声知识点（已归档 JSON，可追溯）。
            # 不删会更糟：垃圾条目混在新结构里，章节/进度统计全是假的。
            removed = db.query(KnowledgePoint).delete(synchronize_session=False)
            db.flush()
            print(f"    已清理旧知识点 {removed} 条（归档在 data/archive/knowledge_points_legacy.json）")

            res = kp_builder.upsert_knowledge_points(db, all_items, commit=False)
            print(f"    [✓] 新建 {res['created']} 条 / 补全 {res['updated']} 条 / 跳过 {res['skipped']} 条")

            # 3e. 合并同名重复知识点（不同来源会产出同名条目，如"触发器"）
            db.flush()
            merged = _dedupe_knowledge_points(db)
            print(f"    合并同名重复 {merged} 条")

            # 步骤 4：把题量/考频**重新推导**一遍（幂等，不是递增）。
            # 递增会让脚本每次重跑都把题量翻倍，所以这里按题库重新统计覆盖。
            print("\n[4] 题目关联知识点（按题库重新统计题量与考频）")
            db.flush()
            kp_all = db.query(KnowledgePoint).all()
            by_subject: dict[str, list[KnowledgePoint]] = {}
            for kp in kp_all:
                by_subject.setdefault(taxonomy.normalize_subject(kp.subject), []).append(kp)

            # 先清零，再重新统计
            for kp in kp_all:
                kp.question_count = 0
            db.flush()

            linked = 0
            for q in db.query(QuizQuestion).all():
                subj = taxonomy.normalize_subject(q.subject)
                pool = by_subject.get(subj, [])
                if not pool:
                    continue
                stem = q.content or ""
                kp = None
                # 优先：题干里出现知识点名（取最长命中，避免"门电路"盖过"TTL与非门"）
                hits = [k for k in pool if k.name and len(k.name) >= 2 and k.name in stem]
                if hits:
                    kp = max(hits, key=lambda k: len(k.name))
                # 回退：同章节下考频最高的知识点
                elif q.chapter:
                    same_ch = [k for k in pool if k.chapter == q.chapter]
                    if same_ch:
                        kp = max(same_ch, key=lambda k: (k.exam_frequency or 0))
                if not kp:
                    continue
                kp.question_count = (kp.question_count or 0) + 1
                if q.chapter and not kp.chapter:
                    kp.chapter = q.chapter
                linked += 1

            # 由题量反推考频（1 题=1 星，5 题及以上=5 星）
            for kp in kp_all:
                n = kp.question_count or 0
                if n:
                    kp.exam_frequency = min(5, max(1, n))

            db.commit()
            print(f"    已关联 {linked} 道题 → 知识点（题量、考频已按题库重算）")

        # ================= 5. 体检对照 ================= #
        print("\n[5] 重建后体检")
        total_kp = db.query(KnowledgePoint).count()
        total_q = db.query(QuizQuestion).count()
        print(f"    知识点：{len(old_kps)} → {total_kp}")
        print(f"    题目：7 → {total_q}")

        from sqlalchemy import func
        print("\n    各科目知识点 / 已标章节：")
        for subj, cnt in db.query(
            KnowledgePoint.subject, func.count(KnowledgePoint.id)
        ).group_by(KnowledgePoint.subject).order_by(func.count(KnowledgePoint.id).desc()).all():
            with_ch = db.query(func.count(KnowledgePoint.id)).filter(
                KnowledgePoint.subject == subj,
                KnowledgePoint.chapter.isnot(None),
                KnowledgePoint.chapter != "",
            ).scalar() or 0
            with_qt = db.query(func.count(KnowledgePoint.id)).filter(
                KnowledgePoint.subject == subj,
                KnowledgePoint.question_types.isnot(None),
            ).scalar() or 0
            print(f"      {subj:<14} {cnt:>5}  章节 {with_ch:>5} ({round(with_ch/cnt*100) if cnt else 0}%)"
                  f"  题型 {with_qt:>5}")

        print("\n    各科目题目数：")
        for subj, cnt in db.query(
            QuizQuestion.subject, func.count(QuizQuestion.id)
        ).group_by(QuizQuestion.subject).order_by(func.count(QuizQuestion.id).desc()).all():
            with_ch = db.query(func.count(QuizQuestion.id)).filter(
                QuizQuestion.subject == subj, QuizQuestion.chapter.isnot(None)
            ).scalar() or 0
            print(f"      {subj:<14} {cnt:>5}  已归章节 {with_ch:>5}")

        if DRY_RUN:
            print("\n[!] DRY-RUN 模式，未写入数据库")
        else:
            print("\n[✓] 知识库重建完成")
        return 0
    finally:
        db.close()


def _module_subject(module: str) -> str:
    if "数字" in (module or ""):
        return "数字电子技术"
    if "模拟" in (module or ""):
        return "模拟电子技术"
    return "真题综合"


# 数据库题型（single/fill/...）→ 中文题型（选择/填空/...）
_TYPE_LABELS = {
    "single": "选择", "multiple": "多选", "judge": "判断",
    "fill": "填空", "essay": "简答", "calc": "计算", "draw": "画图",
}


def _label_of_type(qtype: str | None) -> str:
    return _TYPE_LABELS.get((qtype or "").strip(), "")


def _dedupe_knowledge_points(db) -> int:
    """合并 (科目, 名称) 相同的知识点，保留信息最全的一条。

    不同数据源会产出同名条目（"触发器"同时来自章节资料和真题考点），
    不合并会让同一个考点在进度面板里出现两次，掌握度还算两遍。
    """
    from collections import defaultdict

    groups: dict[tuple[str, str], list] = defaultdict(list)
    for kp in db.query(KnowledgePoint).all():
        groups[(taxonomy.normalize_subject(kp.subject), (kp.name or "").strip())].append(kp)

    merged = 0
    for (subj, name), rows in groups.items():
        if len(rows) < 2 or not name:
            continue
        rows.sort(key=lambda k: (k.question_count or 0), reverse=True)
        keep = rows[0]
        for dup in rows[1:]:
            keep.question_count = (keep.question_count or 0) + (dup.question_count or 0)
            keep.exam_frequency = max(keep.exam_frequency or 0, dup.exam_frequency or 0)
            keep.difficulty = max(keep.difficulty or 3, dup.difficulty or 3)
            if not keep.chapter and dup.chapter:
                keep.chapter = dup.chapter
            if not keep.description and dup.description:
                keep.description = dup.description
            # 题型取并集
            types = list(dict.fromkeys((keep.question_types or []) + (dup.question_types or [])))
            keep.question_types = types
            db.delete(dup)
            merged += 1
    return merged


if __name__ == "__main__":
    raise SystemExit(main())
