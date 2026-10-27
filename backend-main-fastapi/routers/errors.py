"""错题路由。"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import User
from utils.scope import owner_id, scoped  # B4 行级隔离
from utils.security import current_user
from models import ErrorKnowledgeLink, ErrorRecord, QuizQuestion
from schemas import ErrorRecordCreate, ErrorRecordUpdate, GenericResponse
from services.review_scheduler import ReviewScheduler
from services.ocr_service import OCRService
from utils.timeutil import local_today, utcnow  # 统一 naive UTC 时间规范（P0-4）

from utils.response import MAX_PAGE_SIZE

router = APIRouter(prefix="/api/errors", tags=["errors"])


@router.get("")
async def list_errors(
    subject: Optional[str] = None,
    error_reason: Optional[str] = None,
    tag: Optional[str] = None,
    status: Optional[str] = None,
    mastery_state: Optional[str] = None,
    knowledge_point_id: Optional[int] = None,
    page: int = 1,
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """错题列表（支持筛选，B4：只看本人错题）。

    ``mastery_state`` 按掌握度**三态**筛选（unlearned 未学 / weak 薄弱 /
    mastered 已掌握），与 ``services/kp_mastery.error_mastery_state`` 同一口径；
    每条也回带 ``mastery_state`` / ``mastery_label``，前端不再自行写死档位。

    ``knowledge_point_id`` 按挂接的知识点筛选，走 ``error_knowledge_links``
    （唯一关联表，口径同 ``error_linker.weak_knowledge_points``）。仪表盘首屏的
    薄弱知识点 Top3 就靠它跳到「这个考点下我错的那几道」。
    用 ``IN (select…)`` 而不是 join：join 会把这个筛选条件带进 ``query.count()``，
    计数与列表走两条不同 SQL 时容易分叉出「total 与 items 长度不一致」。
    """
    from services import kp_mastery

    query = db.query(ErrorRecord).filter(scoped(ErrorRecord, user))
    if subject:
        query = query.filter(ErrorRecord.subject == subject)
    if error_reason:
        query = query.filter(ErrorRecord.error_reason == error_reason)
    if status:
        query = query.filter(ErrorRecord.status == status)
    if tag:
        query = query.filter(ErrorRecord.tags.like(f'%"{tag}"%'))
    if knowledge_point_id is not None:
        query = query.filter(
            ErrorRecord.id.in_(
                select(ErrorKnowledgeLink.error_id)
                .where(ErrorKnowledgeLink.knowledge_point_id == knowledge_point_id)
            )
        )
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
async def error_stats(subject: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """错题统计（**唯一口径**，错题本 / 错题复盘 / 仪表盘共用）。

    与 ``services/error_linker.error_stats`` 同一实现：
    total / active_errors / due_errors / graduated_errors / archived_errors /
    today_reviews / total_reviews / error_reviews + 三态计数。

    性能优化（2026-10）：套 3 秒 TTL 内存缓存（``services/stats_cache``）——
    前端仪表盘/错题本会轮询本端点，重复轮询不再反复打 12 条聚合 count。
    缓存 key 含 subject；pytest 环境下自动禁用（测试隔离铁律）。
    """
    from services import error_linker
    from services.stats_cache import cached

    return cached(
        f"errors/stats:{subject or ''}:u{owner_id(user)}",  # B4：缓存 key 带用户维度
        lambda: error_linker.error_stats(db, subject=subject),
    )


@router.post("")
async def add_error(error: ErrorRecordCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """添加错题，并自动关联到知识库知识点。"""
    from services import error_linker

    new_error = ErrorRecord(**error.model_dump())
    new_error.user_id = owner_id(user)  # B4：归属当前用户
    # 错因自动判定：用户没写 category 时按可观测信号补一个（可后续改写/AI 覆盖）。
    if not getattr(new_error, "error_category", None):
        try:
            from services.error_analyzer import infer_error_category

            new_error.error_category = infer_error_category(
                my_answer=new_error.my_answer,
                correct_answer=new_error.correct_answer,
            )
        except Exception:  # noqa: BLE001 - 判因失败不影响错题入库
            pass
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
async def error_knowledge_points(error_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """这道错题考的知识点（含掌握度、章节、题型）。"""
    from services import error_linker

    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id, scoped(ErrorRecord, user)).first()
    if not db_error:
        raise HTTPException(status_code=404, detail="错题不存在")
    return {"error_id": error_id, "items": error_linker.knowledge_points_of_error(db, error_id)}


@router.post("/{error_id}/link-knowledge")
async def link_error_knowledge(error_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """手动指定错题关联的知识点。

    body: {knowledge_point_id: int} 或 {auto: true} 重新自动关联
    """
    from services import error_linker

    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id, scoped(ErrorRecord, user)).first()
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
async def unlink_error_knowledge(link_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """解除一条错题↔知识点关联。

    B4 间接隔离：error_knowledge_links 不落 user_id，
    先按本人错题校验该 link 的归属，查不到一律 404。
    """
    from services import error_linker

    link = db.query(ErrorKnowledgeLink).filter(ErrorKnowledgeLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="关联不存在")
    parent = db.query(ErrorRecord).filter(
        ErrorRecord.id == link.error_id, scoped(ErrorRecord, user)
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="关联不存在")
    if not error_linker.unlink(db, link_id):
        raise HTTPException(status_code=404, detail="关联不存在")
    return {"message": "关联已解除"}



@router.put("/{error_id}")
async def update_error(error_id: int, error: ErrorRecordUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """更新错题。"""
    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id, scoped(ErrorRecord, user)).first()
    if not db_error:
        raise HTTPException(status_code=404, detail="错题不存在")

    update_data = error.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_error, key, value)

    db.commit()
    return {"id": db_error.id, "message": "错题更新成功"}


@router.delete("/{error_id}")
async def delete_error(error_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """删除错题（连带清理它与知识点的关联，避免外键约束失败）。"""
    from models import ErrorKnowledgeLink

    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id, scoped(ErrorRecord, user)).first()
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
async def graduate_error(error_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """标记毕业移出。"""
    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id, scoped(ErrorRecord, user)).first()
    if not db_error:
        raise HTTPException(status_code=404, detail="错题不存在")

    db_error.status = "graduated"
    db.commit()
    return {"id": db_error.id, "status": "graduated", "message": "错题已毕业移出"}


@router.post("/ocr")
async def ocr_recognize(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
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
        # P0-2：recognize() 是**同步**函数（内部跑 ONNX 推理，可达数秒）。
        # 原实现写成 `await ocr.recognize(...)` 会直接
        # `TypeError: object str can't be used in 'await' expression` → 500；
        # 即便它是协程，在 async 端点里同步跑推理也会按住整个事件循环。
        # 挪到线程池：本请求自己等，别的连接不受影响。
        from starlette.concurrency import run_in_threadpool

        text = await run_in_threadpool(ocr.recognize, tmp_path)
        questions = ocr.extract_questions(text)
        return {
            "raw_text": text,
            "questions": questions,
            "count": len(questions),
        }
    finally:
        os.unlink(tmp_path)


@router.get("/export-pdf")
async def export_errors_pdf(
    subject: Optional[str] = None,
    status: Optional[str] = None,
    tag: Optional[str] = None,
    mastery_state: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """错题本 PDF 导出（对标「不背单词」纸质导出；B4：仅导出本人错题）。

    支持与列表页一致的筛选参数（subject / status / tag / mastery_state），
    导出结果为中文 PDF，前端直接以 blob 下载。
    """
    from fastapi.responses import Response
    from services import pdf_export

    query = db.query(ErrorRecord).filter(scoped(ErrorRecord, user))
    if subject:
        query = query.filter(ErrorRecord.subject == subject)
    if status:
        query = query.filter(ErrorRecord.status == status)
    if tag:
        query = query.filter(ErrorRecord.tags.like(f'%"{tag}"%'))
    if mastery_state:
        from services import error_linker

        cond = error_linker.mastery_state_condition(mastery_state)
        if cond is not None:
            query = query.filter(cond)

    rows = query.order_by(ErrorRecord.created_at.desc()).limit(500).all()

    from services import kp_mastery

    errors = []
    for e in rows:
        state = kp_mastery.error_mastery_state(e.accuracy, e.review_count, e.status)
        errors.append({
            "content": e.content,
            "my_answer": e.my_answer,
            "correct_answer": e.correct_answer,
            "error_reason": e.error_reason,
            "error_category": e.error_category,
            "subject": e.subject,
            "accuracy": e.accuracy,
            "review_count": e.review_count,
            "status": e.status,
            "mastery_label": kp_mastery.STATE_LABELS.get(state, state),
            "tags": e.tags,
            "analysis": e.analysis,
        })

    pdf_bytes = pdf_export.build_errors_pdf(
        errors,
        title="考研错题本",
        subtitle="按艾宾浩斯遗忘曲线自动排期复习 · 导出自考研备考平台",
    )
    filename = f"错题本_{local_today().isoformat()}.pdf"
    # RFC 5987 编码文件名，保证中文文件名在浏览器中正常显示
    from urllib.parse import quote
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.post("/{error_id}/ai-analyze")
async def ai_analyze_error(error_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """AI 深度分析错题（A8 四段式错因分析：错因分类→归因→对策→复练）。"""
    db_error = db.query(ErrorRecord).filter(ErrorRecord.id == error_id, scoped(ErrorRecord, user)).first()
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
        # AI 分析也是一次「想起了但吃力」的复习（FSRS rating=2 Hard）。
        # 统一走 review_schedules，避免与 SM-2 各排各的。
        from services.srs import fsrs

        sched = fsrs.schedule(
            db,
            item_type="error_record",
            item_id=int(db_error.id),
            rating=2,
            user_id=owner_id(user),  # B4：复习排程跟随操作者
            commit=False,
        )
        db_error.next_review = datetime.datetime.fromisoformat(sched["due"])
        db_error.interval_days = int(sched["interval_days"])
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
