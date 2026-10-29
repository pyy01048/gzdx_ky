"""背诵卡片路由。"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Flashcard, User
from utils.scope import owner_id, scoped  # B4 行级隔离
from utils.security import current_user
from schemas import FlashcardCreate, FlashcardBatchCreate, FlashcardReview
from services.review_scheduler import ReviewScheduler
from utils.timeutil import utcnow  # 统一 naive UTC 时间规范（P0-4）

from utils.response import MAX_PAGE_SIZE

router = APIRouter(prefix="/api/flashcards", tags=["flashcards"])


@router.get("")
async def list_flashcards(
    mastery: Optional[str] = None,
    page: int = 1,
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """卡片列表（B4：只看本人卡片）。"""
    query = db.query(Flashcard).filter(scoped(Flashcard, user))
    if mastery:
        query = query.filter(Flashcard.mastery == mastery)

    total = query.count()
    cards = (
        query.order_by(Flashcard.next_review.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": [
            {
                "id": c.id,
                "front": c.front,
                "back": c.back,
                "knowledge_point_id": c.knowledge_point_id,
                "next_review": c.next_review.isoformat() if c.next_review else None,
                "review_count": c.review_count,
                "interval": c.interval,
                "ease_factor": c.ease_factor,
                "mastery": c.mastery,
            }
            for c in cards
        ],
    }


@router.post("")
async def create_flashcard(card: FlashcardCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """创建卡片。"""
    new_card = Flashcard(**card.model_dump())
    new_card.user_id = owner_id(user)  # B4：归属当前用户
    if not new_card.next_review:
        # V12 同族口径：新卡走"学习"流程，不进当日复习队列；首排程至少 1 天后
        # （旧逻辑 = utcnow() → 建卡即到期，647/649 全部涌入"今日待复习"，实测失真）
        new_card.next_review = utcnow() + datetime.timedelta(days=1)
    db.add(new_card)
    db.commit()
    db.refresh(new_card)
    return {"id": new_card.id, "message": "卡片创建成功"}


@router.post("/batch")
async def batch_create_flashcards(data: FlashcardBatchCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """批量创建。"""
    count = 0
    for card in data.cards:
        new_card = Flashcard(**card.model_dump())
        new_card.user_id = owner_id(user)  # B4：归属当前用户
        if not new_card.next_review:
            # 同上：新卡首排程至少 1 天后，不进当日 due 队列
            new_card.next_review = utcnow() + datetime.timedelta(days=1)
        db.add(new_card)
        count += 1
    db.commit()
    return {"created": count, "message": f"成功创建 {count} 张卡片"}


@router.put("/{card_id}/review")
async def review_flashcard(card_id: int, review: FlashcardReview, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """复习打卡（更新艾宾浩斯）。"""
    card = db.query(Flashcard).filter(Flashcard.id == card_id, scoped(Flashcard, user)).first()
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")

    next_review, new_reps, new_interval, new_ef, mastery = ReviewScheduler.calculate_next_review(
        quality=review.quality,
        repetitions=card.review_count or 0,
        interval=card.interval or 1,
        ef=card.ease_factor or 2.5,
    )

    # FSRS：统一调度表为准；SM-2 字段保留为兼容快照
    from services.srs import fsrs
    sched = fsrs.schedule(
        db,
        item_type="flashcard",
        item_id=int(card.id),
        rating=fsrs.rating_from_grade(review.quality),
        user_id=owner_id(user),  # B4：复习排程跟随操作者
    )
    card.review_count = new_reps
    card.interval_days = int(sched["interval_days"])
    card.ease_factor = new_ef
    card.next_review = utcnow() + datetime.timedelta(days=int(sched["interval_days"]))
    card.mastery = mastery

    db.commit()
    return {
        "id": card.id,
        "next_review": card.next_review.isoformat(),
        "review_count": new_reps,
        "interval": int(sched["interval_days"]),
        "ease_factor": new_ef,
        "mastery": mastery,
        "fsrs": sched,
        "message": "复习打卡成功",
    }


@router.get("/due")
async def due_flashcards(limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """今日待复习卡片（B4：只看本人）。"""
    cards = ReviewScheduler.get_due_flashcards(db, limit=limit, user_id=owner_id(user))
    return {
        "total": len(cards),
        "cards": [
            {
                "id": c.id,
                "front": c.front,
                "back": c.back,
                "review_count": c.review_count,
                "mastery": c.mastery,
                "next_review": c.next_review.isoformat() if c.next_review else None,
            }
            for c in cards
        ],
    }


@router.delete("/{card_id}")
async def delete_flashcard(card_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """删除卡片。"""
    card = db.query(Flashcard).filter(Flashcard.id == card_id, scoped(Flashcard, user)).first()
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    db.delete(card)
    db.commit()
    return {"id": card_id, "message": "卡片删除成功"}
