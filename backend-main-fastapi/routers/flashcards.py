"""背诵卡片路由。"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Flashcard
from schemas import FlashcardCreate, FlashcardBatchCreate, FlashcardReview
from services.review_scheduler import ReviewScheduler
from utils.timeutil import utcnow  # 统一 naive UTC 时间规范（P0-4）

router = APIRouter(prefix="/api/flashcards", tags=["flashcards"])


@router.get("")
async def list_flashcards(
    mastery: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    """卡片列表。"""
    query = db.query(Flashcard)
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
async def create_flashcard(card: FlashcardCreate, db: Session = Depends(get_db)):
    """创建卡片。"""
    new_card = Flashcard(**card.model_dump())
    if not new_card.next_review:
        new_card.next_review = utcnow()  # naive UTC，与 DB 列对齐（P0-4）
    db.add(new_card)
    db.commit()
    db.refresh(new_card)
    return {"id": new_card.id, "message": "卡片创建成功"}


@router.post("/batch")
async def batch_create_flashcards(data: FlashcardBatchCreate, db: Session = Depends(get_db)):
    """批量创建。"""
    count = 0
    for card in data.cards:
        new_card = Flashcard(**card.model_dump())
        if not new_card.next_review:
            new_card.next_review = utcnow()  # naive UTC，与 DB 列对齐（P0-4）
        db.add(new_card)
        count += 1
    db.commit()
    return {"created": count, "message": f"成功创建 {count} 张卡片"}


@router.put("/{card_id}/review")
async def review_flashcard(card_id: int, review: FlashcardReview, db: Session = Depends(get_db)):
    """复习打卡（更新艾宾浩斯）。"""
    card = db.query(Flashcard).filter(Flashcard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")

    next_review, new_reps, new_interval, new_ef, mastery = ReviewScheduler.calculate_next_review(
        quality=review.quality,
        repetitions=card.review_count or 0,
        interval=card.interval or 1,
        ef=card.ease_factor or 2.5,
    )

    card.review_count = new_reps
    card.interval = new_interval
    card.ease_factor = new_ef
    card.next_review = next_review
    card.mastery = mastery

    db.commit()
    return {
        "id": card.id,
        "next_review": next_review.isoformat(),
        "review_count": new_reps,
        "interval": new_interval,
        "ease_factor": new_ef,
        "mastery": mastery,
        "message": "复习打卡成功",
    }


@router.get("/due")
async def due_flashcards(limit: int = 50, db: Session = Depends(get_db)):
    """今日待复习卡片。"""
    cards = ReviewScheduler.get_due_flashcards(db, limit=limit)
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
async def delete_flashcard(card_id: int, db: Session = Depends(get_db)):
    """删除卡片。"""
    card = db.query(Flashcard).filter(Flashcard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    db.delete(card)
    db.commit()
    return {"id": card_id, "message": "卡片删除成功"}
