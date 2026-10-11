# -*- coding: utf-8 -*-
"""复习进度追踪路由。

前端「复习进度」面板消费这里的数据：今天该复习什么、复习完掌握度怎么变、
整体复习到哪一步了。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import ErrorRecord, ReviewRecord
from services import review_service, error_linker, taxonomy

router = APIRouter(prefix="/api/review", tags=["复习进度"])


@router.get("/due")
async def due_list(
    subject: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    include_new: bool = Query(True, description="是否包含从未复习过的新知识点"),
    db: Session = Depends(get_db),
):
    """今日复习队列（逾期越久、掌握度越低越靠前）。"""
    items = review_service.due_items(db, subject=subject, limit=limit, include_new=include_new)
    return {
        "total": len(items),
        "subject": taxonomy.normalize_subject(subject) if subject else None,
        "items": items,
    }


@router.post("/submit")
async def submit_review(payload: dict, db: Session = Depends(get_db)):
    """提交一次复习结果，回写掌握度并排下次复习。

    body: {item_type: 'knowledge'|'error', item_id: int,
           result: 'forgotten'|'fuzzy'|'mastered', duration?: int, note?: str}
    """
    item_type = payload.get("item_type") or "knowledge"
    item_id = payload.get("item_id")
    result = payload.get("result")

    if item_id is None:
        raise HTTPException(status_code=400, detail="缺少 item_id")
    if result not in review_service.RESULT_GRADE:
        raise HTTPException(
            status_code=400,
            detail=f"result 必须是 {list(review_service.RESULT_GRADE)} 之一",
        )

    try:
        out = review_service.apply_review(
            db,
            item_type=item_type,
            item_id=int(item_id),
            result=result,
            duration=int(payload.get("duration") or 0),
            note=payload.get("note"),
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "复习已记录", **out}


@router.get("/progress")
async def progress(subject: Optional[str] = None, db: Session = Depends(get_db)):
    """复习进度总览：掌握率、到期数、分科目、薄弱章节与知识点。"""
    return review_service.progress_overview(db, subject=subject)


@router.get("/history")
async def history(
    item_type: Optional[str] = None,
    item_id: Optional[int] = None,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """复习留痕时间线。"""
    rows = review_service.review_history(
        db, item_type=item_type, item_id=item_id, days=days, limit=limit
    )
    return {"total": len(rows), "items": rows}


@router.get("/weak-points")
async def weak_points(
    subject: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """错题密度最高的知识点（错题本 × 知识库联动的直接产出）。

    这就是"我最近错得最多的知识点是哪些"的答案。
    """
    items = error_linker.weak_knowledge_points(db, subject=subject, limit=limit)
    return {"total": len(items), "items": items}


@router.get("/link-stats")
async def link_stats(db: Session = Depends(get_db)):
    """错题↔知识库联动覆盖率（还有多少错题没挂上考点）。"""
    return error_linker.link_stats(db)


@router.get("/stats")
async def review_stats(db: Session = Depends(get_db)):
    """复习闭环统计：待复习 / 已完成 / 掌握进度。

    P0 修复：
    1. 原来 `from datetime import datetime, ...` 之后又写 `datetime.now(datetime.UTC)`，
       此时 `datetime` 是**类**而不是模块，`.UTC` 触发
       `AttributeError: type object 'datetime.datetime' has no attribute 'UTC'`。
    2. 时间戳必须与 DB 列对齐：DB 读回的`next_review` / `created_at` 都是 naive，
       若用 aware 的 `now` 比较会抛
       `TypeError: can't compare offset-naive and offset-aware datetimes`。
       故统一使用 utils.timeutil.utcnow()（naive UTC）。
    """
    from sqlalchemy import func  # noqa: F401  保持与既有导入一致
    from utils.timeutil import utcnow
    now = utcnow()  # naive UTC，与 SQLite DateTime 列对齐
    active_errors = db.query(ErrorRecord).filter(ErrorRecord.status == "active").count()
    due_errors = db.query(ErrorRecord).filter(ErrorRecord.status == "active", ErrorRecord.next_review.isnot(None), ErrorRecord.next_review <= now).count()
    graduated = db.query(ErrorRecord).filter(ErrorRecord.status == "graduated").count()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_reviews = db.query(ReviewRecord).filter(ReviewRecord.created_at >= today_start).count()
    total_reviews = db.query(ReviewRecord).count()
    return {
        "active_errors": active_errors,
        "due_errors": due_errors,
        "graduated_errors": graduated,
        "today_reviews": today_reviews,
        "total_reviews": total_reviews,
    }
