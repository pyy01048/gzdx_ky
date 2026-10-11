# -*- coding: utf-8 -*-
"""知识结构路由：科目 / 章节 / 知识点 / 题型 三级目录。

前端「知识地图」页与错题本、刷题中心的筛选器都消费这里的数据。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import KnowledgePoint, Document, KnowledgeChunk, SubjectConfig, QuizQuestion, ErrorRecord
from services import taxonomy

router = APIRouter(prefix="/api/taxonomy", tags=["知识结构"])


@router.get("/subjects")
async def list_subjects(db: Session = Depends(get_db)):
    """科目清单（V8 阶段1 升级为完整科目管理接口）。

    返回**向后兼容**的超集：
    - 新字段 ``subjects``：合并内置默认 + 用户自定义后的完整科目字典，每项含
      ``subject / chapters / question_types / is_custom / question_count / error_count``；
    - 旧字段 ``core / extension / question_type_pool / doc_types`` 保持不变
      （前端「知识地图」页仍在消费，不在本任务改动范围内）。

    question_count / error_count 的统计口径与 ``routers/quiz.py`` 的
    ``GET /api/quiz/subjects`` 对齐：按 ``quiz_questions.subject`` 原值 group by 计数，
    错题仅统计 ``error_records.status == "active"``。
    """
    # 幂等播种内置默认科目（仅空库首建；不复活已删除行）
    taxonomy.ensure_subject_config_seeds(db)
    rows = (
        db.query(SubjectConfig)
        .order_by(SubjectConfig.is_custom.asc(), SubjectConfig.subject.asc())
        .all()
    )
    # 刷新 normalize_subject 的"已配置科目"缓存
    taxonomy.load_configured_subjects(db)

    q_rows = dict(
        db.query(QuizQuestion.subject, func.count(QuizQuestion.id))
        .filter(QuizQuestion.subject.isnot(None))
        .group_by(QuizQuestion.subject)
        .all()
    )
    e_rows = dict(
        db.query(ErrorRecord.subject, func.count(ErrorRecord.id))
        .filter(ErrorRecord.subject.isnot(None), ErrorRecord.status == "active")
        .group_by(ErrorRecord.subject)
        .all()
    )

    subjects = [
        {
            "subject": r.subject,
            "chapters": r.chapters or [],
            "question_types": r.question_types or [],
            "is_custom": bool(r.is_custom),
            "question_count": q_rows.get(r.subject, 0),
            "error_count": e_rows.get(r.subject, 0),
        }
        for r in rows
    ]

    return {
        # ---- 新：完整科目管理列表 ----
        "subjects": subjects,
        # ---- 旧：保持既有契约不动（前端知识地图页仍在用）----
        "core": [
            {
                "name": s,
                "chapters": taxonomy.chapters_of(s),
                "question_types": taxonomy.question_types_of(s),
                "is_core": True,
            }
            for s in taxonomy.CORE_SUBJECTS
        ],
        "extension": [
            {
                "name": s,
                "chapters": taxonomy.chapters_of(s),
                "question_types": taxonomy.question_types_of(s),
                "is_core": False,
            }
            for s in taxonomy.EXT_SUBJECTS
        ],
        "question_type_pool": taxonomy.all_question_types(),
        "doc_types": taxonomy.DOC_TYPES,
    }


def _validate_chapters(chapters) -> list[str]:
    if not isinstance(chapters, list) or any(not isinstance(c, str) or not c.strip() for c in chapters):
        raise HTTPException(status_code=400, detail="chapters 必须为非空字符串数组")
    return list(chapters)


def _validate_question_types(types) -> list[str]:
    if not isinstance(types, list):
        raise HTTPException(status_code=400, detail="question_types 必须为字符串数组")
    bad = [t for t in types if t not in taxonomy.ALLOWED_QUESTION_TYPES]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"非法题型 {bad}；允许枚举 {taxonomy.ALLOWED_QUESTION_TYPES}",
        )
    return list(types)


@router.post("/subjects")
async def create_subject(payload: dict, db: Session = Depends(get_db)):
    """新增自定义科目（is_custom=True）。

    body: ``{subject, chapters?, question_types?}``
    - subject 必填；重名（内置或自定义）→ 409；
    - chapters 任意字符串数组；question_types 须为
      single/judge/fill/essay/calc/draw 子集，否则 400。
    """
    name = (payload.get("subject") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="科目名不能为空")
    if taxonomy.is_configured_subject(db, name):
        raise HTTPException(status_code=409, detail=f"科目已存在：{name}")

    chapters = _validate_chapters(payload.get("chapters") or []) if payload.get("chapters") else []
    qtypes = _validate_question_types(payload["question_types"]) if payload.get("question_types") else []

    row = SubjectConfig(
        subject=name,
        chapters=chapters,
        question_types=qtypes,
        is_custom=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    taxonomy.load_configured_subjects(db)
    return {
        "subject": row.subject,
        "chapters": row.chapters or [],
        "question_types": row.question_types or [],
        "is_custom": True,
        "message": "自定义科目已创建",
    }


@router.put("/subjects/{subject}")
async def update_subject(subject: str, payload: dict, db: Session = Depends(get_db)):
    """更新科目配置：重命名 / 改章节 / 改题型。

    body: ``{subject?(新名), chapters?, question_types?}``
    - 目标科目不存在 → 404；
    - 重命名到一个已存在的科目名 → 409；
    - 重命名只改配置行；``quiz_questions`` 里既有题目的科目标签**保持原串不动**，
      响应通过 ``renamed`` / ``question_tag_note`` 提示。
    """
    row = db.query(SubjectConfig).filter(SubjectConfig.subject == subject).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"科目不存在：{subject}")

    renamed = False
    if payload.get("subject") is not None:
        new_name = str(payload["subject"]).strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="新科目名不能为空")
        if new_name != subject:
            if taxonomy.is_configured_subject(db, new_name):
                raise HTTPException(status_code=409, detail=f"目标科目名已存在：{new_name}")
            row.subject = new_name
            renamed = True

    if payload.get("chapters") is not None:
        row.chapters = _validate_chapters(payload["chapters"])
    if payload.get("question_types") is not None:
        row.question_types = _validate_question_types(payload["question_types"])

    db.commit()
    db.refresh(row)
    taxonomy.load_configured_subjects(db)

    resp = {
        "subject": row.subject,
        "chapters": row.chapters or [],
        "question_types": row.question_types or [],
        "is_custom": bool(row.is_custom),
        "renamed": renamed,
        "message": "科目配置已更新",
    }
    if renamed:
        resp["question_tag_note"] = "题库中既有题目的科目标签保持原串不动，未跟随改名"
    return resp


@router.delete("/subjects/{subject}")
async def delete_subject(subject: str, db: Session = Depends(get_db)):
    """删除科目配置行（内置默认也可删）。

    仅删除科目字典配置；``quiz_questions`` / ``error_records`` 等业务表里
    既有的题目数据**不受影响**（题目上的科目标签字符串保持原值）。
    """
    row = db.query(SubjectConfig).filter(SubjectConfig.subject == subject).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"科目不存在：{subject}")
    db.delete(row)
    db.commit()
    taxonomy.load_configured_subjects(db)
    return {
        "message": "科目配置已删除",
        "subject": subject,
        "note": "仅删除科目字典配置，业务表中既有题目数据不受影响",
    }


@router.get("/tree")
async def structure_tree(
    subject: Optional[str] = None,
    include_extension: bool = Query(True, description="是否包含拓展科目"),
    db: Session = Depends(get_db),
):
    """三级结构树：科目 → 章节 → 知识点（含题型与掌握度）。

    以**大纲为标准骨架**，再把数据库里已有知识点挂上去，
    这样"还没录入资料"的章节也会显示为空白节点，一眼看出进度缺口。
    """
    subjects = list(taxonomy.CORE_SUBJECTS)
    if include_extension:
        subjects += list(taxonomy.EXT_SUBJECTS)
    if subject:
        std = taxonomy.normalize_subject(subject)
        subjects = [s for s in subjects if s == std] or [std]

    # 一次性取全部知识点，按科目分组
    rows = db.query(KnowledgePoint).all()
    by_subject: dict[str, list[KnowledgePoint]] = {}
    for kp in rows:
        by_subject.setdefault(taxonomy.normalize_subject(kp.subject), []).append(kp)

    tree = []
    for s in subjects:
        kps = by_subject.get(s, [])
        chapter_map: dict[str, list[KnowledgePoint]] = {}
        uncategorized: list[KnowledgePoint] = []
        for kp in kps:
            if kp.chapter:
                chapter_map.setdefault(kp.chapter, []).append(kp)
            else:
                uncategorized.append(kp)

        chapters = []
        # 先按大纲章序列出
        for ch_name in taxonomy.chapters_of(s):
            items = chapter_map.pop(ch_name, [])
            chapters.append(_chapter_node(ch_name, items, s))
        # 再列出大纲外的章（实际资料里的自定义章）
        for ch_name in sorted(chapter_map.keys()):
            chapters.append(_chapter_node(ch_name, chapter_map[ch_name], s))
        # 未标章节的
        if uncategorized:
            chapters.append(_chapter_node("未归章", uncategorized, s))

        total = len(kps)
        mastered = sum(1 for k in kps if (k.mastery or 0) >= 70)
        tree.append({
            "subject": s,
            "is_core": taxonomy.is_core(s),
            "knowledge_point_count": total,
            "mastered_count": mastered,
            "avg_mastery": round(sum(int(k.mastery or 0) for k in kps) / total, 1) if total else 0.0,
            "outline_chapter_count": len(taxonomy.chapters_of(s)),
            "filled_chapter_count": sum(1 for c in chapters if c["knowledge_point_count"] > 0),
            "chapters": chapters,
        })

    return {"tree": tree}


def _chapter_node(title: str, kps: list[KnowledgePoint], subject: str) -> dict:
    types: list[str] = []
    for kp in kps:
        for t in (kp.question_types or []):
            if t not in types:
                types.append(t)
    if not types:
        types = taxonomy.question_types_of(subject)

    return {
        "title": title,
        "knowledge_point_count": len(kps),
        "mastered_count": sum(1 for k in kps if (k.mastery or 0) >= 70),
        "avg_mastery": round(sum(int(k.mastery or 0) for k in kps) / len(kps), 1) if kps else 0.0,
        "question_types": types,
        "knowledge_points": [
            {
                "id": kp.id,
                "name": kp.name,
                "question_types": kp.question_types or taxonomy.question_types_of(kp.subject),
                "mastery": int(kp.mastery or 0),
                "difficulty": kp.difficulty or 3,
                "exam_frequency": kp.exam_frequency or 0,
                "review_count": kp.review_count or 0,
                "next_review": kp.next_review.isoformat() if kp.next_review else None,
                "document_id": kp.document_id,
            }
            for kp in sorted(kps, key=lambda k: (int(k.mastery or 0), -(k.exam_frequency or 0)))
        ],
    }


@router.get("/knowledge-points")
async def list_knowledge_points(
    subject: Optional[str] = None,
    chapter: Optional[str] = None,
    question_type: Optional[str] = None,
    keyword: Optional[str] = None,
    low_mastery: bool = False,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """知识点列表（支持 科目 / 章节 / 题型 / 关键词 / 薄弱 筛选）。"""
    q = db.query(KnowledgePoint)
    if subject:
        q = q.filter(KnowledgePoint.subject == taxonomy.normalize_subject(subject))
    if chapter:
        q = q.filter(KnowledgePoint.chapter.like(f"%{chapter}%"))
    if keyword:
        q = q.filter(KnowledgePoint.name.like(f"%{keyword}%"))
    if low_mastery:
        q = q.filter(KnowledgePoint.mastery < 40)
    rows = q.all()

    if question_type:
        rows = [r for r in rows if question_type in (r.question_types or [])]

    total = len(rows)
    rows.sort(key=lambda k: (taxonomy.normalize_subject(k.subject), k.chapter or "", k.name or ""))
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": [
            {
                "id": k.id,
                "name": k.name,
                "subject": k.subject,
                "chapter": k.chapter,
                "question_types": k.question_types or taxonomy.question_types_of(k.subject),
                "mastery": int(k.mastery or 0),
                "difficulty": k.difficulty or 3,
                "exam_frequency": k.exam_frequency or 0,
                "review_count": k.review_count or 0,
                "last_review": k.last_review.isoformat() if k.last_review else None,
                "next_review": k.next_review.isoformat() if k.next_review else None,
                "description": k.description,
                "document_id": k.document_id,
            }
            for k in page_rows
        ],
    }


@router.get("/coverage")
async def structure_coverage(db: Session = Depends(get_db)):
    """结构化覆盖率体检：哪些科目/章节还没有结构化资料。

    直接回答"知识库搭好了没有、缺哪一块"。
    """
    # 按科目统计
    kp_rows = (
        db.query(KnowledgePoint.subject, func.count(KnowledgePoint.id))
        .group_by(KnowledgePoint.subject)
        .all()
    )
    doc_rows = dict(db.query(Document.subject, func.count(Document.id)).group_by(Document.subject).all())
    chunk_rows = dict(db.query(KnowledgeChunk.subject, func.count(KnowledgeChunk.id)).group_by(KnowledgeChunk.subject).all())

    kp_counts: dict[str, int] = {}
    for subject, cnt in kp_rows:
        std = taxonomy.normalize_subject(subject)
        kp_counts[std] = kp_counts.get(std, 0) + (cnt or 0)

    # 有章节标注的知识点数
    with_chapter = (
        db.query(KnowledgePoint.subject, func.count(KnowledgePoint.id))
        .filter(KnowledgePoint.chapter.isnot(None), KnowledgePoint.chapter != "")
        .group_by(KnowledgePoint.subject)
        .all()
    )
    chapter_counts: dict[str, int] = {}
    for subject, cnt in with_chapter:
        std = taxonomy.normalize_subject(subject)
        chapter_counts[std] = chapter_counts.get(std, 0) + (cnt or 0)

    ocr_docs = db.query(func.count(Document.id)).filter(Document.ocr_used == True).scalar() or 0  # noqa: E712

    subjects = []
    for s in taxonomy.CORE_SUBJECTS + taxonomy.EXT_SUBJECTS:
        kpc = kp_counts.get(s, 0)
        chc = chapter_counts.get(s, 0)
        outline = taxonomy.chapters_of(s)
        subjects.append({
            "subject": s,
            "is_core": taxonomy.is_core(s),
            "documents": doc_rows.get(s, 0),
            "chunks": chunk_rows.get(s, 0),
            "knowledge_points": kpc,
            "structured_knowledge_points": chc,
            "structure_rate": round(chc / kpc * 100, 1) if kpc else 0.0,
            "outline_chapters": len(outline),
            "covered_chapters": _covered_chapters(db, s, outline),
        })

    return {
        "subjects": subjects,
        "totals": {
            "documents": db.query(func.count(Document.id)).scalar() or 0,
            "ocr_documents": ocr_docs,
            "chunks": db.query(func.count(KnowledgeChunk.id)).scalar() or 0,
            "knowledge_points": db.query(func.count(KnowledgePoint.id)).scalar() or 0,
        },
    }


def _covered_chapters(db: Session, subject: str, outline: list[str]) -> int:
    """大纲章中已有知识点的数量。"""
    if not outline:
        return 0
    rows = (
        db.query(KnowledgePoint.chapter, func.count(KnowledgePoint.id))
        .filter(KnowledgePoint.subject == subject, KnowledgePoint.chapter.isnot(None))
        .group_by(KnowledgePoint.chapter)
        .all()
    )
    have = {ch for ch, cnt in rows if ch and cnt}
    return sum(1 for o in outline if o in have)


@router.get("/knowledge-points/{kp_id}")
async def knowledge_point_detail(kp_id: int, db: Session = Depends(get_db)):
    """知识点详情：含关联错题、关联分块、复习记录。"""
    kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")

    from services import error_linker, review_service

    chunks = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.subject == kp.subject)
        .limit(5)
        .all()
    ) if not kp.document_id else (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.document_id == kp.document_id)
        .limit(5)
        .all()
    )

    return {
        "id": kp.id,
        "name": kp.name,
        "subject": kp.subject,
        "chapter": kp.chapter,
        "description": kp.description,
        "question_types": kp.question_types or taxonomy.question_types_of(kp.subject),
        "mastery": int(kp.mastery or 0),
        "difficulty": kp.difficulty or 3,
        "exam_frequency": kp.exam_frequency or 0,
        "review_count": kp.review_count or 0,
        "last_review": kp.last_review.isoformat() if kp.last_review else None,
        "next_review": kp.next_review.isoformat() if kp.next_review else None,
        "interval": kp.interval or 0,
        "ease_factor": kp.ease_factor or 2.5,
        "lapses": kp.lapses or 0,
        "related_errors": error_linker.related_errors(db, kp.id, limit=20),
        "related_chunks": [
            {"chunk_id": c.id, "document_id": c.document_id, "doc_name": c.doc_name, "text": (c.text or "")[:400]}
            for c in chunks
        ],
        "review_history": review_service.review_history(
            db, item_type="knowledge", item_id=kp.id, days=180, limit=50
        ),
    }


@router.post("/knowledge-points")
async def create_knowledge_point(payload: dict, db: Session = Depends(get_db)):
    """手动新增知识点（补录大纲里缺失的考点）。"""
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="知识点名称不能为空")

    subject = taxonomy.normalize_subject(payload.get("subject"))
    kp = KnowledgePoint(
        name=name,
        subject=subject,
        chapter=(payload.get("chapter") or "").strip() or None,
        description=payload.get("description"),
        exam_frequency=int(payload.get("exam_frequency") or 0),
        difficulty=int(payload.get("difficulty") or 3),
        question_types=payload.get("question_types") or taxonomy.question_types_of(subject),
        document_id=payload.get("document_id"),
    )
    db.add(kp)
    db.commit()
    db.refresh(kp)
    return {"id": kp.id, "message": "知识点已创建"}


@router.put("/knowledge-points/{kp_id}")
async def update_knowledge_point(kp_id: int, payload: dict, db: Session = Depends(get_db)):
    """更新知识点（章节归属、题型、考频、掌握度）。"""
    kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")

    for field in ("name", "chapter", "description"):
        if field in payload:
            setattr(kp, field, payload[field])
    if "subject" in payload:
        kp.subject = taxonomy.normalize_subject(payload["subject"])
    for field in ("exam_frequency", "difficulty", "mastery"):
        if field in payload and payload[field] is not None:
            setattr(kp, field, int(payload[field]))
    if "question_types" in payload:
        kp.question_types = payload["question_types"]

    db.commit()
    return {"id": kp.id, "message": "知识点已更新"}


@router.delete("/knowledge-points/{kp_id}")
async def delete_knowledge_point(kp_id: int, db: Session = Depends(get_db)):
    kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")
    db.delete(kp)
    db.commit()
    return {"message": "知识点已删除"}
