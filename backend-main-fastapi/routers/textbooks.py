# -*- coding: utf-8 -*-
"""教材目录路由：书目 / 初试复试分类 / 院校关联 / 知识地图挂接。

背景
----
平台此前没有任何承载教材元数据的接口，教材只作为 documents 表里的一个文件存在，
前端无法回答「这门课指定哪本书、谁编的、第几版、用于初试还是复试、哪些学校在用」。

本路由把 PG 的 textbook 三表（textbooks / textbook_schools / textbook_documents）
暴露成只读查询接口，供「知识地图」页与「择校」页消费。

设计口径
--------
* ``exam_stage`` 是教材属性（同一本书可初试、复试两用），返回数组，不拆表；
* 院校关联通过 textbook_schools ↔ kaoyan_schools 打通，支持按学校反查书目；
* 数据来源标注在 ``source`` / ``confidence``，前端需展示，禁止把人工整理的
  常见考情归纳伪装成官方指定。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/textbooks", tags=["教材目录"])


@router.get("")
async def list_textbooks(
    db: Session = Depends(get_db),
    subject: Optional[str] = Query(None, description="按科目中文名筛选"),
    stage: Optional[str] = Query(None, description="按阶段筛选：初试 / 复试"),
    school_id: Optional[int] = Query(None, description="按院校 ID 筛选"),
    keyword: Optional[str] = Query(None, description="书名/作者模糊搜索"),
):
    """教材清单（支持按科目 / 阶段 / 院校 / 关键词筛选）。

    科目名走 subjects.name 精确匹配（与 ADR-002 科目单一权威源一致），
    不再对教材表硬编码中文科目名。
    """
    sql = """
        SELECT t.id, t.title, t.subtitle, t.edition, t.authors, t.publisher, t.isbn,
               t.subject_id, s.name AS subject_name, t.exam_stages::text[] AS stages,
               t.role, t.summary, t.note, t.source, t.confidence::text AS confidence,
               t.school_count,
               (SELECT COUNT(*) FROM textbook_documents td WHERE td.textbook_id = t.id) AS doc_count
          FROM textbooks t
          LEFT JOIN subjects s ON s.id = t.subject_id
         WHERE t.is_active
    """
    params: dict = {}
    if subject:
        sql += " AND s.name = :subject"
        params["subject"] = subject
    if stage:
        sql += " AND :stage = ANY(t.exam_stages::text[])"
        params["stage"] = stage
    if school_id:
        sql += (" AND EXISTS (SELECT 1 FROM textbook_schools ts "
                "WHERE ts.textbook_id = t.id AND ts.school_id = :sid)")
        params["sid"] = school_id
    if keyword:
        sql += " AND (t.title ILIKE :kw OR t.authors ILIKE :kw OR t.publisher ILIKE :kw)"
        params["kw"] = f"%{keyword}%"
    sql += " ORDER BY t.subject_id NULLS LAST, t.sort_order, t.id"

    rows = db.execute(text(sql), params).mappings().all()
    return {"items": [dict(r) for r in rows], "total": len(rows)}


@router.get("/by-subject")
async def textbooks_by_subject(
    db: Session = Depends(get_db),
    stage: Optional[str] = Query(None, description="按阶段筛选：初试 / 复试"),
):
    """按科目分组的教材清单——知识地图左栏「教材」维度的数据源。

    返回结构对齐 taxonomy 的口径：每个科目一个分组，内含该科目下的全部教材，
    并按初试/复试分开列出，便于前端做阶段切换。
    """
    rows = db.execute(text("""
        SELECT s.id AS subject_id, s.code AS subject_code, s.name AS subject_name,
               s.category::text AS category, s.sort_order,
               t.id, t.title, t.edition, t.authors, t.publisher, t.isbn,
               t.exam_stages::text[] AS stages, t.role, t.note, t.school_count,
               t.confidence::text AS confidence
          FROM subjects s
          JOIN textbooks t ON t.subject_id = s.id AND t.is_active
         WHERE (CAST(:stage AS text) IS NULL
                OR CAST(:stage AS text) = ANY(t.exam_stages::text[]))
         ORDER BY s.sort_order, t.sort_order, t.id
    """), {"stage": stage or None}).mappings().all()

    groups: dict[int, dict] = {}
    for r in rows:
        sid = r["subject_id"]
        if sid not in groups:
            groups[sid] = {
                "subject_id": sid, "subject_code": r["subject_code"],
                "subject_name": r["subject_name"], "category": r["category"],
                "sort_order": r["sort_order"], "textbooks": [],
            }
        groups[sid]["textbooks"].append({
            "id": r["id"], "title": r["title"], "edition": r["edition"],
            "authors": r["authors"], "publisher": r["publisher"], "isbn": r["isbn"],
            "stages": r["stages"], "role": r["role"], "note": r["note"],
            "school_count": r["school_count"], "confidence": r["confidence"],
        })
    items = sorted(groups.values(), key=lambda g: (g["sort_order"] or 0))
    return {"groups": items, "total_subjects": len(items),
            "total_books": sum(len(g["textbooks"]) for g in items)}


@router.get("/{textbook_id}")
async def textbook_detail(textbook_id: int, db: Session = Depends(get_db)):
    """教材详情：书目 + 院校使用清单 + 关联文档。"""
    book = db.execute(text("""
        SELECT t.*, s.name AS subject_name, t.exam_stages::text[] AS stages,
               t.confidence::text AS confidence_text
          FROM textbooks t LEFT JOIN subjects s ON s.id = t.subject_id
         WHERE t.id = :tid
    """), {"tid": textbook_id}).mappings().first()
    if not book:
        raise HTTPException(status_code=404, detail="教材不存在")

    schools = db.execute(text("""
        SELECT ks.id, ks.name, ks.province, ts.usage_note,
               ts.exam_stage::text AS exam_stage, ts.is_official
          FROM textbook_schools ts
          JOIN kaoyan_schools ks ON ks.id = ts.school_id
         WHERE ts.textbook_id = :tid
         ORDER BY ks.name
    """), {"tid": textbook_id}).mappings().all()

    docs = db.execute(text("""
        SELECT d.id, d.file_name, d.source_format::text AS source_format, td.doc_role
          FROM textbook_documents td
          JOIN documents d ON d.id = td.document_id
         WHERE td.textbook_id = :tid
    """), {"tid": textbook_id}).mappings().all()

    out = dict(book)
    out["schools"] = [dict(s) for s in schools]
    out["documents"] = [dict(d) for d in docs]
    return out


@router.get("/school/{school_id}")
async def textbooks_of_school(school_id: int, db: Session = Depends(get_db)):
    """某院校涉及的全部教材——择校页「考这所学校要读哪些书」。"""
    school = db.execute(
        text("SELECT id, name, province FROM kaoyan_schools WHERE id = :sid"),
        {"sid": school_id},
    ).mappings().first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    rows = db.execute(text("""
        SELECT t.id, t.title, t.edition, t.authors, t.publisher,
               s.name AS subject_name, ts.usage_note, ts.exam_stage::text AS exam_stage,
               ts.is_official, t.confidence::text AS confidence
          FROM textbook_schools ts
          JOIN textbooks t ON t.id = ts.textbook_id
          LEFT JOIN subjects s ON s.id = t.subject_id
         WHERE ts.school_id = :sid AND t.is_active
         ORDER BY s.sort_order NULLS LAST, t.sort_order
    """), {"sid": school_id}).mappings().all()
    return {"school": dict(school), "items": [dict(r) for r in rows],
            "total": len(rows)}


@router.get("/stats/overview")
async def textbook_stats(db: Session = Depends(get_db)):
    """教材域概览：总数 / 按阶段 / 按科目 / 按出版社分布。"""
    total = db.execute(text("SELECT COUNT(*) FROM textbooks WHERE is_active")).scalar()
    by_stage = db.execute(text("""
        SELECT st AS stage, COUNT(*) AS n FROM textbooks t, unnest(t.exam_stages) st
         WHERE t.is_active GROUP BY st ORDER BY n DESC
    """)).mappings().all()
    by_subject = db.execute(text("""
        SELECT COALESCE(s.name,'未归类') AS subject, COUNT(*) AS n
          FROM textbooks t LEFT JOIN subjects s ON s.id = t.subject_id
         WHERE t.is_active GROUP BY s.name ORDER BY n DESC
    """)).mappings().all()
    by_publisher = db.execute(text("""
        SELECT COALESCE(publisher,'未知') AS publisher, COUNT(*) AS n
          FROM textbooks WHERE is_active GROUP BY publisher ORDER BY n DESC LIMIT 10
    """)).mappings().all()
    by_school = db.execute(text("""
        SELECT ks.name AS school, COUNT(DISTINCT ts.textbook_id) AS n
          FROM textbook_schools ts JOIN kaoyan_schools ks ON ks.id = ts.school_id
         GROUP BY ks.name ORDER BY n DESC LIMIT 15
    """)).mappings().all()
    return {"total": total, "by_stage": [dict(r) for r in by_stage],
            "by_subject": [dict(r) for r in by_subject],
            "by_publisher": [dict(r) for r in by_publisher],
            "top_schools": [dict(r) for r in by_school]}
