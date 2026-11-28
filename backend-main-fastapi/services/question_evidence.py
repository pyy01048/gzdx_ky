"""题目证据链解析：题目 → 考点 → 知识片段 → 教材页 → 原卷。

所有节点均来自显式外键或已有关联表。缺失节点、页码与来源显式返回 None；
不按标题模糊匹配试卷，也不用 chunk 序号推算页码。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from models import (
    Document,
    KnowledgeChunk,
    KnowledgePoint,
    Paper,
    PaperQuestion,
    QuestionEvidenceLink,
    QuestionKnowledgeLink,
    QuizQuestion,
    Textbook,
    TextbookDocument,
)


def _provenance(source: str, *, confidence: float | None = None, status: str = "unverified") -> dict[str, Any]:
    return {"source": source, "confidence": confidence, "verification_status": status}


def _document(document: Document | None) -> dict[str, Any] | None:
    if document is None:
        return None
    return {
        "id": document.id,
        "file_name": document.file_name,
        "source_format": document.source_format,
        "subject": document.subject,
    }


def _paper(
    question: QuizQuestion,
    explicit_ids: set[int],
    membership: dict[int, list[tuple[int, int]]],
    papers: dict[int, Paper],
) -> dict[str, Any]:
    """只接受题目 FK、证据关联或 paper_questions 的精确 ID 关联。"""
    label = question.paper if question.paper is not None else question.source_paper
    candidates: list[tuple[int, str]] = []
    if question.paper_id is not None:
        candidates.append((int(question.paper_id), "quiz_questions.paper_id"))
    for paper_id in sorted(explicit_ids):
        candidates.append((paper_id, "question_evidence_links"))
    for paper_id in sorted({pid for pid, _ in membership.get(question.id, [])}):
        candidates.append((paper_id, "paper_questions.question_id"))

    unique: dict[int, str] = {}
    for paper_id, source in candidates:
        unique.setdefault(paper_id, source)
    paper_id = next(iter(unique)) if len(unique) == 1 else None
    paper = papers.get(paper_id) if paper_id is not None else None
    if paper_id is not None and paper is None:
        return {
            "id": None,
            "label": label,
            "raw_paper": question.paper,
            "source_paper": question.source_paper,
            "linked": False,
            "match_method": None,
            "unlinked_reason": "paper_not_found",
        }
    if paper is None:
        reason = (
            "ambiguous_explicit_relations"
            if len(unique) > 1
            else ("no_explicit_relation" if label not in (None, "") else "missing_paper")
        )
        return {
            "id": None,
            "label": label,
            "raw_paper": question.paper,
            "source_paper": question.source_paper,
            "linked": False,
            "match_method": None,
            "unlinked_reason": reason,
        }

    source = unique[paper_id]
    seqs = [seq for pid, seq in membership.get(question.id, []) if pid == paper_id]
    return {
        "id": paper.id,
        "title": paper.title,
        "year": paper.year,
        "paper_type": paper.paper_type,
        "is_mock": bool(paper.is_mock),
        "label": label,
        "raw_paper": question.paper,
        "source_paper": question.source_paper,
        "question_no": min(seqs) if seqs else question.question_no,
        "linked": True,
        "match_method": source,
        "unlinked_reason": None,
        **_provenance(source, confidence=1.0, status="verified"),
    }


def evidence_for_questions(db: Session, questions: list[QuizQuestion]) -> dict[int, dict[str, Any]]:
    """批量解析证据，避免会话创建时逐题 N+1。"""
    if not questions:
        return {}
    question_ids = [question.id for question in questions]

    explicit_rows = (
        db.query(QuestionEvidenceLink)
        .filter(
            QuestionEvidenceLink.question_id.in_(question_ids),
            QuestionEvidenceLink.verification_status != "rejected",
        )
        .order_by(QuestionEvidenceLink.id)
        .all()
    )
    explicit_by_question: dict[int, list[QuestionEvidenceLink]] = defaultdict(list)
    for row in explicit_rows:
        explicit_by_question[row.question_id].append(row)

    link_rows = (
        db.query(QuestionKnowledgeLink, KnowledgePoint)
        .join(KnowledgePoint, KnowledgePoint.id == QuestionKnowledgeLink.knowledge_point_id)
        .filter(QuestionKnowledgeLink.question_id.in_(question_ids))
        .order_by(QuestionKnowledgeLink.weight.desc(), QuestionKnowledgeLink.id)
        .all()
    )
    links_by_question: dict[int, list[tuple[QuestionKnowledgeLink, KnowledgePoint]]] = defaultdict(list)
    for link, point in link_rows:
        links_by_question[link.question_id].append((link, point))

    chunk_ids: set[int] = set()
    document_ids: set[int] = set()
    knowledge_point_ids: set[int] = set()
    textbook_ids: set[int] = set()
    paper_ids: set[int] = set()
    subject_ids = {int(row.subject_id) for row in explicit_rows if row.subject_id is not None}
    for question in questions:
        if question.origin_chunk_id is not None:
            chunk_ids.add(int(question.origin_chunk_id))
        if question.origin_document_id is not None:
            document_ids.add(int(question.origin_document_id))
        if question.paper_id is not None:
            paper_ids.add(int(question.paper_id))
        for _, point in links_by_question.get(question.id, []):
            knowledge_point_ids.add(point.id)
            if point.source_chunk_id is not None:
                chunk_ids.add(int(point.source_chunk_id))
            if point.document_id is not None:
                document_ids.add(int(point.document_id))
        for row in explicit_by_question.get(question.id, []):
            for value, target in (
                (row.knowledge_point_id, knowledge_point_ids),
                (row.knowledge_chunk_id, chunk_ids),
                (row.document_id, document_ids),
                (row.textbook_id, textbook_ids),
                (row.paper_id, paper_ids),
            ):
                if value is not None:
                    target.add(int(value))

    chunks = (
        {chunk.id: chunk for chunk in db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()}
        if chunk_ids
        else {}
    )
    for chunk in chunks.values():
        if chunk.document_id is not None:
            document_ids.add(int(chunk.document_id))
    documents = (
        {document.id: document for document in db.query(Document).filter(Document.id.in_(document_ids)).all()}
        if document_ids
        else {}
    )
    points = (
        {point.id: point for point in db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(knowledge_point_ids)).all()}
        if knowledge_point_ids
        else {}
    )

    textbook_documents = (
        (
            db.query(TextbookDocument)
            .filter(TextbookDocument.document_id.in_(document_ids))
            .order_by(TextbookDocument.id)
            .all()
        )
        if document_ids
        else []
    )
    for row in textbook_documents:
        textbook_ids.add(int(row.textbook_id))
    textbooks = (
        {book.id: book for book in db.query(Textbook).filter(Textbook.id.in_(textbook_ids)).all()}
        if textbook_ids
        else {}
    )
    subject_ids.update(int(book.subject_id) for book in textbooks.values() if book.subject_id is not None)

    membership_rows = (
        db.query(PaperQuestion.question_id, PaperQuestion.paper_id, PaperQuestion.seq)
        .filter(PaperQuestion.question_id.in_(question_ids))
        .all()
    )
    membership: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for question_id, paper_id, seq in membership_rows:
        membership[int(question_id)].append((int(paper_id), int(seq or 0)))
        paper_ids.add(int(paper_id))
    papers = {paper.id: paper for paper in db.query(Paper).filter(Paper.id.in_(paper_ids)).all()} if paper_ids else {}

    # 专业用于展开真实 school_id；不根据学校或专业名称猜测教材关系。
    major_ids = {int(row.major_id) for row in explicit_rows if row.major_id is not None}
    school_ids = {int(row.school_id) for row in explicit_rows if row.school_id is not None}
    if major_ids:
        from models import KaoyanMajor

        majors = {major.id: major for major in db.query(KaoyanMajor).filter(KaoyanMajor.id.in_(major_ids)).all()}
        school_ids.update(int(major.school_id) for major in majors.values())
    else:
        majors = {}
    if school_ids:
        from models import KaoyanSchool

        schools = {school.id: school for school in db.query(KaoyanSchool).filter(KaoyanSchool.id.in_(school_ids)).all()}
    else:
        schools = {}
    if subject_ids:
        from models import Subject

        subjects = {subject.id: subject for subject in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()}
    else:
        subjects = {}

    td_by_document: dict[int, list[TextbookDocument]] = defaultdict(list)
    for row in textbook_documents:
        td_by_document[int(row.document_id)].append(row)

    result: dict[int, dict[str, Any]] = {}
    for question in questions:
        rows = explicit_by_question.get(question.id, [])
        explicit_papers = {int(row.paper_id) for row in rows if row.paper_id is not None}

        knowledge_points: list[dict[str, Any]] = []
        seen_points: set[int] = set()
        for link, point in links_by_question.get(question.id, []):
            seen_points.add(point.id)
            chunk = chunks.get(int(point.source_chunk_id)) if point.source_chunk_id is not None else None
            document_id = (
                int(chunk.document_id)
                if chunk and chunk.document_id is not None
                else (int(point.document_id) if point.document_id is not None else None)
            )
            knowledge_points.append(
                {
                    "id": point.id,
                    "name": point.name,
                    "role": link.role or "primary",
                    "weight": float(link.weight) if link.weight is not None else 1.0,
                    "knowledge_chunk_id": chunk.id if chunk else None,
                    "document_id": document_id,
                    "page_start": chunk.page_start if chunk else None,
                    "page_end": chunk.page_end if chunk else None,
                    **_provenance(
                        "question_knowledge_links",
                        status="verified" if link.is_verified else "unverified",
                    ),
                }
            )
        for row in rows:
            if row.knowledge_point_id is None or int(row.knowledge_point_id) in seen_points:
                continue
            point = points.get(int(row.knowledge_point_id))
            if point is None:
                continue
            seen_points.add(point.id)
            chunk_id = row.knowledge_chunk_id if row.knowledge_chunk_id is not None else point.source_chunk_id
            chunk = chunks.get(int(chunk_id)) if chunk_id is not None else None
            document_id = row.document_id or point.document_id or (chunk.document_id if chunk else None)
            if row.page_start is not None or row.page_end is not None:
                page_start, page_end = row.page_start, row.page_end
            else:
                page_start = chunk.page_start if chunk else None
                page_end = chunk.page_end if chunk else None
            if page_start is None and page_end is not None:
                page_start = page_end
            if page_end is None and page_start is not None:
                page_end = page_start
            knowledge_points.append(
                {
                    "id": point.id,
                    "name": point.name,
                    "role": "evidence",
                    "weight": None,
                    "knowledge_chunk_id": chunk.id if chunk else chunk_id,
                    "document_id": document_id,
                    "page_start": page_start,
                    "page_end": page_end,
                    **_provenance(row.source, confidence=row.confidence, status=row.verification_status),
                }
            )

        chunk_source: dict[int, list[QuestionEvidenceLink]] = defaultdict(list)
        chunk_sources: dict[int, set[str]] = defaultdict(set)
        if question.origin_chunk_id is not None and int(question.origin_chunk_id) in chunks:
            chunk_sources[int(question.origin_chunk_id)].add("quiz_questions.origin_chunk_id")
        for _, point in links_by_question.get(question.id, []):
            if point.source_chunk_id is not None and int(point.source_chunk_id) in chunks:
                chunk_sources[int(point.source_chunk_id)].add("knowledge_points.source_chunk_id")
        for row in rows:
            point = points.get(int(row.knowledge_point_id)) if row.knowledge_point_id is not None else None
            chunk_id = (
                row.knowledge_chunk_id
                if row.knowledge_chunk_id is not None
                else (point.source_chunk_id if point is not None else None)
            )
            if chunk_id is not None and int(chunk_id) in chunks:
                chunk_source[int(chunk_id)].append(row)
                chunk_sources[int(chunk_id)].add(row.source)

        knowledge_chunks: list[dict[str, Any]] = []
        anchors: list[dict[str, Any]] = []
        for chunk_id in sorted(chunk_sources):
            chunk = chunks[chunk_id]
            explicit = chunk_source.get(chunk_id, [])
            provenance = explicit[0] if explicit else None
            if provenance and (provenance.page_start is not None or provenance.page_end is not None):
                page_start = provenance.page_start
                page_end = provenance.page_end
                page_source = provenance.source
            else:
                page_start = chunk.page_start
                page_end = chunk.page_end
                page_source = "knowledge_chunks" if page_start is not None or page_end is not None else None
                if page_start is None and page_end is None and question.origin_chunk_id == chunk_id:
                    page_start = question.source_page
                    page_end = question.source_page
                    page_source = "quiz_questions.source_page" if page_start is not None else None
            if page_start is None and page_end is not None:
                page_start = page_end
            if page_end is None and page_start is not None:
                page_end = page_start
            document_id = (
                int(chunk.document_id)
                if chunk.document_id is not None
                else (int(explicit[0].document_id) if explicit and explicit[0].document_id is not None else None)
            )
            item = {
                "id": chunk.id,
                "document_id": document_id,
                "document": _document(documents.get(document_id)) if document_id is not None else None,
                "chunk_index": chunk.chunk_index,
                "subject": chunk.subject,
                "page_start": page_start,
                "page_end": page_end,
                "page_source": page_source,
                "sources": sorted(chunk_sources[chunk_id]),
                **_provenance(
                    provenance.source if provenance else sorted(chunk_sources[chunk_id])[0],
                    confidence=provenance.confidence if provenance else None,
                    status=provenance.verification_status if provenance else "unverified",
                ),
            }
            knowledge_chunks.append(item)
            anchors.append(
                {
                    "document_id": document_id,
                    "knowledge_chunk_id": chunk.id,
                    "page_start": page_start,
                    "page_end": page_end,
                    "page_source": page_source,
                    "provenance": item,
                }
            )

        # 只有 origin_document_id 时仍保留真实文档节点，但不虚构 chunk 或页码。
        if question.origin_document_id is not None and int(question.origin_document_id) in documents:
            document_id = int(question.origin_document_id)
            if not any(anchor["document_id"] == document_id for anchor in anchors):
                provenance = _provenance("quiz_questions.origin_document_id")
                anchors.append(
                    {
                        "document_id": document_id,
                        "knowledge_chunk_id": None,
                        "page_start": question.source_page,
                        "page_end": question.source_page,
                        "page_source": "quiz_questions.source_page" if question.source_page is not None else None,
                        "provenance": provenance,
                    }
                )

        textbook_pages: list[dict[str, Any]] = []
        seen_textbook_pages: set[tuple] = set()

        def add_textbook_page(
            book: Textbook, anchor: dict[str, Any], row: TextbookDocument | None, explicit=None
        ) -> None:
            document_id = anchor["document_id"] if row is None else int(row.document_id)
            chunk_id = anchor.get("knowledge_chunk_id")
            if explicit and (explicit.page_start is not None or explicit.page_end is not None):
                # 显式页码优先；只缺一端时复制同一显式页码，不与 chunk 页码混拼成伪范围。
                page_start = explicit.page_start
                page_end = explicit.page_end
            else:
                page_start = anchor.get("page_start")
                page_end = anchor.get("page_end")
            if page_start is None and page_end is not None:
                page_start = page_end
            if page_end is None and page_start is not None:
                page_end = page_start
            school_id = explicit.school_id if explicit else None
            major_id = explicit.major_id if explicit else None
            subject_id = explicit.subject_id if explicit else book.subject_id
            major = majors.get(int(major_id)) if major_id is not None else None
            if school_id is None and major is not None:
                school_id = major.school_id
            school = schools.get(int(school_id)) if school_id is not None else None
            subject = subjects.get(int(subject_id)) if subject_id is not None else None
            provenance = _provenance(
                explicit.source if explicit else "textbook_documents",
                confidence=explicit.confidence if explicit else None,
                status=explicit.verification_status if explicit else "unverified",
            )
            key = (
                book.id,
                document_id,
                chunk_id,
                page_start,
                page_end,
                school_id,
                major_id,
                subject_id,
                provenance["source"],
            )
            if key in seen_textbook_pages:
                return
            seen_textbook_pages.add(key)
            textbook_pages.append(
                {
                    "textbook_id": book.id,
                    "title": book.title,
                    "document_id": document_id,
                    "document": _document(documents.get(document_id)) if document_id is not None else None,
                    "knowledge_chunk_id": chunk_id,
                    "doc_role": row.doc_role if row else None,
                    "page_start": page_start,
                    "page_end": page_end,
                    "page_source": (
                        explicit.source
                        if explicit and (explicit.page_start is not None or explicit.page_end is not None)
                        else anchor.get("page_source")
                    ),
                    "school_id": int(school_id) if school_id is not None else None,
                    "school_name": school.name if school else None,
                    "major_id": int(major_id) if major_id is not None else None,
                    "major_name": major.name if major else None,
                    "subject_id": int(subject_id) if subject_id is not None else None,
                    "subject_name": subject.name if subject else None,
                    "catalog_source": book.source,
                    "catalog_confidence": book.confidence,
                    "evidence_link_id": explicit.id if explicit else None,
                    **provenance,
                }
            )

        for anchor in anchors:
            document_id = anchor["document_id"]
            if document_id is None:
                continue
            for row in td_by_document.get(int(document_id), []):
                book = textbooks.get(int(row.textbook_id))
                if book is None:
                    continue
                explicit = next(
                    (
                        link
                        for link in rows
                        if link.textbook_id == book.id
                        and (link.document_id is None or int(link.document_id) == int(document_id))
                        and (
                            link.knowledge_chunk_id is None
                            or int(link.knowledge_chunk_id) == anchor.get("knowledge_chunk_id")
                        )
                    ),
                    None,
                )
                add_textbook_page(book, anchor, row, explicit)

        # 明确指定教材但未知文档时仍返回教材节点，document/page 保持 None。
        for row in rows:
            if row.textbook_id is None:
                continue
            book = textbooks.get(int(row.textbook_id))
            if book is None:
                continue
            document_id = int(row.document_id) if row.document_id is not None else None
            chunk_id = int(row.knowledge_chunk_id) if row.knowledge_chunk_id is not None else None
            chunk = chunks.get(chunk_id) if chunk_id is not None else None
            if document_id is None and chunk is not None and chunk.document_id is not None:
                document_id = int(chunk.document_id)
            td = (
                next((item for item in td_by_document.get(document_id, []) if item.textbook_id == book.id), None)
                if document_id is not None
                else None
            )
            provenance = _provenance(row.source, confidence=row.confidence, status=row.verification_status)
            anchor = {
                "document_id": document_id,
                "knowledge_chunk_id": chunk_id,
                "page_start": chunk.page_start if chunk else None,
                "page_end": chunk.page_end if chunk else None,
                "page_source": "knowledge_chunks"
                if chunk and (chunk.page_start is not None or chunk.page_end is not None)
                else None,
                "provenance": provenance,
            }
            add_textbook_page(book, anchor, td, row)

        textbook_pages.sort(
            key=lambda item: (
                item["textbook_id"],
                item["document_id"] or 0,
                item["knowledge_chunk_id"] or 0,
                item["page_start"] or 0,
            )
        )
        paper = _paper(question, explicit_papers, membership, papers)
        origin_document_id = int(question.origin_document_id) if question.origin_document_id is not None else None
        question_document_ids = {origin_document_id} if origin_document_id is not None else set()
        question_document_ids.update(
            int(chunk.document_id)
            for chunk in chunks.values()
            if chunk.id in chunk_sources and chunk.document_id is not None
        )
        question_document_ids.update(
            int(point.document_id)
            for _, point in links_by_question.get(question.id, [])
            if point.document_id is not None
        )
        question_document_ids.update(
            int(points[int(row.knowledge_point_id)].document_id)
            for row in rows
            if row.knowledge_point_id is not None
            and int(row.knowledge_point_id) in points
            and points[int(row.knowledge_point_id)].document_id is not None
        )
        question_document_ids.update(int(row.document_id) for row in rows if row.document_id is not None)
        documents_summary = [
            _document(documents[document_id])
            for document_id in sorted(question_document_ids)
            if document_id in documents
        ]
        missing: list[str] = []
        if not knowledge_points:
            missing.append("knowledge_points")
        if not knowledge_chunks:
            missing.append("knowledge_chunks")
        if not textbook_pages:
            missing.append("textbooks")
        elif not any(item["page_start"] is not None or item["page_end"] is not None for item in textbook_pages):
            missing.append("textbook_page_numbers")
        if not paper["linked"]:
            missing.append("paper")

        first_page = textbook_pages[0] if textbook_pages else None
        chain_summary = {
            "knowledge_point": (
                {"id": knowledge_points[0]["id"], "name": knowledge_points[0]["name"]} if knowledge_points else None
            ),
            "knowledge_chunk": (
                {
                    "id": knowledge_chunks[0]["id"],
                    "document_id": knowledge_chunks[0]["document_id"],
                    "page_start": knowledge_chunks[0]["page_start"],
                    "page_end": knowledge_chunks[0]["page_end"],
                }
                if knowledge_chunks
                else None
            ),
            "textbook_page": (
                {
                    "textbook_id": first_page["textbook_id"],
                    "title": first_page["title"],
                    "document_id": first_page["document_id"],
                    "page_start": first_page["page_start"],
                    "page_end": first_page["page_end"],
                    "page_source": first_page["page_source"],
                }
                if first_page
                else None
            ),
            # 原卷字符串不是精确关系；未关联时摘要也保持 NULL。
            "paper": paper if paper["linked"] else None,
            "complete": not missing,
        }

        result[question.id] = {
            "schema_version": 1,
            "question_id": question.id,
            "origin_document_id": origin_document_id,
            "origin_document": _document(documents.get(origin_document_id)) if origin_document_id is not None else None,
            "origin_chunk_id": int(question.origin_chunk_id) if question.origin_chunk_id is not None else None,
            "source_page": question.source_page,
            "documents": documents_summary,
            "knowledge_points": knowledge_points,
            "knowledge_chunks": knowledge_chunks,
            "textbook_pages": textbook_pages,
            "paper": paper,
            "chain_summary": chain_summary,
            "missing": missing,
        }
    return result


def evidence_for_question(db: Session, question: QuizQuestion) -> dict[str, Any]:
    return evidence_for_questions(db, [question])[question.id]
