# -*- coding: utf-8 -*-
"""错题本 ↔ 知识库联动服务。

这是用户明确要求的"错题本与知识库的联动"落地层。此前 `error_records`
与 `knowledge_points` 之间**没有任何关联**：AI 分析出了考点，结果只
写进一段文本 `analysis` 里，无法反查、无法统计。

本模块建立双向可查的强关联：

  错题 → 知识点：`auto_link_error()` 用本地 RAG 检索命中的知识分块，
                 反查其所属知识点，写入 error_knowledge_links
  知识点 → 错题：`related_errors()` 反查该考点下所有错题
  薄弱考点评分：`weak_knowledge_points()` = 错题数 × 考频加权
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import and_, func, not_, or_
from sqlalchemy.orm import Session

from models import (
    ErrorRecord, KnowledgePoint, KnowledgeChunk, Document,
    ErrorKnowledgeLink, QuestionKnowledgeLink, ReviewRecord,
)
from services import taxonomy, kp_cleaner
from services.delete_guard import require_physical_delete_enabled
from utils.timeutil import utcnow  # 统一 naive UTC 时间规范（P0-4）


def _now() -> datetime.datetime:
    """当前时间（naive UTC），与 DB 的 DateTime 列保持同语义。"""
    return utcnow()


# 领域核心术语（超出 search_service.CORE_TERMS 的补充，覆盖数据结构/计组/政治/英语等）
# 原则：只放"出现即指向某考点"的具体术语，杜绝"特点/方法/分析"这类泛词。
ERR_TERMS = [
    "线性表", "栈", "队列", "链表", "二叉树", "树", "图", "查找", "排序",
    "哈希", "时间复杂度", "空间复杂度", "递归",
    "进制", "原码", "反码", "补码", "浮点数", "指令", "中断", "存储系统",
    "进程", "线程", "虚拟内存", "文件系统", "网络层", "传输层", "路由",
    "马克思主义", "哲学", "辩证法", "矛盾", "实践", "物质", "意识", "认识论", "历史唯物主义",
    "极限", "连续", "导数", "微分", "积分", "级数", "矩阵", "行列式", "特征值", "向量组",
    "阅读理解", "词汇", "语法", "长难句", "翻译", "作文", "书信", "完形",
    "触发器", "计数器", "寄存器", "译码器", "编码器", "加法器", "全加器", "多谐振荡器",
    "二极管", "三极管", "晶体管", "运算放大器", "反馈", "振荡", "滤波器", "门电路",
]


def _build_query(err: ErrorRecord) -> str:
    """用错题内容构造检索 query。

    把「题干 + 错误原因 + 标签 + 科目/章节」都算进去：题干里的术语是主要依据，
    错误原因（如"概念不清-触发器"）常直接点出考点；科目名与章节名辅助检索定位。
    """
    parts = [
        err.content or "",
        err.error_reason or "",
    ]
    tags = err.tags
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags)
    elif tags:
        parts.append(str(tags))
    subject = (err.subject or "").strip()
    if subject:
        parts.append(subject)
    q = " ".join(p for p in parts if p).strip()
    return q[:500]


def _compact(text: str) -> str:
    """去掉空格/全角空格，便于名称直击（'JK 触发器' == 'JK触发器'）。"""
    if not text:
        return ""
    return text.replace(" ", "").replace("\u3000", "")


def _named_hits(
    db: Session, text: str, subject: str, chapter: str | None,
    *, strict_subject: bool = True,
) -> list[tuple]:
    """知识点名直接出现在错题正文里 —— 最可靠的关联依据。

    返回 [(kp, score)]，按"名字越长越具体"降序（"TTL与非门" 优于 "门电路"）。
    strict_subject=True 时限定同科目（最严谨）；False 时跨科目兜底
    （错题科目为"专业课/其他"这类无法归一时，仍可借题干直击的知识点名关联）。
    """
    if not text:
        return []
    compact_text = _compact(text)
    q = db.query(KnowledgePoint)
    if subject and strict_subject:
        q = q.filter(KnowledgePoint.subject == subject)
    hits = []
    for kp in q.all():
        name = (kp.name or "").strip()
        compact_name = _compact(name)
        if len(name) >= 2 and compact_name and compact_name in compact_text:
            # 名字越长、考频越高、同章越可信
            bonus = 8 if (chapter and kp.chapter == chapter) else 0
            hits.append((kp, len(name) * 10 + (kp.exam_frequency or 0) + bonus))
    hits.sort(key=lambda x: -x[1])
    return hits


def _keyword_hits(
    db: Session, text: str, subject: str, chapter: str | None,
) -> list[tuple]:
    """领域核心术语直击：题干出现 CORE_TERMS 术语且知识点名包含该术语。

    如题干"构成一个 7 进制计数器需要" 含"计数器"→ 知识点"计数器"、
    "同步计数器"等直接命中。这是"题干关键词"维度的强信号，安全可靠。
    """
    if not text:
        return []
    try:
        from services.search_service import CORE_TERMS
        terms = list(CORE_TERMS)
    except Exception:
        terms = []
    terms.extend(t for t in ERR_TERMS if t not in terms)
    compact_text = _compact(text)
    terms = [t for t in terms if t and (t in compact_text or compact_text in t)]
    if not terms:
        return []
    hits = []
    for kp in db.query(KnowledgePoint).all():
        name = (kp.name or "").strip()
        compact_name = _compact(name)
        if not name:
            continue
        for t in terms:
            # 单字术语（如"栈/树/图"）只接受中短知识点名，避免"特点/方法"式噪声
            if len(t) == 1 and not (2 <= len(compact_name) <= 12):
                continue
            if t in compact_name or compact_name in t:
                bonus = 0
                if subject and kp.subject == subject:
                    bonus += 6
                if chapter and kp.chapter == chapter:
                    bonus += 8
                hits.append(
                    (kp, 5 + len(t) + bonus + (kp.exam_frequency or 0))
                )
                break
    hits.sort(key=lambda x: -x[1])
    return hits


def _lexical_overlap(text: str, name: str) -> float:
    """错题正文与知识点名的字面重合度 0-1。

    用来给"检索命中"一个可解释的相关度，替代 RRF 原始分
    （RRF 分值是 1/(k+rank) 量级，约 0.016，直接展示没有意义）。
    """
    if not text or not name:
        return 0.0
    n = set(name)
    t = set(text)
    return round(len(n & t) / max(len(n), 1), 4)


def auto_link_error(
    db: Session,
    err: ErrorRecord,
    *,
    top_k: int = 5,
    replace: bool = True,
    commit: bool = True,
) -> list[dict[str, Any]]:
    """自动把错题关联到最相关的知识点。

    关联质量优先于数量，逐级降级：
      1. **名称直击**：知识点名直接出现在错题正文里（最可靠）
      2. **章节内检索**：先用 kp_cleaner 判定错题所属章节，只在该章内检索
      3. **全局检索**：仅在相关度达标时采纳（避免"触发器"被挂到"卡诺图化简"）
      4. **放弃**：以上都不成立就返回空，让用户手动指定 ——
         宁可不挂，也不要挂错（挂错会污染"薄弱考点"统计）
    """
    if replace:
        # 物理删除闸门：replace=True 会物理删除既有关联行，不可逆。
        # 该表为错题-知识点关联表，属受控重建语义，加闸防止误触。
        require_physical_delete_enabled("error_knowledge_links")
        db.query(ErrorKnowledgeLink).filter(
            ErrorKnowledgeLink.error_id == err.id
        ).delete(synchronize_session=False)
        db.flush()

    query = _build_query(err)
    subject = taxonomy.normalize_subject(err.subject)
    created: list[dict[str, Any]] = []
    seen_kp: set[int] = set()

    def add(kp: KnowledgePoint, relevance: float, source: str, chunk_id=None, doc_id=None):
        if kp is None or kp.id in seen_kp:
            return
        seen_kp.add(kp.id)
        link = ErrorKnowledgeLink(
            error_id=err.id,
            knowledge_point_id=kp.id,
            chunk_id=chunk_id,
            document_id=doc_id,
            relevance=round(relevance, 4),
            source=source,
        )
        db.add(link)
        created.append({
            "knowledge_point_id": kp.id,
            "name": kp.name,
            "chapter": kp.chapter,
            "relevance": round(relevance, 4),
            "source": source,
        })

    # —— 第 0 步：错题所属章节 —— #
    chapter = None
    if query:
        chapter = kp_cleaner.map_chapter(query, None, subject, query)

    # —— 第 1 步：名称直击（同科目，最严谨）—— #
    for kp, _score in _named_hits(db, query, subject, chapter, strict_subject=True)[:top_k]:
        add(kp, _lexical_overlap(query, kp.name), "name_match")

    # —— 第 1.5 步：名称直击（跨科目兜底：科目未归一/信息缺失时）—— #
    if len(created) < top_k:
        for kp, _score in _named_hits(db, query, None, chapter, strict_subject=False)[:top_k]:
            add(kp, max(_lexical_overlap(query, kp.name), 0.12), "name_match_cross")

    # —— 第 1.6 步：领域核心术语直击（题干关键词维度）—— #
    if len(created) < top_k and query:
        for kp, _score in _keyword_hits(db, query, subject, chapter)[:top_k]:
            add(kp, max(_lexical_overlap(query, kp.name), 0.18), "keyword_match")

    # —— 第 2/3 步：检索 —— #
    if len(created) < top_k and query:
        try:
            from services import search_service

            scoped = chapter is not None
            results = search_service.hybrid_search(
                db, query, limit=max(top_k * 3, 12),
                subject=subject if subject and subject != "其他" else None,
            )
            for r in results:
                if len(created) >= top_k:
                    break
                rtype = r.get("source_type")
                if rtype == "knowledge_point":
                    encoded = r.get("chunk_id")
                    kp_id = abs(int(encoded)) - 100000 if encoded is not None else None
                    kp = db.query(KnowledgePoint).filter(
                        KnowledgePoint.id == kp_id
                    ).first() if kp_id else None
                elif rtype == "chunk":
                    kp = _point_for_chunk(db, r.get("chunk_id"), r.get("document_id"), subject)
                else:
                    continue

                if not kp:
                    continue
                # 章节内命中可信；跨章节命中要求中等字面重合度（术语直击已覆盖大部分）
                overlap = _lexical_overlap(query, kp.name or "")
                if chapter and kp.chapter == chapter:
                    add(kp, max(overlap, 0.15), "chapter_match", r.get("chunk_id"), r.get("document_id"))
                elif overlap >= 0.45:
                    add(kp, overlap, "search_match", r.get("chunk_id"), r.get("document_id"))
                elif subject and subject != "其他" and kp.subject == subject:
                    # 检索已命中该科目文档但字面重合低：科目内兜底关联（弱信号，低相关度）
                    add(kp, 0.1, "subject_fallback", r.get("chunk_id"), r.get("document_id"))
        except Exception:
            # 检索失败不致命，保留已建立的名称/关键词直击关联
            pass

    if commit:
        db.commit()
    return created


def _point_for_chunk(
    db: Session, chunk_id: int | None, doc_id: int | None, subject: str
) -> KnowledgePoint | None:
    """由知识分块反查知识点。"""
    doc = None
    if doc_id:
        doc = db.query(Document).filter(Document.id == doc_id).first()

    if doc:
        # 优先：同文档且名称出现在分块正文里的知识点
        chunk_text = ""
        if chunk_id:
            kc = db.query(KnowledgeChunk).filter(KnowledgeChunk.id == chunk_id).first()
            chunk_text = kc.text or "" if kc else ""

        candidates = db.query(KnowledgePoint).filter(
            KnowledgePoint.document_id == doc.id
        ).all()
        if chunk_text and candidates:
            for kp in sorted(candidates, key=lambda k: -len(k.name or "")):
                if kp.name and kp.name in chunk_text:
                    return kp
        if candidates:
            return candidates[0]

    # 其次：同科目 + 章节匹配（无法定位时返回该科目掌握度最低者）
    if subject and subject != "其他":
        return (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.subject == subject)
            .order_by(KnowledgePoint.mastery.asc())
            .first()
        )
    return None


def link_manually(
    db: Session,
    error_id: int,
    knowledge_point_id: int,
    *,
    relevance: float = 1.0,
    commit: bool = True,
) -> dict[str, Any]:
    """手动建立关联（用户在界面上指定"这道题考的是这个知识点"）。"""
    err = db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first()
    if not err:
        raise LookupError("错题不存在")
    kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == knowledge_point_id).first()
    if not kp:
        raise LookupError("知识点不存在")

    exists = db.query(ErrorKnowledgeLink).filter(
        ErrorKnowledgeLink.error_id == error_id,
        ErrorKnowledgeLink.knowledge_point_id == knowledge_point_id,
    ).first()
    if exists:
        return {"id": exists.id, "message": "关联已存在"}

    link = ErrorKnowledgeLink(
        error_id=error_id,
        knowledge_point_id=knowledge_point_id,
        relevance=relevance,
        source="manual",
    )
    db.add(link)
    if commit:
        db.commit()
        db.refresh(link)
    return {"id": link.id, "message": "关联已建立", "kp_name": kp.name}


def unlink(db: Session, link_id: int, *, commit: bool = True) -> bool:
    link = db.query(ErrorKnowledgeLink).filter(ErrorKnowledgeLink.id == link_id).first()
    if not link:
        return False
    db.delete(link)
    if commit:
        db.commit()
    return True


def mastery_state_condition(state: str):
    """把三态名（unlearned/weak/mastered）翻译成 SQLAlchemy 过滤条件。

    与 ``services/kp_mastery.error_mastery_state`` **逐条对齐**（同一阈值
    ``MASTERED_THRESHOLD``，同一"有学习记录"定义），保证"列表筛选出来的条数"
    与"逐条算出来的三态"完全一致 —— 避免又出现"页面显示和筛选对不上"。

        mastered : status='graduated' OR (review_count>0 AND accuracy*100 ≥ 阈值)
        unlearned: status≠'graduated' AND review_count 为 0/NULL
        weak     : status≠'graduated' AND review_count>0 AND accuracy*100 < 阈值

    未知 state 返回 ``None``（调用方不追加过滤）。
    """
    from services import kp_mastery

    not_grad = func.coalesce(ErrorRecord.status, "active") != kp_mastery.STATE_MASTERED_MARK
    reviewed = func.coalesce(ErrorRecord.review_count, 0) > 0
    high_acc = (
        func.coalesce(ErrorRecord.accuracy, 0) * 100 >= kp_mastery.MASTERED_THRESHOLD
    )
    if state == kp_mastery.STATE_MASTERED:
        return or_(ErrorRecord.status == kp_mastery.STATE_MASTERED_MARK, and_(reviewed, high_acc))
    if state == kp_mastery.STATE_UNLEARNED:
        return and_(not_grad, not_(reviewed))
    if state == kp_mastery.STATE_WEAK:
        return and_(not_grad, reviewed, not_(high_acc))
    return None


def error_stats(db: Session, *, subject: str | None = None) -> dict[str, Any]:
    """**错题统计的唯一口径**（错题本 / 错题复盘 / 仪表盘共用同一实现）。

    修复背景：此前"错题数 / 今日待复习"至少有三套算法在跑 ——
    仪表盘前端用本地 ``reviewStatus()``（mastery 缺失 → 落到 5 分钟节点 →
    几乎所有复习过的错题都被判"到期"）、``/api/review/stats`` 用一套、
    错题本页面又各自从当前页 items 现算一套。同一个"今日待复习错题"，
    三个页面三个数。

    本函数是唯一事实源；``GET /api/errors/stats`` 与仪表盘 ``stats`` 都走它。
    """
    from services import kp_mastery

    now = utcnow()
    q = db.query(ErrorRecord)
    if subject:
        q = q.filter(ErrorRecord.subject == taxonomy.normalize_subject(subject))

    total = q.count()
    active = q.filter(ErrorRecord.status == "active").count()
    graduated = q.filter(ErrorRecord.status == kp_mastery.STATE_MASTERED_MARK).count()
    archived = q.filter(ErrorRecord.status == "archived").count()
    # 到期 = 在练 且 已排期 且 next_review ≤ 现在（无排期的脏数据不计入，口径同
    # ReviewScheduler.get_due_errors / review.py:132）
    due = q.filter(
        ErrorRecord.status == "active",
        ErrorRecord.next_review.isnot(None),
        ErrorRecord.next_review <= now,
    ).count()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total_reviews = db.query(func.count(ReviewRecord.id)).scalar() or 0
    today_reviews = (
        db.query(func.count(ReviewRecord.id))
        .filter(ReviewRecord.created_at >= today_start)
        .scalar()
        or 0
    )
    error_reviews = (
        db.query(func.count(ReviewRecord.id))
        .filter(ReviewRecord.item_type == "error")
        .scalar()
        or 0
    )

    states = {}
    for name in (kp_mastery.STATE_UNLEARNED, kp_mastery.STATE_WEAK, kp_mastery.STATE_MASTERED):
        cond = mastery_state_condition(name)
        states[name] = q.filter(cond).count() if cond is not None else 0

    return {
        "total": total,
        "active_errors": active,
        "due_errors": due,
        "graduated_errors": graduated,
        "archived_errors": archived,
        "today_reviews": today_reviews,
        "total_reviews": total_reviews,
        "error_reviews": error_reviews,
        # 三态计数（键名与 kp_mastery.STATE_* 一致）
        "unlearned": states[kp_mastery.STATE_UNLEARNED],
        "weak": states[kp_mastery.STATE_WEAK],
        "mastered": states[kp_mastery.STATE_MASTERED],
        # 三态中文标签（前端不再自行写死档位文案）
        "labels": dict(kp_mastery.STATE_LABELS),
        "subject": taxonomy.normalize_subject(subject) if subject else None,
    }


def knowledge_points_of_error(db: Session, error_id: int) -> list[dict[str, Any]]:
    """错题关联的知识点（**按实际链路展示，不再只是启发式关联**）。

    修复背景（docx/22 F3「知识点关联硬编码且关联错」）：
    此前本函数只读 ``error_knowledge_links``（RAG/keyword 自动挂接），
    于是页面上出现的往往是"进制/计数器/触发器"这类低置信弱关联
    （真实库 34 条里 19 条是 ``name_match_cross`` 跨科目兜底），而错题背后
    **真正的题目**在 ``question_knowledge_links`` 里有 ``is_verified=1`` 的
    人工校验关联，却被完全忽略 —— 用户看到的"这道题考什么"因此是错的。

    现在按优先级合并两条真实链路，且各自标注来源，页面可如实呈现：

      1. ``question_knowledge_links``（错题 underlying question 的关联）——
         权威、可人工校验（``is_verified`` / ``role``），来源标 ``question_link``；
      2. ``error_knowledge_links``（错题本身的自动/手动挂接）——
         补充，保留 ``relevance`` 与 ``source``（auto 族 / manual）。

    同一知识点在两处都出现时以 (1) 为准（``verified`` 字段透出）。
    每个知识点附带掌握度三态（``state`` / ``state_label``），前端不再自行写死档位。
    """
    from services import kp_mastery

    err = db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first()
    if not err:
        return []

    learned = kp_mastery.learned_kp_ids(db)
    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    def _kp_dict(kp: KnowledgePoint) -> dict[str, Any]:
        state = kp_mastery.classify_state(kp.mastery, kp.id in learned)
        return {
            "name": kp.name,
            "subject": kp.subject,
            "chapter": kp.chapter,
            "mastery": int(kp.mastery or 0),
            "state": state,
            "state_label": kp_mastery.STATE_LABELS.get(state, state),
            "question_types": (kp.question_types if kp else None)
                              or taxonomy.question_types_of(kp.subject if kp else None),
        }

    # —— 1. 题目实际关联（question_knowledge_links）—— 权威 —— #
    if err.question_id:
        qkl_rows = (
            db.query(QuestionKnowledgeLink, KnowledgePoint)
            .join(KnowledgePoint, KnowledgePoint.id == QuestionKnowledgeLink.knowledge_point_id)
            .filter(QuestionKnowledgeLink.question_id == err.question_id)
            .order_by(QuestionKnowledgeLink.is_verified.desc(), QuestionKnowledgeLink.weight.desc())
            .all()
        )
        for qkl, kp in qkl_rows:
            if kp is None or kp.id in seen:
                continue
            seen.add(kp.id)
            out.append({
                "link_id": None,  # question_link 无 error_knowledge_links 行，不可在此解除
                "knowledge_point_id": kp.id,
                "relevance": round(float(qkl.weight or 1.0), 4),
                "source": "question_link",
                "role": qkl.role,
                "verified": bool(qkl.is_verified),
                "chunk_id": None,
                "document_id": None,
                **_kp_dict(kp),
            })

    # —— 2. 错题启发式/手动挂接（error_knowledge_links）—— 补充 —— #
    links = (
        db.query(ErrorKnowledgeLink)
        .filter(ErrorKnowledgeLink.error_id == error_id)
        .order_by(ErrorKnowledgeLink.relevance.desc())
        .all()
    )
    for lk in links:
        kp = None
        if lk.knowledge_point_id:
            kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == lk.knowledge_point_id).first()
        if kp is not None and kp.id in seen:
            continue
        if kp is not None:
            seen.add(kp.id)
        out.append({
            "link_id": lk.id,
            "knowledge_point_id": lk.knowledge_point_id,
            "relevance": lk.relevance,
            "source": lk.source,
            "role": None,
            "verified": False,
            "chunk_id": lk.chunk_id,
            "document_id": lk.document_id,
            **(_kp_dict(kp) if kp is not None else {
                "name": None, "subject": None, "chapter": None,
                "mastery": None, "state": None, "state_label": None,
                "question_types": None,
            }),
        })
    return out


def related_errors(
    db: Session,
    knowledge_point_id: int,
    *,
    limit: int = 20,
    only_active: bool = True,
) -> list[dict[str, Any]]:
    """某知识点下的所有错题（错题本按考点聚类）。"""
    q = db.query(ErrorRecord).join(
        ErrorKnowledgeLink, ErrorKnowledgeLink.error_id == ErrorRecord.id
    ).filter(ErrorKnowledgeLink.knowledge_point_id == knowledge_point_id)
    if only_active:
        q = q.filter(ErrorRecord.status == "active")
    rows = q.order_by(ErrorRecord.created_at.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "content": (e.content or "")[:300],
            "my_answer": e.my_answer,
            "correct_answer": e.correct_answer,
            "error_reason": e.error_reason,
            "subject": e.subject,
            "review_count": e.review_count,
            "status": e.status,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


def weak_knowledge_points(
    db: Session,
    *,
    subject: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """错题密度最高的知识点 —— 直接指出"我最近错得最多的知识点"。

    评分 = 错题数 × 2 + 考频 × 1 - 掌握度 / 20
    """
    q = (
        db.query(
            KnowledgePoint.id,
            KnowledgePoint.name,
            KnowledgePoint.subject,
            KnowledgePoint.chapter,
            KnowledgePoint.mastery,
            KnowledgePoint.exam_frequency,
            KnowledgePoint.question_types,
            func.count(ErrorKnowledgeLink.id).label("error_count"),
        )
        .join(ErrorKnowledgeLink, ErrorKnowledgeLink.knowledge_point_id == KnowledgePoint.id)
        .join(ErrorRecord, ErrorRecord.id == ErrorKnowledgeLink.error_id)
        .filter(ErrorRecord.status == "active")
    )
    if subject:
        q = q.filter(KnowledgePoint.subject == taxonomy.normalize_subject(subject))
    q = q.group_by(KnowledgePoint.id)
    rows = q.all()

    out = []
    for r in rows:
        score = (r.error_count or 0) * 2 + (r.exam_frequency or 0) - int(r.mastery or 0) / 20
        out.append({
            "knowledge_point_id": r.id,
            "name": r.name,
            "subject": r.subject,
            "chapter": r.chapter,
            "mastery": int(r.mastery or 0),
            "exam_frequency": r.exam_frequency or 0,
            "question_types": r.question_types or taxonomy.question_types_of(r.subject),
            "error_count": r.error_count,
            "weak_score": round(score, 2),
        })
    out.sort(key=lambda x: -x["weak_score"])
    return out[:limit]


def link_stats(db: Session) -> dict[str, Any]:
    """联动覆盖率统计：还有多少错题没挂上知识点。"""
    total_errors = db.query(func.count(ErrorRecord.id)).scalar() or 0
    linked_errors = (
        db.query(func.count(func.distinct(ErrorKnowledgeLink.error_id))).scalar() or 0
    )
    total_links = db.query(func.count(ErrorKnowledgeLink.id)).scalar() or 0
    manual = db.query(func.count(ErrorKnowledgeLink.id)).filter(
        ErrorKnowledgeLink.source == "manual"
    ).scalar() or 0
    # 没有任何错题挂靠的知识点 = 关联缺口
    orphan_points = (
        db.query(func.count(KnowledgePoint.id))
        .filter(~KnowledgePoint.id.in_(
            db.query(ErrorKnowledgeLink.knowledge_point_id).filter(
                ErrorKnowledgeLink.knowledge_point_id.isnot(None)
            )
        ))
        .scalar() or 0
    )
    return {
        "total_errors": total_errors,
        "linked_errors": linked_errors,
        "unlinked_errors": max(0, total_errors - linked_errors),
        "total_links": total_links,
        "manual_links": manual,
        "coverage_rate": round(linked_errors / total_errors * 100, 1) if total_errors else 0.0,
        "knowledge_points_without_error": orphan_points,
    }
