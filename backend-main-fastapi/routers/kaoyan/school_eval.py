# -*- coding: utf-8 -*-
"""08 工学学科评估路由（119 分片配套，2026-11-21 并入 data-assets/工学院校评价库）。

四组只读能力（全部共享择校数据，零 current_user 依赖 → /api/kaoyan 前缀访客可读）：
- GET /api/kaoyan/school-eval/schools                 院校卡片列表（筛选/搜索/排序/分页）
- GET /api/kaoyan/school-eval/schools/{school_id}     院校详情（评估明细+双一流+优势学科）
- GET /api/kaoyan/school-eval/disciplines             08 工学学科字典（48）
- GET /api/kaoyan/school-eval/disciplines/{code}/rank 按学科选校（等级排序榜单）

口径纪律（源 README 第三节，响应里带 caveats 供前端渲染）：
* 评估只公布前 70%：未上榜≠学科差，文案「未上榜/未公布」。
* 0838/0839 未列入第四轮公布；第五轮未官方公开。
* joint 两地联合 / institute 科研院所单列，不与普通高校混排（榜单分组返回）。
* heat_tag 主观估算；data_status=3 补充院校待核验。
"""

from __future__ import annotations

from typing import Optional

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from utils.response import MAX_PAGE_SIZE

router = APIRouter(prefix="/api/kaoyan/school-eval", tags=["工学学科评估"])

GRADE_ORDER = {"A+": 1, "A": 2, "A-": 3, "B+": 4, "B": 5, "B-": 6, "C+": 7, "C": 8, "C-": 9}

CAVEATS = [
    "第四轮学科评估仅公布前70%：未上榜不代表学科差（可能未参评或位于后30%）。",
    "0838公安技术、0839网络空间安全未列入第四轮公布结果；第五轮结果未官方公开。",
    "两地联合评估（joint）与科研院所单列（institute）单独分组，不与普通高校混排。",
    "竞争热度为基于院校层次/学科实力/区位的主观估算，仅供参考。",
]


def _school_row(r) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "school_code": r.school_code,
        "province": r.province,
        "city": r.city,
        "school_type": r.school_type,
        "unit_type": r.unit_type,
        "is_985": bool(r.is_985),
        "is_211": bool(r.is_211),
        "is_double_first": bool(r.is_double_first),
        "is_self_marked": bool(r.is_self_marked),
        "eval_cnt": r.eval_cnt,
        "a_cnt": r.a_cnt,
        "bp_cnt": r.bp_cnt,
        "heat_tag": r.heat_tag,
        "heat_note": r.heat_note,
        "industry_tags": r.industry_tags or [],
        "tier_txt": r.tier_txt,
        "data_status": r.data_status,
        "intro": r.intro,
    }


