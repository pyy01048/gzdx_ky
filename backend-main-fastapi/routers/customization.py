"""自定义链接与系统设置路由。"""

import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db, BASE_DIR
from models import CustomLink
from schemas import CustomLinkCreate, CustomLinkUpdate

router = APIRouter(prefix="/api", tags=["customization"])

SETTINGS_FILE = os.path.join(BASE_DIR, "data", "settings.json")


# ----------------------------------------------------------------------- #
# 快捷链接
# ----------------------------------------------------------------------- #
@router.get("/links")
async def list_links(category: Optional[str] = None, db: Session = Depends(get_db)):
    """快捷链接列表。"""
    query = db.query(CustomLink)
    if category:
        query = query.filter(CustomLink.category == category)
    links = query.order_by(CustomLink.sort_order.asc(), CustomLink.id.asc()).all()
    return [
        {
            "id": l.id,
            "name": l.name,
            "url": l.url,
            "category": l.category,
            "icon": l.icon,
            "sort_order": l.sort_order,
        }
        for l in links
    ]


@router.post("/links")
async def create_link(link: CustomLinkCreate, db: Session = Depends(get_db)):
    """添加链接。"""
    new_link = CustomLink(**link.model_dump())
    db.add(new_link)
    db.commit()
    db.refresh(new_link)
    return {"id": new_link.id, "message": "链接添加成功"}


@router.put("/links/{link_id}")
async def update_link(link_id: int, link: CustomLinkUpdate, db: Session = Depends(get_db)):
    """更新链接。"""
    db_link = db.query(CustomLink).filter(CustomLink.id == link_id).first()
    if not db_link:
        raise HTTPException(status_code=404, detail="链接不存在")

    update_data = link.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_link, key, value)

    db.commit()
    return {"id": db_link.id, "message": "链接更新成功"}


@router.delete("/links/{link_id}")
async def delete_link(link_id: int, db: Session = Depends(get_db)):
    """删除链接。"""
    db_link = db.query(CustomLink).filter(CustomLink.id == link_id).first()
    if not db_link:
        raise HTTPException(status_code=404, detail="链接不存在")

    db.delete(db_link)
    db.commit()
    return {"message": "链接已删除"}


# ----------------------------------------------------------------------- #
# 系统设置
# ----------------------------------------------------------------------- #
def _load_settings() -> Dict[str, Any]:
    """从 JSON 文件加载系统设置。"""
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "theme": "light",
        "language": "zh-CN",
        "study_reminder": True,
        "reminder_time": "08:00",
        "daily_goal_minutes": 480,
        "weekend_goal_minutes": 720,
        "auto_sync_netdisk": False,
    }


def _save_settings(settings: Dict[str, Any]) -> None:
    """保存系统设置到 JSON 文件。"""
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


@router.get("/settings")
async def get_settings():
    """系统参数。"""
    return _load_settings()


@router.put("/settings")
async def update_settings(settings: Dict[str, Any]):
    """更新系统参数。"""
    current = _load_settings()
    current.update(settings)
    _save_settings(current)
    return {"message": "设置已更新", "settings": current}
