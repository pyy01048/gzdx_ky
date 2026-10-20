# -*- coding: utf-8 -*-
"""考研择校数据中心 API 路由（增强版）。

D1: 择校推荐算法增强（复录比+录取均分+区域+学科权重）
D3: 择校结果关联 Goal 表
D5: 区域择校地图热力图数据
D6: 招生人数分布散点图数据
C5: 数据版本管理（历史对比）
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from typing import Optional, List
import json
import re

from services.dbapi_compat import wrap_conn
from utils.timeutil import (
    day_bucket_text_expr,
    iso_utc_z,
    local_today,
    utcnow,
)
from database import SessionLocal
from models import (
    KaoyanSchool, KaoyanCollege, KaoyanMajor,
    KaoyanAdmission, KaoyanAdmissionDetail, KaoyanScoreLine, KaoyanSubject, Goal,
    KaoyanCollectionRun, SchoolAlias,
)
from services.kaoyan.datasource_registry import (
    list_datasources, register_datasource, get_datasource, resolve_source_type,
)
from services.kaoyan.school_alias import normalize_alias, match_aliases
from services.kaoyan.data_years import available_years, resolve_year

router = APIRouter(prefix="/api/kaoyan", tags=["考研择校"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 院校列表聚合（对标 txkyer：学院数/专业方向/进复试/拟录取/复录比/均分/热度/星级）
# --------------------------------------------------------------------------- #
# 星级：由院校层级派生（数据无「星级」列，透明派生而非伪造）
_STAR_BY_LEVEL = {
    "985": 5.0, "C9": 5.0, "211": 4.0, "双一流": 4.0, "双非": 3.0,
}


def _derive_star(level: Optional[str]) -> float:
    if not level:
        return 3.0
    return _STAR_BY_LEVEL.get(level.strip(), 3.0)


def _coverage_score(agg: dict, school) -> int:
    """资料完整度（列表卡片用，5 项/100 分）。

    口径透明：专业目录 25 + 招生数据 25 + 分数线 20 + 简介 15 + 官网 15。
    """
    score = 0
    if int(agg.get("major_count") or 0) > 0:
        score += 25
    if int(agg.get("admit") or 0) > 0 or int(agg.get("enroll") or 0) > 0:
        score += 25
    if int(agg.get("scoreline_count") or 0) > 0:
        score += 20
    if getattr(school, "intro", None):
        score += 15
    if getattr(school, "official_url", None):
        score += 15
    return score


def _aggregate_schools(db: Session, school_ids: List[int]) -> dict:
    """按学校聚合学院数/专业方向数/招生指标（取每校最近有数据的年份）。

    返回 {school_id: {college_count, major_count, year, enroll, retest, admit,
                     retest_ratio, admit_avg, major_avg, heat}}
    高效批量查询（避免 N+1）：仅对当页 school_ids 聚合。
    """
    if not school_ids:
        return {}
    ids = list(school_ids)

    college_cnt = dict(
        db.query(KaoyanCollege.school_id, func.count(KaoyanCollege.id))
        .filter(KaoyanCollege.school_id.in_(ids)).group_by(KaoyanCollege.school_id).all()
    )
    major_cnt = dict(
        db.query(KaoyanMajor.school_id, func.count(KaoyanMajor.id))
        .filter(KaoyanMajor.school_id.in_(ids)).group_by(KaoyanMajor.school_id).all()
    )
    scoreline_cnt = dict(
        db.query(KaoyanScoreLine.school_id, func.count(KaoyanScoreLine.id))
        .filter(KaoyanScoreLine.school_id.in_(ids)).group_by(KaoyanScoreLine.school_id).all()
    )
    # 每校最近年份
    latest_year = dict(
        db.query(KaoyanAdmission.school_id, func.max(KaoyanAdmission.year))
        .filter(KaoyanAdmission.school_id.in_(ids)).group_by(KaoyanAdmission.school_id).all()
    )
    # 招生指标：按 (school, 最近年份) 聚合各专业
    adm_rows = (
        db.query(
            KaoyanAdmission.school_id,
            func.sum(KaoyanAdmission.enroll_count),
            func.sum(KaoyanAdmission.retest_count),
            func.sum(KaoyanAdmission.admit_count),
            func.avg(KaoyanAdmission.admit_avg_score),
            func.avg(KaoyanAdmission.major_avg_score),
        )
        .filter(KaoyanAdmission.school_id.in_(ids))
        .group_by(KaoyanAdmission.school_id)
        .all()
    )
    adm = {}
    for sid, enroll, retest, admit, aavg, mavg in adm_rows:
        retest = int(retest or 0)
        admit = int(admit or 0)
        ratio = round(retest / admit, 2) if admit else None
        adm[sid] = {
            "year": latest_year.get(sid),
            "enroll": int(enroll or 0) or None,
            "retest": retest or None,
            "admit": admit or None,
            "retest_ratio": ratio,
            "admit_avg": round(float(aavg), 1) if aavg else None,
            "major_avg": round(float(mavg), 1) if mavg else None,
        }

    out = {}
    for sid in ids:
        a = adm.get(sid, {})
        admit = a.get("admit") or 0
        enroll = a.get("enroll") or 0
        # 热度（无「报考人数」列，透明派生代理）：拟录取规模为主 + 拟招生规模为辅
        heat = int(round(admit * 1.0 + enroll * 0.3))
        out[sid] = {
            "college_count": int(college_cnt.get(sid, 0)),
            "major_count": int(major_cnt.get(sid, 0)),
            "scoreline_count": int(scoreline_cnt.get(sid, 0)),
            "heat": heat,
            **a,
        }
    return out


# ---- 学科 ----
@router.get("/subjects")
def list_subjects(db: Session = Depends(get_db)):
    items = db.query(KaoyanSubject).order_by(KaoyanSubject.sort_order).all()
    return [{"id": s.id, "code": s.code, "name": s.name, "category": s.category,
             "exam_overlap": s.exam_overlap, "description": s.description} for s in items]


# ---- 院校列表 ----
@router.get("/schools")
def list_schools(
    level: Optional[str] = Query(None, description="层级：985/211/双一流/双非（不传=不限；库内level 为空的院校在列表页归入「未分类」）"),
    province: Optional[str] = Query(None, description="省份"),
    type: Optional[str] = Query(None, description="院校类型：公办/科研院所/军队院校/其他"),
    region: Optional[str] = Query(None, description="分区：A/B（B区=内蒙古/广西/海南/贵州/云南/西藏/甘肃/青海/宁夏/新疆）"),
    subject_code: Optional[str] = Query(None, description="学科代码"),
    keyword: Optional[str] = Query(None, description="院校名关键词"),
    year: Optional[int] = Query(None, description="年份筛选"),
    sort: Optional[str] = Query("heat", description="排序：heat 热度 / admit 拟录取 / ratio 复录比 / name 名称 / id"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """院校列表（对标 txkyer 核心数据表格）。

    每行返回：层级/省份/学校/学院数/专业方向数/进复试/拟录取/复录比/录取均分/专业课均分/热度/星级。
    热度与星级为透明派生（无对应原始列，口径见 _aggregate_schools / _derive_star），非伪造数据。
    """
    # V16 A/B 区筛选：B 区十省固定映射（国家线分区口径），纯派生不动库
    _REGION_B = ("内蒙古", "广西", "海南", "贵州", "云南", "西藏", "甘肃", "青海", "宁夏", "新疆")
    q = db.query(KaoyanSchool)
    if level:
        q = q.filter(KaoyanSchool.level == level)
    if province:
        q = q.filter(KaoyanSchool.province == province)
    # M3-1：A/B 区与院校类型（新增列，服务端筛选；列不存在时静默跳过以保持向后兼容）
    if region and hasattr(KaoyanSchool, "region"):
        q = q.filter(KaoyanSchool.region == region)
    if type and hasattr(KaoyanSchool, "type"):
        q = q.filter(KaoyanSchool.type == type)
    if region == "B":
        q = q.filter(KaoyanSchool.province.in_(_REGION_B))
    elif region == "A":
        q = q.filter(~KaoyanSchool.province.in_(_REGION_B))
    if keyword:
        alias_ids = [s.id for s in match_aliases(db, keyword)]
        if alias_ids:
            q = q.filter(
                (KaoyanSchool.name.like(f"%{keyword}%")) | (KaoyanSchool.id.in_(alias_ids))
            )
        else:
            q = q.filter(KaoyanSchool.name.like(f"%{keyword}%"))
    if subject_code:
        school_ids = [r[0] for r in db.query(KaoyanMajor.school_id).filter(KaoyanMajor.subject_code == subject_code).all()]
        if school_ids:
            q = q.filter(KaoyanSchool.id.in_(school_ids))
        else:
            return {"total": 0, "page": page, "page_size": page_size, "items": []}

    schools = q.all()  # 全量（≤数百所）→ 聚合 → 排序 → 分页，保证按热度/均分排序跨页正确
    agg = _aggregate_schools(db, [s.id for s in schools])

    def enriched(s):
        a = agg.get(s.id, {})
        return {
            "id": s.id, "name": s.name, "level": s.level,
            "province": s.province, "city": s.city,
            # M3-1：新增列（getattr 兼容旧库未加列的情况）
            "region": getattr(s, "region", None),
            "type": getattr(s, "type", None),
            "logo_url": s.logo_url, "tags": s.tags,
            "intro": (s.intro or "")[:200],
            "official_url": s.official_url,
            "data_source": s.data_source,
            "data_source_type": resolve_source_type(s.data_source),
            # —— benchmark 表格列 ——
            "college_count": a.get("college_count", 0),
            "major_count": a.get("major_count", 0),
            "year": a.get("year"),
            "enroll_count": a.get("enroll"),
            "retest_count": a.get("retest"),      # 进复试
            "admit_count": a.get("admit"),        # 拟录取
            "retest_ratio": a.get("retest_ratio"),# 复录比
            "admit_avg_score": a.get("admit_avg"),# 录取均分
            "major_avg_score": a.get("major_avg"),# 专业课均分
            "heat": a.get("heat", 0),             # 热度（派生）
            "star": _derive_star(s.level),        # 星级（层级派生）
            "scoreline_count": a.get("scoreline_count", 0),
            "coverage_score": _coverage_score(a, s),
        }

    rows = [enriched(s) for s in schools]
    total = len(rows)

    if sort == "name":
        rows.sort(key=lambda r: r["name"] or "")
    elif sort == "id":
        rows.sort(key=lambda r: r["id"])
    elif sort == "admit":
        rows.sort(key=lambda r: (r["admit_count"] or 0), reverse=True)
    elif sort == "ratio":
        rows.sort(key=lambda r: (r["retest_ratio"] or 0), reverse=True)
    elif sort == "avg":
        rows.sort(key=lambda r: (r["admit_avg_score"] or 0), reverse=True)
    else:  # heat（默认）
        rows.sort(key=lambda r: (r["heat"] or 0), reverse=True)

    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "sort": sort,
        "items": page_rows,
    }


# ---- 院校热度榜 TOP N（对标 txkyer 首页热度榜）----
@router.get("/analysis/hot")
def hot_schools(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """热度榜 TOP N。热度为派生代理指标（拟录取规模为主 + 拟招生规模为辅）。"""
    schools = db.query(KaoyanSchool).all()
    agg = _aggregate_schools(db, [s.id for s in schools])
    rows = []
    for s in schools:
        a = agg.get(s.id, {})
        rows.append({
            "id": s.id, "name": s.name, "level": s.level, "province": s.province,
            "heat": a.get("heat", 0), "admit_count": a.get("admit"),
            "retest_ratio": a.get("retest_ratio"), "star": _derive_star(s.level),
        })
    rows.sort(key=lambda r: (r["heat"] or 0), reverse=True)
    ranked = rows[:limit]
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return {"total": len(ranked), "items": ranked}



# ---- 院校详情 ----
@router.get("/schools/{school_id}")
def get_school(school_id: int, db: Session = Depends(get_db)):
    s = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not s:
        raise HTTPException(404, "院校不存在")
    colleges = db.query(KaoyanCollege).filter(KaoyanCollege.school_id == school_id).all()
    # 复用列表页同款聚合：详情页顶部汇总卡片直接可用，口径与列表一致
    agg = _aggregate_schools(db, [school_id]).get(school_id, {})

    # 资料完整度：把用户清单里的核心项逐项标出，页面直接告诉用户缺什么。
    notice_rows = db.execute(text(
        "SELECT notice_type, COUNT(*) FROM kaoyan_notices "
        "WHERE school_id = :sid GROUP BY notice_type"
    ), {"sid": school_id}).fetchall()
    notice_types = {str(t or "公告"): int(n or 0) for t, n in notice_rows}
    notice_count = sum(notice_types.values())
    textbook_count = int(db.execute(text(
        "SELECT COUNT(*) FROM textbook_schools WHERE school_id = :sid"
    ), {"sid": school_id}).scalar() or 0)
    detail_count = int(db.query(KaoyanAdmissionDetail)
                       .filter(KaoyanAdmissionDetail.school_id == school_id).count())
    refbook_count = int(db.execute(text("""
        SELECT COUNT(*) FROM kaoyan_majors
         WHERE school_id = :sid
           AND reference_books IS NOT NULL
           AND reference_books::text NOT IN ('', '[]', 'null', '{}')
    """), {"sid": school_id}).scalar() or 0)
    major_count = int(agg.get("major_count") or 0)
    admit_count = int(agg.get("admit") or 0)
    scoreline_count = int(agg.get("scoreline_count") or 0)
    coverage_items = [
        {"key": "majors", "label": "招生计划 / 专业目录", "ok": major_count > 0,
         "detail": f"{major_count} 个专业方向"},
        {"key": "scorelines", "label": "近 3–5 年复试线", "ok": scoreline_count > 0,
         "detail": f"{scoreline_count} 条分数线"},
        {"key": "admissions", "label": "报录比 / 录取人数", "ok": admit_count > 0,
         "detail": f"拟录取 {admit_count} 人"},
        {"key": "retest", "label": "复试细则", "ok": bool(notice_types.get("复试")),
         "detail": f"{notice_types.get('复试', 0)} 条复试公告"},
        {"key": "reference", "label": "参考书 / 考试大纲", "ok": refbook_count > 0 or textbook_count > 0,
         "detail": f"参考书 {refbook_count} 条 · 教材关联 {textbook_count} 本"},
        {"key": "score_dist", "label": "录取分数分布", "ok": detail_count > 0,
         "detail": f"{detail_count} 条考生明细"},
        {"key": "notices", "label": "招生公告 / 简章", "ok": notice_count > 0,
         "detail": f"{notice_count} 条公告"},
        {"key": "intro", "label": "院校简介", "ok": bool(s.intro),
         "detail": "已收录" if s.intro else "暂无简介"},
        {"key": "official", "label": "官网 / 数据来源", "ok": bool(s.official_url),
         "detail": s.official_url or "未配置"},
    ]
    coverage_score = round(100 * sum(1 for x in coverage_items if x["ok"]) / len(coverage_items))
    return {
        "id": s.id, "name": s.name, "level": s.level,
        "province": s.province, "city": s.city,
        "logo_url": s.logo_url, "intro": s.intro,
        "tags": s.tags, "official_url": s.official_url,
        "college_count": len(colleges),
        "major_count": agg.get("major_count", 0),
        "year": agg.get("year"),
        "enroll_count": agg.get("enroll"),
        "retest_count": agg.get("retest"),
        "admit_count": agg.get("admit"),
        "retest_ratio": agg.get("retest_ratio"),
        "admit_avg_score": agg.get("admit_avg"),
        "major_avg_score": agg.get("major_avg"),
        "heat": agg.get("heat", 0),
        "star": _derive_star(s.level),
        "scoreline_count": scoreline_count,
        "notice_count": notice_count,
        "notice_types": notice_types,
        "textbook_count": textbook_count,
        "admission_detail_count": detail_count,
        "coverage_score": coverage_score,
        "coverage_items": coverage_items,
    }


# ---- 院校专业方向 ----
@router.get("/schools/{school_id}/majors")
def get_school_majors(school_id: int, db: Session = Depends(get_db)):
    """专业方向列表，附 kb_coverage：该专业初试专业课在本知识库里的语料覆盖。

    覆盖口径见 services/major_coverage.py（专业课名精确匹配，公共课不参与）。
    """
    from services import major_coverage as mc

    majors = db.query(KaoyanMajor).filter(KaoyanMajor.school_id == school_id).all()
    supply = mc.subject_supply(db)
    return [{
        "id": m.id, "code": m.code, "name": m.name,
        "research_direction": m.research_direction,
        "subject_code": m.subject_code,
        "exam_subjects": m.exam_subjects,
        "reference_books": m.reference_books,
        "degree_type": m.degree_type,
        "kb_coverage": mc.coverage_for(m.exam_subjects, supply),
    } for m in majors]


# ---- 院校历年分数线 ----
@router.get("/schools/{school_id}/scores")
def get_school_scores(school_id: int, db: Session = Depends(get_db)):
    lines = db.query(KaoyanScoreLine).filter(
        KaoyanScoreLine.school_id == school_id
    ).order_by(KaoyanScoreLine.year.desc()).all()
    return [{
        "year": l.year, "total_line": l.total_line,
        "politics_line": l.politics_line, "english_line": l.english_line,
        "math_line": l.math_line, "major_line": l.major_line,
        "national_line": l.national_line, "retest_line": l.retest_line,
        "line_type": l.line_type,
        "source": l.source,
        "source_type": resolve_source_type(l.source),
    } for l in lines]


# ---- 院校历年招生数据 ----
@router.get("/schools/{school_id}/admissions")
def get_school_admissions(school_id: int, db: Session = Depends(get_db)):
    # join majors 带出专业代码/名称：详情页「各专业均分对比」图表与参考站
    # （txkyer 详细数据表）同维度的前提
    items = (
        db.query(KaoyanAdmission, KaoyanMajor.code, KaoyanMajor.name)
        .outerjoin(KaoyanMajor, KaoyanAdmission.major_id == KaoyanMajor.id)
        .filter(KaoyanAdmission.school_id == school_id)
        .order_by(KaoyanAdmission.year.desc())
        .all()
    )
    return [{
        "year": a.year, "enroll_count": a.enroll_count,
        "retest_count": a.retest_count, "admit_count": a.admit_count,
        "admit_avg_score": a.admit_avg_score,
        "major_avg_score": a.major_avg_score,
        "retest_ratio": a.retest_ratio,
        "major_code": code,
        "major_name": name or "未标注专业",
        "data_source": a.data_source,
    } for a, code, name in items]


@router.get("/schools/{school_id}/admissions/details")
def get_school_admission_details(school_id: int, year: int | None = None,
                                 name: str | None = None,
                                 limit: int = Query(200, ge=1, le=200),
                                 db: Session = Depends(get_db)):
    """院校拟录取/复试名单逐人明细（DeepSeek-OCR 扫描件名单）。"""
    q = db.query(KaoyanAdmissionDetail).filter(KaoyanAdmissionDetail.school_id == school_id)
    if year is not None:
        q = q.filter(KaoyanAdmissionDetail.year == year)
    if name:
        q = q.filter(KaoyanAdmissionDetail.name.like(f"%{name}%"))
    limit = max(1, min(limit, 5000))
    items = q.order_by(KaoyanAdmissionDetail.year.desc(), KaoyanAdmissionDetail.id).limit(limit).all()
    return [{
        "id": d.id,
        "year": d.year,
        "exam_no": d.exam_no,
        "name": d.name,
        "major_name": d.major_name,
        "score_initial": d.score_initial,
        "score_retest": d.score_retest,
        "score_total": d.score_total,
        "data_source": d.data_source,
    } for d in items]


# ---- M3-4: 招生计划聚合（院系 → 专业 → 拟招人数 → 考试科目） ----
# 考试科目原始串形如 "(302)数学（二） | (204)英语（二） | (857)电子技术基础"，
# 需解析为结构化 [{code, name}]：code=3 位科目代码（如 "302"），name=纯科目名。
_EXAM_SUBJECT_RE = re.compile(
    r"^\s*[（(]?\s*(?P<code>\d{3})\s*[)）]?\s*(?P<name>.*?)\s*$"
)


def _decode_escaped_text(raw) -> str:
    """修复「JSON 双重编码」文本。

    历史导入脚本把中文串先 ``json.dumps``（ensure_ascii=True）再落库，导致
    ``kaoyan_majors.exam_subjects`` 在库内长这样（字面量，含外层引号）::

        "(302)\u6570\u5b66\uff08\u4e8c\uff09 | (204)\u82f1\u8bed\uff08\u4e8c\uff09"

    后果：``"数学" in s`` 永远为假 → 公开课统计恒为空；前端展示为转义乱码。
    本函数做**幂等**解码：不是该形态就原样返回，最多解两层。
    """
    text = str(raw)
    for _ in range(2):
        stripped = text.strip()
        looks_json_string = (
            len(stripped) >= 2
            and stripped.startswith('"')
            and stripped.endswith('"')
        )
        has_escape = "\\u" in stripped
        if not (looks_json_string or has_escape):
            break
        try:
            decoded = json.loads(stripped)
        except Exception:
            break
        if not isinstance(decoded, str) or decoded == stripped:
            break
        text = decoded
    return text


def _split_exam_subject_segments(raw) -> List[str]:
    """把 exam_subjects 原始值切成单科目片段列表。

    支持 JSON 数组（list/tuple）与字符串两种存储形态；
    字符串按 ``|`` 拆分，并兼容中文分号与换行。
    文本形态先过 :func:`_decode_escaped_text`，兼容历史遗留的双重编码数据。
    """
    if raw is None:
        return []
    segments: List[str] = []
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if item is None:
                continue
            segments.extend(_decode_escaped_text(item).split("|"))
    else:
        text = _decode_escaped_text(raw)
        segments.extend(text.replace("；", "|").replace("\n", "|").split("|"))
    return segments


def _parse_exam_subjects(raw) -> List[dict]:
    """把考试科目原始值解析为结构化列表 ``[{"code": "302", "name": "数学（二）"}]``。

    解析规则：
      - 每段形如 ``(302)数学（二）`` / ``302数学二`` / ``（302）数学（二）``；
      - ``code`` 取开头的 3 位数字（缺失则为 ``None``），``name`` 为去掉编号后的科目名；
      - 空段丢弃；结果保序，并按 ``(code, name)`` 去重。

    无编号的科目（如 "无" 或纯文本）仍会保留，``code`` 为 ``None``。
    """
    structured: List[dict] = []
    seen = set()
    for seg in _split_exam_subject_segments(raw):
        seg = seg.strip()
        if not seg:
            continue
        match = _EXAM_SUBJECT_RE.match(seg)
        if match:
            code = match.group("code")
            name = match.group("name").strip()
        else:
            code = None
            name = seg
        if not name:
            continue
        key = (code, name)
        if key in seen:
            continue
        seen.add(key)
        structured.append({"code": code, "name": name})
    return structured


def _normalize_exam_subjects(raw) -> List[str]:
    """把考试科目原始值归一为**纯科目名**字符串列表（兼容旧契约）。

    等价于 :func:`_parse_exam_subjects` 只取 ``name`` 字段。
    """
    return [item["name"] for item in _parse_exam_subjects(raw)]


# 全国统考公共课：政治 / 外语 / 数学（含经济类联考与部分自命题数学）。
# 判定「业务课二（专业课）」＝ 初试科目里**不是**公共课的那一门。
_PUBLIC_SUBJECT_CODES = {
    "101",  # 思想政治理论
    "199",  # 管理类联考综合能力
    "201", "202", "203", "204",  # 英语（一/二）、俄语、日语
    "301", "302", "303", "304",  # 数学（一/二/三）、教育学专业基础
    "306",  # 西医综合
    "307",  # 中医综合
}
_PUBLIC_SUBJECT_KEYS = ("政治", "思想", "英语", "外语", "俄语", "日语", "数学")


def _is_public_subject(item: dict) -> bool:
    """该考试科目是否属于全国统考公共课（政治 / 外语 / 数学）。

    判据：3 位科目代码命中统考代码表，或科目名含公共课关键词。
    """
    code = (item.get("code") or "").strip()
    if code in _PUBLIC_SUBJECT_CODES:
        return True
    name = (item.get("name") or "").strip()
    return any(k in name for k in _PUBLIC_SUBJECT_KEYS)


@router.get("/schools/{school_id}/enrollment-plan")
def get_school_enrollment_plan(
    school_id: int,
    year: Optional[int] = Query(None, description="招生年度，缺省取该校最大年份"),
    db: Session = Depends(get_db),
):
    """院校招生计划聚合端点（M3-4）。

    一次性返回「院系 → 专业 → 拟招人数 → 考试科目」，避免前端两次调用拼接。
    数据来源：kaoyan_colleges ⋈ kaoyan_majors ⋈ kaoyan_admissions。

    - ``year`` 缺省时取该校招生数据中的最大年份；
    - 该年无招生数据时如实返回空 ``items``（不伪造）；
    - 考试科目归一为纯科目名数组，同时保留原始串供溯源。

    向后兼容：不影响 ``/majors``、``/admissions`` 端点行为。
    """
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not school:
        raise HTTPException(404, f"院校不存在: {school_id}")

    # 年份解析：显式传入则用之；否则取该校 admissions 最大年份（无数据则 None）
    if year is None:
        year = (
            db.query(func.max(KaoyanAdmission.year))
            .filter(KaoyanAdmission.school_id == school_id)
            .scalar()
        )

    # 一次 join 拉全：admissions 为驱动，左连 majors、colleges
    # （以 admissions 的 year 过滤，确保 enroll_count 语义正确）
    rows = (
        db.query(
            KaoyanAdmission,
            KaoyanMajor,
            KaoyanCollege.name,
        )
        .outerjoin(KaoyanMajor, KaoyanAdmission.major_id == KaoyanMajor.id)
        .outerjoin(KaoyanCollege, KaoyanMajor.college_id == KaoyanCollege.id)
        .filter(KaoyanAdmission.school_id == school_id)
        .filter(KaoyanAdmission.year == year)
        .order_by(KaoyanCollege.name.is_(None), KaoyanCollege.name, KaoyanMajor.name)
        .all()
    ) if year is not None else []

    items: List[dict] = []
    for adm, major, college_name in rows:
        raw_subjects = major.exam_subjects if major is not None else None
        # 结构化考试科目：[{code, name}]（前端主用）
        structured = _parse_exam_subjects(raw_subjects)
        items.append({
            "college": college_name,
            "major": (major.name if major is not None else None) or "未标注专业",
            "major_code": major.code if major is not None else None,
            "direction": major.research_direction if major is not None else None,
            "degree_type": major.degree_type if major is not None else None,
            "enroll_count": adm.enroll_count,
            "retest_count": adm.retest_count,
            "admit_count": adm.admit_count,
            # 结构化科目（含 3 位科目代码）：前端可按 code 做科目归类/统计
            "exam_subjects": structured,
            # 兼容：纯科目名扁平数组，避免破坏既有前端消费方
            "exam_subjects_names": [s["name"] for s in structured],
            # 原始串保留，不丢（溯源用）
            "exam_subjects_raw": raw_subjects,
        })

    return {
        "school_id": school.id,
        "school_name": school.name,
        "year": year,
        "items": items,
    }


# ---- 多年趋势分析 ----
@router.get("/analysis/trend")
def analysis_trend(
    school_id: int = Query(..., description="院校ID"),
    metric: str = Query("total_line", description="指标"),
    years: int = Query(5, description="近N年"),
    db: Session = Depends(get_db),
):
    end_year = local_today().year
    start_year = end_year - years + 1
    if metric in ("total_line", "retest_line", "national_line"):
        rows = db.query(KaoyanScoreLine).filter(
            KaoyanScoreLine.school_id == school_id,
            KaoyanScoreLine.year >= start_year,
        ).order_by(KaoyanScoreLine.year).all()
        data = [{"year": r.year, "value": getattr(r, metric, None)} for r in rows]
    elif metric in ("enroll_count", "admit_count", "retest_count", "admit_avg_score", "major_avg_score", "retest_ratio"):
        rows = db.query(KaoyanAdmission).filter(
            KaoyanAdmission.school_id == school_id,
            KaoyanAdmission.year >= start_year,
        ).order_by(KaoyanAdmission.year).all()
        data = [{"year": r.year, "value": getattr(r, metric, None)} for r in rows]
    else:
        raise HTTPException(400, f"不支持的指标: {metric}")
    return {"school_id": school_id, "metric": metric, "data": data}


# ---- C5: 历史对比（同年多校 or 同校多年） ----
@router.get("/analysis/compare")
def analysis_compare(
    school_ids: str = Query(..., description="院校ID列表，逗号分隔，最多5个"),
    db: Session = Depends(get_db),
):
    ids = [int(x) for x in school_ids.split(",")[:5]]
    result = []
    for sid in ids:
        s = db.query(KaoyanSchool).filter(KaoyanSchool.id == sid).first()
        if not s:
            continue
        scores = db.query(KaoyanScoreLine).filter(
            KaoyanScoreLine.school_id == sid
        ).order_by(KaoyanScoreLine.year.desc()).limit(3).all()
        admits = db.query(KaoyanAdmission).filter(
            KaoyanAdmission.school_id == sid
        ).order_by(KaoyanAdmission.year.desc()).limit(3).all()
        result.append({
            "id": s.id, "name": s.name, "level": s.level,
            "province": s.province,
            "recent_scores": [{"year": l.year, "total_line": l.total_line, "retest_line": l.retest_line} for l in scores],
            "recent_admissions": [{"year": a.year, "enroll_count": a.enroll_count, "admit_count": a.admit_count, "admit_avg_score": a.admit_avg_score} for a in admits],
        })
    return {"items": result}


# ---- D1: 智能择校推荐（增强版：多维权重打分） ----
@router.get("/analysis/recommend")
def analysis_recommend(
    score: int = Query(..., description="预估总分"),
    level: Optional[str] = Query(None, description="目标层级"),
    province: Optional[str] = Query(None, description="目标省份（区域偏好）"),
    subject_code: Optional[str] = Query(None, description="学科代码（学科匹配）"),
    target_avg_score: Optional[int] = Query(None, description="目标录取均分（匹配录取均分）"),
    max_retest_ratio: Optional[float] = Query(1.5, description="最大可接受复录比"),
    year: Optional[int] = Query(None, description="参考年份；不传则用库里最新的年份"),
    db: Session = Depends(get_db),
):
    """D1: 多维权重择校推荐。一次 JOIN 查询消除 N+1。"""
    year = resolve_year(db, year)
    years = available_years(db)
    if year is None:
        # 库里还没有择校数据：给空结果 + 空年份列表，让前端显示导入空态，
        # 而不是拿一个写死的年份去查出一个「0 所院校推荐」的假结论。
        return {
            "score": score, "year": None, "available_years": [],
            "recommendations": [],
            "algorithm": "多维权重: 分差40% + 复录比20% + 录取均分20% + 区域10% + 学科10%",
            "note": "院校库为空：导入招生/分数线数据后这里会按库里最新年份给出推荐",
        }
    # 子查询：按学校去重，取最低分数线
    subq = db.query(
        KaoyanScoreLine.school_id,
        func.min(KaoyanScoreLine.total_line).label("min_line"),
        func.min(KaoyanScoreLine.retest_line).label("min_retest"),
        func.min(KaoyanScoreLine.national_line).label("min_national"),
    ).filter(
        KaoyanScoreLine.year == year,
        KaoyanScoreLine.total_line <= score,
    ).group_by(KaoyanScoreLine.school_id).subquery()

    q = db.query(
        subq.c.school_id,
        subq.c.min_line,
        subq.c.min_retest,
        subq.c.min_national,
        KaoyanSchool,
        KaoyanAdmission,
    ).join(
        KaoyanSchool, subq.c.school_id == KaoyanSchool.id
    ).outerjoin(
        KaoyanAdmission,
        (KaoyanAdmission.school_id == KaoyanSchool.id) & (KaoyanAdmission.year == year),
    )

    if province:
        q = q.filter(KaoyanSchool.province == province)
    if level:
        q = q.filter(KaoyanSchool.level == level)

    rows = q.limit(100).all()

    # 预加载学科匹配：有该学科的 school_id 集合
    subject_schools = set()
    if subject_code:
        subject_schools = {
            r[0] for r in db.query(KaoyanMajor.school_id).filter(
                KaoyanMajor.subject_code == subject_code
            ).all()
        }

    recs = []
    seen = set()
    for school_id, total_line, retest_line, national_line, s, adm in rows:
        if s.id in seen:
            continue
        seen.add(s.id)

        score_total = 0.0
        gap = score - (total_line or 0)
        gap_score = max(0, 40 - gap * 0.4)
        score_total += gap_score

        retest_ratio = adm.retest_ratio if adm else None
        ratio_score = 0.0
        if retest_ratio and retest_ratio > 0:
            if retest_ratio <= (max_retest_ratio or 1.5):
                ratio_score = max(0, 20 - (retest_ratio - 1.0) * 10)
                score_total += ratio_score
        else:
            ratio_score = 10.0
            score_total += ratio_score

        admit_avg = adm.admit_avg_score if adm else None
        avg_score = 0.0
        if target_avg_score and admit_avg:
            avg_gap = abs(target_avg_score - admit_avg)
            avg_score = max(0, 20 - avg_gap * 0.2)
            score_total += avg_score
        else:
            avg_score = 10.0
            score_total += avg_score

        region_score = 5.0
        if province and s.province == province:
            region_score = 10.0
            score_total += 10
        else:
            score_total += 5

        subject_score = 5.0
        if subject_code:
            subject_score = 10.0 if s.id in subject_schools else 3.0
            score_total += subject_score
        else:
            score_total += 5

        if gap > 30:
            safety = "稳妥"
        elif gap > 10:
            safety = "适中"
        else:
            safety = "冲刺"

        recs.append({
            "school_id": s.id, "name": s.name, "level": s.level,
            "province": s.province, "retest_line": retest_line,
            "national_line": national_line, "total_line": total_line,
            "gap": gap, "safety": safety,
            "retest_ratio": retest_ratio,
            "admit_avg_score": admit_avg,
            "data_source": s.data_source,
            "data_source_type": resolve_source_type(s.data_source),
            "score": round(score_total, 1),
            "score_breakdown": {
                "gap": round(gap_score, 1),
                "retest_ratio": round(ratio_score, 1),
                "admit_avg": round(avg_score, 1),
                "region": round(region_score, 1),
                "subject": round(subject_score, 1),
            },
        })

    recs.sort(key=lambda x: x["score"], reverse=True)
    top = recs[:20]
    # 语料可靠度：该校有多少专业的初试专业课在本库有语料
    # （口径见 services/major_coverage.py：专业课名精确匹配，公共课不计入分母）
    from services import major_coverage as mc

    supply = mc.subject_supply(db)
    cov = mc.school_coverage(db, supply, [r["school_id"] for r in top])
    for r in top:
        c = cov.get(r["school_id"]) or {}
        r["kb_coverage"] = {k: int(c.get(k, 0))
                            for k in ("majors", "covered", "thin", "unindexed", "uncovered")}

    return {
        "score": score, "year": year, "available_years": years,
        "recommendations": top,
        "algorithm": "多维权重: 分差40% + 复录比20% + 录取均分20% + 区域10% + 学科10%",
    }


# ---- D3: 把推荐院校设为目标（关联 Goal 表） ----
@router.post("/analysis/recommend/{school_id}/set-goal")
def set_recommend_as_goal(
    school_id: int,
    target_score: Optional[int] = Query(None, description="目标总分"),
    db: Session = Depends(get_db),
):
    """D3: 将推荐院校设为考研目标，写入 Goal 表。"""
    s = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not s:
        raise HTTPException(404, "院校不存在")

    goal = db.query(Goal).order_by(Goal.id.asc()).first()
    if not goal:
        goal = Goal()
        db.add(goal)
    goal.university = s.name
    if target_score:
        goal.total_score_target = target_score
    goal.updated_at = utcnow()
    db.commit()
    return {"success": True, "goal_university": s.name, "target_score": target_score}


# ---- D4: 自然语言择校问答引擎 ----
PROVINCE_NAMES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
    "台湾", "香港", "澳门",
]
LEVEL_NAMES = ["985", "211", "双一流", "双非"]
# 「一本/二本/民办」是高考录取批次旧口径，教育部学科目录中无此分类，库内已清理完毕。
# 但用户口语仍会说「考一本的学校」，故保留解析能力并统一归一到「双非」，
# 保证解析结果仍能命中数据，而不是静默失效。
_LEVEL_ALIAS = {"一本": "双非", "二本": "双非", "三本": "双非", "重点": "双非"}
# 匹配顺序：先长后短，避免「一本」抢在「双非」类词前误命中（实际无重叠，仅为稳妥）
_LEVEL_PARSE_KEYS = LEVEL_NAMES + list(_LEVEL_ALIAS.keys())


def _parse_level(q: str) -> Optional[str]:
    """从自然语言中提取院校层级，归一到权威取值（985/211/双一流/双非）。"""
    hit = next((lv for lv in _LEVEL_PARSE_KEYS if lv in q), None)
    if hit is None:
        return None
    return _LEVEL_ALIAS.get(hit, hit)


def _parse_question(question: str) -> dict:
    """从自然语言问题中提取结构化择校条件。"""
    q = question or ""
    m = re.search(r"(?:考|大概|约|预估)?\s*(\d{3})\s*分", q)
    score = int(m.group(1)) if m else None
    province = next((p for p in PROVINCE_NAMES if p in q), None)
    level = _parse_level(q)
    return {
        "score": score,
        "province": province,
        "level": level,
        "retest_intent": "复录比" in q,
        "admission_intent": "招生" in q or "人数" in q,
    }


def _format_recommendations(recs: List[dict], max_n: int = 5) -> str:
    lines = []
    for i, r in enumerate(recs[:max_n], 1):
        lines.append(
            f"{i}. {r['name']}（{r.get('level') or '-'} · {r.get('province') or '-'}）"
            f" 分数线 {r.get('total_line') or '-'} 分差+{r.get('gap')} "
            f"复录比 {r.get('retest_ratio') or '-'} 综合评分 {r.get('score')} 安全度:{r.get('safety')}"
        )
    return "\n".join(lines)


@router.post("/assistant/query")
def assistant_query(question: str = Query(..., description="自然语言择校问题"), db: Session = Depends(get_db)):
    """D4: 择校问答新引擎。解析自然语言 → 结构化条件 → 调用推荐/统计接口 → 生成回答。"""
    parsed = _parse_question(question)
    answer = ""
    extra = []
    # 年份一律由库里数据决定（见 services/kaoyan/data_years.py）。
    # 以前这里三处写死 2026，用户导入的是别的年份时答案仍在讲「2026 年」。
    ref_year = resolve_year(db)

    if parsed["score"]:
        rec_data = analysis_recommend(
            score=parsed["score"],
            level=parsed["level"],
            province=parsed["province"],
            subject_code=None,
            target_avg_score=None,
            max_retest_ratio=None,
            year=None,
            db=db,
        )
        recs = rec_data.get("recommendations", [])
        conds = []
        if parsed["province"]:
            conds.append(f"偏好省份 {parsed['province']}")
        if parsed["level"]:
            conds.append(f"目标层级 {parsed['level']}")
        cond_part = "（" + "、".join(conds) + "）" if conds else ""
        answer = (
            f"按你的预估分数 {parsed['score']} 分{cond_part}，基于 {rec_data.get('year')} 年数据推荐 {len(recs)} 所院校（综合评分排序）：\n"
            + _format_recommendations(recs)
        )
        extra = recs[:5]
    elif parsed["retest_intent"]:
        # 复录比低优先：按库里最新年份的复录比升序
        rows = []
        if ref_year is not None:
            rows = db.query(
                KaoyanSchool.name, KaoyanSchool.level, KaoyanSchool.province,
                KaoyanAdmission.retest_ratio, KaoyanAdmission.enroll_count,
            ).join(KaoyanAdmission, KaoyanAdmission.school_id == KaoyanSchool.id).filter(
                KaoyanAdmission.year == ref_year, KaoyanAdmission.retest_ratio.isnot(None)
            ).order_by(KaoyanAdmission.retest_ratio.asc()).limit(8).all()
        if parsed["level"]:
            rows = [r for r in rows if r[1] == parsed["level"]][:8]
        lines = [
            f"{i}. {r[0]}（{r[1] or '-'} · {r[2] or '-'}）复录比 {r[3]} 招生 {r[4] or '-'}"
            for i, r in enumerate(rows, 1)
        ]
        answer = f"{ref_year} 年复录比最低的院校参考（复试竞争越小越友好）：\n" + "\n".join(lines) if lines else "暂无复录比数据（院校库还没导入对应年份的招生记录）"
    elif parsed["admission_intent"]:
        sc = analysis_scatter(year=None, db=db)
        items = sorted(sc.get("items", []), key=lambda x: -(x.get("enroll") or 0))[:8]
        lines = [
            f"{i}. {r['name']}（{r.get('level') or '-'} · {r.get('province') or '-'}）拟招 {r.get('enroll')} 人 均分 {r.get('admit_avg') or '-'}"
            for i, r in enumerate(items, 1)
        ]
        answer = f"{sc.get('year')} 年招生人数较多的院校参考：\n" + "\n".join(lines) if lines else "暂无招生数据（院校库还没导入招生记录）"
    else:
        stats = kaoyan_stats(db=db)
        answer = (
            f"数据库概况：{stats['school_count']} 所院校、{stats['major_count']} 个专业、"
            f"{stats['admission_records']} 条招生数据、{stats['scoreline_records']} 条分数线记录。\n"
            "你可以这样问我：「350分能上哪些211」「哪些985复录比较低」「北京地区哪些学校招生多」等。"
        )

    return {"answer": answer, "recommendations": extra, "parsed": parsed}


# ---- D5: 区域择校地图热力图数据 ----
@router.get("/analysis/heatmap")
def analysis_heatmap(
    year: Optional[int] = Query(None, description="年份；不传则用库里最新的年份"),
    db: Session = Depends(get_db),
):
    """D5: 按省份统计院校数、平均分数线、平均复录比。单次聚合查询。"""
    year = resolve_year(db, year)
    years = available_years(db)
    rows = db.query(
        KaoyanSchool.province,
        func.count(KaoyanSchool.id).label("school_count"),
        func.avg(KaoyanScoreLine.total_line).label("avg_line"),
        func.avg(KaoyanAdmission.retest_ratio).label("avg_ratio"),
    ).outerjoin(
        KaoyanScoreLine,
        (KaoyanScoreLine.school_id == KaoyanSchool.id) & (KaoyanScoreLine.year == year),
    ).outerjoin(
        KaoyanAdmission,
        (KaoyanAdmission.school_id == KaoyanSchool.id) & (KaoyanAdmission.year == year),
    ).group_by(KaoyanSchool.province).all()

    result = []
    for province, school_count, avg_line, avg_ratio in rows:
        if not province:
            continue
        result.append({
            "name": province,
            "value": school_count,
            "avg_line": round(avg_line, 1) if avg_line else None,
            "avg_retest_ratio": round(avg_ratio, 2) if avg_ratio else None,
        })

    return {"year": year, "available_years": years, "items": result}


# ---- D6: 招生人数分布散点图数据 ----
@router.get("/analysis/scatter")
def analysis_scatter(
    year: Optional[int] = Query(None, description="年份；不传则用库里最新的年份"),
    db: Session = Depends(get_db),
):
    """D6: 招生人数 vs 录取均分散点图数据。JOIN 院校信息一次查询。"""
    year = resolve_year(db, year)
    years = available_years(db)
    if year is None:
        return {"year": None, "available_years": [], "items": []}
    rows = db.query(
        KaoyanAdmission.school_id,
        KaoyanSchool.name,
        KaoyanSchool.level,
        KaoyanSchool.province,
        func.avg(KaoyanAdmission.enroll_count).label("avg_enroll"),
        func.avg(KaoyanAdmission.admit_count).label("avg_admit"),
        func.avg(KaoyanAdmission.admit_avg_score).label("avg_score"),
        func.avg(KaoyanAdmission.retest_ratio).label("avg_ratio"),
    ).join(
        KaoyanSchool, KaoyanAdmission.school_id == KaoyanSchool.id
    ).filter(
        KaoyanAdmission.year == year,
    ).group_by(
        KaoyanAdmission.school_id, KaoyanSchool.name, KaoyanSchool.level, KaoyanSchool.province
    ).all()

    items = []
    for school_id, name, level, province, avg_enroll, avg_admit, avg_score, avg_ratio in rows:
        if not avg_enroll:
            continue
        items.append({
            "name": name,
            "level": level,
            "province": province,
            "enroll": round(avg_enroll, 1),
            "admit": round(avg_admit, 1) if avg_admit else None,
            "admit_avg": round(avg_score, 1) if avg_score else None,
            "retest_ratio": round(avg_ratio, 2) if avg_ratio else None,
        })

    return {"year": year, "available_years": years, "items": items}


@router.get("/analysis/years")
def analysis_years(db: Session = Depends(get_db)):
    """择校数据里真实存在的年份（倒序）。

    择校推荐/地图/散点三个页面的年份下拉都取这里，不在前端写死 ``[2026,2025,2024,2023]``：
    写死意味着用户导入 2027 数据后仍只能选到 2026，而选 2026 又查不到东西。
    空库返回空列表，前端据此显示导入空态而不是假年份。
    """
    return {"items": available_years(db)}


# ---- 统计概览 ----
@router.get("/stats")
def kaoyan_stats(db: Session = Depends(get_db)):
    return {
        "school_count": db.query(KaoyanSchool).count(),
        "major_count": db.query(KaoyanMajor).count(),
        "admission_records": db.query(KaoyanAdmission).count(),
        "scoreline_records": db.query(KaoyanScoreLine).count(),
        "subject_count": db.query(KaoyanSubject).count(),
        "years": [y[0] for y in db.query(KaoyanAdmission.year).distinct().order_by(KaoyanAdmission.year.desc()).all() if y[0]],
    }


# ---- C1+C2: 触发爬虫 ----
@router.post("/notices/crawl")
def notices_crawl(
    school_id: int = Query(..., description="院校 ID，单校爬取公告"),
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
):
    """单校公告爬取（院校详情页「随时爬取」按钮）。返回本次新增/总条数。"""
    from services.kaoyan.spider_notices import crawl_school_notices, ensure_notices_schema
    from sqlalchemy import text as _sql
    ensure_notices_schema(db)
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="院校不存在")
    before = db.execute(_sql(
        "SELECT COUNT(*) FROM kaoyan_notices WHERE school_id=:i"), {"i": school_id}).scalar()
    result = crawl_school_notices(db_session=db, school_names=[school.name],
                                  max_schools=1, dry_run=dry_run)
    after = db.execute(_sql(
        "SELECT COUNT(*) FROM kaoyan_notices WHERE school_id=:i"), {"i": school_id}).scalar()
    return {"school": school.name, "dry_run": dry_run, "result": result,
            "notices_total": after, "new": max(0, after - before)}


@router.post("/spider/run")
def spider_run(
    provinces: Optional[str] = Query(None, description="省份代码逗号分隔，如 11,12,13"),
    all_provinces: bool = Query(False, description="是否爬全部省份"),
    db: Session = Depends(get_db),
):
    """C1: 触发研招网爬虫（前端按钮调用）。"""
    from services.kaoyan.spider_yz import crawl
    province_codes = [p.strip() for p in provinces.split(",")] if provinces else None
    before = db.query(KaoyanSchool).count()
    try:
        crawl(province_codes=province_codes, all_provinces=all_provinces)
        after = db.query(KaoyanSchool).count()
        # C5: 记录采集版本
        db.add(KaoyanCollectionRun(
            source="spider_yz",
            scope=",".join(province_codes) if province_codes else "all",
            item_type="school",
            row_count=max(0, after - before),
            detail={"provinces": province_codes or "all", "schools_after": after, "schools_before": before},
            status="success",
        ))
        db.commit()
        return {"success": True, "message": "爬虫执行完成", "added_schools": max(0, after - before)}
    except Exception as e:
        db.add(KaoyanCollectionRun(
            source="spider_yz",
            scope=",".join(province_codes) if province_codes else "all",
            item_type="school",
            row_count=0,
            detail={"error": str(e)},
            status="failed",
        ))
        db.commit()
        raise HTTPException(500, f"爬虫执行失败: {e}")


# ---- C5: 数据版本管理 ----
@router.get("/collection/runs")
def list_collection_runs(
    source: Optional[str] = Query(None, description="来源过滤"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """C5: 列出采集版本记录（支持历史对比溯源）。"""
    q = db.query(KaoyanCollectionRun)
    if source:
        q = q.filter(KaoyanCollectionRun.source == source)
    runs = q.order_by(KaoyanCollectionRun.created_at.desc()).limit(limit).all()
    return [{
        "id": r.id, "source": r.source, "scope": r.scope,
        "item_type": r.item_type, "row_count": r.row_count,
        "status": r.status, "detail": r.detail,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in runs]


@router.post("/collection/runs")
def create_collection_run(
    source: str = Query(...),
    scope: Optional[str] = Query(None),
    item_type: Optional[str] = Query(None),
    row_count: int = Query(0),
    status: str = Query("success"),
    detail: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """C5: 手动登记一次采集/导入版本（csv/supplement 等外部流程）。"""
    import json as _json
    detail_obj = None
    if detail:
        try:
            detail_obj = _json.loads(detail)
        except Exception:
            detail_obj = {"raw": detail}
    run = KaoyanCollectionRun(
        source=source, scope=scope, item_type=item_type,
        row_count=row_count, detail=detail_obj, status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"success": True, "run_id": run.id, "created_at": run.created_at.isoformat() if run.created_at else None}


# ---- 动态数据源：数据源列表 ----
@router.get("/datasources")
def list_kaoyan_datasources(
    source_type: Optional[str] = Query(None, description="过滤：yz / exam_authority / school_official / aggregator"),
    province: Optional[str] = Query(None, description="按省份过滤"),
    status: Optional[str] = Query(None, description="过滤：active / paused / deprecated"),
):
    """D1: 返回数据源注册中心列表（研招网 + 省考试院 + 重点院校研究生院 + 自定义注册）。"""
    items = list_datasources(source_type=source_type, province=province, status=status)
    return {
        "total": len(items),
        "items": [{
            "key": it["key"], "name": it["name"], "base_url": it["base_url"],
            "source_type": it["source_type"], "source_type_label": resolve_source_type(it["source_type"]),
            "parser": it["parser"], "status": it["status"],
            "province": it.get("province"), "remark": it.get("remark", ""),
        } for it in items],
    }


# ---- 动态数据源：动态采集刷新 ----
@router.post("/collection/refresh")
def collection_refresh(
    source: str = Query("yz", description="数据源：yz / school，或注册中心 key（逗号分隔多个）"),
    province: Optional[str] = Query(None, description="省份代码逗号分隔（yz 源），如 11,12,13"),
    all_provinces: bool = Query(False, description="yz 源是否全量省份"),
    school: Optional[str] = Query(None, description="院校名（school 源），如 清华大学"),
    year: Optional[int] = Query(None, description="school 源采集年度；不传则按当前届推断，不写死年份"),
    max_schools: int = Query(20, ge=1, le=500, description="notices 源单次采集的院校数上限"),
    dry_run: bool = Query(False, description="仅参数校验并登记采集版本，不实际发起网络请求"),
    db: Session = Depends(get_db),
):
    """D1: 按省份/院校/数据源触发动态采集。

    - source=yz：复用 spider_yz.crawl（研招网院校目录，含 checkpoint 断点续爬）
    - source=school：复用 spider_school.crawl_school（院校官网复试线/拟录取）
    - 其他 source 取值：按注册中心 key 解析（如 sch_tsinghua / ee_bj），映射到对应 parser
    """
    results = []
    sources = [s.strip() for s in source.split(",") if s.strip()]
    if not sources:
        raise HTTPException(400, "source 不能为空")

    for src in sources:
        src_lower = src.lower()
        if src_lower in ("engineering", "engineering_collect"):
            # ---- T5 工科定向采集（电子/通信/408/光学/电气/AI 代码集过滤） ----
            from services.kaoyan.collector import collect_engineering

            if dry_run:
                results.append({"source": "engineering", "status": "skipped", "detail": "dry_run 校验通过"})
                continue
            try:
                province_codes = [p.strip() for p in province.split(",")] if province else None
                detail = collect_engineering(provinces=province_codes)
                results.append({"source": "engineering", "status": "success", **detail})
            except Exception as e:
                results.append({"source": "engineering", "status": "failed", "error": str(e)})
        elif src_lower in ("national_line", "national"):
            # ---- T5 国家线回填（官方核实静态数据） ----
            from services.kaoyan.collector import backfill_national_lines_task

            if dry_run:
                results.append({"source": "national_line", "status": "skipped", "detail": "dry_run 校验通过"})
                continue
            try:
                detail = backfill_national_lines_task()
                results.append({"source": "national_line", "status": "success", **detail})
            except Exception as e:
                results.append({"source": "national_line", "status": "failed", "error": str(e)})
        elif src_lower in ("notices", "notice"):
            # ---- T5 公告采集（各校研究生院官网列表页） ----
            from services.kaoyan.collector import collect_notices_task

            if dry_run:
                results.append({"source": "notices", "status": "skipped", "detail": "dry_run 校验通过"})
                continue
            try:
                # 原先写的是 int((year or 20) if str(year).isdigit() else 20)：
                # year 默认 2026 是数字，于是 max_schools 变成 2026，公告采集会遍历全站院校。
                stats = collect_notices_task(max_schools=max_schools)
                results.append({"source": "notices", "status": "success", **stats})
            except Exception as e:
                results.append({"source": "notices", "status": "failed", "error": str(e)})
        elif src_lower in ("yz", "yz_chsi"):
            # ---- 研招网 ----
            from services.kaoyan.spider_yz import crawl
            province_codes = [p.strip() for p in province.split(",")] if province else None
            scope = ",".join(province_codes) if province_codes else ("all" if all_provinces else "default3")
            if dry_run:
                db.add(KaoyanCollectionRun(source="spider_yz", scope=scope, item_type="school",
                                           row_count=0, detail={"dry_run": True, "province_codes": province_codes, "all_provinces": all_provinces},
                                           status="skipped"))
                db.commit()
                results.append({"source": "yz", "status": "skipped", "detail": "dry_run 校验通过"})
                continue
            before = db.query(KaoyanSchool).count()
            try:
                crawl(province_codes=province_codes, all_provinces=all_provinces)
                after = db.query(KaoyanSchool).count()
                db.add(KaoyanCollectionRun(source="spider_yz", scope=scope, item_type="school",
                                           row_count=max(0, after - before),
                                           detail={"provinces": province_codes or ("all" if all_provinces else "default3"),
                                                   "schools_before": before, "schools_after": after},
                                           status="success"))
                db.commit()
                results.append({"source": "yz", "status": "success", "added_schools": max(0, after - before)})
            except Exception as e:
                db.add(KaoyanCollectionRun(source="spider_yz", scope=scope, item_type="school",
                                           row_count=0, detail={"error": str(e)}, status="failed"))
                db.commit()
                results.append({"source": "yz", "status": "failed", "error": str(e)})
        elif src_lower in ("school", "school_official"):
            # ---- 院校官网 ----
            from services.kaoyan.spider_school import crawl_school
            from services import exam_calendar

            if not school:
                raise HTTPException(400, "school 源必须提供 school 院校名参数")
            # 采集目标是「下一届简章」，所以默认跟着时间走，而不是停在某个写死的年份上
            target_year = exam_calendar.validate_exam_year(year) if year is not None else exam_calendar.default_exam_year()
            if dry_run:
                db.add(KaoyanCollectionRun(source="spider_school", scope=school, item_type="scoreline",
                                           row_count=0, detail={"dry_run": True, "year": target_year}, status="skipped"))
                db.commit()
                results.append({"source": "school", "status": "skipped", "detail": f"dry_run 校验通过（{school}）"})
                continue
            try:
                school_obj = db.query(KaoyanSchool).filter(KaoyanSchool.name == school).first()
                if not school_obj:
                    raise HTTPException(404, f"院校不存在: {school}")
                before = db.query(KaoyanScoreLine).filter(
                    KaoyanScoreLine.school_id == school_obj.id,
                    KaoyanScoreLine.year == target_year,
                ).count()
                crawl_school(school, year=target_year)
                after = db.query(KaoyanScoreLine).filter(
                    KaoyanScoreLine.school_id == school_obj.id,
                    KaoyanScoreLine.year == target_year,
                ).count()
                db.add(KaoyanCollectionRun(source="spider_school", scope=school, item_type="scoreline",
                                           row_count=max(0, after - before),
                                           detail={"year": target_year, "scorelines_before": before, "scorelines_after": after},
                                           status="success"))
                db.commit()
                results.append({"source": "school", "status": "success", "school": school,
                               "scorelines_added": max(0, after - before)})
            except Exception as e:
                db.add(KaoyanCollectionRun(source="spider_school", scope=school, item_type="scoreline",
                                           row_count=0, detail={"error": str(e)}, status="failed"))
                db.commit()
                results.append({"source": "school", "status": "failed", "school": school, "error": str(e)})
        else:
            # ---- 注册中心 key ----
            ds = get_datasource(src)
            if not ds:
                raise HTTPException(404, f"数据源未注册: {src}（可用 yz / school 或注册中心 key）")
            parser = ds.get("parser", "manual")
            if parser == "spider_yz":
                results.append({"source": src, "parser": parser,
                               "status": "skipped", "detail": "注册中心 yz 类源请用 source=yz 触发"})
            elif parser == "spider_school":
                if not school:
                    raise HTTPException(400, f"数据源 {src} 需提供 school 院校名参数")
                results.append({"source": src, "parser": parser, "school": school,
                               "status": "skipped", "detail": "院校官网类源请用 source=school 触发"})
            else:
                results.append({"source": src, "parser": parser, "status": "skipped",
                               "detail": f"manual 解析器（{ds.get('name')}）请人工录入"})
    return {"success": True, "count": len(results), "results": results}


# --------------------------------------------------------------------------- #
# 择校数据分析聚合（院校库页「数据分析」区块专用，任务完善项）
# --------------------------------------------------------------------------- #


# ---- T5：院校公告（详情页「公告文章」标签数据源） ----
@router.get("/schools/{school_id}/notices")
def get_school_notices(
    school_id: int,
    notice_type: Optional[str] = Query(None, description="公告/简章/复试/调剂/录取"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """院校招生公告列表（spider_notices 采集，kaoyan_notices 表）。"""
    from services.kaoyan.spider_notices import ensure_notices_schema

    ensure_notices_schema(db)
    conn = wrap_conn(db.connection().connection)
    sql = "SELECT id, title, notice_type, publish_date, url, source FROM kaoyan_notices WHERE school_id = ?"
    args: list = [school_id]
    if notice_type:
        sql += " AND notice_type = ?"
        args.append(notice_type)
    sql += " ORDER BY publish_date DESC, id DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    return [
        {"id": r[0], "title": r[1], "notice_type": r[2],
         "publish_date": r[3], "url": r[4], "source": r[5]}
        for r in rows
    ]


@router.get("/notices/types")
def notice_type_stats(db: Session = Depends(get_db)):
    """公告类型分布（前端「公告文章」子标签：招生公告/招生简章）。"""
    from services.kaoyan.spider_notices import ensure_notices_schema

    ensure_notices_schema(db)
    conn = wrap_conn(db.connection().connection)
    rows = conn.execute(
        "SELECT notice_type, COUNT(*) FROM kaoyan_notices GROUP BY notice_type ORDER BY 2 DESC"
    ).fetchall()
    return {"total": sum(r[1] for r in rows), "by_type": dict(rows)}


@router.get("/notices/stats")
def notices_center_stats(db: Session = Depends(get_db)):
    """通知中心统计卡（2026-10-19 信息架构精简）：总数/未读/星标/覆盖院校 + 四类分计数。

    口径：NOT is_read（双方言可移植，PG boolean / SQLite 0/1）；
    覆盖院校 = 有通知挂接的院校数（采集总量见 KaoyanCollectionRun）。
    """
    from services.kaoyan.spider_notices import ensure_notices_schema

    ensure_notices_schema(db)
    conn = wrap_conn(db.connection().connection)
    rows = conn.execute(
        "SELECT notice_type, COUNT(*), "
        "COALESCE(SUM(CASE WHEN NOT is_read THEN 1 ELSE 0 END), 0) "
        "FROM kaoyan_notices GROUP BY notice_type ORDER BY 2 DESC"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
    unread = conn.execute(
        "SELECT COUNT(*) FROM kaoyan_notices WHERE NOT is_read"
    ).fetchone()[0]
    starred = conn.execute(
        "SELECT COUNT(*) FROM kaoyan_notices WHERE is_starred"
    ).fetchone()[0]
    covered = conn.execute(
        "SELECT COUNT(DISTINCT school_id) FROM kaoyan_notices WHERE school_id IS NOT NULL"
    ).fetchone()[0]
    return {
        "total": int(total),
        "unread": int(unread),
        "starred": int(starred),
        "schools_covered": int(covered),
        "by_type": [
            {"type": r[0], "total": int(r[1]), "unread": int(r[2] or 0)}
            for r in rows
        ],
    }


# ---- T6：跨校公告聚合（首页「院校公告」栏数据源） ----
# 说明：现有 /schools/{id}/notices 是按单校查（详情页用），首页需要「当日/近期
# 哪些院校更新了」的跨校视角，故新增本聚合端点。全部只读，SQL 参数化，向后兼容。
@router.get("/notices")
def list_all_notices(
    limit: int = Query(30, ge=1, le=200, description="返回条数上限"),
    since: Optional[str] = Query(None, description="只返回该 ISO 日期(YYYY-MM-DD)当天及之后的公告"),
    notice_type: Optional[str] = Query(None, description="按类型过滤：简章/复试/调剂/录取/公告…"),
    keyword: Optional[str] = Query(None, description="标题关键词（模糊匹配）"),
    school_id: Optional[int] = Query(None, description="仍可按院校过滤"),
    order_by: str = Query("publish_date", description="排序字段：publish_date | fetched_at"),
    db: Session = Depends(get_db),
):
    """跨校公告聚合（首页公告栏）。

    返回：
      - ``items``：公告列表，按 ``order_by`` 倒序（默认 publish_date，同值再按 id 倒序）
      - ``stats``：首页「今日更新」概览
          ``{total, school_count, latest_fetched_at, by_type}``

    过滤参数均可选，可组合；``since`` 用 ``>= since``（当日含）。
    """
    from services.kaoyan.spider_notices import ensure_notices_schema
    from services.kaoyan.notice_read import ensure_notice_read_schema

    # 补齐 is_read/is_starred 列，使首页公告栏也能渲染未读状态
    ensure_notice_read_schema(db)
    conn = wrap_conn(db.connection().connection)

    # ---- 组装过滤条件（全部参数化，杜绝注入）----
    where: List[str] = []
    args: list = []
    if since:
        # 只认 YYYY-MM-DD 前缀，避免非法输入直接进 SQL 造成异常比较
        since_clean = str(since).strip()[:10]
        where.append("publish_date IS NOT NULL AND publish_date != '' AND publish_date >= ?")
        args.append(since_clean)
    if notice_type:
        where.append("notice_type = ?")
        args.append(notice_type)
    if keyword:
        where.append("title LIKE ?")
        args.append(f"%{keyword}%")
    if school_id is not None:
        where.append("school_id = ?")
        args.append(school_id)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    # ---- 排序字段白名单（防注入：仅允许两个已知列名）----
    sort_col = "fetched_at" if str(order_by).strip() == "fetched_at" else "publish_date"
    order_sql = f" ORDER BY {sort_col} DESC, id DESC"

    # ---- 明细列表（附已读/加星状态，供首页公告栏渲染未读圆点）----
    rows = conn.execute(
        "SELECT id, school_id, school_name, title, notice_type, publish_date,"
        " url, source, fetched_at, is_read, is_starred FROM kaoyan_notices"
        + where_sql
        + order_sql
        + " LIMIT ?",
        args + [limit],
    ).fetchall()
    items = [
        {
            "id": r[0], "school_id": r[1], "school_name": r[2], "title": r[3],
            "notice_type": r[4], "publish_date": r[5], "url": r[6],
            "source": r[7], "fetched_at": r[8],
            "is_read": bool(r[9]), "is_starred": bool(r[10]),
        }
        for r in rows
    ]

    # ---- 概览统计（同过滤条件，不受 limit 影响）----
    total = conn.execute(
        "SELECT COUNT(*) FROM kaoyan_notices" + where_sql, args
    ).fetchone()[0]
    # 有 school_id 的按 id 去重；school_id 为空的用 school_name 兜底（采集时可能未入库）
    school_count = conn.execute(
        "SELECT COUNT(*) FROM ("
        " SELECT COALESCE(CAST(school_id AS TEXT), 'n:' || school_name) AS sk"
        " FROM kaoyan_notices" + where_sql + " GROUP BY sk)",
        args,
    ).fetchone()[0]
    # 最近一次采集时间（不过滤，表示数据新鲜度）
    latest_row = conn.execute(
        "SELECT MAX(fetched_at) FROM kaoyan_notices"
    ).fetchone()
    by_type_rows = conn.execute(
        "SELECT notice_type, COUNT(*) FROM kaoyan_notices"
        + where_sql
        + " GROUP BY notice_type ORDER BY 2 DESC",
        args,
    ).fetchall()

    return {
        "items": items,
        # 翻页壳约定：给了 items 就必须同级给 total。这里 total 早就算好（在
        # stats 里），提到顶层只是让所有列表端点共用同一个读取路径，前端不必
        # 为该端点单独写 stats.total 分支。
        "total": total,
        "stats": {
            "total": total,
            "school_count": school_count,
            "latest_fetched_at": latest_row[0] if latest_row else None,
            "by_type": {k: v for k, v in by_type_rows},
        },
    }


@router.get("/notices/updates")
def notice_updates(
    days: int = Query(7, ge=1, le=365, description="最近 N 天内有更新的院校"),
    db: Session = Depends(get_db),
):
    """最近 N 天内有哪些院校更新了公告（首页「今日更新」概览）。

    返回：``{days, total_schools, total_notices, schools:[{school_id, school_name, count, latest_date}]}``
    「更新日期」口径：``publish_date`` 的日期优先；公告没有发布日（列表页解析不到）
    时退化为采集日，并按**北京自然日**归日（采集时间存的是 naive UTC，UTC 16:00
    之后属于北京的次日）。退化而来而非过滤掉，如实标注。
    """
    from services.kaoyan.spider_notices import ensure_notices_schema
    from datetime import timedelta

    ensure_notices_schema(db)
    conn = wrap_conn(db.connection().connection)

    cutoff = (local_today() - timedelta(days=days)).isoformat()
    # 「更新日期」= publish_date（纯日期）优先，缺失时退化为采集日。fetched_at 存的是
    # naive UTC 串，必须按北京自然日归日，否则北京 00:00~08:00 采集的公告会记到前一天
    # （与 cutoff 这个北京日直接比字符串会整点错 8 小时）。
    day_expr = (
        "CASE WHEN COALESCE(publish_date, '') <> '' THEN substr(publish_date, 1, 10)"
        f" ELSE {day_bucket_text_expr('fetched_at')} END"
    )
    rows = conn.execute(
        "SELECT school_id, school_name,"
        " COUNT(*) AS cnt,"
        f" MAX({day_expr}) AS latest_date"
        " FROM kaoyan_notices"
        f" WHERE {day_expr} >= ?"
        " GROUP BY COALESCE(CAST(school_id AS TEXT), 'n:' || school_name), school_id, school_name"
        " ORDER BY latest_date DESC, cnt DESC",
        [cutoff],
    ).fetchall()
    schools = [
        {
            "school_id": r[0],
            "school_name": r[1],
            "count": r[2],
            "latest_date": (r[3] or "")[:10] or None,
        }
        for r in rows
    ]
    return {
        "days": days,
        "total_schools": len(schools),
        "total_notices": sum(s["count"] for s in schools),
        "schools": schools,
    }


@router.get("/analysis/dashboard")
def analysis_dashboard(db: Session = Depends(get_db)):
    """择校多维聚合数据，供院校库页「数据分析」区块实时渲染。

    全部 SQLAlchemy 实时聚合（无任何前端硬编码）：
      subject_math / subject_english / major2_top —— 从 kaoyan_majors.exam_subjects(JSON) 解析
      major_comparison  —— 专业级：招生规模 + 复试/录取均分 + 复录比
      college_enroll    —— 学院级：招生人数
      major_score_dist  —— 专业课均分分数段分布
    """
    # ---- 1) 科目分布：遍历专业考试科目 ----
    majors = db.query(KaoyanMajor).all()
    math_agg, english_agg, major2_agg = {}, {}, {}
    for m in majors:
        # 库内 exam_subjects 实为竖线分隔文本 "(302)数学（二） | (204)英语（二） | ..."，
        # 不能用 isinstance(list) 判断（那会让数学/英语/专业课统计**恒为空**）。
        # 统一走 _parse_exam_subjects：兼容文本与 JSON 数组两种存储形态。
        for item in _parse_exam_subjects(m.exam_subjects):
            s = (item.get("name") or "").strip()
            if not s:
                continue
            if "数学" in s:
                math_agg[s] = math_agg.get(s, 0) + 1
            elif any(k in s for k in ("英语", "外语", "俄语", "日语")):
                english_agg[s] = english_agg.get(s, 0) + 1
            elif not _is_public_subject(item):
                # 业务课二（专业课）：按公共课集合反选，而不是写死 idx == 3。
                # 真库多数专业只有「数学 | 英语 | 专业课」三门，写死第 4 位会让专业课统计恒为空。
                major2_agg[s] = major2_agg.get(s, 0) + 1

    def top(items, n=15):
        return [
            {"name": k, "count": v}
            for k, v in sorted(items.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
        ]

    # ---- 2) 专业级聚合：招生规模 + 复试/录取均分 + 复录比 ----
    major_rows = (
        db.query(
            KaoyanMajor.name.label("major"),
            func.sum(KaoyanAdmission.enroll_count).label("enroll_count"),
            func.avg(KaoyanAdmission.admit_avg_score).label("admit_avg"),
            func.avg(KaoyanAdmission.major_avg_score).label("major_avg"),
            func.avg(KaoyanAdmission.retest_ratio).label("retest_ratio"),
        )
        .join(KaoyanAdmission, KaoyanAdmission.major_id == KaoyanMajor.id)
        .group_by(KaoyanMajor.name)
        .all()
    )
    major_comparison = [
        {
            "major": r.major,
            "enroll_count": int(r.enroll_count or 0),
            "admit_avg": round(r.admit_avg, 1) if r.admit_avg is not None else None,
            "major_avg": round(r.major_avg, 1) if r.major_avg is not None else None,
            "retest_ratio": round(r.retest_ratio, 2) if r.retest_ratio is not None else None,
        }
        for r in major_rows
    ]
    major_comparison.sort(key=lambda x: -(x["enroll_count"] or 0))

    # ---- 3) 学院级聚合：招生人数 ----
    college_rows = (
        db.query(
            KaoyanCollege.name.label("college"),
            func.sum(KaoyanAdmission.enroll_count).label("enroll_count"),
        )
        .select_from(KaoyanAdmission)
        .join(KaoyanMajor, KaoyanAdmission.major_id == KaoyanMajor.id)
        .join(KaoyanCollege, KaoyanMajor.college_id == KaoyanCollege.id)
        .group_by(KaoyanCollege.name)
        .all()
    )
    college_enroll = [
        {"college": r.college, "enroll_count": int(r.enroll_count or 0)}
        for r in college_rows
    ]
    college_enroll.sort(key=lambda x: -(x["enroll_count"] or 0))

    # ---- 4) 专业课均分分数段分布 ----
    bands = [
        ("<90", 0, 90),
        ("90-100", 90, 100),
        ("100-110", 100, 110),
        ("110-120", 110, 120),
        ("120-130", 120, 130),
        ("130-140", 130, 140),
        ("≥140", 140, 10000),
    ]
    major_score_dist = []
    for label, lo, hi in bands:
        cnt = (
            db.query(func.count(KaoyanAdmission.id))
            .filter(
                KaoyanAdmission.major_avg_score.isnot(None),
                KaoyanAdmission.major_avg_score >= lo,
                KaoyanAdmission.major_avg_score < hi,
            )
            .scalar()
            or 0
        )
        major_score_dist.append({"band": label, "count": int(cnt)})

    # ---- 5) 总分线分数段分布（kaoyan_scorelines.total_line，代表总分分布） ----
    total_bands = [
        ("<300", 0, 300),
        ("300-320", 300, 320),
        ("320-340", 320, 340),
        ("340-360", 340, 360),
        ("360-380", 360, 380),
        ("≥380", 380, 10000),
    ]
    total_score_dist = []
    for label, lo, hi in total_bands:
        cnt = (
            db.query(func.count(KaoyanScoreLine.id))
            .filter(
                KaoyanScoreLine.total_line.isnot(None),
                KaoyanScoreLine.total_line >= lo,
                KaoyanScoreLine.total_line < hi,
            )
            .scalar()
            or 0
        )
        total_score_dist.append({"band": label, "count": int(cnt)})

    # ---- 6) 数学线分数段分布（kaoyan_scorelines.math_line，代表数学分数分布） ----
    math_bands = [
        ("<60", 0, 60),
        ("60-80", 60, 80),
        ("80-100", 80, 100),
        ("100-120", 100, 120),
        ("120-140", 120, 140),
        ("≥140", 140, 10000),
    ]
    math_score_dist = []
    for label, lo, hi in math_bands:
        cnt = (
            db.query(func.count(KaoyanScoreLine.id))
            .filter(
                KaoyanScoreLine.math_line.isnot(None),
                KaoyanScoreLine.math_line >= lo,
                KaoyanScoreLine.math_line < hi,
            )
            .scalar()
            or 0
        )
        math_score_dist.append({"band": label, "count": int(cnt)})

    return {
        "subject_math": top(math_agg),
        "subject_english": top(english_agg),
        "major2_top": top(major2_agg, 15),
        "major_comparison": major_comparison,
        "college_enroll": college_enroll,
        "major_score_dist": major_score_dist,
        "total_score_dist": total_score_dist,
        "math_score_dist": math_score_dist,
        "generated_at": iso_utc_z(utcnow()),
    }

