"""水印词库管理路由（智能识别的最后一环：候选 → 一键审核 → 全站生效）。

设计（与 services/content_sanitizer 配套）：
- ``learn_watermark_lexicon`` 自动把统计可疑项写入候选队列（enabled=FALSE）；
- 本路由让人工一键 启用/禁用/新增/删除 词条，改完即全站清洗生效；
- 也可随时触发重新学习（新机构水印出现后无需改代码）。

端点：
    GET   /api/admin/watermark-lexicon            列表（默认只看候选）
    POST  /api/admin/watermark-lexicon/learn      重新自学习
    POST  /api/admin/watermark-lexicon/{phrase}   启用/禁用（body: {"enabled": true}）
    DELETE /api/admin/watermark-lexicon/{phrase}  删除词条
"""

from __future__ import annotations

import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from database import get_db

from utils.response import MAX_PAGE_SIZE
from utils.security import require_admin

router = APIRouter(prefix="/api/admin/watermark-lexicon", tags=["admin-watermark"], dependencies=[Depends(require_admin)])


class LexiconToggle(BaseModel):
    enabled: bool


@router.get("")
async def list_lexicon(
    db=Depends(get_db),
    only_candidates: bool = Query(True, description="只看待审核候选（enabled=False）"),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
):
    rows = db.execute(text("""
        SELECT phrase, doc_count, confidence, enabled, auto_learned, created_at
        FROM watermark_lexicon
        WHERE (:only = FALSE OR enabled = FALSE)
        ORDER BY doc_count DESC
        LIMIT :lim
    """), {"only": only_candidates, "lim": limit}).fetchall()
    return {
        "total": len(rows),
        "items": [
            {
                "phrase": r[0],
                "doc_count": r[1],
                "confidence": round(r[2] or 0, 3),
                "enabled": r[3],
                "auto_learned": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ],
    }


@router.post("/learn")
async def relearn(db=Depends(get_db)):
    """重新自学习（定期跑或新语料导入后跑）。"""
    from services.content_sanitizer import learn_watermark_lexicon

    stats = learn_watermark_lexicon(db)
    return {"ok": True, "stats": stats}


@router.post("/{phrase}")
async def toggle_lexicon(phrase: str, body: LexiconToggle, db=Depends(get_db)):
    """启用/禁用词条（启用后全站清洗立即生效）。"""
    from services.content_sanitizer import invalidate_learned_cache

    phrase = urllib.parse.unquote(phrase)
    res = db.execute(text("""
        UPDATE watermark_lexicon SET enabled = :en, updated_at = now()
        WHERE phrase = :p
    """), {"en": body.enabled, "p": phrase})
    if res.rowcount == 0:
        db.execute(text("""
            INSERT INTO watermark_lexicon (phrase, doc_count, confidence, enabled, auto_learned)
            VALUES (:p, 0, 0.9, :en, FALSE)
        """), {"p": phrase, "en": body.enabled})
    db.commit()
    invalidate_learned_cache()
    return {"ok": True, "phrase": phrase, "enabled": body.enabled}


@router.delete("/{phrase}")
async def delete_lexicon(phrase: str, db=Depends(get_db)):
    """删除词条（误学的正文结构用这个移除）。"""
    from services.content_sanitizer import invalidate_learned_cache

    phrase = urllib.parse.unquote(phrase)
    res = db.execute(text("DELETE FROM watermark_lexicon WHERE phrase = :p"), {"p": phrase})
    db.commit()
    invalidate_learned_cache()
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="词条不存在")
    return {"ok": True, "deleted": phrase}
