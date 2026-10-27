"""刷题路由。"""

from utils.security import require_admin
import datetime
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    User,
    QuizQuestion,
    ErrorRecord,
    AnswerRecord,
    ErrorKnowledgeLink,
    QuestionKnowledgeLink,
    KnowledgePoint,
    StudyEvent,
    Word,
)
from schemas import QuizQuestionCreate, QuizQuestionUpdate, QuizSubmit, GenericResponse
from services.quiz_content_gate import admit as gate_admit
from services.delete_guard import require_physical_delete_enabled
from services.review_scheduler import ReviewScheduler

from utils.response import MAX_PAGE_SIZE
from utils.scope import owner_id, scoped  # B4 行级隔离：个人域查询按用户过滤、写入落归属
from utils.security import current_user

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


# --------------------------------------------------------------------------- #
# 来源大类（真题 / 教材题 / 自建）的唯一派生规则见
# ``services/quiz_query.py``（source_kind_of / source_kind_expr），
# 此处仅做薄封装以保持本文件既有调用点不变，**不再维护第二份规则**。
# --------------------------------------------------------------------------- #
from services.quiz_query import (  # noqa: E402
    SOURCE_KIND_CHOICES as _SOURCE_KIND_CHOICES,
    source_kind_expr as _source_kind_expr_shared,
    answerable_expr as _answerable_expr_shared,
)

SOURCE_KIND_CHOICES = _SOURCE_KIND_CHOICES


def _source_kind_expr(source_kind: Optional[str]):
    """转发到共享派生器；非法值转 400（明确失败，不静默返回全部）。"""
    try:
        return _source_kind_expr_shared(source_kind)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{exc}；可选 {' | '.join(SOURCE_KIND_CHOICES)}",
        ) from exc


def _answerable_expr():
    """转发到共享「可作答」判定（is_available 为 True 或 NULL）。"""
    return _answerable_expr_shared()


@router.get("/questions")
async def list_questions(
    subject: Optional[str] = None,
    chapter: Optional[str] = None,
    difficulty: Optional[int] = None,
    source: Optional[str] = None,
    source_kind: Optional[str] = Query(
        None,
        description="来源大类：exam(真题) | textbook(教材/知识库) | custom(自建/ai)；不传=全部。"
                    "用于「真题 / 教材题」分页隔离",
    ),
    question_type: Optional[str] = None,
    mode: Optional[str] = None,
    q: Optional[str] = None,
    year: Optional[int] = None,
    paper: Optional[str] = None,
    kp_id: Optional[int] = Query(None, description="按知识点ID过滤"),
    include_junk: bool = Query(False, description="是否包含 OCR 碎片题（is_junk=1）；默认排除"),
    answerable: bool = Query(True, description="是否只要「可作答」的题（有答案、is_available=1）。默认 True；真题浏览/审计可传 False 查看缺答案题"),
    is_retest: Optional[bool] = Query(None, description="M6-3：按初试/复试过滤。None=全部（向后兼容）；False=仅初试；True=仅复试"),
    page: int = 1,
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底：未登录一律 401
):
    """题目列表（支持筛选与刷题模式）。

    统一查询参数（M0 刷题中心）：前端所有刷题入口收敛到同一套参数——
    ``subject`` / ``source`` / ``source_kind`` / ``answerable`` / ``kp_id`` /
    ``year`` / ``paper`` / ``mode``。

    新增筛选：
    - q：题干/解析关键词模糊搜索（修复题库管理页搜索框无效的问题）
    - year：按真题年份（回填后的 year 列）
    - paper：按真题套卷名（回填后的 paper 列）；配合 mode=sequential 得到套卷内题号顺序
    - kp_id：按知识点 ID 过滤（M2-3）。经 question_knowledge_links 关联表 join，
      命中的题目为「与该知识点存在链路」的题目；不传则行为完全不变（向后兼容）。
    - include_junk：是否包含 OCR 碎片题（M1-1f）。默认 False=排除 is_junk=1 的题，
      避免碎片/答案串污染刷题；题库管理需排查时可传 true。
    - is_retest：初试/复试分区过滤（M6-3）。None=全部（默认，向后兼容）；False=仅初试
      （含 is_retest 为 NULL 的存量题）；True=仅复试。可与 subject/chapter/kp_id 等叠加（AND）。
    - source_kind：来源大类 exam/textbook/custom。真题与教材题分页隔离的**唯一**依据。

    返回体在原有 ``{total, page, page_size, mode, questions}`` 基础上**新增**：
    - ``total_count``：当前筛选（不含 answerable 限制）的可见题数；
    - ``answerable_count``：其中「可作答」的题数（前端「可作答 N 题」据此显示，保证真实）；
    - ``source_kind`` / ``subject`` / ``applied``：回显本次生效的筛选（前端「依据明示」）。
    原有字段语义不变（``total`` 仍为应用 answerable 后的结果总数，分页依赖它）。
    """
    from sqlalchemy import func, or_
    from services.quiz_query import visible_quiz_filter

    # —— 基础筛选（不含 answerable 限制，用于口径计数）——
    base = db.query(QuizQuestion)
    # M1-1f/h：默认排除 OCR 碎片题（碎片/答案串不参与刷题）——统一走共享过滤
    base = visible_quiz_filter(base, include_junk=include_junk)
    # 科目严格过滤：空白串一律视为「未指定」，避免前端传空串导致全表裸返回
    subj_norm = (str(subject).strip() if subject is not None else "")
    if subj_norm:
        base = base.filter(QuizQuestion.subject == subj_norm)
    if chapter:
        base = base.filter(QuizQuestion.chapter == chapter)
    if difficulty:
        base = base.filter(QuizQuestion.difficulty == difficulty)
    if source:
        base = base.filter(QuizQuestion.source == source)
    sk_expr = _source_kind_expr(source_kind)
    if sk_expr is not None:
        base = base.filter(sk_expr)
    # M6-3：初试/复试分区过滤。None=不过滤（向后兼容，行为完全不变）。
    # is_retest 列约定：1/True=复试，0/False=初试；存量题默认 0。
    if is_retest is not None:
        if is_retest:
            base = base.filter(QuizQuestion.is_retest.is_(True))
        else:
            base = base.filter(or_(QuizQuestion.is_retest.is_(False),
                                   QuizQuestion.is_retest.is_(None)))
    if question_type:
        base = base.filter(QuizQuestion.question_type == question_type)
    if year:
        base = base.filter(QuizQuestion.year == year)
    if paper:
        base = base.filter(QuizQuestion.paper == paper)

    # kp_id / q 也纳入 base，保证 total_count / answerable_count 与结果集同口径
    if kp_id is not None:
        # M2-3：知识点过滤——经 question_knowledge_links 反查关联的题目 ID 集合。
        # 用 select 构造子查询内联，避免大 IN 列表与 SAWarning；与其余筛选参数可叠加（AND 语义）。
        from sqlalchemy import select

        linked_ids = select(QuestionKnowledgeLink.question_id).where(
            QuestionKnowledgeLink.knowledge_point_id == kp_id
        )
        base = base.filter(QuizQuestion.id.in_(linked_ids))
    if q:
        like = f"%{q.strip()}%"
        base = base.filter(
            or_(
                QuizQuestion.content.like(like),
                QuizQuestion.analysis.like(like),
                QuizQuestion.knowledge_point.like(like),
            )
        )

    # —— 口径计数：total_count（可见全量）/ answerable_count（可作答）——
    total_count = base.count()
    answerable_count = base.filter(_answerable_expr()).count()

    # —— 应用 answerable 限制，得到实际结果集 query ——
    # 刷题口径（2026-10）：默认只返回「可作答」的题（有答案，is_available=1）。
    # 无答案题（quality=C / incomplete）在真题浏览/审计场景才需要，默认不进入刷题池。
    query = base
    if answerable:
        query = query.filter(_answerable_expr())

    # total 与上面两个口径计数恒等（answerable=True 时等于 answerable_count，
    # False 时等于 total_count）—— 原实现这里又发了一次 count，属于纯浪费，
    # 直接复用已算出的值，SQL 语句与结果完全不变。
    total = answerable_count if answerable else total_count

    # 错题强化模式：优先返回错题相关知识点/章节的题目
    weakness_kps = []
    if mode == "weakness":
        # ErrorRecord 无 knowledge_point，经关联题目取知识点
        weak_rows = (
            db.query(QuizQuestion.knowledge_point, func.count(ErrorRecord.id))
            .join(ErrorRecord, ErrorRecord.question_id == QuizQuestion.id)
            .filter(
                ErrorRecord.status == "active",
                QuizQuestion.knowledge_point.isnot(None),
                scoped(ErrorRecord, user),  # B4：错题强化只看本人错题
            )
            .group_by(QuizQuestion.knowledge_point)
            .order_by(func.count(ErrorRecord.id).desc())
            .all()
        )
        weakness_kps = [kp for kp, _ in weak_rows if kp]
        if weakness_kps:
            # 先取命中薄弱知识点的题目
            weak_query = query.filter(
                or_(
                    QuizQuestion.knowledge_point.in_(weakness_kps),
                    QuizQuestion.chapter.in_(weakness_kps),
                )
            )
            total = weak_query.count()
            # 若薄弱题不够一页，补充普通题
            if total < page_size:
                extra_query = query.filter(
                    ~or_(
                        QuizQuestion.knowledge_point.in_(weakness_kps),
                        QuizQuestion.chapter.in_(weakness_kps),
                    )
                )
                weak_questions = (
                    weak_query.order_by(func.random()).all()
                )
                extra_count = page_size - total
                extra_questions = (
                    extra_query.order_by(func.random()).limit(extra_count).all()
                )
                questions = weak_questions + extra_questions
            else:
                questions = (
                    weak_query.order_by(func.random()).limit(page_size).all()
                )
            return {
                "total": total,
                "page": 1,
                "page_size": page_size,
                "mode": mode,
                "total_count": total_count,
                "answerable_count": answerable_count,
                "source_kind": source_kind or "all",
                "subject": subj_norm or None,
                "applied": _applied_filters(
                    subject=subj_norm or None, chapter=chapter, source=source,
                    source_kind=source_kind, answerable=answerable, kp_id=kp_id,
                    year=year, paper=paper, question_type=question_type, mode=mode,
                ),
                "weakness_knowledge_points": weakness_kps,
                "questions": [_serialize_question(q) for q in questions],
            }

    applied = _applied_filters(
        subject=subj_norm or None, chapter=chapter, source=source,
        source_kind=source_kind, answerable=answerable, kp_id=kp_id,
        year=year, paper=paper, question_type=question_type, mode=mode,
    )

    # 随机模式
    if mode == "random":
        questions = query.order_by(func.random()).limit(page_size).all()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "mode": mode,
            "total_count": total_count,
            "answerable_count": answerable_count,
            "source_kind": source_kind or "all",
            "subject": subj_norm or None,
            "applied": applied,
            "questions": [_serialize_question(q) for q in questions],
        }

    # 顺序模式 / 章节模式 / 默认
    # 套卷视图（带 paper 筛选）按 question_no 升序，得到套卷内题号顺序
    if paper:
        order_col = QuizQuestion.question_no.asc()
    elif mode == "sequential":
        order_col = QuizQuestion.id.asc()
    else:
        order_col = QuizQuestion.id.desc()
    questions = (
        query.order_by(order_col)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "mode": mode,
        "total_count": total_count,
        "answerable_count": answerable_count,
        "source_kind": source_kind or "all",
        "subject": subj_norm or None,
        "applied": applied,
        "questions": [_serialize_question(q) for q in questions],
    }


