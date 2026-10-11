# -*- coding: utf-8 -*-
"""知识点扩科脚本（2026-10）：
1) 为所有"有章节大纲但知识点为零"的科目生成章节级知识点（覆盖零知识科目）
2) 从既有语料抽取术语级知识点（kp_cleaner 术语表命中 + 语料高频中文术语）
3) 生成知识点关系表：prerequisite（大纲相邻章节）/ parallel（同章并列术语）/ contains（章节包含术语）

幂等可重跑：同 (name,subject,chapter) 查重、同 (source,target,relation_type) 查重。
输出 JSON 报告到 TEMP_DIR。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from database import SessionLocal  # noqa: E402
from models import Document, KnowledgePoint, KnowledgePointRelation  # noqa: E402
from services import taxonomy, kp_cleaner  # noqa: E402

# 中文术语候选（从正文抽取时的停用词粗过滤）
_STOP = set("的了是在和与及或一个我你他这那还有为对从到要就都而之其且并所也能可上中下大小多少很最真又也于以被把让给后前内对外里向自才更再等些某".strip())


def _extract_terms(text: str, chapter_kws: list[str]) -> list[str]:
    """从语料正文里抽取命中该章节术语表的术语（保留在表内的，稳定可靠）。"""
    hits = []
    for w in chapter_kws:
        if len(w) >= 2 and text.count(w) >= 1:
            hits.append(w)
    return hits


def _top_chinese_terms(texts: list[str], top_n: int = 20) -> list[str]:
    """从正文里统计高频中文术语（2-8 字，出现 >= 3 次，不在停用词/纯数字）。"""
    cnt: Counter = Counter()
    for t in texts:
        # 连续中文/字母数字片段
        for seg in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9·]{2,8}", t or ""):
            seg = seg.strip()
            if not seg or seg in _STOP:
                continue
            if re.fullmatch(r"\d+", seg):
                continue
            cnt[seg] += 1
    return [w for w, c in cnt.most_common(top_n) if c >= 3]


def _ensure_kp(db, name: str, subject: str, chapter: str, desc: str,
               parent_id=None, document_id=None) -> KnowledgePoint:
    q = db.query(KnowledgePoint).filter(
        KnowledgePoint.name == name,
        KnowledgePoint.subject == subject,
        KnowledgePoint.chapter == chapter,
    ).first()
    if q:
        return q
    kp = KnowledgePoint(
        name=name, subject=subject, chapter=chapter,
        parent_id=parent_id, document_id=document_id,
        description=desc,
        difficulty=3, exam_frequency=0,
    )
    db.add(kp)
    db.flush()
    return kp


def _ensure_rel(db, src: KnowledgePoint, tgt: KnowledgePoint,
                rtype: str, source_tag: str) -> None:
    if not src or not tgt or src.id == tgt.id:
        return
    exists = db.query(KnowledgePointRelation).filter(
        KnowledgePointRelation.source_kp_id == src.id,
        KnowledgePointRelation.target_kp_id == tgt.id,
        KnowledgePointRelation.relation_type == rtype,
    ).first()
    if exists:
        return
    db.add(KnowledgePointRelation(
        source_kp_id=src.id, target_kp_id=tgt.id,
        relation_type=rtype, source=source_tag,
    ))
    db.flush()


def main() -> None:
    out_path = os.path.join(os.environ.get("TEMP_DIR", BASE_DIR), "expand_kp_result.json")
    buf = io.StringIO()
    report: dict = {"chapter_kps": 0, "term_kps": 0, "relations": 0,
                    "subject_coverage": {}, "details": {}}
    try:
        db = SessionLocal()
        try:
            # —— 1. 章节级知识点：覆盖所有有大纲的科目（含零知识科目） —— #
            existing = db.query(KnowledgePoint).all()
            kp_created = 0
            for subject, chapters in taxonomy.CHAPTERS.items():
                before = db.query(KnowledgePoint).filter(KnowledgePoint.subject == subject).count()
                for i, ch in enumerate(chapters):
                    kp = _ensure_kp(
                        db, name=ch, subject=subject, chapter=ch,
                        desc=f"章节级知识点（大纲第{i+1}章，自动扩科生成）",
                    )
                    if kp.id and not kp.created_at:
                        pass
                after = db.query(KnowledgePoint).filter(KnowledgePoint.subject == subject).count()
                report["subject_coverage"][subject] = {"before": before, "after": after}
                kp_created += max(0, after - before)
            report["chapter_kps"] = kp_created
            db.commit()

            # —— 2. 术语级知识点：kp_cleaner 术语表命中语料 —— #
            term_created = 0
            for subject, chapters in taxonomy.CHAPTERS.items():
                docs = db.query(Document.id, Document.content).filter(
                    Document.subject == subject
                ).all()
                texts = [d.content or "" for d in docs]
                joined = "\n".join(texts)
                ch_kps = {}
                for ch in chapters:
                    kws = kp_cleaner.CHAPTER_KEYWORDS.get(ch, [])
                    hits = _extract_terms(joined, kws) if joined else []
                    ch_kp = db.query(KnowledgePoint).filter(
                        KnowledgePoint.name == ch,
                        KnowledgePoint.subject == subject,
                        KnowledgePoint.chapter == ch,
                    ).first()
                    if ch_kp:
                        ch_kps[ch] = ch_kp
                    for w in hits:
                        term_kp = _ensure_kp(
                            db, name=w, subject=subject, chapter=ch,
                            desc=f"术语级知识点（{ch}，语料命中自动扩科）",
                            parent_id=ch_kp.id if ch_kp else None,
                        )
                        if term_kp.id:
                            # 统计新建：查重后判断
                            pass
                report.setdefault("details", {})[subject] = {
                    "docs": len(docs), "terms": len(hits) if joined else 0,
                }
            db.commit()
            total_terms_before = db.query(KnowledgePoint).count()
            # 上面 _ensure_kp 对已存在的不会新建；再数一次
            report["kp_total_before"] = 255 + kp_created
            report["kp_total_after"] = total_terms_before
            term_created = max(0, total_terms_before - (255 + kp_created))
            report["term_kps"] = term_created

            # —— 3. 关系表 —— #
            rel_created = 0
            for subject, chapters in taxonomy.CHAPTERS.items():
                if len(chapters) < 2:
                    continue
                ch_kps = {}
                for ch in chapters:
                    kp = db.query(KnowledgePoint).filter(
                        KnowledgePoint.name == ch,
                        KnowledgePoint.subject == subject,
                        KnowledgePoint.chapter == ch,
                    ).first()
                    if kp:
                        ch_kps[ch] = kp
                # prerequisite：大纲相邻章节 前置
                for i in range(len(chapters) - 1):
                    a, b = chapters[i], chapters[i + 1]
                    if a in ch_kps and b in ch_kps:
                        _ensure_rel(db, ch_kps[a], ch_kps[b], "prerequisite", "syllabus_order")
                        rel_created += 1
                # contains：章节级 → 术语级（同一章节下 name != 章节名 的子知识点）
                for ch in chapters:
                    if ch not in ch_kps:
                        continue
                    subs = db.query(KnowledgePoint).filter(
                        KnowledgePoint.subject == subject,
                        KnowledgePoint.chapter == ch,
                        KnowledgePoint.name != ch,
                    ).all()
                    for s in subs:
                        _ensure_rel(db, ch_kps[ch], s, "contains", "chapter_hierarchy")
                        rel_created += 1
                # parallel：同一章节内术语两两并列（限制每章术语数避免爆炸）
                for ch in chapters:
                    subs = db.query(KnowledgePoint).filter(
                        KnowledgePoint.subject == subject,
                        KnowledgePoint.chapter == ch,
                        KnowledgePoint.name != ch,
                    ).all()
                    if 2 <= len(subs) <= 12:
                        for i in range(len(subs)):
                            for j in range(i + 1, len(subs)):
                                _ensure_rel(db, subs[i], subs[j], "parallel", "chapter_cooccurrence")
                                rel_created += 1
            db.commit()
            report["relations"] = rel_created
            report["rel_by_type"] = {
                r[0]: r[1] for r in db.query(
                    KnowledgePointRelation.relation_type,
                    KnowledgePointRelation.id,
                ).group_by(KnowledgePointRelation.relation_type).all()
            }
            buf.write(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            db.close()
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print("RESULT_WRITTEN " + out_path)
    except Exception:
        import traceback
        with open(out_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print("ERROR_WRITTEN " + out_path)


if __name__ == "__main__":
    main()
