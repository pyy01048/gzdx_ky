"""全站通用收藏路由（S7：收藏 / 学习轨迹）。

设计：
- 弱引用：item_type + item_id 指向任意实体（document/question/error/kp/word/flashcard），
  不设外键；被收藏对象删除后收藏行保留（title 快照可标注"已失效"）。
- 幂等收藏：重复收藏同一实体返回 200 且不产生重复行（UNIQUE 约束兜底）。

端点：
    GET    /api/favorites                 列表（可按类型筛选、关键词搜索、分页）
    POST   /api/favorites                 收藏（body: item_type/item_id/title/snippet/meta）
    GET    /api/favorites/check           查询是否已收藏（单项 item_id，或批量 ids）
    GET    /api/favorites/ids             当前用户已收藏的全部 item_id
    POST   /api/favorites/toggle          切换收藏状态，返回 {favorited: bool}
    DELETE /api/favorites/{item_type}/{item_id}  取消收藏
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import bindparam, text

from database import get_db
from models import User
from utils.scope import owner_id  # B4 行级隔离：原生 SQL 按 user_id 过滤
from utils.security import current_user

router = APIRouter(prefix="/api/favorites", tags=["favorites"])

_ALLOWED_TYPES = {"document", "question", "error", "kp", "word", "flashcard", "link"}

#: 单次批量 check 的 ID 上限（P0-3）：383 篇文档一次打进来也只有 383 个 ID，
#: 留足余量同时挡住失控的超大 IN 列表把查询计划拖垮。
_BATCH_MAX_IDS = 1000


class FavoriteIn(BaseModel):
    item_type: str
    item_id: int
    title: str = ""
    snippet: Optional[str] = None
    meta: Optional[dict] = None


def _validate_type(item_type: str) -> str:
    if item_type not in _ALLOWED_TYPES:
        raise HTTPException(422, f"不支持的收藏类型: {item_type}，允许值: {sorted(_ALLOWED_TYPES)}")
    return item_type


def _parse_ids(raw: str) -> list[int]:
    """解析逗号分隔的 ID 串；去重保序，非法值直接 422（前端传错要立刻暴露）。"""
    out: list[int] = []
    seen: set[int] = set()
    for part in (raw or "").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            v = int(p)
        except ValueError:
            raise HTTPException(422, f"非法 item_id: {p}")
        if v not in seen:
            seen.add(v)
            out.append(v)
    if not out:
        raise HTTPException(422, "ids 不能为空")
    if len(out) > _BATCH_MAX_IDS:
        raise HTTPException(422, f"单次批量查询上限 {_BATCH_MAX_IDS} 个 ID，实际 {len(out)}")
    return out


@router.get("")
async def list_favorites(
    db=Depends(get_db),
    item_type: Optional[str] = Query(None, description="按类型筛选"),
    q: Optional[str] = Query(None, description="标题/摘要关键词"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
):
    """收藏列表（时间倒序，B4：只看本人收藏）。"""
    conds, params = ["user_id = :uid"], {"uid": owner_id(user), "lim": limit, "off": offset}
    if item_type:
        _validate_type(item_type)
        conds.append("item_type = :itype")
        params["itype"] = item_type
    if q:
        conds.append("(title ILIKE :kw OR snippet ILIKE :kw)")
        params["kw"] = f"%{q}%"
    where = " AND ".join(conds)

    total = db.execute(
        text(f"SELECT count(*) FROM favorites WHERE {where}"), params
    ).scalar_one()
    rows = db.execute(text(f"""
        SELECT id, item_type, item_id, title, snippet, meta, created_at
        FROM favorites WHERE {where}
        ORDER BY created_at DESC, id DESC
        LIMIT :lim OFFSET :off
    """), params).fetchall()
    return {
        "total": total,
        "items": [
            {
                "id": r[0],
                "item_type": r[1],
                "item_id": r[2],
                "title": r[3],
                "snippet": r[4],
                "meta": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ],
    }


@router.post("")
async def add_favorite(body: FavoriteIn, db=Depends(get_db), user: User = Depends(current_user)):
    """收藏。重复收藏幂等返回（不报错、不重复建行）。

    B4：唯一键 (user_id, item_type, item_id)，幂等判断跟随当前用户。
    """
    _validate_type(body.item_type)
    db.execute(text("""
        INSERT INTO favorites (user_id, item_type, item_id, title, snippet, meta)
        VALUES (:uid, :t, :i, :title, :sn, CAST(:meta AS JSONB))
        ON CONFLICT (user_id, item_type, item_id)
        DO UPDATE SET title = EXCLUDED.title, snippet = EXCLUDED.snippet,
                      meta = EXCLUDED.meta
    """), {
        "uid": owner_id(user),
        "t": body.item_type, "i": body.item_id,
        "title": (body.title or "")[:500], "sn": body.snippet,
        "meta": __import__("json").dumps(body.meta, ensure_ascii=False) if body.meta else None,
    })
    db.commit()
    row = db.execute(text("""
        SELECT id, created_at FROM favorites
        WHERE user_id = :uid AND item_type = :t AND item_id = :i
    """), {"uid": owner_id(user), "t": body.item_type, "i": body.item_id}).first()
    return {"ok": True, "id": row[0], "created_at": row[1].isoformat() if row[1] else None}


@router.get("/check")
async def check_favorite(
    item_type: str,
    item_id: Optional[int] = None,
    ids: Optional[str] = Query(
        None, description="批量查询：逗号分隔的 item_id，如 1,2,3；与 item_id 二选一"),
    db=Depends(get_db),
    user: User = Depends(current_user),
):
    """查询是否已收藏。两种形态：

    - 单查 ``?item_type=document&item_id=1`` → ``{"favorited": bool, "id": int|null}``
      （老契约，前端 FavoriteStar 单例仍走这条）
    - 批查 ``?item_type=document&ids=1,2,3`` → ``{"item_type", "requested",
      "map": {"1": true, "2": false}, "favorited_ids": [1, 3]}``

    批查是 P0-3 的修复点。此前文档知识库 383 篇逐篇单查（N+1），383 路并发
    打满 PG 连接池（生产 max_connections=50），连带把全部个人数据端点拖成 500。
    批查把 383 次请求压成 1 次，且 ``map`` 对未收藏 ID 显式给 false——
    前端缓存据此把"未知"落成"未收藏"，不会留下空洞导致下次重复探测。
    """
    _validate_type(item_type)
    uid = owner_id(user)

    if ids is not None:
        id_list = _parse_ids(ids)
        stmt = text(
            "SELECT item_id FROM favorites "
            "WHERE user_id = :uid AND item_type = :t AND item_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        hit = {r[0] for r in db.execute(stmt, {"uid": uid, "t": item_type, "ids": id_list})}
        return {
            "item_type": item_type,
            "requested": len(id_list),
            "map": {str(i): (i in hit) for i in id_list},
            "favorited_ids": [i for i in id_list if i in hit],
        }

    if item_id is None:
        raise HTTPException(422, "item_id 与 ids 至少提供一个")
    fid = db.execute(text(
        "SELECT id FROM favorites WHERE user_id = :uid AND item_type = :t AND item_id = :i"
    ), {"uid": uid, "t": item_type, "i": item_id}).scalar()
    return {"favorited": fid is not None, "id": fid}


@router.get("/ids")
async def list_favorite_ids(
    item_type: Optional[str] = Query(None, description="按类型筛选；不传=返回按类型分组的全量"),
    db=Depends(get_db),
    user: User = Depends(current_user),
):
    """当前用户已收藏的全部 item_id（P0-3）。

    列表页首屏用这一条替代"逐项 check"：一次取回全部收藏 ID，前端拿集合做
    O(1) 判存，不再需要为每一行发请求。
    """
    uid = owner_id(user)
    if item_type:
        _validate_type(item_type)
        rows = db.execute(text(
            "SELECT item_id FROM favorites WHERE user_id = :uid AND item_type = :t"
        ), {"uid": uid, "t": item_type}).fetchall()
        ids = [r[0] for r in rows]
        return {"item_type": item_type, "ids": ids, "total": len(ids)}

    rows = db.execute(text(
        "SELECT item_type, item_id FROM favorites WHERE user_id = :uid"
    ), {"uid": uid}).fetchall()
    grouped: dict[str, list[int]] = {}
    for t, i in rows:
        grouped.setdefault(t, []).append(i)
    return {"grouped": grouped, "total": len(rows)}


@router.post("/toggle")
async def toggle_favorite(body: FavoriteIn, db=Depends(get_db), user: User = Depends(current_user)):
    """切换收藏状态：已收藏则取消，未收藏则新增。"""
    _validate_type(body.item_type)
    existing = db.execute(text(
        "SELECT id FROM favorites WHERE user_id = :uid AND item_type = :t AND item_id = :i"
    ), {"uid": owner_id(user), "t": body.item_type, "i": body.item_id}).scalar()
    if existing:
        db.execute(text("DELETE FROM favorites WHERE id = :id"), {"id": existing})
        db.commit()
        return {"favorited": False}
    await add_favorite(body, db, user)
    return {"favorited": True}


@router.delete("/{item_type}/{item_id}")
async def remove_favorite(
    item_type: str,
    item_id: int,
    db=Depends(get_db),
    user: User = Depends(current_user),
):
    """取消收藏。不存在返回 404。"""
    _validate_type(item_type)
    res = db.execute(text(
        "DELETE FROM favorites WHERE user_id = :uid AND item_type = :t AND item_id = :i"
    ), {"uid": owner_id(user), "t": item_type, "i": item_id})
    db.commit()
    if res.rowcount == 0:
        raise HTTPException(404, "收藏不存在")
    return {"ok": True}