def _applied_filters(**kw) -> dict:
    """归一化「本次生效的筛选」，供前端「依据明示」展示（不暴露内部实现）。"""
    out: dict = {}
    for k in ("subject", "chapter", "source", "source_kind", "kp_id",
              "year", "paper", "question_type", "mode"):
        v = kw.get(k)
        if v not in (None, "", 0):
            out[k] = v
    if kw.get("answerable") is False:
        out["answerable"] = False
    return out


def _serialize_question(q):
    """题目序列化。

    M0 刷题中心：新增 ``answer_type`` / ``quality`` / ``is_available``，供前端
    区分「可作答客观题 / 仅记忆参考（无选项有答案）/ 不可作答（空题假题）」，避免
    渲染空白选项按钮。
    """
    return {
        "id": q.id,
        "content": q.content,
        "options": q.options,
        "images": getattr(q, "images", None) or [],
        "answer": q.answer,
        "analysis": q.analysis,
        "subject": q.subject,
        "chapter": q.chapter,
        "knowledge_point": q.knowledge_point,
        "difficulty": q.difficulty,
        "source": getattr(q, "source", None) or getattr(q, "source_label", None),
        "question_type": q.question_type,
        "answer_type": getattr(q, "answer_type", None),
        "quality": getattr(q, "quality", None),
        "is_available": getattr(q, "is_available", None),
        "year": getattr(q, "year", None),
        "paper": getattr(q, "paper", None),
        "question_no": getattr(q, "question_no", None),
    }


@router.get("/questions/{question_id}")
async def get_question_detail(
    question_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """单题详情（M2-5）：完整字段 + 关联知识点列表。

    - 题目不存在 → 404（HTTPException）。
    - 关联知识点经 ``question_knowledge_links`` join ``knowledge_points``，
      返回 ``[{id, name, role, weight}]``（role/weight 取自链路表）。
    - 只读端点，无副作用；无法访问时明确 404 而非静默返回空对象。
    """
    question = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail=f"题目 {question_id} 不存在")

    # 该题关联的知识点（多对多链路 → 知识点主表），按权重降序
    link_rows = (
        db.query(
            KnowledgePoint.id,
            KnowledgePoint.name,
            QuestionKnowledgeLink.role,
            QuestionKnowledgeLink.weight,
        )
        .join(QuestionKnowledgeLink, QuestionKnowledgeLink.knowledge_point_id == KnowledgePoint.id)
        .filter(QuestionKnowledgeLink.question_id == question_id)
        .order_by(QuestionKnowledgeLink.weight.desc())
        .all()
    )
    knowledge_points = [
        {
            "id": kp_id,
            "name": kp_name,
            "role": role or "primary",
            "weight": float(weight) if weight is not None else 1.0,
        }
        for kp_id, kp_name, role, weight in link_rows
    ]

    detail = _serialize_question(question)
    detail["knowledge_points"] = knowledge_points
    return detail


