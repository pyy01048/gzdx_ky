"""刷题路由。"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from database import get_db
from models import QuizQuestion, ErrorRecord, AnswerRecord
from schemas import QuizQuestionCreate, QuizQuestionUpdate, QuizSubmit, GenericResponse
from services.review_scheduler import ReviewScheduler

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


@router.get("/questions")
async def list_questions(
    subject: Optional[str] = None,
    chapter: Optional[str] = None,
    difficulty: Optional[int] = None,
    source: Optional[str] = None,
    question_type: Optional[str] = None,
    mode: Optional[str] = None,
    q: Optional[str] = None,
    year: Optional[int] = None,
    paper: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """题目列表（支持筛选与刷题模式）。

    新增筛选：
    - q：题干/解析关键词模糊搜索（修复题库管理页搜索框无效的问题）
    - year：按真题年份（回填后的 year 列）
    - paper：按真题套卷名（回填后的 paper 列）；配合 mode=sequential 得到套卷内题号顺序
    """
    from sqlalchemy import func, or_

    query = db.query(QuizQuestion)
    if subject:
        query = query.filter(QuizQuestion.subject == subject)
    if chapter:
        query = query.filter(QuizQuestion.chapter == chapter)
    if difficulty:
        query = query.filter(QuizQuestion.difficulty == difficulty)
    if source:
        query = query.filter(QuizQuestion.source == source)
    if question_type:
        query = query.filter(QuizQuestion.question_type == question_type)
    if year:
        query = query.filter(QuizQuestion.year == year)
    if paper:
        query = query.filter(QuizQuestion.paper == paper)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                QuizQuestion.content.like(like),
                QuizQuestion.analysis.like(like),
                QuizQuestion.knowledge_point.like(like),
            )
        )

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
            from sqlalchemy import or_
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
                "weakness_knowledge_points": weakness_kps,
                "questions": [_serialize_question(q) for q in questions],
            }

    total = query.count()

    # 随机模式
    if mode == "random":
        questions = query.order_by(func.random()).limit(page_size).all()
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "mode": mode,
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
        "questions": [_serialize_question(q) for q in questions],
    }


def _serialize_question(q):
    """题目序列化。"""
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
        "year": getattr(q, "year", None),
        "paper": getattr(q, "paper", None),
        "question_no": getattr(q, "question_no", None),
    }


@router.get("/papers-index")
async def papers_index(
    subject: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """真题套卷索引（对标 gitgraduate「真题专项训练体系」）。

    返回每份真题套卷的题数、涉及科目、年份（若有）。前端据此渲染套卷列表，
    点击某套卷 → /questions?paper=xxx&mode=sequential 得到题号网格。
    诚实口径：paper 来自 source 文档名回填，question_no 为套卷内录入顺序号。
    """
    from sqlalchemy import func

    query = db.query(
        QuizQuestion.paper,
        func.count(QuizQuestion.id),
        func.min(QuizQuestion.year),
        func.max(QuizQuestion.year),
    ).filter(QuizQuestion.paper.isnot(None))
    if subject:
        query = query.filter(QuizQuestion.subject == subject)
    rows = query.group_by(QuizQuestion.paper).order_by(func.count(QuizQuestion.id).desc()).all()

    # 每份套卷的科目分布（一次查回，避免 N+1）
    subj_query = db.query(QuizQuestion.paper, QuizQuestion.subject, func.count(QuizQuestion.id))
    subj_query = subj_query.filter(QuizQuestion.paper.isnot(None))
    if subject:
        subj_query = subj_query.filter(QuizQuestion.subject == subject)
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
async def years_index(db: Session = Depends(get_db)):
    """年份 × 科目 聚合（对标 gitgraduate「按年份浏览」）。

    仅统计 year 非空的题目（回填自真题文档名，无歧义年份）。
    返回：每个年份下各科目的题数，供「年→科目→题号网格」渲染。
    诚实口径：只覆盖能可靠解析年份的真题子集，不伪造年份。
    """
    from sqlalchemy import func

    rows = (
        db.query(QuizQuestion.year, QuizQuestion.subject, func.count(QuizQuestion.id))
        .filter(QuizQuestion.year.isnot(None))
        .group_by(QuizQuestion.year, QuizQuestion.subject)
        .all()
    )
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


@router.post("/questions")
async def add_question(question: QuizQuestionCreate, db: Session = Depends(get_db)):
    """添加题目。"""
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

    count = 0
    classify_stats = None
    if auto_classify and questions:
        payloads = [q.model_dump() for q in questions]
        classify_stats = autoclassify(payloads, use_llm=True, db=db)
        for p in payloads:
            db.add(QuizQuestion(**p))
        count = len(payloads)
    else:
        for q in questions:
            db.add(QuizQuestion(**q.model_dump()))
        count = len(questions)
    db.commit()
    msg = f"成功导入 {count} 道题目"
    if classify_stats and classify_stats["classified"]:
        msg += f"（自动分类 {classify_stats['classified']}：规则 {classify_stats['by_rules']}/AI {classify_stats['by_llm']}）"
    return {"imported": count, "classify": classify_stats, "message": msg}


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
    if not correct and not low_confidence:
        error = ErrorRecord(
            question_id=question.id,
            content=question.content,
            my_answer=submission.my_answer,
            correct_answer=question.answer,
            error_reason="答题错误",
            subject=question.subject,
            status="active",
            next_review=ReviewScheduler.ebinghaus_next_review(0),
        )
        db.add(error)

    db.commit()

    return {
        "question_id": question.id,
        "correct": correct,
        "needs_review": low_confidence,
        "correct_answer": question.answer,
        "analysis": question.analysis,
        "record_id": record.id,
    }


@router.get("/stats")
async def quiz_stats(db: Session = Depends(get_db)):
    """答题统计（基于真实答题记录计算正确率）。"""
    total_questions = db.query(QuizQuestion).count()
    total_errors = db.query(ErrorRecord).filter(ErrorRecord.status == "active").count()
    graduated_errors = db.query(ErrorRecord).filter(ErrorRecord.status == "graduated").count()

    # 真实正确率 = 答对次数 / 答题总次数
    total_attempts = db.query(AnswerRecord).count()
    correct_attempts = db.query(AnswerRecord).filter(AnswerRecord.is_correct == True).count()  # noqa: E712
    accuracy_rate = round(correct_attempts / total_attempts * 100, 1) if total_attempts else 0

    # 各科目答题正确率
    from sqlalchemy import func
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

    # 各科目题目数
    subject_counts = (
        db.query(QuizQuestion.subject, func.count(QuizQuestion.id))
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


@router.post("/import/markdown")
async def import_markdown(payload: dict, db: Session = Depends(get_db)):
    """从 Markdown 文本导入题目。请求体：{"text": "...markdown...", "auto_classify": true}

    T3：解析出的题目缺 subject/question_type/knowledge_point 时自动判定（规则+LLM兜底）。
    """
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="内容为空")

    questions = _parse_markdown_questions(text)
    if not questions:
        raise HTTPException(status_code=400, detail="未解析到任何题目，请检查 Markdown 格式")

    from services.quiz_autoclassify import autoclassify

    classify_stats = autoclassify(questions, use_llm=True, db=db)
    count = 0
    for q in questions:
        db.add(QuizQuestion(**q))
        count += 1
    db.commit()
    msg = f"成功导入 {count} 道题目"
    if classify_stats["classified"]:
        msg += f"（自动分类 {classify_stats['classified']}：规则 {classify_stats['by_rules']}/AI {classify_stats['by_llm']}）"
    return {"imported": count, "classify": classify_stats, "message": msg}


@router.get("/subjects")
async def quiz_subjects(db: Session = Depends(get_db)):
    """分项导航：各科目题目数与活跃错题数。"""
    from sqlalchemy import func
    rows = (
        db.query(QuizQuestion.subject, func.count(QuizQuestion.id))
        .filter(QuizQuestion.subject.isnot(None))
        .group_by(QuizQuestion.subject)
        .order_by(func.count(QuizQuestion.id).desc())
        .all()
    )
    err_rows = (
        db.query(ErrorRecord.subject, func.count(ErrorRecord.id))
        .filter(ErrorRecord.subject.isnot(None), ErrorRecord.status == "active")
        .group_by(ErrorRecord.subject)
        .all()
    )
    err_map = dict(err_rows)
    return {
        "total": len(rows),
        "items": [
            {"subject": s or "未分类", "question_count": c, "error_count": err_map.get(s, 0)}
            for s, c in rows
        ],
    }


@router.get("/sections")
async def quiz_sections(
    subject: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """分项列表：指定科目（或全部）下的章节分布。"""
    from sqlalchemy import func
    q = db.query(QuizQuestion.chapter, func.count(QuizQuestion.id))
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
