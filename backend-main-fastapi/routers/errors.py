"""错题路由。"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db
from models import ErrorRecord, QuizQuestion
from schemas import ErrorRecordCreate, ErrorRecordUpdate, GenericResponse
from services.review_scheduler import ReviewScheduler
from services import review_service  # SM-2 变体排程（AI 分析后的下次复习）
from services.ocr_service import OCRService
from utils.timeutil import utcnow  # 统一 naive UTC 时间规范（P0-4）

router = APIRouter(prefix="/api/errors", tags=["errors"])


@router.get("")
async def list_errors(
    subject: Optional[str] = None,
    error_reason: Optional[str] = None,
    tag: Optional[str] = None,
    status: Optional[str] = None,
    mastery_state: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """错题列表（支持筛选）。

    ``mastery_state`` 按掌握度**三态**筛选（unlearned 未学 / weak 薄弱 /
    mastered 已掌握），与 ``services/kp_mastery.error_mastery_state`` 同一口径；
    每条也回带 ``mastery_state`` / ``mastery_label``，前端不再自行写死档位。
    """
    from services import kp_mastery

    query = db.query(ErrorRecord)
    if subject:
        query = query.filter(ErrorRecord.subject == subject)
    if error_reason:
        query = query.filter(ErrorRecord.error_reason == error_reason)
    if status:
        query = query.filter(ErrorRecord.status == status)
    if tag:
        query = query.filter(ErrorRecord.tags.like(f'%"{tag}"%'))
    if mastery_state:
        from services import error_linker

        cond = error_linker.mastery_state_condition(mastery_state)
        if cond is not None:
            query = query.filter(cond)

    total = query.count()
    errors = (
        query.order_by(ErrorRecord.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    def _row(e: ErrorRecord) -> dict:
        state = kp_mastery.error_mastery_state(e.accuracy, e.review_count, e.status)
        return {
            "id": e.id,
            "question_id": e.question_id,
            "content": e.content,
            "my_answer": e.my_answer,
            "correct_answer": e.correct_answer,
            "error_reason": e.error_reason,
            "subject": e.subject,
            "accuracy": e.accuracy,
            "review_count": e.review_count,
            "last_review": e.last_review.isoformat() if e.last_review else None,
            "next_review": e.next_review.isoformat() if e.next_review else None,
            "status": e.status,
            "mastery_state": state,
            "mastery_label": kp_mastery.STATE_LABELS.get(state, state),
            "tags": e.tags,
            "analysis": e.analysis,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": [_row(e) for e in errors],
    }


@router.get("/stats")
async def error_stats(subject: Optional[str] = None, db: Session = Depends(get_db)):
    """错题统计（**唯一口径**，错题本 / 错题复盘 / 仪表盘共用）。

    与 ``services/error_linker.error_stats`` 同一实现：
    total / active_errors / due_errors / graduated_errors / archived_errors /
    today_reviews / total_reviews / error_reviews + 三态计数。
    """
    from services import error_linker

    return error_linker.error_stats(db, subject=subject)


@router.post("")
async def add_error(error: ErrorRecordCreate, db: Session = Depends(get_db)):
    """添加错题，并自动关联到知识库知识点。"""
    from services import error_linker

    new_error = ErrorRecord(**error.model_dump())
    if not new_error.next_review:
        # V12 同族修复：新错题首入库按掌握度排首次复习（≥1 天），
        # 不再用 ebinghaus_next_review(0)（20 分钟后即当日到期）——
        # 那会让新错题当天全部涌入"今日复习队列"。
        new_error.next_review = ReviewScheduler.first_review_at(new_error.accuracy)
    db.add(new_error)
    db.commit()
    db.refresh(new_error)

    # 错题本 ↔ 知识库联动：收录即挂考点，避免"错题孤岛"
    linked = []
    try:
        linked = error_linker.auto_link_error(db, new_error, top_k=3)
    except Exception as e:  # 联动失败不影响错题本身入库
        print(f"[error_linker] 错题 {new_error.id} 自动关联失败: {e}")

    return {
        "id": new_error.id,
        "message": "错题添加成功",
        "linked_knowledge_points": linked,
    }


@router.get("/{error_id}/knowledge-points")
async def error_knowledge_points(error_id: int, db: Session = Depends(get_db)):
    """这道错题考的知识点（含掌握度、章节、题型）。"""
    from services import error_linker

    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first()
    if not db_error:
        raise HTTPException(status_code=404, detail="错题不存在")
    return {"error_id": error_id, "items": error_linker.knowledge_points_of_error(db, error_id)}


@router.post("/{error_id}/link-knowledge")
async def link_error_knowledge(error_id: int, payload: dict, db: Session = Depends(get_db)):
    """手动指定错题关联的知识点。

    body: {knowledge_point_id: int} 或 {auto: true} 重新自动关联
    """
    from services import error_linker

    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first()
    if not db_error:
        raise HTTPException(status_code=404, detail="错题不存在")

    if payload.get("auto"):
        items = error_linker.auto_link_error(db, db_error, top_k=int(payload.get("top_k") or 3))
        return {"message": "已重新自动关联", "items": items}

    kp_id = payload.get("knowledge_point_id")
    if kp_id is None:
        raise HTTPException(status_code=400, detail="缺少 knowledge_point_id（或传 auto:true）")
    try:
        return error_linker.link_manually(db, error_id, int(kp_id))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/links/{link_id}")
async def unlink_error_knowledge(link_id: int, db: Session = Depends(get_db)):
    """解除一条错题↔知识点关联。"""
    from services import error_linker

    if not error_linker.unlink(db, link_id):
        raise HTTPException(status_code=404, detail="关联不存在")
    return {"message": "关联已解除"}



@router.put("/{error_id}")
async def update_error(error_id: int, error: ErrorRecordUpdate, db: Session = Depends(get_db)):
    """更新错题。"""
    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first()
    if not db_error:
        raise HTTPException(status_code=404, detail="错题不存在")

    update_data = error.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_error, key, value)

    db.commit()
    return {"id": db_error.id, "message": "错题更新成功"}


@router.delete("/{error_id}")
async def delete_error(error_id: int, db: Session = Depends(get_db)):
    """删除错题（连带清理它与知识点的关联，避免外键约束失败）。"""
    from models import ErrorKnowledgeLink

    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first()
    if not db_error:
        raise HTTPException(status_code=404, detail="错题不存在")

    # 先删关联：error_knowledge_links.error_id 有外键约束，
    # 不先清理会直接 IntegrityError（500）。
    removed_links = db.query(ErrorKnowledgeLink).filter(
        ErrorKnowledgeLink.error_id == error_id
    ).delete(synchronize_session=False)

    db.delete(db_error)
    db.commit()
    return {"message": "错题已删除", "removed_links": removed_links}


@router.post("/{error_id}/graduate")
async def graduate_error(error_id: int, db: Session = Depends(get_db)):
    """标记毕业移出。"""
    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first()
    if not db_error:
        raise HTTPException(status_code=404, detail="错题不存在")

    db_error.status = "graduated"
    db.commit()
    return {"id": db_error.id, "status": "graduated", "message": "错题已毕业移出"}


@router.post("/ocr")
async def ocr_recognize(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """OCR 识别错题。"""
    import os
    import tempfile

    # 限制文件大小 20MB（图片）
    MAX_IMG_SIZE = 20 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_IMG_SIZE:
        raise HTTPException(status_code=413, detail=f"图片过大，最大支持 {MAX_IMG_SIZE // (1024*1024)}MB")

    suffix = os.path.splitext(file.filename or "upload.png")[1] or ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        ocr = OCRService()
        text = await ocr.recognize(tmp_path)
        questions = ocr.extract_questions(text)
        return {
            "raw_text": text,
            "questions": questions,
            "count": len(questions),
        }
    finally:
        os.unlink(tmp_path)


@router.post("/{error_id}/ai-analyze")
async def ai_analyze_error(error_id: int, db: Session = Depends(get_db)):
    """AI 深度分析错题（A8 四段式错因分析：错因分类→归因→对策→复练）。"""
    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id).first()
    if not db_error:
        raise HTTPException(status_code=404, detail="错题不存在")

    try:
        from services.error_analyzer import analyze_error

        result = analyze_error(db, error_id, use_llm=True)
        if result.get("error"):
            raise RuntimeError(result["message"])
        db_error.analysis = result["analysis"]
        db_error.last_review = utcnow()  # naive UTC，与 DB 列对齐（P0-4）
        db_error.review_count = (db_error.review_count or 0) + 1
        # V12 同族修复：AI 分析也是一次复习，首次复习后排程同样不能落到
        # 20 分钟后（ebinghaus_next_review(0)）——否则新错题分析完立刻
        # 又算"今日到期"。改用 SM-2 变体：首复习 +1 天，之后逐级拉长。
        _, _, nxt = review_service.next_review_at(
            review_count=db_error.review_count - 1,
            ease_factor=2.5,
            interval=0,
            result="fuzzy",
        )
        db_error.next_review = nxt
        db.commit()
        return {
            "analysis": result["analysis"],
            "message": "AI 分析完成",
            "category": result.get("category", ""),
            "knowledge_point_id": result.get("knowledge_point_id"),
            "knowledge_point": result.get("knowledge_point", ""),
            "suggestion": result.get("suggestion", ""),
            "practice_questions": result.get("practice_questions", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 分析失败：{str(e)}")