@router.get("/frequency")
async def quiz_frequency(
    dimension: str = Query(
        "chapter",
        description="聚合维度：paper(套卷) | chapter(章节) | kp(知识点考频)",
    ),
    subject: Optional[str] = None,
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE, description="返回条数上限"),
    include_junk: bool = Query(False, description="是否包含 OCR 碎片题；默认排除，口径同列表"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """考频聚合（M2-4）：按 套卷/章节/知识点 维度聚合知识点出现频次。

    ⚠️ 诚实口径：``quiz_questions.year`` 覆盖率仅 7.9%（725/9171），
    **因此本端点不按年份聚合**——按年份统计会给出严重失真的结论。
    改为按以下维度聚合（口径真实、可复现）：

    - ``dimension=paper``：按套卷（``paper``）聚合，返回每个套卷的题数、
      涉及知识点数（经 ``question_knowledge_links`` 去重）；
    - ``dimension=chapter``：按章节（``chapter``）聚合，返回每章题数、
      涉及知识点数；
    - ``dimension=kp``：按知识点聚合，用现有 ``knowledge_points.exam_frequency``
      降序排序，并带出该知识点经链路关联的真实题数。

    统一返回：``{dimension, subject, items: [{name, question_count, kp_count, ...}],
    total}``；``total`` 是过滤条件下的**分组总数**（可能大于 ``len(items)``，
    差额即被 ``limit`` 截掉的部分）。
    只读端点，无副作用。题数默认排除 OCR 碎片题（``is_junk=1``）。
    """
    from sqlalchemy import func, distinct
    from services.quiz_query import visible_quiz_filter

    if dimension == "paper":
        base = visible_quiz_filter(
            db.query(QuizQuestion.paper, func.count(QuizQuestion.id)),
            include_junk=include_junk,
        ).filter(QuizQuestion.paper.isnot(None))
        # subject 口径必须与下面的 total 同源，否则「按科目筛」只对 items 生效、
        # total 却统计全部，前端会算出根本不存在的页数。
        if subject:
            base = base.filter(QuizQuestion.subject == subject)
        rows = (
            base.group_by(QuizQuestion.paper)
            .order_by(func.count(QuizQuestion.id).desc())
            .limit(limit)
            .all()
        )
        # 每个套卷涉及的知识点数（经链路表去重，一次查回避免 N+1）
        kp_q = (
            visible_quiz_filter(
                db.query(
                    QuizQuestion.paper,
                    func.count(distinct(QuestionKnowledgeLink.knowledge_point_id)),
                ),
                include_junk=include_junk,
            )
            .join(QuestionKnowledgeLink, QuestionKnowledgeLink.question_id == QuizQuestion.id)
            .filter(QuizQuestion.paper.isnot(None))
        )
        if subject:
            kp_q = kp_q.filter(QuizQuestion.subject == subject)
        kp_map = {
            paper: cnt
            for paper, cnt in kp_q.group_by(QuizQuestion.paper).all()
        }
        items = [
            {
                "name": paper or "未标套卷",
                "question_count": cnt,
                "kp_count": kp_map.get(paper, 0),
            }
            for paper, cnt in rows
        ]
        # total = 过滤条件下的**全部组数**（不是 len(items)）：limit 截掉的部分
        # 前端要能知道，否则考频榜会显示成「一共就这 50 套」。
        total_q = visible_quiz_filter(
            db.query(func.count(distinct(QuizQuestion.paper))), include_junk=include_junk
        ).filter(QuizQuestion.paper.isnot(None))
        if subject:
            total_q = total_q.filter(QuizQuestion.subject == subject)
        return {
            "dimension": "paper",
            "subject": subject,
            "items": items,
            "total": int(total_q.scalar() or 0),
        }

    if dimension == "chapter":
        rows = visible_quiz_filter(
            db.query(QuizQuestion.chapter, func.count(QuizQuestion.id)),
            include_junk=include_junk,
        ).filter(QuizQuestion.chapter.isnot(None))
        if subject:
            rows = rows.filter(QuizQuestion.subject == subject)
        rows = (
            rows.group_by(QuizQuestion.chapter)
            .order_by(func.count(QuizQuestion.id).desc())
            .limit(limit)
            .all()
        )
        kp_q = (
            visible_quiz_filter(
                db.query(
                    QuizQuestion.chapter,
                    func.count(distinct(QuestionKnowledgeLink.knowledge_point_id)),
                ),
                include_junk=include_junk,
            )
            .join(QuestionKnowledgeLink, QuestionKnowledgeLink.question_id == QuizQuestion.id)
            .filter(QuizQuestion.chapter.isnot(None))
        )
        if subject:
            kp_q = kp_q.filter(QuizQuestion.subject == subject)
        kp_map = {
            chapter: cnt
            for chapter, cnt in kp_q.group_by(QuizQuestion.chapter).all()
        }
        items = [
            {
                "name": chapter or "未归章",
                "question_count": cnt,
                "kp_count": kp_map.get(chapter, 0),
            }
            for chapter, cnt in rows
        ]
        total_q = visible_quiz_filter(
            db.query(func.count(distinct(QuizQuestion.chapter))), include_junk=include_junk
        ).filter(QuizQuestion.chapter.isnot(None))
        if subject:
            total_q = total_q.filter(QuizQuestion.subject == subject)
        return {
            "dimension": "chapter",
            "subject": subject,
            "items": items,
            "total": int(total_q.scalar() or 0),
        }

    if dimension == "kp":
        # 按知识点聚合考频：用现有 exam_frequency 降序，并带出真实关联题数。
        q = db.query(KnowledgePoint)
        if subject:
            q = q.filter(KnowledgePoint.subject == subject)
        total = int(q.count())
        kp_rows = (
            q.order_by(KnowledgePoint.exam_frequency.desc(), KnowledgePoint.id.asc())
            .limit(limit)
            .all()
        )
        kp_ids = [k.id for k in kp_rows]
        # 关联题数（经链路表去重，且排除碎片题）一次查回
        count_map: dict[int, int] = {}
        if kp_ids:
            cnt_rows = (
                visible_quiz_filter(
                    db.query(
                        QuestionKnowledgeLink.knowledge_point_id,
                        func.count(distinct(QuestionKnowledgeLink.question_id)),
                    ),
                    include_junk=include_junk,
                )
                .join(QuizQuestion, QuizQuestion.id == QuestionKnowledgeLink.question_id)
                .filter(QuestionKnowledgeLink.knowledge_point_id.in_(kp_ids))
                .group_by(QuestionKnowledgeLink.knowledge_point_id)
                .all()
            )
            count_map = {kp_id: cnt for kp_id, cnt in cnt_rows}
        items = [
            {
                "name": k.name,
                "exam_frequency": int(k.exam_frequency or 0),
                "question_count": count_map.get(k.id, 0),
                "kp_count": 1,
                "subject": k.subject,
                "chapter": k.chapter,
                "mastery": int(k.mastery or 0),
            }
            for k in kp_rows
        ]
        return {"dimension": "kp", "subject": subject, "items": items, "total": total}

    raise HTTPException(
        status_code=400,
        detail=f"不支持的 dimension：{dimension}；可选 paper | chapter | kp",
    )


@router.get("/papers-index")
async def papers_index(
    subject: Optional[str] = None,
    source_kind: Optional[str] = Query(
        None, description="来源大类：exam(真题) | textbook(教材/知识库) | custom；不传=全部"),
    include_junk: bool = Query(False, description="是否包含 OCR 碎片题；默认排除，口径同列表"),
    db: Session = Depends(get_db),
):
    """真题套卷索引（对标 gitgraduate「真题专项训练体系」）。

    返回每份真题套卷的题数、涉及科目、年份（若有）。前端据此渲染套卷列表，
    点击某套卷 → /questions?paper=xxx&mode=sequential 得到题号网格。
    诚实口径：paper 来自 source 文档名回填，question_no 为套卷内录入顺序号。
    题数默认排除 OCR 碎片题（``is_junk=1``）。
    ``source_kind`` 用于「真题 / 教材题」分页隔离（教材题通常无 paper，默认列表为空属正常）。
    """
    from sqlalchemy import func
    from services.quiz_query import visible_quiz_filter

    query = visible_quiz_filter(
        db.query(
            QuizQuestion.paper,
            func.count(QuizQuestion.id),
            func.min(QuizQuestion.year),
            func.max(QuizQuestion.year),
        ),
        include_junk=include_junk,
    ).filter(QuizQuestion.paper.isnot(None))
    if subject:
        query = query.filter(QuizQuestion.subject == subject)
    sk_expr = _source_kind_expr(source_kind)
    if sk_expr is not None:
        query = query.filter(sk_expr)
    rows = query.group_by(QuizQuestion.paper).order_by(func.count(QuizQuestion.id).desc()).all()

    # 每份套卷的科目分布（一次查回，避免 N+1）
    subj_query = visible_quiz_filter(
        db.query(QuizQuestion.paper, QuizQuestion.subject, func.count(QuizQuestion.id)),
        include_junk=include_junk,
    ).filter(QuizQuestion.paper.isnot(None))
    if subject:
        subj_query = subj_query.filter(QuizQuestion.subject == subject)
    if sk_expr is not None:
        subj_query = subj_query.filter(sk_expr)
    subj_map: dict[str, dict[str, int]] = {}
    for p, s, c in subj_query.group_by(QuizQuestion.paper, QuizQuestion.subject).all():
        subj_map.setdefault(p, {})[s or "未分类"] = c

    papers = []
    for paper, cnt, ymin, ymax in rows:
        years = [y for y in (ymin, ymax) if y]
        year_label = None
        if ymin and ymax and ymin != ymax:
            year_label = f"{ymin}-{ymax}"
        elif ymin:
            year_label = str(ymin)
        papers.append({
            "paper": paper,
            "count": cnt,
            "year": ymin if (ymin and ymin == ymax) else None,
            "year_label": year_label,
            "subjects": subj_map.get(paper, {}),
        })
    return {"total": len(papers), "papers": papers}


@router.get("/years")
async def years_index(
    source_kind: Optional[str] = Query(
        None, description="来源大类：exam(真题) | textbook(教材/知识库) | custom；不传=全部"),
    include_junk: bool = Query(False, description="是否包含 OCR 碎片题；默认排除，口径同列表"),
    db: Session = Depends(get_db),
):
    """年份 × 科目 聚合（对标 gitgraduate「按年份浏览」）。

    仅统计 year 非空的题目（回填自真题文档名，无歧义年份）。
    返回：每个年份下各科目的题数，供「年→科目→题号网格」渲染。
    诚实口径：只覆盖能可靠解析年份的真题子集，不伪造年份。
    题数默认排除 OCR 碎片题（``is_junk=1``）。
    """
    from sqlalchemy import func
    from services.quiz_query import visible_quiz_filter

    yquery = visible_quiz_filter(
        db.query(QuizQuestion.year, QuizQuestion.subject, func.count(QuizQuestion.id)),
        include_junk=include_junk,
    ).filter(QuizQuestion.year.isnot(None))
    sk_expr = _source_kind_expr(source_kind)
    if sk_expr is not None:
        yquery = yquery.filter(sk_expr)
    rows = yquery.group_by(QuizQuestion.year, QuizQuestion.subject).all()
    by_year: dict[int, dict] = {}
    for year, subject, cnt in rows:
        node = by_year.setdefault(int(year), {"year": int(year), "total": 0, "subjects": {}})
        node["subjects"][subject or "未分类"] = node["subjects"].get(subject or "未分类", 0) + cnt
        node["total"] += cnt
    years = sorted(by_year.values(), key=lambda x: x["year"], reverse=True)
    return {"total_years": len(years), "years": years}



@router.delete("/questions/{question_id}", dependencies=[Depends(require_admin)])
async def delete_question(
    question_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """删除题目（题库管理用）。"""
    question = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail=f"题目 {question_id} 不存在")
    # 物理删除闸门：quiz_questions 的 DELETE 不可逆。本周曾因判重缺陷
    # 误删 158 条真题（仅恢复 89 条），这里加硬防护，默认必须显式
    # 设置 KAOYAN_ALLOW_PHYSICAL_DELETE=1 才放行。
    require_physical_delete_enabled("quiz_questions")
    # 同时删除关联的答题记录
    db.query(AnswerRecord).filter(AnswerRecord.question_id == question_id).delete()
    db.delete(question)
    db.commit()
    return {"success": True, "message": f"题目 {question_id} 已删除", "id": question_id}


@router.put("/questions/{question_id}", dependencies=[Depends(require_admin)])
async def update_question(
    question_id: int,
    payload: QuizQuestionUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """更新题目（局部更新：仅覆盖请求体中显式传入的字段）。"""
    question = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail=f"题目 {question_id} 不存在")

    # exclude_unset=True：只更新客户端显式传入的字段，未传字段保持原值，
    # 避免全量覆盖把 options/analysis 等可空字段误清空。
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(question, field, value)

    db.commit()
    db.refresh(question)
    return _serialize_question(question)


def _gate_rows(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """用题目内容闸门过滤待写入的题，返回 ``(放行列表, 拦截原因计数)``。

    拦截项**不静默丢弃**：调用方必须把计数回给前端，否则用户看不到
    「导入 20 道只进 3 道」的原因。

    手工单题录入（``POST /questions``）和人工确认闭环
    （``POST /import/confirm``）不走这里——那是人有意识覆盖闸门的入口，
    登记在 ``tests/test_quiz_gate_ast.py`` 的白名单里。
    """
    kept: list[dict] = []
    rejected: dict[str, int] = {}
    for p in rows:
        ok, reason = gate_admit(
            (p.get("content") or "").strip(),
            options=p.get("options") or [],
            answer=p.get("answer"),
            source=p.get("source") or "",
        )
        if ok:
            kept.append(p)
        else:
            rejected[reason] = rejected.get(reason, 0) + 1
    return kept, rejected


def _sanitize_rows(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """导入前统一清洗（services/content_sanitizer 单一来源）。

    在分类与内容闸门**之前**执行：先洗干净再分类（关键词/向量看到的才是
    无水印正文），闸门校验的也是干净结构。返回 (清洗后列表, 统计)。
    """
    from services.content_sanitizer import sanitize_question_fields

    stats = {"fields_cleaned": 0, "watermark_cleaned": 0, "options_from_inline": 0}
    out: list[dict] = []
    for p in rows:
        cleaned, issues = sanitize_question_fields(p)
        if any(i.startswith("watermark_removed") for i in issues):
            stats["watermark_cleaned"] += 1
        if "options_from_inline" in issues:
            stats["options_from_inline"] += 1
        if cleaned != p:
            stats["fields_cleaned"] += 1
        out.append(cleaned)
    return out, stats


@router.post("/questions", dependencies=[Depends(require_admin)])
async def add_question(
    question: QuizQuestionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """添加题目（人工单题录入，内容闸门白名单入口）。

    仍走 sanitize 清洗（水印/空白规整）——人工粘贴同样可能带水印，
    但**不拦截**（人有意识覆盖闸门的入口，登记在 gate 测试白名单）。
    """
    from services.content_sanitizer import sanitize_question_fields

    fields = sanitize_question_fields(question.model_dump())[0]
    new_q = QuizQuestion(**fields)
    db.add(new_q)
    db.commit()
    db.refresh(new_q)
    return {"id": new_q.id, "message": "题目添加成功"}


@router.post("/import", dependencies=[Depends(require_admin)])
async def import_questions(
    questions: list[QuizQuestionCreate],
    auto_classify: bool = Query(True, description="缺省字段自动识别分类（规则优先，LLM兜底）"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """批量导入题目。

    v2（可信闸门）：缺省字段自动判定——关键词加权 × 向量质心 softmax × LLM 受控兜底。
    高置信（科目≥0.90、题型≥0.85）直接自动入库（可信集）；低置信打 needs_review
    进复核队列（不静默错标、不丢弃）。返回 auto_accepted / needs_review 分别计数。
    """
    from services.quiz_classifier_v2 import autoclassify_v2, ensure_quiz_classify_columns

    sanitize_stats = None
    rejected_by_gate: dict[str, int] = {}
    classify_stats = None
    if auto_classify and questions:
        payloads = [q.model_dump() for q in questions]
        payloads, sanitize_stats = _sanitize_rows(payloads)
        classify_stats = autoclassify_v2(payloads, use_llm=True, db=db)
        ensure_quiz_classify_columns(db)
        payloads, rejected_by_gate = _gate_rows(payloads)
        for p in payloads:
            db.add(QuizQuestion(**p))
        count = len(payloads)
    else:
        rows = [q.model_dump() for q in questions]
        rows, sanitize_stats = _sanitize_rows(rows)
        rows, rejected_by_gate = _gate_rows(rows)
        ensure_quiz_classify_columns(db)
        for p in rows:
            db.add(QuizQuestion(**p))
        count = len(rows)
    db.commit()
    msg = f"成功导入 {count} 道题目"
    if rejected_by_gate:
        msg += f"（内容闸门拦截 {sum(rejected_by_gate.values())} 道）"
    if sanitize_stats and sanitize_stats["fields_cleaned"]:
        msg += (f"（清洗 {sanitize_stats['fields_cleaned']} 道："
                f"去水印 {sanitize_stats['watermark_cleaned']} / "
                f"抽取选项 {sanitize_stats['options_from_inline']}）")
    if classify_stats and classify_stats["classified"]:
        msg += (f"（自动分类 {classify_stats['classified']}："
                f"直接入库 {classify_stats['auto_accepted']} / 待复核 "
                f"{classify_stats['needs_review']}）")
    return {
        "imported": count,
        "rejected": sum(rejected_by_gate.values()),
        "rejected_by_gate": rejected_by_gate,
        "sanitize": sanitize_stats,
        "classify": classify_stats,
        "message": msg,
    }


@router.get("/modes")
async def list_modes(user: User = Depends(current_user)):  # B4 访客兜底
    """刷题模式列表。"""
    return {
        "modes": [
            {"id": "sequential", "name": "顺序刷题", "description": "按顺序逐题作答"},
            {"id": "random", "name": "随机刷题", "description": "随机抽取题目"},
            {"id": "weakness", "name": "错题强化", "description": "优先复习错题相关知识点"},
            {"id": "timed", "name": "限时模拟", "description": "模拟考试环境限时作答"},
            {"id": "chapter", "name": "章节练习", "description": "按章节专项练习"},
        ]
    }


def _resolve_chapter_id(
    db: Session,
    question: QuizQuestion,
    knowledge_point_id: Optional[int] = None,
) -> Optional[int]:
    """解析题目所属的**权威章节 ID**（``subject_chapters.id``）。

    ``study_events.chapter_id`` 的外键指向 ``subject_chapters(id)``，不是
    ``knowledge_points.id``——早期实现拿知识点的 id 直接塞进来，两者 id
    空间重叠时写成了脏关联，不重叠时整条埋点被外键打回、静默丢失。

    解析顺序（逐级降级，任一命中即返回）：
    1. 题目已关联知识点自身的 ``knowledge_points.chapter_id``（权威外键列）；
    2. 知识点 ``chapter`` 文本 / 题目 ``chapter`` 文本 → 同科目下
       ``subject_chapters.title`` 匹配。

    解析不到一律返回 ``None``（埋点允许章节为空），不影响答题主流程。
    """
    try:
        from sqlalchemy import text as _text

        # 1) 知识点上的权威章节外键（legacy ORM 未映射 chapter_id，走 SQL）
        if knowledge_point_id is not None:
            row = db.execute(
                _text(
                    "SELECT chapter_id FROM knowledge_points "
                    "WHERE id = :kid AND chapter_id IS NOT NULL LIMIT 1"
                ),
                {"kid": int(knowledge_point_id)},
            ).first()
            if row and row[0] is not None:
                return int(row[0])

        # 2) 文本兜底：知识点 chapter → 题目 chapter → subject_chapters.title
        chapter_text: Optional[str] = None
        if knowledge_point_id is not None:
            kp = (
                db.query(KnowledgePoint)
                .filter(KnowledgePoint.id == knowledge_point_id)
                .first()
            )
            if kp is not None and kp.chapter:
                chapter_text = kp.chapter
        if not chapter_text:
            chapter_text = getattr(question, "chapter", None)
        if not chapter_text:
            return None

        sql = "SELECT sc.id FROM subject_chapters sc"
        params: dict = {"title": str(chapter_text).strip()}
        if question.subject:
            sql += " JOIN subjects s ON s.id = sc.subject_id"
            sql += " WHERE s.name = :subject AND sc.title = :title"
            params["subject"] = question.subject
        else:
            sql += " WHERE sc.title = :title"
        sql += " ORDER BY sc.id ASC LIMIT 1"
        row = db.execute(_text(sql), params).first()
        return int(row[0]) if row else None
    except Exception:  # pragma: no cover - 章节解析失败不影响埋点
        return None


@router.post("/submit")
async def submit_answer(
    submission: QuizSubmit,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """提交答案（记录答题历史，答错自动入错题本）。

    P0-2：主观题（answer_type='subjective' 或 question_type 为
    essay/calc/fill）不再做字符串精确匹配判分：
    - 若传入 self_score，则按及格线（默认 60% max_score）判定 correct；
    - 未传 self_score 时 correct=None（不判对错），needs_review=True 交前端提示。
    """
    question = db.query(QuizQuestion).filter(QuizQuestion.id == submission.question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    # V12 置信度分级：低置信答案（LLM 生成/缺失）不参与自动判分，
    # 仅记录作答流水，返回 needs_review 交前端提示「答案待人工核对」。
    low_confidence = getattr(question, "answer_confidence", 1.0) is not None and \
        getattr(question, "answer_confidence", 1.0) < 0.8

    # —— P0-2：主观题判定 —— #
    # 命中主观题时不做精确字符串匹配，避免 essay/calc/fill 几乎必然判错。
    is_subjective = (
        str(getattr(question, "answer_type", "") or "").lower() == "subjective"
        or (question.question_type or "").lower() in ("essay", "calc", "fill")
    )

    correct = False
    self_score = None
    max_score = None
    if is_subjective:
        # 主观题：有自评则按及格线判对错；无自评则不判对错（correct=None）
        if submission.self_score is not None:
            self_score = float(submission.self_score)
            max_score = float(submission.max_score) if submission.max_score is not None else 10.0
            if max_score <= 0:
                max_score = 10.0
            # 及格线默认 60% max_score
            passing = 0.6 * max_score
            correct = self_score >= passing
        else:
            correct = None  # 不判对错
    elif question.answer and not low_confidence:
        correct = submission.my_answer.strip().upper() == question.answer.strip().upper()

    # 记录答题历史（用于真实正确率统计）
    record = AnswerRecord(
        question_id=question.id,
        my_answer=submission.my_answer,
        correct_answer=question.answer,
        is_correct=correct if not low_confidence else None,
        subject=question.subject,
        mode=submission.mode,
        cost_seconds=submission.cost_seconds or 0,
        user_id=owner_id(user),  # B4：归属当前用户
    )
    db.add(record)

    # 答错自动加入错题本（低置信题不判错——答案本身可能不可靠；
    # P0-2：主观题未自评时 correct=None，也不入错题本）
    error = None
    if correct is not None and not correct and not low_confidence:
        # 错因自动判定（信号驱动，零 LLM）：答题当下即填 error_category，
        # 让错因分布/薄弱点分析当天就有数据；用户可手动改写、也可点 AI 归因覆盖。
        try:
            from services.error_analyzer import infer_error_category

            category = infer_error_category(
                question_type=question.question_type,
                my_answer=submission.my_answer,
                correct_answer=question.answer,
                cost_seconds=submission.cost_seconds,
                option_count=len(question.options) if question.options else None,
                subject=question.subject,
            )
        except Exception:  # noqa: BLE001 - 判因失败不影响错题入库
            category = None
        error = ErrorRecord(
            question_id=question.id,
            content=question.content,
            my_answer=submission.my_answer,
            correct_answer=question.answer,
            error_reason="答题错误",
            error_category=category,
            subject=question.subject,
            status="active",
            # V12 同族修复：新错题首入库按掌握度排首次复习（≥1 天），
            # 不再 20 分钟后即当日到期、当天全部涌入"今日复习队列"。
            next_review=ReviewScheduler.first_review_at(),
            user_id=owner_id(user),  # B4：归属当前用户
        )
        db.add(error)

    db.commit()

    # —— P0-2：主观题自评分写入 answer_records（若表无 self_score 列则跳过）—— #
    if is_subjective and submission.self_score is not None:
        try:
            from sqlalchemy import text as _score_text

            db.execute(
                _score_text(
                    "UPDATE answer_records SET self_score = :sc "
                    "WHERE id = :rid AND self_score IS NULL"
                ),
                {"sc": float(submission.self_score), "rid": record.id},
            )
            db.commit()
        except Exception:  # noqa: BLE001 - 表无该列时静默跳过，不报错
            db.rollback() if db.in_transaction() else None

    # —— 错题 ↔ 知识点联动（2026-10）—— #
    # 此前只有「手动收录错题」(POST /api/errors) 会挂知识点，导致刷题产生的错题
    # 大量「错题孤岛」（联调实测覆盖率仅 12.5%）。此处与手动收录对齐，答错即挂考点。
    if error is not None:
        try:
            from services import error_linker

            error_linker.auto_link_error(db, error, top_k=3)
        except Exception as exc:  # 联动失败不影响答题响应
            import logging

            logging.getLogger(__name__).warning(
                "刷题错题自动关联知识点失败（已忽略）: %s", exc)

        # B4 行级隔离：error_linker（禁改服务）建链时不知道归属，这里按错题
        # 主人回填 error_knowledge_links.user_id（列语义即"跟随 error_id 的主人"）；
        # 只补 NULL 行，不覆盖既有归属。
        if owner_id(user) is not None:
            db.query(ErrorKnowledgeLink).filter(
                ErrorKnowledgeLink.error_id == error.id,
                ErrorKnowledgeLink.user_id.is_(None),
            ).update({"user_id": owner_id(user)}, synchronize_session=False)
            db.commit()

    # —— 掌握度刷新（S3 链路）—— #
    # mastery 兼容列只在 knowledge_points 被 UPDATE 时经触发器同步派生值；
    # 答题只写 answer_records，不碰 knowledge_points → 列会一直停留在旧值。
    # 这里提交后 touch 关联知识点（SET mastery=mastery），触发器即时拉取
    # v_knowledge_mastery 派生值，图谱/文档/错题的掌握度读数当场变准。
    try:
        from sqlalchemy import text as _text

        db.execute(_text(
            "UPDATE knowledge_points kp SET mastery = kp.mastery "
            "WHERE EXISTS (SELECT 1 FROM question_knowledge_links qkl "
            "              WHERE qkl.knowledge_point_id = kp.id "
            "                AND qkl.question_id = :qid)"
        ), {"qid": question.id})
        db.commit()
    except Exception as exc:  # 掌握度刷新失败不影响答题响应
        import logging

        logging.getLogger(__name__).warning(
            "答题后知识点掌握度刷新失败（已忽略）: %s", exc)
    db.rollback() if db.in_transaction() else None

    # —— M5-1：学习行为埋点（旁路，容错，绝不影响答题响应结构）—— #
    # 判分完成后写入一条 study_events，供学习统计 / 热力图 / 连续天数消费。
    # 幂等：以 answer_records.id 为去重键，同一份提交重复调用只落一条。
    # 独立会话写入：埋点失败只回滚它自己，不会碰到答题主事务。
    # 低置信答案（答案本身可能不可靠）不写入 is_correct，避免污染正确率。
    try:
        from services.study_event_service import record_answer, resolve_knowledge_point_id
        from utils.scope import owner_id as _owner_id

        kp_id = resolve_knowledge_point_id(db, question.id)
        chapter_id = _resolve_chapter_id(db, question, kp_id)
        record_answer(
            question_id=question.id,
            is_correct=None if low_confidence else correct,
            duration_seconds=submission.cost_seconds or None,
            subject=question.subject,
            knowledge_point_id=kp_id,
            chapter_id=chapter_id,
            user_id=_owner_id(user),
            answer_record_id=record.id,
            mode=submission.mode,
            payload={
                "question_type": question.question_type,
                "difficulty": question.difficulty,
                "low_confidence": bool(low_confidence),
                "answer_confidence": float(question.answer_confidence or 0)
                if getattr(question, "answer_confidence", None) is not None
                else None,
            },
        )
    except Exception as exc:  # pragma: no cover - 埋点异常绝不影响答题
        import logging

        logging.getLogger(__name__).warning("submit_answer 埋点异常（已忽略）: %s", exc)

    return {
        "question_id": question.id,
        "correct": correct,
        "needs_review": low_confidence or (is_subjective and submission.self_score is None),
        "correct_answer": question.answer,
        "analysis": question.analysis,
        "record_id": record.id,
        # P0-2：主观题透传字段（前端据此展示自评/AI 批改入口）
        "question_type": question.question_type,
        "is_subjective": is_subjective,
        "self_score": self_score,
        "max_score": max_score,
    }


# --------------------------------------------------------------------------- #
# P0-1：刷题生词提取（一键进词库的后端准备）
# --------------------------------------------------------------------------- #
#: 提取英文单词时的常见停用词（含冠词/代词/介词/连词/助动词等虚词）。
#: 正则已保证长度 ≥4，这里再过滤掉高频功能词，避免词库被噪音污染。
_QUIZ_STOPWORDS = {
    # —— 冠词 / 代词 / 指示词 ——
    "the", "this", "that", "these", "those", "there", "their", "them", "they",
    "your", "yours", "you", "yourself", "ours", "ourselves", "its", "itself",
    "her", "hers", "him", "his", "my", "mine", "our", "us", "we",
    "who", "whom", "whose", "which", "what", "when", "where", "why", "how",
    # —— 介词 / 连词 ——
    "with", "from", "have", "will", "were", "would", "could", "should",
    "about", "being", "been", "into", "over", "under", "again", "further",
    "once", "only", "than", "then", "very", "just", "also", "after",
    "before", "between", "during", "through", "above", "below", "against",
    "along", "among", "around", "because", "while", "though", "although",
    "without", "within", "across", "behind", "beyond", "beside", "besides",
    "except", "toward", "towards", "upon", "until", "unless", "since",
    "still", "even", "ever", "never", "always", "often", "rather", "either",
    "neither", "whether", "however", "therefore", "moreover", "furthermore",
    "instead", "otherwise", "whatever", "whenever", "wherever", "whoever",
    "some", "any", "all", "each", "every", "both", "few", "many", "much",
    "most", "more", "less", "least", "other", "another", "such", "own",
    "same", "different", "several", "certain",
    # —— 助动词 / 情态动词 / be 动词 ——
    "may", "might", "must", "shall", "can", "does", "did", "doing", "has",
    "had", "having", "need", "used", "use", "using", "get", "got", "give",
    "given", "take", "took", "taken", "come", "came", "become", "became",
    "keep", "know", "known", "think", "thought", "want", "wanted", "look",
    "looked", "like", "liked", "way", "ways", "thing", "things", "time",
    "times", "year", "years", "day", "days", "new", "now", "two", "one",
    "first", "second", "last", "next",
}



def _extract_english_words(text: Optional[str]) -> list:
    """从文本中提取英文单词候选。

    - 正则 ``[A-Za-z][A-Za-z-]{3,}``（≥4 字母，含连字符）
    - 统一小写
    - 过滤停用词
    - 保持首次出现顺序去重
    """
    if not text:
        return []
    found = []
    seen = set()
    for m in re.finditer(r"[A-Za-z][A-Za-z-]{3,}", str(text)):
        word = m.group(0).strip("-").lower()
        # 连字符单词去掉首尾连字符后再判断
        if len(word) < 4:
            continue
        if word in _QUIZ_STOPWORDS:
            continue
        if word not in seen:
            seen.add(word)
            found.append(word)
    return found


@router.post("/{question_id}/extract-words", dependencies=[Depends(require_admin)])
def extract_words(
    question_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """从题目中提取英文生词候选，并标注是否已在当前用户词库。

    - 提取来源：题干 content + options + analysis
    - 返回 ``{question_id, words: [{word, exists, source}]}``，按首次出现顺序去重。
    - ``exists=true`` 表示该词已在当前用户词库中（Word.word 精确匹配，按 user_id 过滤）。
    """
    question = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    # 收集文本来源
    sources = []
    if question.content:
        sources.append(("题干", question.content))
    if question.options:
        for opt in question.options:
            if opt:
                sources.append(("选项", str(opt)))
    if question.analysis:
        sources.append(("解析", question.analysis))

    # 提取候选词（保持首次出现顺序去重）
    candidate_words = []
    seen_words = set()
    for source, text in sources:
        for w in _extract_english_words(text):
            if w not in seen_words:
                seen_words.add(w)
                candidate_words.append({"word": w, "source": source})

    # 查询当前用户已有词（精确匹配，按 user_id 过滤）
    existing = set()
    if candidate_words:
        word_list = [c["word"] for c in candidate_words]
        rows = (
            db.query(Word.word)
            .filter(Word.word.in_(word_list), scoped(Word, user))
            .all()
        )
        existing = {r[0] for r in rows}

    words = [
        {
            "word": c["word"],
            "exists": c["word"] in existing,
            "source": c["source"],
        }
        for c in candidate_words
    ]
    return {"question_id": question.id, "words": words}


# --------------------------------------------------------------------------- #
# P0-2：主观题 AI 批改
# --------------------------------------------------------------------------- #
class GradeSubjectiveRequest(BaseModel):
    question_id: int
    my_answer: str = Field(..., min_length=1)
    max_score: Optional[float] = None


@router.post("/grade-subjective")
def grade_subjective(
    request: GradeSubjectiveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """主观题 AI 批改（绑定题目上下文）。

    - 查询题目（含题干/标准答案/解析）
    - 调用 ``services.subjective_grader.grade_subjective``（与模考引擎同款 prompt）
    - 成功返回 ``{score, max_score, evaluation, reference_answer}``
    - LLM 失败时返回 HTTP 200 + ``score=None`` 降级提示，不报错。
    """
    question = db.query(QuizQuestion).filter(QuizQuestion.id == request.question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    max_score = request.max_score
    # 若请求未传满分，尝试从题目/默认值取
    effective_max = max_score if max_score is not None else 10.0

    from services.subjective_grader import grade_subjective as _grade
    from services.subjective_grader import sandbox_verify, verify_score

    score, evaluation = _grade(
        question=question,
        my_answer=request.my_answer,
        max_score=effective_max,
        db=db,
    )

    # P0-2 结构分离验证器：沙箱验算 + 独立二次验证（评分卡）。
    # 生成器与验证器使用不同 prompt 与独立模型调用；任何失败都降级返回，
    # 不影响批改主流程。
    try:
        sbx = sandbox_verify(question=question, reference_answer=question.answer or "")
        verification = verify_score(
            question=question,
            my_answer=request.my_answer,
            score=score,
            max_score=effective_max,
            db=db,
        )
        verification["sandbox"] = sbx
    except Exception:  # noqa: BLE001 - 验证器旁路，失败不阻塞批改
        verification = {
            "verified_score": score,
            "dimensions": {},
            "verdict": "degraded",
            "comment": "验证器暂不可用",
            "degraded": True,
            "sandbox": {
                "verified": False,
                "expr": None,
                "value": None,
                "detail": "沙箱验算不可用",
                "usable": False,
            },
        }

    # 三层可审计记忆（55 号方案 P0-1）：旁路写入 L1 批改轨迹，供 L2 蒸馏。
    # 任何失败都不影响批改主流程（memory_service 内部已 try/except）。
    try:
        from services import memory_service

        memory_service.record_grading_trace(
            user_id=user.id,
            question_id=question.id,
            subject=question.subject,
            question_content=question.content,
            my_answer=request.my_answer,
            score=score,
            max_score=effective_max,
            evaluation=evaluation or "",
            db=db,
        )
    except Exception:  # noqa: BLE001 - 埋点旁路
        pass

    return {
        "question_id": question.id,
        "score": score,
        "max_score": effective_max,
        "evaluation": evaluation,
        "reference_answer": question.answer,
        "verification": verification,
    }


@router.get("/stats")
async def quiz_stats(
    include_junk: bool = Query(False, description="是否包含 OCR 碎片题；默认排除，与列表端点口径一致"),
    subject: Optional[str] = Query(None, description="按科目过滤统计（与 /questions 同语义；空串=不过滤）"),
    source_kind: Optional[str] = Query(
        None, description="来源大类：exam(真题) | textbook(教材/知识库) | custom；不传=全部"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """答题统计（基于真实答题记录计算正确率）。

    口径（M0-103①，全部**显式命名**，前端不再猜）：
    - ``total_questions`` / ``visible_total``：可见题总数（排除 is_junk=1），二者**相等**
      （``total_questions`` 为历史字段名，保留兼容）；
    - ``answerable_total``：其中可自动判分的题（is_available 为 True/NULL）；
    - ``junk_total``：被排除的 OCR 碎片题数（严格等于 raw - visible，junk 直接取 raw 差额）；
    - ``raw_total``：不排除任何题的原始总数（= visible_total + junk_total）。
    传 ``subject`` / ``source_kind`` 时，以上题目维度计数与 ``subject_distribution``
    一并按同条件收窄，保证与 ``GET /questions`` 的筛选语义完全一致。
    答题记录维度（attempts/accuracy/错题数）为**当前用户**口径（B4 行级隔离），
    不随题目筛选变化。

    性能优化（2026-10）：套 3 秒 TTL 内存缓存（``services/stats_cache``）——
    本端点每次要跑 6 条聚合 count（quiz_questions / answer_records /
    error_records 均为大表），前端仪表盘/刷题中心会轮询。缓存 key 含全部
    入参；pytest 环境下自动禁用（测试隔离铁律，见 stats_cache 模块文档）。
    """
    from services.quiz_query import normalize_source_kind
    from services.stats_cache import cached_async

    subj_norm = (str(subject).strip() if subject is not None else "")
    sk = normalize_source_kind(source_kind)
    # payload 生产者是 async（_quiz_stats_payload），必须用异步版缓存，
    # 否则缓存层返回协程对象，FastAPI 序列化直接 500。
    return await cached_async(
        # B4：缓存 key 并入用户维度，避免 A 用户的统计命中 B 用户的缓存串号
        f"quiz/stats:u{owner_id(user)}:{int(bool(include_junk))}:{subj_norm}:{sk}",
        lambda: _quiz_stats_payload(
            include_junk=include_junk,
            subject=subject,
            source_kind=source_kind,
            db=db,
            user=user,
        ),
    )


async def _quiz_stats_payload(
    include_junk: bool,
    subject: Optional[str],
    source_kind: Optional[str],
    db: Session,
    user: User = None,
) -> dict:
    """``quiz_stats`` 的真实计算体（与缓存分离，便于测试与复用）。

    B4 行级隔离：``user`` 传入时答题/错题维度聚合按该用户过滤；
    None（旧行为）不过滤，兼容未传用户的直接调用。
    """
    # M1-1h：统一走共享过滤，避免口径漂移
    from services.quiz_query import visible_quiz_filter, answerable_expr, normalize_source_kind

    sk = normalize_source_kind(source_kind)
    sk_expr = _source_kind_expr(source_kind)  # 非法值 → 400
    subj_norm = (str(subject).strip() if subject is not None else "")

    from sqlalchemy import func

    def _scoped(base):
        """套上科目/来源筛选（与 /questions 一致）。"""
        if subj_norm:
            base = base.filter(QuizQuestion.subject == subj_norm)
        if sk_expr is not None:
            base = base.filter(sk_expr)
        return base

    raw_total = _scoped(db.query(QuizQuestion)).count()
    visible_base = _scoped(visible_quiz_filter(db.query(QuizQuestion), include_junk=include_junk))
    total_questions = visible_base.count()
    answerable_total = _scoped(
        visible_quiz_filter(db.query(QuizQuestion), include_junk=include_junk)
    ).filter(answerable_expr()).count()
    junk_total = raw_total - total_questions

    # 性能优化（2026-10）：错题两态计数与答题两条 count 各合并为一条条件聚合
    # 查询（count(case when … then 1 end)），数值与原逐条 count 一致。
    from sqlalchemy import case

    err_row = (
        db.query(
            func.count(case((ErrorRecord.status == "active", 1))),
            func.count(case((ErrorRecord.status == "graduated", 1))),
        )
        .filter(scoped(ErrorRecord, user))  # B4：错题计数只看本人
        .first()
    )
    total_errors = int(err_row[0] or 0)
    graduated_errors = int(err_row[1] or 0)

    # 真实正确率 = 答对次数 / 答题总次数（全库口径）
    att_row = (
        db.query(
            func.count(AnswerRecord.id),
            func.count(case((AnswerRecord.is_correct == True, 1))),  # noqa: E712
        )
        .filter(scoped(AnswerRecord, user))  # B4：答题次数只看本人
        .first()
    )
    total_attempts = int(att_row[0] or 0)
    correct_attempts = int(att_row[1] or 0)
    accuracy_rate = round(correct_attempts / total_attempts * 100, 1) if total_attempts else 0
    # 各科目答题正确率
    subject_rows = (
        db.query(
            AnswerRecord.subject,
            func.count(AnswerRecord.id),
            func.sum(AnswerRecord.is_correct.cast(Integer)),
        )
        .filter(scoped(AnswerRecord, user))  # B4：分科正确率只看本人
        .group_by(AnswerRecord.subject)
        .all()
    )
    subject_accuracy = [
        {
            "subject": s or "未分类",
            "attempts": c,
            "correct": int(t or 0),
            "accuracy": round(int(t or 0) / c * 100, 1) if c else 0,
        }
        for s, c, t in subject_rows
    ]

    # —— 学习行为埋点口径（study_events）—— #
    # answer_records 是"提交流水"，study_events 是"学习行为流水"：前者用于
    # 正确率，后者用于真实时长 / 学习频次 / 连续天数。两者按 user_id 同源过滤，
    # 不再出现"页面按用户看、SQL 查全库"的数不上问题。
    from utils.timeutil import local_today, local_window_for_day

    ev_q = db.query(
        func.count(StudyEvent.id),
        func.coalesce(func.sum(StudyEvent.duration_seconds), 0),
    )
    if owner_id(user) is not None:
        ev_q = ev_q.filter(StudyEvent.user_id == owner_id(user))
    ev_total, ev_seconds = ev_q.first()
    study_events_total = int(ev_total or 0)
    study_minutes = round(int(ev_seconds or 0) / 60)

    answer_ev_q = db.query(
        func.count(StudyEvent.id),
        func.count(case((StudyEvent.is_correct.is_(True), 1))),
    ).filter(StudyEvent.event_type == "answer")
    if owner_id(user) is not None:
        answer_ev_q = answer_ev_q.filter(StudyEvent.user_id == owner_id(user))
    ev_answers, ev_correct = answer_ev_q.first()
    answer_events_total = int(ev_answers or 0)
    event_accuracy_rate = (
        round(int(ev_correct or 0) / answer_events_total * 100, 1)
        if answer_events_total
        else 0
    )

    today_start = local_window_for_day(local_today())[0]
    today_q = db.query(
        func.count(StudyEvent.id),
        func.coalesce(func.sum(StudyEvent.duration_seconds), 0),
    ).filter(StudyEvent.occurred_at >= today_start)
    if owner_id(user) is not None:
        today_q = today_q.filter(StudyEvent.user_id == owner_id(user))
    today_events, today_seconds = today_q.first()

    # 各科目题目数（默认排除碎片题，与 total_questions 同口径；随 subject/source_kind 收窄）
    subject_counts = (
        _scoped(
            visible_quiz_filter(
                db.query(QuizQuestion.subject, func.count(QuizQuestion.id)),
                include_junk=include_junk,
            )
        )
        .group_by(QuizQuestion.subject)
        .all()
    )

    return {
        # —— 题目维度：三个显式口径 ——
        "total_questions": total_questions,   # = visible_total（历史字段名，保留兼容）
        "visible_total": total_questions,     # 显式命名，与 total_questions 恒等
        "answerable_total": answerable_total,
        "junk_total": junk_total,
        "raw_total": raw_total,
        # —— 筛选回显（前端「依据明示」）——
        "subject": subj_norm or None,
        "source_kind": sk or "all",
        "caliber": {
            "total_questions": "可见题总数（排除 OCR 碎片 junk），等于 visible_total",
            "visible_total": "可见题总数（显式命名）",
            "answerable_total": "可自动判分的题（is_available 为 True/NULL）",
            "junk_total": "被排除的 OCR 碎片题数",
            "raw_total": "不排除任何题的原始总数 = visible_total + junk_total",
            "study_minutes": "study_events.duration_seconds 求和 / 60（真实记录）",
            "answer_events_total": "study_events 中 event_type='answer' 的流水条数",
        },
        # —— 答题记录维度（全库口径）——
        "total_attempts": total_attempts,
        "active_errors": total_errors,
        "graduated_errors": graduated_errors,
        "accuracy_rate": accuracy_rate,
        # —— 学习行为埋点维度（study_events；与答题记录同 user_id 过滤）——
        "study_events_total": study_events_total,
        "answer_events_total": answer_events_total,
        "event_accuracy_rate": event_accuracy_rate,
        "study_minutes": study_minutes,
        "today_events": int(today_events or 0),
        "today_study_minutes": round(int(today_seconds or 0) / 60),
        "subject_distribution": [
            {"subject": s or "未分类", "count": c} for s, c in subject_counts
        ],
        "subject_accuracy": subject_accuracy,
    }


# --------------------------------------------------------------------------- #
# Markdown 题库导入
# --------------------------------------------------------------------------- #
def _parse_markdown_questions(text: str) -> list:
    """解析 Markdown 格式的题目。

    支持两种常见格式：
    1. 每题以 `## ` 或 `### ` 标题分隔，选项 `- A. xxx` / `- [x] xxx`
    2. 连续段落：题干 + `-` 选项 + `答案：X` + `解析：...`
    """
    questions = []
    current = {}
    lines = text.splitlines()

    def flush():
        nonlocal current
        if current and current.get("content"):
            questions.append(current)
        current = {}

    for line in lines:
        line = line.rstrip()
        stripped = line.strip()
        # 标题分隔新题
        if stripped.startswith("###") or stripped.startswith("##"):
            flush()
            current = {"content": stripped.lstrip("#").strip(), "options": []}
            continue
        if not current:
            current = {"content": "", "options": []}

        # 选项行（仅当确实是列表项或"A."形式才作为选项）
        opt = _extract_option(stripped)
        if opt is not None:
            if current.get("options") is None:
                current["options"] = []
            current["options"].append(opt[1])
            # 带 [x] 勾选标记的选项行直接作为答案
            if opt[0]:
                current["answer"] = opt[0]
            continue

        # 答案 / 解析 / 元信息
        if stripped.startswith("答案"):
            # 支持 "答案：C" / "答案: C" / "答案 C"
            answer_part = stripped.split("答案", 1)[-1].lstrip("：: \t").strip()
            current["answer"] = answer_part.split()[0] if answer_part else current.get("answer")
        elif stripped.startswith("解析"):
            current["analysis"] = stripped.split("解析", 1)[-1].lstrip("：: ").strip()
        elif stripped.startswith("科目"):
            current["subject"] = stripped.split("科目", 1)[-1].lstrip("：: ").strip()
        elif stripped.startswith("章节"):
            current["chapter"] = stripped.split("章节", 1)[-1].lstrip("：: ").strip()
        elif stripped.startswith("知识点"):
            current["knowledge_point"] = stripped.split("知识点", 1)[-1].lstrip("：: ").strip()
        elif stripped.startswith("难度"):
            try:
                current["difficulty"] = int(stripped.split("难度", 1)[-1].lstrip("：: ").strip().split()[0])
            except (ValueError, IndexError):
                current["difficulty"] = 3
        elif stripped.startswith("来源"):
            current["source"] = stripped.split("来源", 1)[-1].lstrip("：: ").strip()
        else:
            # 普通行：追加到题干
            if current["content"]:
                current["content"] += "\n" + stripped
            else:
                current["content"] = stripped

    flush()

    # 清洗与规整
    cleaned = []
    for q in questions:
        content = (q.get("content") or "").strip()
        if not content:
            continue
        cleaned.append(
            {
                "content": content,
                "options": [o for o in (q.get("options") or []) if o],
                "answer": (q.get("answer") or "").strip(),
                "analysis": (q.get("analysis") or "").strip() or None,
                "subject": (q.get("subject") or "").strip() or None,
                "chapter": (q.get("chapter") or "").strip() or None,
                "knowledge_point": (q.get("knowledge_point") or "").strip() or None,
                "difficulty": q.get("difficulty") or 3,
                "source": (q.get("source") or "").strip() or None,
                "question_type": "single",
            }
        )
    return cleaned


def _extract_option(line: str):
    """从行中提取选项。返回 (答案字母, 选项文本)；非选项行返回 None。

    支持：
    - `- A. xxx` / `- A、xxx` / `- A) xxx`          -> 普通选项 (None, "xxx")
    - `- [x] A. xxx` / `- [x] xxx`                   -> 带勾选标记的选项 (字母, "xxx")
    - `A. xxx` / `A、xxx`（无列表符号）               -> 普通选项 (None, "xxx")
    - 其他行（题干/答案/解析/元信息）                 -> None
    """
    import re

    s = line.strip()
    # 列表项：- 或 * 开头
    m_list = re.match(r"^[-*]\s+(.*)$", s)
    if m_list:
        item = m_list.group(1)
        # 勾选标记 [x]
        m_check = re.match(r"^\[([xX])\]\s*(.*)$", item)
        if m_check:
            body = m_check.group(2)
            # 带字母：- [x] A. xxx
            m_letter = re.match(r"^\(?([A-Fa-f])\)?[\.、．]\s*(.*)$", body)
            if m_letter:
                return m_letter.group(1).upper(), m_letter.group(2)
            return None, body
        # 普通列表项：- A. xxx / - xxx
        m_letter = re.match(r"^\(?([A-Fa-f])\)?[\.、．]\s*(.*)$", item)
        if m_letter:
            return None, m_letter.group(2)
        return None, item

    # 无列表符号的直接 "A. xxx" 形式
    m_direct = re.match(r"^\(?([A-Fa-f])\)?[\.、．]\s*(.*)$", s)
    if m_direct:
        return None, m_direct.group(2)

    return None


def _normalize_candidate(q: dict, index: int) -> dict:
    """把解析/确认得到的候选题规整为统一结构（供 dry_run 预览与落库共用）。

    统一字段：content/options/answer/analysis/subject/chapter/knowledge_point/
    difficulty/question_type/source/is_retest。缺省值集中在此，避免两处不一致。

    清洗走 services/content_sanitizer（单一来源）：去水印、空白规整、
    内联选项抽取、选项规整为 [{key,text}]（对齐 DB is_canonical_options）。
    """
    from services.content_sanitizer import normalize_options, sanitize_question_fields

    cleaned, _issues = sanitize_question_fields({
        "content": q.get("content"), "options": q.get("options"),
        "answer": q.get("answer"), "analysis": q.get("analysis"),
        "question_type": q.get("question_type") or "single",
    })
    opts, _opt_issues = normalize_options(cleaned.get("options"))
    return {
        "index": index,
        "content": (cleaned.get("content") or "").strip(),
        "options": opts,
        "answer": cleaned.get("answer"),
        "analysis": cleaned.get("analysis"),
        "subject": q.get("subject"),
        "chapter": q.get("chapter"),
        "knowledge_point": q.get("knowledge_point"),
        "difficulty": q.get("difficulty") or 3,
        "question_type": q.get("question_type") or "single",
        # 来源标注：粘贴导入统一标记，便于溯源（M6-4）；可在候选中显式覆盖。
        "source": q.get("source") or "paste_import",
        "is_retest": bool(q.get("is_retest", False)),
    }


def _candidate_to_model_fields(cand: dict) -> dict:
    """把候选题 dict 转换为 QuizQuestion 构造字段（剔除 index 等非列字段）。

    含 v2 可信闸门字段：classify_confidence / classify_source / needs_review。
    """
    return {
        "content": cand["content"],
        "options": cand["options"],
        "answer": cand.get("answer"),
        "analysis": cand.get("analysis"),
        "subject": cand.get("subject"),
        "chapter": cand.get("chapter"),
        "knowledge_point": cand.get("knowledge_point"),
        "difficulty": cand.get("difficulty", 3),
        "question_type": cand.get("question_type", "single"),
        "source": cand.get("source") or "paste_import",
        "is_retest": bool(cand.get("is_retest", False)),
        "classify_confidence": cand.get("classify_confidence"),
        "classify_source": cand.get("classify_source"),
        "needs_review": bool(cand.get("needs_review", False)),
    }


def _build_paste_candidates(text: str, db: Session, is_retest: bool) -> tuple:
    """解析 Markdown 文本 → 自动分类(v2 可信闸门) → 返回 (候选题列表, 分类统计)，**不落库**。

    这是 M6-4「预览/确认」闭环的公共入口：``dry_run=True`` 直接返回它；
    ``confirm`` 端点也复用它对「原始文本」做一次性重解析。
    """
    questions = _parse_markdown_questions(text)
    if not questions:
        return [], {"classified": 0, "auto_accepted": 0, "needs_review": 0, "by_source": {}}

    from services.quiz_classifier_v2 import autoclassify_v2

    # 自动分类 v2：高置信直接入库、低置信打 needs_review 进复核队列。
    classify_stats = autoclassify_v2(questions, use_llm=True, db=db)

    candidates = []
    for i, q in enumerate(questions):
        # 解析出的题干若未标 is_retest，则由调用方参数统一指定初试/复试。
        q.setdefault("is_retest", is_retest)
        candidates.append(_normalize_candidate(q, i))
    return candidates, classify_stats


@router.post("/import/markdown", dependencies=[Depends(require_admin)])
async def import_markdown(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """从 Markdown 文本导入题目（M6-4 人工确认闭环）。

    请求体：{"text": "...markdown...", "dry_run": false, "is_retest": false}

    - ``dry_run=False``（默认）：保持原有行为，直接落库并返回导入数（**向后兼容**）。
    - ``dry_run=True``：只解析 + 自动分类，**不落库**，返回候选题列表供用户预览确认。
      确认后请把候选题（或原始 text）提交给 ``POST /api/quiz/import/confirm``。
    - ``is_retest``：本次导入的题目是否标记为复试题（M6-3），默认 False=初试。

    落库题目标注 ``source='paste_import'`` 以便溯源。
    """
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="内容为空")

    dry_run = bool(payload.get("dry_run", False))
    is_retest = bool(payload.get("is_retest", False))

    candidates, classify_stats = _build_paste_candidates(text, db, is_retest)
    if not candidates:
        raise HTTPException(status_code=400, detail="未解析到任何题目，请检查 Markdown 格式")

    # —— 预览模式：只返回候选题，绝不落库 —— #
    if dry_run:
        _, preview_rejected = _gate_rows(candidates)
        return {
            "dry_run": True,
            "imported": 0,
            "candidate_count": len(candidates),
            "would_reject": sum(preview_rejected.values()),
            "rejected_by_gate": preview_rejected,
            "candidates": candidates,
            "classify": classify_stats,
            "message": (
                f"已解析 {len(candidates)} 道候选题（未落库），请确认后调用 /api/quiz/import/confirm"
                + (f"；其中 {sum(preview_rejected.values())} 道会被内容闸门拦截" if preview_rejected else "")
            ),
        }

    # —— 直接落库（原有行为）—— #
    from services.quiz_classifier_v2 import ensure_quiz_classify_columns
    ensure_quiz_classify_columns(db)
    candidates, rejected_by_gate = _gate_rows(candidates)
    count = 0
    for cand in candidates:
        db.add(QuizQuestion(**_candidate_to_model_fields(cand)))
        count += 1
    db.commit()
    msg = f"成功导入 {count} 道题目"
    if rejected_by_gate:
        msg += f"（内容闸门拦截 {sum(rejected_by_gate.values())} 道）"
    if classify_stats and classify_stats.get("classified"):
        msg += (f"（自动分类 {classify_stats['classified']}："
                f"直接入库 {classify_stats.get('auto_accepted', 0)} / "
                f"待复核 {classify_stats.get('needs_review', 0)}）")
    return {
        "imported": count,
        "rejected": sum(rejected_by_gate.values()),
        "rejected_by_gate": rejected_by_gate,
        "classify": classify_stats,
        "message": msg,
    }


@router.post("/import/confirm", dependencies=[Depends(require_admin)])
async def import_confirm(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """确认后落库（M6-4 人工确认闭环第二步）。

    请求体（二选一，``candidates`` 优先）：
    - ``{"candidates": [{"content":..., "options":[...], "answer":..., ...,"is_retest":false}, ...]}``
    - ``{"text": "...原始 Markdown...", "is_retest": false}``（服务端重解析，等价于 dry_run 后确认）

    落库题目标注 ``source='paste_import'``（候选中显式指定 source 时以其为准）。
    返回 ``{"imported": N, "ids": [...]}``。
    """
    candidates = payload.get("candidates")
    is_retest = bool(payload.get("is_retest", False))

    if not candidates:
        # 允许只传原始文本：服务端重解析（与 dry_run 完全同源，保证一致）。
        text = (payload.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="缺少 candidates 或 text")
        candidates, _ = _build_paste_candidates(text, db, is_retest)

    if not isinstance(candidates, list) or not candidates:
        raise HTTPException(status_code=400, detail="candidates 为空")

    # 归一化全部候选，再统一跑 v2 可信闸门分类（客户端可能只回传编辑后的候选，
    # 未必带分类标记；v2 只补缺失字段、尊重显式输入，幂等安全）。
    cands = []
    for i, raw in enumerate(candidates):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"第 {i} 个候选题格式非法（应为对象）")
        cand = _normalize_candidate(raw, i)
        if not cand["content"]:
            raise HTTPException(status_code=400, detail=f"第 {i} 个候选题缺少 content")
        if "is_retest" not in raw:
            cand["is_retest"] = is_retest
        cands.append(cand)

    from services.quiz_classifier_v2 import autoclassify_v2, ensure_quiz_classify_columns
    ensure_quiz_classify_columns(db)
    autoclassify_v2(cands, use_llm=True, db=db)

    ids = []
    for cand in cands:
        obj = QuizQuestion(**_candidate_to_model_fields(cand))
        db.add(obj)
        db.flush()  # 取回自增 id，供响应返回
        ids.append(obj.id)
    db.commit()
    n_review = sum(1 for c in cands if c.get("needs_review"))
    return {
        "imported": len(ids),
        "ids": ids,
        "needs_review": n_review,
        "message": f"已确认落库 {len(ids)} 道题目（其中 {n_review} 道进复核队列）",
    }


@router.get("/review-queue")
async def review_queue(
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    subject: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """分类复核队列：返回 needs_review=True 且可用的候选题（供前端人工确认/驳回）。"""
    from sqlalchemy import or_

    q = (
        db.query(QuizQuestion)
        .filter(QuizQuestion.needs_review.is_(True))
        .filter(or_(QuizQuestion.is_junk.is_(False), QuizQuestion.is_junk.is_(None)))
        .filter(or_(QuizQuestion.is_available.is_(True), QuizQuestion.is_available.is_(None)))
    )
    if subject:
        q = q.filter(QuizQuestion.subject == subject)
    # total = 队列全量（不只是本页），前端据此显示「还有 N 条待复核」。
    total = int(q.count())
    rows = q.order_by(QuizQuestion.id.desc()).limit(limit).all()
    return {
        "total": total,
        "total_returned": len(rows),
        "items": [
            {
                "id": r.id,
                "content": r.content,
                "options": r.options,
                "answer": r.answer,
                "analysis": r.analysis,
                "subject": r.subject,
                "question_type": r.question_type,
                "knowledge_point": r.knowledge_point,
                "classify_confidence": r.classify_confidence,
                "classify_source": r.classify_source,
                "source": r.source,
            }
            for r in rows
        ],
    }


class QuizReviewAction(BaseModel):
    action: str                       # accept | reject
    subject: Optional[str] = None
    question_type: Optional[str] = None
    knowledge_point: Optional[str] = None


@router.post("/review/{question_id}")
async def review_question(
    question_id: int,
    body: QuizReviewAction,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """复核处理：accept=确认分类正确并清复核；reject=标记作废（is_junk）移出练习。"""
    q = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    if body.action == "accept":
        if body.subject is not None:
            q.subject = body.subject
        if body.question_type is not None:
            q.question_type = body.question_type
        if body.knowledge_point is not None:
            q.knowledge_point = body.knowledge_point
        q.needs_review = False
        msg = "已确认，移出复核队列"
    elif body.action == "reject":
        q.is_junk = True
        q.needs_review = False
        msg = "已作废（移出练习与复核）"
    else:
        raise HTTPException(status_code=400, detail="action 仅支持 accept / reject")
    db.commit()
    return {"id": question_id, "action": body.action, "message": msg}


@router.get("/retest/stats")
async def retest_stats(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """复试题量统计（M6-3）：按科目拆分初试/复试题目数。

    口径与题库列表一致：排除 OCR 碎片题（is_junk=1）。is_retest 为 NULL 的存量题
    归入初试（向后兼容，与 is_retest=False 过滤语义一致）。
    """
    from sqlalchemy import or_, case

    # 逐科目聚合：total（可用题）/initial（初试）/retest（复试）。
    rows = (
        db.query(
            QuizQuestion.subject,
            func.count(QuizQuestion.id),
            func.sum(
                case(
                    (QuizQuestion.is_retest.is_(True), 1),
                    else_=0,
                )
            ),
        )
        .filter(or_(QuizQuestion.is_junk.is_(False), QuizQuestion.is_junk.is_(None)))
        .group_by(QuizQuestion.subject)
        .all()
    )
    items = []
    total_initial = 0
    total_retest = 0
    for subject, total, retest in rows:
        retest_n = int(retest or 0)
        initial_n = int(total or 0) - retest_n
        total_initial += initial_n
        total_retest += retest_n
        items.append({
            "subject": subject or "未分类",
            "total": int(total or 0),
            "initial": initial_n,
            "retest": retest_n,
        })
    items.sort(key=lambda it: (-it["retest"], -it["total"], it["subject"]))
    return {
        "total": sum(it["total"] for it in items),
        "initial_total": total_initial,
        "retest_total": total_retest,
        "items": items,
    }


@router.post("/extract-knowledge-points", dependencies=[Depends(require_admin)])
async def extract_knowledge_from_text(
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """从粘贴文本中 LLM 抽取候选知识点（M6-4 顺带能力）。

    请求体：{"text": "...", "subject": "可选，缺省时由 LLM 判定", "dry_run": true,
             "max_chunk_size": 3000, "limit": 50}

    - ``dry_run=True``（默认）：只返回候选知识点，**不落库**，供人工确认。
    - ``dry_run=False``：写入 ``knowledge_points``（复用与 document_analyzer 一致的
      去重字段），``document_id`` 置空（非文档来源）。

    说明：本端点复用 document_analyzer 的分块（smart_chunk_text）与 AIService.chat，
    提示词与 ``KNOWLEDGE_POINT_PROMPT`` 同源，保证与文档分析产出一致。
    """
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="内容为空")

    dry_run = bool(payload.get("dry_run", True))
    subject_hint = (payload.get("subject") or "").strip()
    max_chunk_size = int(payload.get("max_chunk_size", 3000) or 3000)
    limit = int(payload.get("limit", 50) or 50)

    from services.document_analyzer import smart_chunk_text, KNOWLEDGE_POINT_PROMPT
    from services.ai_service import AIService

    chunks = smart_chunk_text(text, max_chunk_size=max_chunk_size, overlap=200)
    ai = AIService(db)

    candidates = []
    seen_names = set()
    for chunk in chunks:
        if len(candidates) >= limit:
            break
        try:
            result = await ai.chat([
                {"role": "system", "content": "你是知识提取专家，只返回JSON。"},
                {"role": "user", "content": KNOWLEDGE_POINT_PROMPT.format(content=chunk["text"][:6000])},
            ])
            raw = result.get("content", "") or ""
            # LLM 可能返回 ```json ... ``` 包裹或带前后缀文本，统一提取首个 JSON 数组。
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start < 0 or end <= start:
                continue
            import json as _json
            kps = _json.loads(raw[start:end])
            for kp in kps:
                name = (kp.get("name") or "").strip()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                candidates.append({
                    "name": name[:300],
                    "subject": (kp.get("subject") or subject_hint or "其他")[:50],
                    "chapter": (kp.get("chapter") or chunk.get("heading") or "")[:200],
                    "description": (kp.get("description") or "")[:2000],
                    "exam_frequency": min(5, max(1, int(kp.get("exam_frequency", 3) or 3))),
                })
                if len(candidates) >= limit:
                    break
        except Exception as e:  # noqa: BLE001 —— 单块失败不中断整体
            import logging
            logging.getLogger(__name__).warning("知识点抽取失败: %s", e)
            continue

    # —— 预览：只返回候选，不落库 —— #
    if dry_run:
        return {
            "dry_run": True,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "message": f"已抽取 {len(candidates)} 个候选知识点（未落库）",
        }

    # —— 落库（自定义来源，不关联文档）—— #
    created = 0
    for c in candidates:
        db.add(KnowledgePoint(
            name=c["name"],
            subject=c["subject"],
            chapter=c["chapter"],
            document_id=None,
            description=c["description"],
            exam_frequency=c["exam_frequency"],
            mastery=0,
        ))
        created += 1
    db.commit()
    return {"dry_run": False, "imported": created, "message": f"已落库 {created} 个知识点"}


@router.get("/subjects")
async def quiz_subjects(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """分项导航：各科目题目数与活跃错题数。

    M0-4 学科统一收口：数据源改为 `services.subject_registry` 唯一聚合器，
    响应字段结构**保持不变**（``{"total", "items":[{"subject","question_count","error_count"}]}``），
    前端无需改动。

    口径说明：科目集合以 ``subject_config`` 字典为权威，附带"业务表里出现过
    但字典未登记"的科目（``unregistered``），并按题目数降序返回，确保不漏数据。
    """
    from services import subject_registry
    from sqlalchemy import func

    data = subject_registry.list_subjects(db)["subjects"]

    # 口径显式化（M0-103①）：一科目同时给出三个明确命名的计数，前端不再靠猜。
    #   * raw_count        ：该科目全部题（含 OCR 碎片/junk、含已下架）
    #   * visible_count    ：排除 junk 后的可见题（= subject_registry 的 question_count 口径）
    #   * answerable_count ：其中可自动判分的题（is_available 为 True/NULL）
    # `question_count` 保留为 visible_count 的**同义字段**（不改语义，避免 taxonomy/
    # documents/papers 四个共用该 registry 的页面出现口径回退）。
    from services.quiz_query import visible_quiz_filter, answerable_expr

    rows = (
        db.query(QuizQuestion.subject, func.count(QuizQuestion.id))
        .filter(QuizQuestion.subject.isnot(None))
        .group_by(QuizQuestion.subject)
        .all()
    )
    raw_map = {s: int(c or 0) for s, c in rows}

    vis_rows = (
        visible_quiz_filter(
            db.query(QuizQuestion.subject, func.count(QuizQuestion.id)),
            include_junk=False,
        )
        .group_by(QuizQuestion.subject)
        .all()
    )
    visible_map = {s: int(c or 0) for s, c in vis_rows}

    avail_rows = (
        visible_quiz_filter(
            db.query(QuizQuestion.subject, func.count(QuizQuestion.id)),
            include_junk=False,
        )
        .filter(answerable_expr())
        .group_by(QuizQuestion.subject)
        .all()
    )
    answerable_map = {(s or "未分类"): int(c or 0) for s, c in avail_rows}

    # 逐项带出 subject/question_count/error_count，保持既有契约
    items = [
        {
            "subject": s["subject"],
            "question_count": s["question_count"],       # = visible_count（兼容，语义未变）
            "visible_count": visible_map.get(s["subject"], s["question_count"]),
            "raw_count": raw_map.get(s["subject"], s["question_count"]),
            "answerable_count": answerable_map.get(s["subject"], 0),
            "error_count": s["error_count"],
        }
        for s in data
    ]
    # 兼容旧排序：题目数降序（字典项 question_count=0 会自然沉底）
    items.sort(key=lambda it: (-it["question_count"], it["subject"]))
    return {
        "total": len(items),
        # 三个全库口径（各科目求和），语义与字段名一一对应，前端可直接引用
        "raw_total": sum(it["raw_count"] for it in items),
        "visible_total": sum(it["visible_count"] for it in items),
        "answerable_total": sum(it["answerable_count"] for it in items),
        # 口径说明（供前端 tooltip / 说明文案直接采用，避免各处自造描述）
        "caliber": {
            "question_count": "subject 原值可见题数（排除 OCR 碎片 junk）",
            "visible_count": "同 question_count（显式命名）",
            "raw_count": "该科目全部题，含 junk 与已下架",
            "answerable_count": "其中可自动判分的题（is_available 为 True/NULL）",
        },
        "items": items,
    }


@router.get("/sections")
async def quiz_sections(
    subject: Optional[str] = None,
    include_junk: bool = Query(False, description="是否包含 OCR 碎片题；默认排除，口径同列表"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """分项列表：指定科目（或全部）下的章节分布。题数默认排除 OCR 碎片题。"""
    from sqlalchemy import func
    from services.quiz_query import visible_quiz_filter
    q = visible_quiz_filter(
        db.query(QuizQuestion.chapter, func.count(QuizQuestion.id)),
        include_junk=include_junk,
    )
    if subject:
        q = q.filter(QuizQuestion.subject == subject)
    q = q.filter(QuizQuestion.chapter.isnot(None)).group_by(QuizQuestion.chapter).order_by(func.count(QuizQuestion.id).desc())
    rows = q.all()
    err_rows = (
        db.query(QuizQuestion.subject, QuizQuestion.chapter, func.count(ErrorRecord.id))
        .join(ErrorRecord, ErrorRecord.question_id == QuizQuestion.id)
        .filter(ErrorRecord.status == "active", scoped(ErrorRecord, user))  # B4：只看本人错题
        .group_by(QuizQuestion.subject, QuizQuestion.chapter)
        .all()
    )
    err_map = {(s or "", c or ""): n for s, c, n in err_rows}
    return {
        "total": len(rows),
        "items": [
            {
                "chapter": c or "未分类",
                "question_count": n,
                "error_count": err_map.get((subject, c), 0),
            }
            for c, n in rows
        ],
    }


@router.get("/wrong-reasons")
async def quiz_wrong_reasons(
    subject: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """错因汇总：活跃错题的错误原因分布（错题闭环第一环）。"""
    from sqlalchemy import func
    q = db.query(ErrorRecord.error_reason, func.count(ErrorRecord.id))
    if subject:
        q = q.filter(ErrorRecord.subject == subject)
    q = q.filter(
        ErrorRecord.status == "active",
        ErrorRecord.error_reason.isnot(None),
        scoped(ErrorRecord, user),  # B4：错因分布只看本人
    )
    rows = q.group_by(ErrorRecord.error_reason).order_by(func.count(ErrorRecord.id).desc()).limit(limit).all()
    return {"total": len(rows), "items": [{"reason": r or "未填错因", "count": c} for r, c in rows]}


@router.get("/weak-points")
async def quiz_weak_points(
    subject: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),  # B4 访客兜底
):
    """薄弱点排行：按 科目×章节×知识点 聚合活跃错题数（刷题视角的错题闭环）。"""
    from sqlalchemy import func
    q = (
        db.query(
            QuizQuestion.subject,
            QuizQuestion.chapter,
            QuizQuestion.knowledge_point,
            func.count(ErrorRecord.id),
        )
        .join(ErrorRecord, ErrorRecord.question_id == QuizQuestion.id)
        .filter(ErrorRecord.status == "active", scoped(ErrorRecord, user))  # B4：只看本人错题
    )
    if subject:
        q = q.filter(QuizQuestion.subject == subject)
    rows = (
        q.group_by(QuizQuestion.subject, QuizQuestion.chapter, QuizQuestion.knowledge_point)
        .order_by(func.count(ErrorRecord.id).desc())
        .limit(limit)
        .all()
    )
    items = []
    for s, ch, kp, c in rows:
        items.append({
            "subject": s or "",
            "chapter": ch or "",
            "knowledge_point": kp or "",
            "error_count": c,
            "key": f"{s or ''}|{ch or ''}|{kp or ''}",
        })
    return {"total": len(items), "items": items}
