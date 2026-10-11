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

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from services.kaoyan import reform_detector, score_insight

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
    conn = db.connection().connection

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
    conn = db.connection().connection
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
    limit: int = Query(100, ge=1, le=500),
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


@router.post("/reforms/scan")
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
@router.post("/analysis/auto-adjust")
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
