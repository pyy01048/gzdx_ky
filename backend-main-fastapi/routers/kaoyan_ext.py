# -*- coding: utf-8 -*-
"""考研择校扩展路由（V10 新增，routers/kaoyan_ext.py）。

在 routers/kaoyan.py 基础上追加四组能力，原文件不动：
- 全局通知流  GET  /api/kaoyan/notices/feed       （搜索/过滤/分页）
- 改考雷达    GET  /api/kaoyan/reforms             （列表+统计）
              POST /api/kaoyan/reforms/scan        （触发扫描）
- 分数全景    GET  /api/kaoyan/analysis/score-detail/{school_id}
- 自动调整    POST /api/kaoyan/analysis/auto-adjust （冲稳保+理由）
"""
from __future__ import annotations
from utils.security import require_admin

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from services.dbapi_compat import wrap_conn
from database import get_db
from services.kaoyan import reform_detector, score_insight
from models import KaoyanSchool, KaoyanCrawlTarget

from utils.response import MAX_PAGE_SIZE

router = APIRouter(prefix="/api/kaoyan", tags=["考研择校扩展"])


class ReformScanReq(BaseModel):
    """POST /reforms/scan 请求体。"""
    school_ids: Optional[List[int]] = Field(None, description="限定院校，空=全量")
    dry_run: bool = Field(False, description="只检测不入库（预览）")
    limit: int = Field(5000, ge=1, le=20000, description="最多扫描公告数")


# --------------------------------------------------------------------------- #
# 全局通知流
# --------------------------------------------------------------------------- #
@router.get("/notices/feed")
def notices_feed(
    q: Optional[str] = Query(None, max_length=100, description="标题关键词"),
    notice_type: Optional[str] = Query(None, description="公告/简章/复试/调剂/录取"),
    school_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """全局通知流：跨院校公告聚合 + 搜索 + 分页（通知中心页数据源）。"""
    from services.kaoyan.spider_notices import ensure_notices_schema

    ensure_notices_schema(db)
    conn = wrap_conn(db.connection().connection)

    where = ["1=1"]
    args: list = []
    if q:
        where.append("title LIKE ?")
        args.append(f"%{q}%")
    if notice_type:
        where.append("notice_type = ?")
        args.append(notice_type)
    if school_id:
        where.append("school_id = ?")
        args.append(school_id)
    wsql = " AND ".join(where)

    total = conn.execute(
        f"SELECT COUNT(*) FROM kaoyan_notices WHERE {wsql}", args
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT id, school_id, school_name, title, notice_type, publish_date, "
        f"url, source FROM kaoyan_notices WHERE {wsql} "
        f"ORDER BY publish_date DESC, id DESC LIMIT ? OFFSET ?",
        args + [page_size, (page - 1) * page_size],
    ).fetchall()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {"id": r[0], "school_id": r[1], "school_name": r[2], "title": r[3],
             "notice_type": r[4], "publish_date": r[5], "url": r[6], "source": r[7]}
            for r in rows
        ],
    }


