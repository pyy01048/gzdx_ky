# -*- coding: utf-8 -*-
"""工科08公共学习目录与可见题库。

招生学科（``disciplines``）以 08 开头；考试科目（``subjects``）经公共关联表
进入专业目录。题目不直接关联院校，因此所有可用计数均使用 DISTINCT，且必须
同时满足 08 专业链路、可作答和当前用户可见性。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from services.quiz_query import answerable_expr, question_owner_expr, visible_quiz_filter
from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.orm import Session
from utils.response import page_params, paginate_query
from utils.security import optional_user

from models import (
    Discipline,
    KaoyanMajor,
    KaoyanMajorSubjectLink,
    KaoyanSchool,
    QuizQuestion,
    Subject,
    SubjectDisciplineLink,
)

router = APIRouter(prefix="/api/kaoyan", tags=["工科08学习空间"])


def _visible_clause(user: Any):
    """匿名用户必须显式收紧到公共题；question_owner_expr(None) 并非访客规则。"""
    owner = QuizQuestion.owner_user_id.is_(None) if user is None else question_owner_expr(user)
    return and_(
        owner,
        answerable_expr(),
        or_(QuizQuestion.is_junk.is_(False), QuizQuestion.is_junk.is_(None)),
    )


def _major_is_08():
    """EXISTS 谓词：该专业的 subject_code 命中 08 开头的学科代码。"""
    return exists(
        select(Discipline.id)
        .where(
            Discipline.code == KaoyanMajor.subject_code,
            Discipline.code.like("08%"),
        )
        .correlate(KaoyanMajor)
    )


def _matched_link_join():
    """207 关联表「已匹配且科目非空」的连接条件。"""
    return and_(
        KaoyanMajorSubjectLink.major_id == KaoyanMajor.id,
        KaoyanMajorSubjectLink.match_status == "matched",
        KaoyanMajorSubjectLink.subject_id.is_not(None),
    )


def _school_has_08():
    """EXISTS 谓词：该校至少有一个 08 专业。"""
    return exists(
        select(KaoyanMajor.id)
        .join(
            Discipline,
            Discipline.code == KaoyanMajor.subject_code,
        )
        .where(
            KaoyanMajor.school_id == KaoyanSchool.id,
            Discipline.code.like("08%"),
        )
    ).correlate(KaoyanSchool)


def _matched_subject_rows(db: Session, major_id: int, user: Any) -> list:
    """按专业返回去重前的 207 匹配行及当前用户可见题目数。"""
    question_count = (
        select(func.count(QuizQuestion.id.distinct()))
        .where(
            QuizQuestion.subject_id == KaoyanMajorSubjectLink.subject_id,
            _visible_clause(user),
        )
        .correlate(KaoyanMajorSubjectLink)
        .scalar_subquery()
    )

    return (
        db.query(
            KaoyanMajorSubjectLink.id.label("link_id"),
            KaoyanMajorSubjectLink.exam_subject_code,
            KaoyanMajorSubjectLink.exam_subject_name,
            KaoyanMajorSubjectLink.confidence,
            KaoyanMajorSubjectLink.source,
            Subject.id.label("subject_id"),
            Subject.code.label("subject_code"),
            Subject.name.label("subject_name"),
            Subject.short_name,
            Subject.category,
            question_count.label("question_count"),
        )
        .join(
            Subject,
            Subject.id == KaoyanMajorSubjectLink.subject_id,
        )
        .filter(
            KaoyanMajorSubjectLink.major_id == major_id,
            KaoyanMajorSubjectLink.match_status == "matched",
            KaoyanMajorSubjectLink.subject_id.is_not(None),
        )
        .order_by(
            Subject.sort_order,
            Subject.id,
            KaoyanMajorSubjectLink.id,
        )
        .all()
    )


def _serialize_matched_subjects(rows) -> list[dict[str, Any]]:
    """将同一科目的多条目录匹配记录合并，保留来源而不重复计数。"""
    grouped: dict[int, dict[str, Any]] = {}
    for raw in rows:
        row = raw._mapping if hasattr(raw, "_mapping") else raw
        subject_id = int(row["subject_id"])
        item = grouped.setdefault(
            subject_id,
            {
                "id": subject_id,
                "code": row.get("subject_code"),
                "name": row.get("subject_name"),
                "short_name": row.get("short_name"),
                "category": row.get("category"),
                "exam_subject_codes": [],
                "exam_subject_names": [],
                "confidence": None,
                "match_sources": [],
                "link_ids": [],
                "question_count": int(row.get("question_count") or 0),
            },
        )
        code = row.get("exam_subject_code")
        name = row.get("exam_subject_name")
        if code and code not in item["exam_subject_codes"]:
            item["exam_subject_codes"].append(code)
        if name and name not in item["exam_subject_names"]:
            item["exam_subject_names"].append(name)
        confidence = row.get("confidence")
        if confidence is not None:
            item["confidence"] = max(float(confidence), item["confidence"] or 0)
        source = row.get("source")
        if source and source not in item["match_sources"]:
            item["match_sources"].append(source)
        item["link_ids"].append(int(row["link_id"]))
    return list(grouped.values())


def _major_resource_pack(
    db: Session,
    major_id: int,
    subject_id: int | None,
    user: Any,
) -> dict[str, Any]:
    """读取 210 显式专业—科目资源，不将学校级教材关系推导为专业关系。"""
    table_name = db.execute(text("SELECT to_regclass('kaoyan_major_subject_resources')"), {}).scalar()
    if not table_name:
        return {
            "status": "migration_pending",
            "scope": "major_subject",
            "total": 0,
            "items": [],
        }

    conditions = [
        "r.major_id = :major_id",
        "r.is_active = TRUE",
        "r.verification_status <> 'rejected'",
        "(r.is_public = TRUE OR (r.owner_user_id IS NOT NULL AND r.owner_user_id = :user_id))",
        """EXISTS (
            SELECT 1 FROM kaoyan_major_subject_links l
            WHERE l.major_id = r.major_id
              AND l.subject_id = r.subject_id
              AND l.match_status = 'matched'
              AND l.subject_id IS NOT NULL
        )""",
    ]
    params: dict[str, Any] = {
        "major_id": major_id,
        "user_id": getattr(user, "id", None),
    }
    if subject_id is not None:
        conditions.append("r.subject_id = :subject_id")
        params["subject_id"] = subject_id

    rows = (
        db.execute(
            text(f"""
        SELECT
            r.id, r.major_id, r.subject_id, r.resource_type, r.title,
            r.url, r.description, r.source, r.source_url,
            r.verification_status, r.verified_at, r.sort_order,
            r.is_public, r.metadata,
            s.code AS subject_code, s.name AS subject_name,
            t.id AS textbook_id, t.title AS textbook_title,
            t.subtitle AS textbook_subtitle, t.authors AS textbook_authors,
            t.publisher AS textbook_publisher, t.edition AS textbook_edition,
            t.pub_year AS textbook_pub_year, t.isbn AS textbook_isbn,
            t.source AS textbook_source, t.confidence AS textbook_confidence
        FROM kaoyan_major_subject_resources r
        JOIN subjects s ON s.id = r.subject_id
        LEFT JOIN textbooks t ON t.id = r.textbook_id
        WHERE {" AND ".join(conditions)}
        ORDER BY s.sort_order, s.id, r.sort_order, r.id
    """),
            params,
        )
        .mappings()
        .all()
    )

    items = []
    for row in rows:
        item = dict(row)
        item["visibility"] = "public" if item.pop("is_public") else "personal"
        item["subject"] = {
            "id": item["subject_id"],
            "code": item["subject_code"],
            "name": item["subject_name"],
        }
        item["textbook"] = None
        if item["textbook_id"] is not None:
            item["textbook"] = {
                "id": item["textbook_id"],
                "title": item["textbook_title"],
                "subtitle": item["textbook_subtitle"],
                "authors": item["textbook_authors"],
                "publisher": item["textbook_publisher"],
                "edition": item["textbook_edition"],
                "pub_year": item["textbook_pub_year"],
                "isbn": item["textbook_isbn"],
                "source": item["textbook_source"],
                "confidence": item["textbook_confidence"],
            }
        for key in list(item):
            if key.startswith("textbook_") or key in {"subject_code", "subject_name"}:
                item.pop(key)
        items.append(item)
    return {
        "status": "ready",
        "scope": "major_subject",
        "total": len(items),
        "items": items,
    }


@router.get("/engineering-08/catalog")
def engineering08_catalog(
    db: Session = Depends(get_db),
    user=Depends(optional_user),
) -> dict:
    """返回当前用户可见的 08 学科、院校、专业与考试科目 facets。"""
    visible = _visible_clause(user)
    subject_count_rows = (
        db.query(
            QuizQuestion.subject_id,
            func.count(QuizQuestion.id.distinct()),
        )
        .filter(
            visible,
            QuizQuestion.subject_id.is_not(None),
        )
        .group_by(QuizQuestion.subject_id)
        .all()
    )
    subject_counts = {int(row.subject_id): int(row[1]) for row in subject_count_rows}

    discipline_rows = (
        db.query(
            Discipline.id,
            Discipline.code,
            Discipline.name,
            Discipline.category,
            Discipline.parent_code,
        )
        .filter(Discipline.code.like("08%"))
        .order_by(Discipline.id)
        .all()
    )
    major_rows = (
        db.query(
            KaoyanMajor.id,
            KaoyanMajor.school_id,
            KaoyanMajor.code,
            KaoyanMajor.name,
            KaoyanMajor.subject_code,
        )
        .join(
            Discipline,
            Discipline.code == KaoyanMajor.subject_code,
        )
        .filter(
            Discipline.code.like("08%"),
        )
        .order_by(KaoyanMajor.id)
        .all()
    )
    school_rows = (
        db.query(
            KaoyanSchool.id,
            KaoyanSchool.name,
            KaoyanSchool.level,
            KaoyanSchool.province,
            KaoyanSchool.city,
        )
        .filter(_school_has_08())
        .order_by(KaoyanSchool.id)
        .all()
    )

    linked_to_08 = exists(
        select(KaoyanMajorSubjectLink.id)
        .join(
            KaoyanMajor,
            KaoyanMajor.id == KaoyanMajorSubjectLink.major_id,
        )
        .join(
            Discipline,
            Discipline.code == KaoyanMajor.subject_code,
        )
        .where(
            KaoyanMajorSubjectLink.subject_id == Subject.id,
            KaoyanMajorSubjectLink.match_status == "matched",
            KaoyanMajorSubjectLink.subject_id.is_not(None),
            Discipline.code.like("08%"),
        )
    )
    mapped_to_08 = exists(
        select(SubjectDisciplineLink.id)
        .join(
            Discipline,
            Discipline.id == SubjectDisciplineLink.discipline_id,
        )
        .where(
            SubjectDisciplineLink.subject_id == Subject.id,
            Discipline.code.like("08%"),
        )
    )
    subject_rows = (
        db.query(
            Subject.id,
            Subject.code,
            Subject.name,
            Subject.short_name,
            Subject.category,
        )
        .filter(
            or_(linked_to_08, mapped_to_08),
        )
        .order_by(Subject.id)
        .all()
    )
    reachable_rows = (
        db.query(
            KaoyanMajorSubjectLink.major_id,
            KaoyanMajorSubjectLink.subject_id,
        )
        .join(
            KaoyanMajor,
            KaoyanMajor.id == KaoyanMajorSubjectLink.major_id,
        )
        .join(
            Discipline,
            Discipline.code == KaoyanMajor.subject_code,
        )
        .filter(
            KaoyanMajorSubjectLink.match_status == "matched",
            KaoyanMajorSubjectLink.subject_id.is_not(None),
            Discipline.code.like("08%"),
        )
        .distinct()
        .order_by(
            KaoyanMajorSubjectLink.major_id,
            KaoyanMajorSubjectLink.subject_id,
        )
        .all()
    )

    majors_by_id = {int(row.id): row for row in major_rows}
    major_counts: dict[int, int] = {}
    discipline_subjects: dict[str, set[int]] = {}
    school_subjects: dict[int, set[int]] = {}
    for row in reachable_rows:
        major_id = int(row.major_id)
        subject_id = int(row.subject_id)
        major_counts[major_id] = major_counts.get(major_id, 0) + subject_counts.get(subject_id, 0)
        major = majors_by_id[major_id]
        discipline_subjects.setdefault(major.subject_code, set()).add(subject_id)
        school_subjects.setdefault(int(major.school_id), set()).add(subject_id)

    def subjects_total(subject_ids: set[int]) -> int:
        return sum(subject_counts.get(subject_id, 0) for subject_id in subject_ids)

    def serialized(row, question_count: int):
        return {**row._mapping, "question_count": question_count}

    return {
        "disciplines": [
            serialized(row, subjects_total(discipline_subjects.get(row.code, set()))) for row in discipline_rows
        ],
        "schools": [serialized(row, subjects_total(school_subjects.get(int(row.id), set()))) for row in school_rows],
        "majors": [serialized(row, major_counts.get(int(row.id), 0)) for row in major_rows],
        "subjects": [serialized(row, subject_counts.get(int(row.id), 0)) for row in subject_rows],
        "major_subjects": [
            {"major_id": int(row.major_id), "subject_id": int(row.subject_id)} for row in reachable_rows
        ],
    }


@router.get("/engineering-08/majors/{major_id}", include_in_schema=False)
@router.get("/majors/{major_id}")
def engineering08_major_detail(
    major_id: int,
    db: Session = Depends(get_db),
    user=Depends(optional_user),
    school_id: int | None = Query(default=None, ge=1),
    subject_id: int | None = Query(default=None, ge=1),
) -> dict:
    """返回 08 专业实体、权威匹配科目与显式资源包。

    ``school_id``/``subject_id`` 是深链校验参数，不用于扩大专业实体范围。
    资源包只读取 210 显式关联，并严格限制为公开或当前登录用户私有数据。
    """
    major = db.query(KaoyanMajor).filter(KaoyanMajor.id == major_id).one_or_none()
    if major is None:
        raise HTTPException(status_code=404, detail="专业不存在")
    discipline = (
        db.query(Discipline)
        .filter(
            Discipline.code == major.subject_code,
            Discipline.code.like("08%"),
        )
        .one_or_none()
    )
    if discipline is None:
        raise HTTPException(status_code=404, detail="该专业不属于工科08目录")
    school = (
        db.query(KaoyanSchool)
        .filter(
            KaoyanSchool.id == major.school_id,
        )
        .one_or_none()
    )
    if school is None:
        raise HTTPException(status_code=404, detail="专业所属院校未收录")
    if school_id is not None and school_id != major.school_id:
        raise HTTPException(status_code=404, detail="院校参数与专业归属不一致")

    matched_subjects = _serialize_matched_subjects(_matched_subject_rows(db, major.id, user))
    matched_ids = {item["id"] for item in matched_subjects}
    if subject_id is not None and subject_id not in matched_ids:
        raise HTTPException(status_code=404, detail="科目不是该专业的 matched 科目")

    selected_subject_id = subject_id or (matched_subjects[0]["id"] if matched_subjects else None)
    practice_query = {
        "tab": "engineering08",
        "school_id": major.school_id,
        "major_id": major.id,
    }
    if selected_subject_id is not None:
        practice_query["subject_id"] = selected_subject_id

    return {
        "major": {
            "id": major.id,
            "school_id": major.school_id,
            "code": major.code,
            "name": major.name,
            "research_direction": major.research_direction,
            "subject_code": major.subject_code,
            "exam_subjects": major.exam_subjects or [],
            "reference_books": major.reference_books or [],
            "degree_type": major.degree_type,
        },
        "school": {
            "id": school.id,
            "name": school.name,
            "level": school.level,
            "province": school.province,
            "city": school.city,
            "data_source": school.data_source,
        },
        "discipline": {
            "id": discipline.id,
            "code": discipline.code,
            "name": discipline.name,
            "category": discipline.category,
            "parent_code": discipline.parent_code,
        },
        "matched_subjects": matched_subjects,
        "selected_subject_id": selected_subject_id,
        "question_count_total": sum(item["question_count"] for item in matched_subjects),
        "practice_path": f"/quiz?{urlencode(practice_query)}",
        "resource_pack": _major_resource_pack(
            db,
            major.id,
            selected_subject_id,
            user,
        ),
    }


def _question_in_major_scope(
    discipline_code: str | None,
    school_id: int | None,
    major_id: int | None,
):
    """所有专业 facets 在同一个 EXISTS 内相交，题目本身不会因 join 重复。"""
    conditions = [
        KaoyanMajorSubjectLink.subject_id == QuizQuestion.subject_id,
        KaoyanMajorSubjectLink.subject_id.is_not(None),
        KaoyanMajorSubjectLink.match_status == "matched",
        KaoyanMajor.subject_code == Discipline.code,
        Discipline.code.like("08%"),
    ]
    if discipline_code is not None:
        conditions.append(KaoyanMajor.subject_code == discipline_code)
    if school_id is not None:
        conditions.append(KaoyanMajor.school_id == school_id)
    if major_id is not None:
        conditions.append(KaoyanMajor.id == major_id)
    return exists(
        select(KaoyanMajorSubjectLink.id)
        .join(KaoyanMajor, KaoyanMajor.id == KaoyanMajorSubjectLink.major_id)
        .join(Discipline, Discipline.code == KaoyanMajor.subject_code)
        .where(*conditions)
    ).correlate(QuizQuestion)


def _serialize_question(question: QuizQuestion) -> dict:
    """沿用刷题列表字段，并补权威科目与明确的私有题标记。"""
    return {
        "id": question.id,
        "content": question.content,
        "options": question.options,
        "images": question.images or [],
        "answer": question.answer,
        "analysis": question.analysis,
        "subject": question.subject,
        "subject_id": question.subject_id,
        "chapter": question.chapter,
        "knowledge_point": question.knowledge_point,
        "difficulty": question.difficulty,
        "source": question.source_label,
        "source_kind": question.source_kind,
        "question_type": question.question_type,
        "question_category": question.question_category,
        "answer_type": question.answer_type,
        "quality": question.quality,
        "is_available": question.is_available,
        "year": question.year,
        "paper": question.paper,
        "question_no": question.question_no,
        "figure_missing": question.figure_missing or 0,
        "owner_user_id": question.owner_user_id,
        "is_personal": question.owner_user_id is not None,
    }


@router.get("/engineering-08/questions")
def engineering08_questions(
    db: Session = Depends(get_db),
    user=Depends(optional_user),
    discipline_code: str | None = Query(None, max_length=20),
    school_id: int | None = Query(None, ge=1),
    major_id: int | None = Query(None, ge=1),
    subject_id: int | None = Query(None, ge=1),
    year: int | None = Query(None, ge=1900, le=2100),
    question_type: str | None = Query(None, max_length=30),
    source_kind: str | None = Query(None, max_length=40),
    difficulty: int | None = Query(None, ge=1, le=5),
    params: dict = Depends(page_params),
) -> dict:
    """按 08 专业链路与同屏 facets 返回可见、可作答且非垃圾题。"""
    query = visible_quiz_filter(
        db.query(QuizQuestion).filter(
            _visible_clause(user),
            _question_in_major_scope(discipline_code, school_id, major_id),
        )
    )
    exact_facets = {
        QuizQuestion.subject_id: subject_id,
        QuizQuestion.year: year,
        QuizQuestion.question_type: question_type,
        QuizQuestion.source_kind: source_kind,
        QuizQuestion.difficulty: difficulty,
    }
    for column, value in exact_facets.items():
        if value is not None:
            query = query.filter(column == value)
    query = query.order_by(QuizQuestion.id.asc())
    return paginate_query(
        query,
        page=params["page"],
        page_size=params["page_size"],
        serialize=_serialize_question,
    ).dict()