@router.get("/schools")
def list_schools(
    q: Optional[str] = Query(None, max_length=60, description="校名关键词"),
    province: Optional[str] = Query(None, max_length=30),
    is_985: Optional[bool] = Query(None),
    is_211: Optional[bool] = Query(None),
    is_double_first: Optional[bool] = Query(None),
    is_self_marked: Optional[bool] = Query(None),
    unit_type: Optional[int] = Query(None, ge=1, le=3, description="1高校2科研院所3军校"),
    data_status: Optional[int] = Query(None, ge=2, le=3),
    sort: str = Query("eval_cnt", pattern="^(eval_cnt|a_cnt|bp_cnt|name)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    """院校卡片列表：08 工学招生院校主档（329 所）筛选/搜索/排序。"""
    where, params = ["1=1"], {}
    if q:
        where.append("name ILIKE :q")
        params["q"] = f"%{q}%"
    if province:
        where.append("province = :province")
        params["province"] = province
    for flag in ("is_985", "is_211", "is_double_first", "is_self_marked"):
        val = locals()[flag]
        if val is not None:
            where.append(f"{flag} = :{flag}")
            params[flag] = 1 if val else 0
    if unit_type is not None:
        where.append("unit_type = :unit_type")
        params["unit_type"] = unit_type
    if data_status is not None:
        where.append("data_status = :data_status")
        params["data_status"] = data_status
    w = " AND ".join(where)
    order = "name" if sort == "name" else f"{sort} DESC, name"
    total = db.execute(text(f"SELECT COUNT(*) FROM ky_school WHERE {w}"), params).scalar()
    rows = db.execute(
        text(f"SELECT * FROM ky_school WHERE {w} ORDER BY {order} LIMIT :lim OFFSET :off"),
        {**params, "lim": page_size, "off": (page - 1) * page_size},
    ).fetchall()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_school_row(r) for r in rows],
        "caveats": CAVEATS,
    }


@router.get("/schools/{school_id}")
def school_detail(school_id: int, db: Session = Depends(get_db)):
    """院校详情：主档 + 第四轮评估明细 + 双一流学科 + 站内院校库联动 id。"""
    r = db.execute(text("SELECT * FROM ky_school WHERE id = :id"), {"id": school_id}).fetchone()
    if r is None:
        raise HTTPException(404, "院校不存在")
    item = _school_row(r)
    item.update(
        {
            "evaluation": r.evaluation,
            "feature": r.feature,
            "strengths": r.strengths_json or [],
            "verify_note": r.verify_note,
        }
    )
    evals = db.execute(
        text("""SELECT e.discipline_code, d.name AS discipline_name, e.grade, e.eval_scope
                  FROM ky_school_discipline_eval e
                  JOIN ky_discipline d ON d.code = e.discipline_code
                 WHERE e.school_name = :name AND e.eval_round = 4
                 ORDER BY e.discipline_code"""),
        {"name": r.name},
    ).fetchall()
    item["evals"] = [
        {
            "discipline_code": e.discipline_code,
            "discipline_name": e.discipline_name,
            "grade": e.grade,
            "eval_scope": e.eval_scope,
        }
        for e in sorted(evals, key=lambda x: (GRADE_ORDER.get(x.grade, 99), x.discipline_code))
    ]
    syl = db.execute(
        text("""SELECT discipline_code, discipline_name FROM ky_school_double_first
                 WHERE school_name = :name AND round = 2 ORDER BY discipline_code"""),
        {"name": r.name},
    ).fetchall()
    item["double_first_disciplines"] = [
        {"discipline_code": s.discipline_code, "discipline_name": s.discipline_name} for s in syl
    ]
    # 站内院校库联动（按校名匹配 kaoyan_schools，供前端跳转既有详情页）
    link = db.execute(
        text("SELECT id FROM kaoyan_schools WHERE name = :name AND deleted_at IS NULL LIMIT 1"),
        {"name": r.name},
    ).fetchone()
    item["kaoyan_school_id"] = link.id if link else None
    item["caveats"] = CAVEATS
    return item


@router.get("/disciplines")
def list_disciplines(db: Session = Depends(get_db)):
    """08 工学学科字典（学硕 0801-0839 + 专硕 0851-0861，48 条）。"""
    rows = db.execute(
        text("""SELECT d.code, d.name, d.degree_type, d.eval4_status, d.note,
                       COUNT(e.id) AS school_cnt
                  FROM ky_discipline d
                  LEFT JOIN ky_school_discipline_eval e
                    ON e.discipline_code = d.code AND e.eval_round = 4
                 GROUP BY d.code, d.name, d.degree_type, d.eval4_status, d.note
                 ORDER BY d.code""")
    ).fetchall()
    return {
        "items": [
            {
                "code": r.code,
                "name": r.name,
                "degree_type": r.degree_type,
                "eval4_status": r.eval4_status,
                "note": r.note,
                "school_cnt": r.school_cnt,
            }
            for r in rows
        ],
        "caveats": CAVEATS,
    }


@router.get("/disciplines/{code}/rank")
def discipline_rank(code: str, db: Session = Depends(get_db)):
    """按学科选校：第四轮评估榜单，按等级排序；joint/institute 单独分组不混排。"""
    disc = db.execute(
        text("SELECT code, name, degree_type, eval4_status, note FROM ky_discipline WHERE code = :c"),
        {"c": code},
    ).fetchone()
    if disc is None:
        raise HTTPException(404, "学科代码不存在")
    rows = db.execute(
        text("""SELECT e.school_name, e.school_code, e.grade, e.eval_scope,
                       s.id AS ky_school_id, s.province, s.is_985, s.is_211, s.is_double_first
                  FROM ky_school_discipline_eval e
                  LEFT JOIN ky_school s ON s.name = e.school_name
                 WHERE e.discipline_code = :c AND e.eval_round = 4"""),
        {"c": code},
    ).fetchall()
    groups = {"normal": [], "joint": [], "institute": []}
    for r in rows:
        groups.setdefault(r.eval_scope, []).append(
            {
                "school_name": r.school_name,
                "school_code": r.school_code,
                "grade": r.grade,
                "eval_scope": r.eval_scope,
                "ky_school_id": r.ky_school_id,
                "province": r.province,
                "is_985": bool(r.is_985),
                "is_211": bool(r.is_211),
                "is_double_first": bool(r.is_double_first),
            }
        )
    for g in groups.values():
        g.sort(key=lambda x: (GRADE_ORDER.get(x["grade"], 99), x["school_name"]))
    return {
        "discipline": {
            "code": disc.code,
            "name": disc.name,
            "degree_type": disc.degree_type,
            "eval4_status": disc.eval4_status,
            "note": disc.note,
        },
        "total": len(rows),
        "groups": groups,
        "caveats": CAVEATS,
    }
