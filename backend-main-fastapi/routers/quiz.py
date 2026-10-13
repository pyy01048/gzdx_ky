"""刷题路由。"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    QuizQuestion,
    ErrorRecord,
    AnswerRecord,
    QuestionKnowledgeLink,
    KnowledgePoint,
)
from schemas import QuizQuestionCreate, QuizQuestionUpdate, QuizSubmit, GenericResponse
from services.quiz_content_gate import admit as gate_admit
from services.delete_guard import require_physical_delete_enabled
from services.review_scheduler import ReviewScheduler

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


# --------------------------------------------------------------------------- #
# 来源大类（M0 刷题中心重构）：真题 / 教材题 的**唯一**判定口径。
#
# 库里没有 source_kind 列，来源大类由 `source` 字段的前缀决定：
#   * `真题:<文档名>`    → exam（历年真题）
#   * `知识库:<文档名>`  → textbook（教材 / 讲义 / 知识库抽取题）
#   * 其余 / NULL        → custom（ai 变式题、手工录入等）
# 前端「一页真题、一页教材题」的 Tab 分离即按此过滤，避免两类题混在一个列表里。
# --------------------------------------------------------------------------- #
SOURCE_KIND_CHOICES = ("exam", "textbook", "custom")
_EXAM_PREFIX = "真题:%"
_TEXTBOOK_PREFIX = "知识库:%"


def _source_kind_expr(source_kind: Optional[str]):
    """返回 source_kind 对应的 SQLAlchemy 过滤表达式；'all'/None 返回 None。

    非法的 source_kind 抛 400（明确失败，不静默返回全部）。
    """
    from sqlalchemy import and_, not_, or_

    if not source_kind or str(source_kind).strip().lower() in ("", "all"):
        return None
    kind = str(source_kind).strip().lower()
    if kind not in SOURCE_KIND_CHOICES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 source_kind：{source_kind}；可选 {' | '.join(SOURCE_KIND_CHOICES)}",
        )
    if kind == "exam":
        return QuizQuestion.source.like(_EXAM_PREFIX)
    if kind == "textbook":
        return QuizQuestion.source.like(_TEXTBOOK_PREFIX)
    # custom：既非真题也非教材（含 source 为 NULL 的历史行），不丢数据。
    # 注意：两个「非」之间必须是 AND——用 OR 会把 exam/textbook 行也放进来。
    return or_(
        QuizQuestion.source.is_(None),
        and_(
            not_(QuizQuestion.source.like(_EXAM_PREFIX)),
            not_(QuizQuestion.source.like(_TEXTBOOK_PREFIX)),
        ),
    )


def _answerable_expr():
    """「可作答」判定表达式：is_available 为 True 或 NULL（NULL 视为可用，向后兼容）。"""
    from sqlalchemy import or_

    return or_(QuizQuestion.is_available.is_(True), QuizQuestion.is_available.is_(None))


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
    page_size: int = 20,
    db: Session = Depends(get_db),
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

    # 错题强化模式：优先返回错题相关知识点/章节的题目
    weakness_kps = []
    if mode == "weakness":
        # ErrorRecord 无 knowledge_point，经关联题目取知识点
        weak_rows = (
            db.query(QuizQuestion.knowledge_point, func.count(ErrorRecord.id))
            .join(ErrorRecord, ErrorRecord.question_id == QuizQuestion.id)
            .filter(ErrorRecord.status == "active", QuizQuestion.knowledge_point.isnot(None))
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

    total = query.count()

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
        "answer": q.answer,
        "analysis": q.analysis,
        "subject": q.subject,
        "chapter": q.chapter,
        "knowledge_point": q.knowledge_point,
        "difficulty": q.difficulty,
        "source": q.source,
        "question_type": q.question_type,
        "answer_type": getattr(q, "answer_type", None),
        "quality": getattr(q, "quality", None),
        "is_available": getattr(q, "is_available", None),
        "year": getattr(q, "year", None),
        "paper": getattr(q, "paper", None),
        "question_no": getattr(q, "question_no", None),
    }


@router.get("/questions/{question_id}")
async def get_question_detail(question_id: int, db: Session = Depends(get_db)):
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
    limit: int = Query(50, ge=1, le=500, description="返回条数上限"),
    include_junk: bool = Query(False, description="是否包含 OCR 碎片题；默认排除，口径同列表"),
    db: Session = Depends(get_db),
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

    统一返回：``{dimension, subject, items: [{name, question_count, kp_count, ...}]}``。
    只读端点，无副作用。题数默认排除 OCR 碎片题（``is_junk=1``）。
    """
    from sqlalchemy import func, distinct
    from services.quiz_query import visible_quiz_filter

    if dimension == "paper":
        rows = (
            visible_quiz_filter(
                db.query(QuizQuestion.paper, func.count(QuizQuestion.id)),
                include_junk=include_junk,
            )
            .filter(QuizQuestion.paper.isnot(None))
            .group_by(QuizQuestion.paper)
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
        return {"dimension": "paper", "subject": subject, "items": items}

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
        return {"dimension": "chapter", "subject": subject, "items": items}

    if dimension == "kp":
        # 按知识点聚合考频：用现有 exam_frequency 降序，并带出真实关联题数。
        q = db.query(KnowledgePoint)
        if subject:
            q = q.filter(KnowledgePoint.subject == subject)
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
        return {"dimension": "kp", "subject": subject, "items": items}

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



@router.delete("/questions/{question_id}")
async def delete_question(question_id: int, db: Session = Depends(get_db)):
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


@router.put("/questions/{question_id}")
async def update_question(
    question_id: int,
    payload: QuizQuestionUpdate,
    db: Session = Depends(get_db),
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


@router.post("/questions")
async def add_question(question: QuizQuestionCreate, db: Session = Depends(get_db)):
    """添加题目（人工单题录入，内容闸门白名单入口）。"""
    new_q = QuizQuestion(**question.model_dump())
    db.add(new_q)
    db.commit()
    db.refresh(new_q)
    return {"id": new_q.id, "message": "题目添加成功"}


@router.post("/import")
async def import_questions(
    questions: list[QuizQuestionCreate],
    auto_classify: bool = Query(True, description="缺省字段自动识别分类（规则优先，LLM兜底）"),
    db: Session = Depends(get_db),
):
    """批量导入题目。

    T3：subject/question_type/knowledge_point 缺省时自动判定——
    规则优先（关键词，确定性），LLM 兜底（缺科目的题批量走本地小模型）。
    LLM 判定的题标 ai_generated=True/verified=False，规则判定不标。
    """
    from services.quiz_autoclassify import autoclassify

    rejected_by_gate: dict[str, int] = {}
    classify_stats = None
    if auto_classify and questions:
        payloads = [q.model_dump() for q in questions]
        classify_stats = autoclassify(payloads, use_llm=True, db=db)
        payloads, rejected_by_gate = _gate_rows(payloads)
        for p in payloads:
            db.add(QuizQuestion(**p))
        count = len(payloads)
    else:
        rows = [q.model_dump() for q in questions]
        rows, rejected_by_gate = _gate_rows(rows)
        for p in rows:
            db.add(QuizQuestion(**p))
        count = len(rows)
    db.commit()
    msg = f"成功导入 {count} 道题目"
    if rejected_by_gate:
        msg += f"（闸门拦截 {sum(rejected_by_gate.values())} 道）"
    if classify_stats and classify_stats["classified"]:
        msg += f"（自动分类 {classify_stats['classified']}：规则 {classify_stats['by_rules']}/AI {classify_stats['by_llm']}）"
    return {
        "imported": count,
        "rejected": sum(rejected_by_gate.values()),
        "rejected_by_gate": rejected_by_gate,
        "classify": classify_stats,
        "message": msg,
    }


@router.get("/modes")
async def list_modes():
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
    """尽力解析题目所属章节 ID（用于 study_events.chapter_id 埋点）。

    解析顺序（逐级降级，任一命中即返回）：
    1. 题目已关联的知识点所属章节：``knowledge_points.chapter`` 文本匹配
       同科目下的章节知识点，取其 ``id``；
    2. 直接用题目自身的 ``chapter`` 文本在同科目知识点里找同名章节。

    注意：本项目 ``chapter`` 为文本字段而非外键，此处只能"尽力"解析；
    解析不到一律返回 ``None``，不影响埋点写入。

    Args:
        db: SQLAlchemy 会话。
        question: 题目 ORM 对象。
        knowledge_point_id: 已反查到的主知识点 ID（可空）。

    Returns:
        章节对应的 ``knowledge_points.id``，解析不到返回 ``None``。
    """
    try:
        chapter_text: Optional[str] = None
        # 1) 优先看已关联知识点自身的 chapter 文本
        if knowledge_point_id is not None:
            kp = (
                db.query(KnowledgePoint)
                .filter(KnowledgePoint.id == knowledge_point_id)
                .first()
            )
            if kp is not None and kp.chapter:
                chapter_text = kp.chapter
        # 2) 回退到题目自身的 chapter 文本
        if not chapter_text:
            chapter_text = getattr(question, "chapter", None)
        if not chapter_text:
            return None

        # 在同科目下找 chapter 文本一致的知识点，取其 id 作为"章节 ID"
        q = db.query(KnowledgePoint).filter(KnowledgePoint.chapter == chapter_text)
        if question.subject:
            q = q.filter(KnowledgePoint.subject == question.subject)
        row = q.order_by(KnowledgePoint.id.asc()).first()
        return row.id if row is not None else None
    except Exception:  # pragma: no cover - 章节解析失败不影响埋点
        return None


@router.post("/submit")
async def submit_answer(submission: QuizSubmit, db: Session = Depends(get_db)):
    """提交答案（记录答题历史，答错自动入错题本）。"""
    question = db.query(QuizQuestion).filter(QuizQuestion.id == submission.question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    # V12 置信度分级：低置信答案（LLM 生成/缺失）不参与自动判分，
    # 仅记录作答流水，返回 needs_review 交前端提示「答案待人工核对」。
    low_confidence = getattr(question, "answer_confidence", 1.0) is not None and \
        getattr(question, "answer_confidence", 1.0) < 0.8

    correct = False
    if question.answer and not low_confidence:
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
    )
    db.add(record)

    # 答错自动加入错题本（低置信题不判错——答案本身可能不可靠）
    error = None
    if not correct and not low_confidence:
        error = ErrorRecord(
            question_id=question.id,
            content=question.content,
            my_answer=submission.my_answer,
            correct_answer=question.answer,
            error_reason="答题错误",
            subject=question.subject,
            status="active",
            # V12 同族修复：新错题首入库按掌握度排首次复习（≥1 天），
            # 不再 20 分钟后即当日到期、当天全部涌入"今日复习队列"。
            next_review=ReviewScheduler.first_review_at(),
        )
        db.add(error)

    db.commit()

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

    # —— M5-1：学习行为埋点（旁路，容错，绝不影响答题响应结构）—— #
    # 判分完成后写入一条 study_events，供后续学习科学分析消费。
    # 反查知识点：经 question_knowledge_links 取主知识点（role='primary' 优先）。
    try:
        from services.study_event_service import record_event, resolve_knowledge_point_id

        kp_id = resolve_knowledge_point_id(db, question.id)
        chapter_id = _resolve_chapter_id(db, question, kp_id)
        record_event(
            db,
            "answer",
            subject=question.subject,
            question_id=question.id,
            knowledge_point_id=kp_id,
            chapter_id=chapter_id,
            is_correct=correct,
            duration_seconds=submission.cost_seconds or None,
            payload={
                "mode": submission.mode,
                "my_answer": submission.my_answer,
                "question_type": question.question_type,
                "difficulty": question.difficulty,
            },
        )
    except Exception as exc:  # pragma: no cover - 埋点异常绝不影响答题
        import logging

        logging.getLogger(__name__).warning("submit_answer 埋点异常（已忽略）: %s", exc)

    return {
        "question_id": question.id,
        "correct": correct,
        "needs_review": low_confidence,
        "correct_answer": question.answer,
        "analysis": question.analysis,
        "record_id": record.id,
    }


@router.get("/stats")
async def quiz_stats(
    include_junk: bool = Query(False, description="是否包含 OCR 碎片题；默认排除，与列表端点口径一致"),
    db: Session = Depends(get_db),
):
    """答题统计（基于真实答题记录计算正确率）。

    M1-1f/g：`total_questions` 与 `subject_distribution` 默认**排除 OCR 碎片题**
    （`is_junk=1`），与 `GET /questions` 的口径保持一致，避免"题库总数 9171
    但可刷 8852"的前端不一致。传 `include_junk=true` 可见全量。
    """
    # M1-1h：统一走共享过滤，避免口径漂移
    from services.quiz_query import visible_quiz_filter

    def _visible(q):
        return visible_quiz_filter(q, include_junk=include_junk)

    from sqlalchemy import func

    total_questions = _visible(db.query(QuizQuestion)).count()
    total_errors = db.query(ErrorRecord).filter(ErrorRecord.status == "active").count()
    graduated_errors = db.query(ErrorRecord).filter(ErrorRecord.status == "graduated").count()

    # 真实正确率 = 答对次数 / 答题总次数
    total_attempts = db.query(AnswerRecord).count()
    correct_attempts = db.query(AnswerRecord).filter(AnswerRecord.is_correct == True).count()  # noqa: E712
    accuracy_rate = round(correct_attempts / total_attempts * 100, 1) if total_attempts else 0

    # 各科目答题正确率
    subject_rows = (
        db.query(
            AnswerRecord.subject,
            func.count(AnswerRecord.id),
            func.sum(AnswerRecord.is_correct.cast(Integer)),
        )
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

    # 各科目题目数（默认排除碎片题，与 total_questions 同口径）
    subject_counts = (
        _visible(db.query(QuizQuestion.subject, func.count(QuizQuestion.id)))
        .group_by(QuizQuestion.subject)
        .all()
    )

    return {
        "total_questions": total_questions,
        "total_attempts": total_attempts,
        "active_errors": total_errors,
        "graduated_errors": graduated_errors,
        "accuracy_rate": accuracy_rate,
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
    """
    content = (q.get("content") or "").strip()
    options = q.get("options")
    if options is None:
        options = []
    return {
        "index": index,
        "content": content,
        "options": options,
        "answer": q.get("answer"),
        "analysis": q.get("analysis"),
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
    """把候选题 dict 转换为 QuizQuestion 构造字段（剔除 index 等非列字段）。"""
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
    }


def _build_paste_candidates(text: str, db: Session, is_retest: bool) -> tuple:
    """解析 Markdown 文本 → 自动分类 → 返回 (候选题列表, 分类统计)，**不落库**。

    这是 M6-4「预览/确认」闭环的公共入口：``dry_run=True`` 直接返回它；
    ``confirm`` 端点也复用它对「原始文本」做一次性重解析。

    分类统计来自 quiz_autoclassify.autoclassify 的真实返回值，保证与旧响应一致。
    """
    questions = _parse_markdown_questions(text)
    if not questions:
        return [], {"classified": 0, "by_rules": 0, "by_llm": 0, "ai_generated": 0}

    from services.quiz_autoclassify import autoclassify

    # 自动分类：缺 subject/question_type/knowledge_point 时用规则+LLM 兜底。
    classify_stats = autoclassify(questions, use_llm=True, db=db)

    candidates = []
    for i, q in enumerate(questions):
        # 解析出的题干若未标 is_retest，则由调用方参数统一指定初试/复试。
        q.setdefault("is_retest", is_retest)
        candidates.append(_normalize_candidate(q, i))
    return candidates, classify_stats


@router.post("/import/markdown")
async def import_markdown(payload: dict, db: Session = Depends(get_db)):
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
    candidates, rejected_by_gate = _gate_rows(candidates)
    count = 0
    for cand in candidates:
        db.add(QuizQuestion(**_candidate_to_model_fields(cand)))
        count += 1
    db.commit()
    msg = f"成功导入 {count} 道题目"
    if rejected_by_gate:
        msg += f"（闸门拦截 {sum(rejected_by_gate.values())} 道）"
    if classify_stats["classified"]:
        msg += f"（自动分类 {classify_stats['classified']}：规则 {classify_stats['by_rules']}/AI {classify_stats['by_llm']}）"
    return {
        "imported": count,
        "rejected": sum(rejected_by_gate.values()),
        "rejected_by_gate": rejected_by_gate,
        "classify": classify_stats,
        "message": msg,
    }


@router.post("/import/confirm")
async def import_confirm(payload: dict, db: Session = Depends(get_db)):
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

    ids = []
    for i, raw in enumerate(candidates):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"第 {i} 个候选题格式非法（应为对象）")
        cand = _normalize_candidate(raw, i)
        if not cand["content"]:
            raise HTTPException(status_code=400, detail=f"第 {i} 个候选题缺少 content")
        # 前端若未显式带 is_retest，则以顶层 is_retest 为准。
        if "is_retest" not in raw:
            cand["is_retest"] = is_retest
        obj = QuizQuestion(**_candidate_to_model_fields(cand))
        db.add(obj)
        db.flush()  # 取回自增 id，供响应返回
        ids.append(obj.id)
    db.commit()
    return {"imported": len(ids), "ids": ids, "message": f"已确认落库 {len(ids)} 道题目"}


@router.get("/retest/stats")
async def retest_stats(db: Session = Depends(get_db)):
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


@router.post("/extract-knowledge-points")
async def extract_knowledge_from_text(payload: dict, db: Session = Depends(get_db)):
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
async def quiz_subjects(db: Session = Depends(get_db)):
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

    # 各科目「可作答」题数（M0）：默认列表只返回可作答题，此处给出同口径计数，
    # 让前端科目卡片能显示「可作答 N」，与实际能刷的题数一致（避免显示 0 却被引导去练习）。
    from services.quiz_query import visible_quiz_filter

    avail_rows = (
        visible_quiz_filter(
            db.query(QuizQuestion.subject, func.count(QuizQuestion.id)),
            include_junk=False,
        )
        .filter(_answerable_expr())
        .group_by(QuizQuestion.subject)
        .all()
    )
    answerable_map = {(s or "未分类"): int(c or 0) for s, c in avail_rows}

    # 逐项带出 subject/question_count/error_count，保持既有契约
    items = [
        {
            "subject": s["subject"],
            "question_count": s["question_count"],
            "answerable_count": answerable_map.get(s["subject"], 0),
            "error_count": s["error_count"],
        }
        for s in data
    ]
    # 兼容旧排序：题目数降序（字典项 question_count=0 会自然沉底）
    items.sort(key=lambda it: (-it["question_count"], it["subject"]))
    return {
        "total": len(items),
        # 全库可作答题总数（各科目求和）：前端「可作答 N 题」的总数口径
        "answerable_total": sum(it["answerable_count"] for it in items),
        "items": items,
    }


@router.get("/sections")
async def quiz_sections(
    subject: Optional[str] = None,
    include_junk: bool = Query(False, description="是否包含 OCR 碎片题；默认排除，口径同列表"),
    db: Session = Depends(get_db),
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
        .filter(ErrorRecord.status == "active")
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
):
    """错因汇总：活跃错题的错误原因分布（错题闭环第一环）。"""
    from sqlalchemy import func
    q = db.query(ErrorRecord.error_reason, func.count(ErrorRecord.id))
    if subject:
        q = q.filter(ErrorRecord.subject == subject)
    q = q.filter(ErrorRecord.status == "active", ErrorRecord.error_reason.isnot(None))
    rows = q.group_by(ErrorRecord.error_reason).order_by(func.count(ErrorRecord.id).desc()).limit(limit).all()
    return {"total": len(rows), "items": [{"reason": r or "未填错因", "count": c} for r, c in rows]}


@router.get("/weak-points")
async def quiz_weak_points(
    subject: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
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
        .filter(ErrorRecord.status == "active")
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