@router.get("/notices/recent")
def notices_recent(limit: int = Query(12, ge=1, le=50),
                   db: Session = Depends(get_db)):
    """首页速览：最新 N 条公告（供择校中心/仪表盘引用）。"""
    from services.kaoyan.spider_notices import ensure_notices_schema

    ensure_notices_schema(db)
    conn = wrap_conn(db.connection().connection)
    rows = conn.execute(
        "SELECT id, school_id, school_name, title, notice_type, publish_date, url "
        "FROM kaoyan_notices ORDER BY publish_date DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"id": r[0], "school_id": r[1], "school_name": r[2], "title": r[3],
         "notice_type": r[4], "publish_date": r[5], "url": r[6]}
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# 改考雷达
# --------------------------------------------------------------------------- #
@router.get("/reforms")
def reforms_list(
    school_id: Optional[int] = Query(None),
    change_type: Optional[str] = Query(None, description="改考科目/停招/新增专业/…"),
    year: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """改考事件列表（通知中心·改考雷达 / 院校详情改考提醒）。"""
    return reform_detector.list_reforms(db, school_id=school_id,
                                        change_type=change_type,
                                        year=year, limit=limit)


@router.get("/reforms/stats")
def reforms_stats(db: Session = Depends(get_db)):
    """改考事件统计：总数/按类型/涉及院校 Top10。"""
    return reform_detector.reform_stats(db)


@router.post("/reforms/scan", dependencies=[Depends(require_admin)])
def reforms_scan(
    req: ReformScanReq,
    db: Session = Depends(get_db),
):
    """触发改考扫描（解析 kaoyan_notices 标题 → 结构化事件）。

    - dry_run=true 只检测不入库，用于预览。
    - 幂等：重复扫描按 (school, type, year, detail_hash) 去重。
    """
    result = reform_detector.scan_notices_for_reforms(
        db, school_ids=req.school_ids, limit=req.limit, dry_run=req.dry_run
    )
    return result


# --------------------------------------------------------------------------- #
# 分数全景
# --------------------------------------------------------------------------- #
@router.get("/analysis/score-detail/{school_id}")
def score_detail(
    school_id: int,
    major_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """院校（或专业）多年分数全景：单科明细/录取/趋势/国家线差值。"""
    detail = score_insight.school_score_detail(db, school_id, major_id=major_id)
    if not detail:
        raise HTTPException(status_code=404, detail="院校不存在")
    return detail


# --------------------------------------------------------------------------- #
# 自动调整
# --------------------------------------------------------------------------- #
@router.post("/analysis/auto-adjust", dependencies=[Depends(require_admin)])
def auto_adjust(
    payload: dict,
    db: Session = Depends(get_db),
):
    """择校自动调整：输入预估分 → 冲/稳/保三档 + 数据化理由。

    body: {user_score, subject_code?, province?, level?, per_bucket?}
    """
    user_score = payload.get("user_score")
    if not isinstance(user_score, int) or not (200 <= user_score <= 500):
        raise HTTPException(status_code=422, detail="user_score 需为 200~500 的整数")
    result = score_insight.auto_adjust_recommend(
        db,
        user_score=user_score,
        subject_code=payload.get("subject_code"),
        province=payload.get("province"),
        level=payload.get("level"),
        per_bucket=int(payload.get("per_bucket", 8)),
    )
    return result


# --------------------------------------------------------------------------- #
# 院校采集开关（/api/kaoyan/crawl-targets）
#
# 设计口径：表中只记录"被用户显式改过"的院校。
#   · 没有记录  → 默认参与采集（enabled=True）
#   · enabled=False → 用户明确排除，采集任务应跳过
# 这样新导入的院校默认就会被采集，不会因为忘配置而漏数据。
# --------------------------------------------------------------------------- #

class CrawlTargetToggleReq(BaseModel):
    school_id: int = Field(..., description="院校 ID")
    enabled: bool = Field(True, description="是否参与采集")


class CrawlTargetBulkReq(BaseModel):
    school_ids: List[int] = Field(..., min_length=1, max_length=2000)
    enabled: bool = Field(True)


class CrawlTargetResetReq(BaseModel):
    confirm: bool = Field(False, description="必须为 true 才会清空全部开关")


def _upsert_target(db: Session, school_id: int, enabled: bool) -> KaoyanCrawlTarget:
    row = db.query(KaoyanCrawlTarget).filter(KaoyanCrawlTarget.school_id == school_id).first()
    if row:
        row.enabled = enabled
    else:
        row = KaoyanCrawlTarget(school_id=school_id, enabled=enabled)
        db.add(row)
    return row


@router.get("/crawl-targets")
def list_crawl_targets(
    q: Optional[str] = Query(None, max_length=100, description="院校名关键词"),
    province: Optional[str] = Query(None, description="省份"),
    level: Optional[str] = Query(None, description="985/211/双一流/双非"),
    enabled: Optional[bool] = Query(None, description="仅看启用/停用"),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """院校采集清单：分页 + 搜索 + 省份/层级/开关筛选。"""
    query = db.query(KaoyanSchool)
    if q:
        query = query.filter(KaoyanSchool.name.like(f"%{q.strip()}%"))
    if province:
        query = query.filter(KaoyanSchool.province == province)
    if level:
        query = query.filter(KaoyanSchool.level == level)

    total_schools = db.query(func.count(KaoyanSchool.id)).scalar() or 0
    disabled_total = (
        db.query(func.count(KaoyanCrawlTarget.id))
        .filter(KaoyanCrawlTarget.enabled.is_(False))
        .scalar() or 0
    )

    # enabled 过滤走反连接：没有开关记录的院校视为默认启用
    if enabled is True:
        excluded = db.query(KaoyanCrawlTarget.school_id).filter(KaoyanCrawlTarget.enabled.is_(False))
        query = query.filter(~KaoyanSchool.id.in_(excluded))
    elif enabled is False:
        excluded = db.query(KaoyanCrawlTarget.school_id).filter(KaoyanCrawlTarget.enabled.is_(False))
        query = query.filter(KaoyanSchool.id.in_(excluded))

    total = query.count()
    rows = (
        query.order_by(KaoyanSchool.province.asc(), KaoyanSchool.name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    ids = [s.id for s in rows]
    targets = {}
    if ids:
        for t in db.query(KaoyanCrawlTarget).filter(KaoyanCrawlTarget.school_id.in_(ids)).all():
            targets[t.school_id] = t

    items = []
    for s in rows:
        t = targets.get(s.id)
        items.append({
            "id": s.id,
            "name": s.name,
            "province": s.province,
            "city": s.city,
            "level": s.level,
            "data_source": s.data_source,
            "official_url": s.official_url,
            "enabled": True if t is None else bool(t.enabled),
            "priority": t.priority if t else 0,
            "note": t.note if t else None,
            "last_crawled_at": t.last_crawled_at.isoformat() if t and t.last_crawled_at else None,
        })

    provinces = [
        r[0] for r in db.query(KaoyanSchool.province).distinct().all() if r[0]
    ]
    levels = [
        r[0] for r in db.query(KaoyanSchool.level).distinct().all() if r[0]
    ]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "total_schools": total_schools,
        "enabled_count": total_schools - disabled_total,
        "disabled_count": disabled_total,
        "provinces": sorted(provinces),
        "levels": sorted(levels),
        "items": items,
    }


@router.post("/crawl-targets/toggle", dependencies=[Depends(require_admin)])
def toggle_crawl_target(req: CrawlTargetToggleReq, db: Session = Depends(get_db)):
    """单校开关（幂等）。"""
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == req.school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    row = _upsert_target(db, req.school_id, req.enabled)
    db.commit()
    db.refresh(row)
    return {
        "success": True,
        "school_id": row.school_id,
        "school_name": school.name,
        "enabled": bool(row.enabled),
    }


@router.post("/crawl-targets/bulk", dependencies=[Depends(require_admin)])
def bulk_crawl_targets(req: CrawlTargetBulkReq, db: Session = Depends(get_db)):
    """批量开关：页面上「全选当前页 / 排除当前页」用。"""
    existing = {
        row[0] for row in db.query(KaoyanSchool.id).filter(KaoyanSchool.id.in_(req.school_ids)).all()
    }
    changed = 0
    for sid in req.school_ids:
        if sid not in existing:
            continue
        _upsert_target(db, sid, req.enabled)
        changed += 1
    db.commit()
    return {"success": True, "changed": changed, "enabled": req.enabled}


@router.post("/crawl-targets/reset", dependencies=[Depends(require_admin)])
def reset_crawl_targets(req: CrawlTargetResetReq, db: Session = Depends(get_db)):
    """清空全部开关 → 回到「所有院校默认参与采集」。"""
    if not req.confirm:
        raise HTTPException(status_code=422, detail="需要 confirm=true 才能重置")
    removed = db.query(KaoyanCrawlTarget).delete()
    db.commit()
    return {"success": True, "removed": removed}
