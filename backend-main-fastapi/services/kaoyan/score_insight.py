# -*- coding: utf-8 -*-
"""分数深度分析与择校自动调整引擎（V10 新增）。

三个能力：
1. ``school_score_detail``：院校多年分数全景 —— 总分/单科线明细、录取
   均分趋势、复录比、国家线差值，支撑「具体分数展示」。
2. ``estimate_score_position``：用户分数 vs 历史录取均分的正态分数相对位置
   （经验模型，非录取概率，绝不冒充精确位次）。
3. ``auto_adjust_recommend``：输入预估分 → 自动分「冲 / 稳 / 保」三档，
   每档附数据化理由，数据不足的院校降置信度或跳过。

与 routers/kaoyan.py 的 recommend 的区别：
- recommend 是多维加权打分（gap/复录比/层级/省份），输出连续分数；
- 本引擎是三档分箱 + 可解释理由，面向「自动调整」场景（分数变化时
  重新推荐），两者互补。
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

# 必须用 models.py 的正典模型：core/models/schools.py 里映射同一张表的旧模型
# 缺 major_code/diff_total/source_id 等 kaoyan.cn 字段，用它查分数全景会
# AttributeError 500。
from models import KaoyanAdmission, KaoyanMajor, KaoyanSchool, KaoyanScoreLine
from services.kaoyan.datasource_registry import official_source_condition
from services.kaoyan.engineering_codes import derive_code_parts

# 正态假设的σ经验值：考研录取分数分布相对集中，公开分析常取 15~22。
# 取 18 为中位估计；结果仅作信心参考，非精确位次。
_SIGMA = 18.0


def _trend_label(values: List[float]) -> str:
    """3+ 点线性趋势的粗判：上升/下降/波动/平稳。"""
    if len(values) < 3:
        return "数据不足"
    n = len(values)
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    denom = sum((x - mx) ** 2 for x in xs) or 1.0
    slope = sum((xs[i] - mx) * (values[i] - my) for i in range(n)) / denom
    if slope > 4:
        return "持续上涨"
    if slope < -4:
        return "持续下降"
    if max(values) - min(values) > 15:
        return "波动较大"
    return "基本平稳"


def school_score_detail(
    db: Session, school_id: int, major_id: Optional[int] = None, subject_code: Optional[str] = None
) -> Optional[Dict]:
    """院校（或指定专业）多年分数全景。"""
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not school:
        return None

    code = str(subject_code or "").strip().upper() or None
    if code:
        category, major, direction = derive_code_parts(code)
        if not category or len(code) == 3 or (len(code) >= 4 and not major):
            raise ValueError("专业代码格式应为 2 位门类、4 位专业或完整方向代码")
        code_condition = KaoyanMajor.code.like(f"{code}%") if len(code) <= 4 else KaoyanMajor.code == code
        major_ids = [
            row[0] for row in db.query(KaoyanMajor.id).filter(KaoyanMajor.school_id == school_id, code_condition).all()
        ]
    else:
        major_ids = []

    sl_q = db.query(KaoyanScoreLine).filter(KaoyanScoreLine.school_id == school_id)
    ad_q = db.query(KaoyanAdmission).filter(
        KaoyanAdmission.school_id == school_id,
        official_source_condition(KaoyanAdmission.data_source),
    )
    if major_id:
        sl_q = sl_q.filter(KaoyanScoreLine.major_id == major_id)
        ad_q = ad_q.filter(KaoyanAdmission.major_id == major_id)
    if code:
        fallback_condition = (
            KaoyanScoreLine.major_code.like(f"{code}%") if len(code) <= 4 else KaoyanScoreLine.major_code == code
        )
        sl_q = sl_q.filter(
            or_(
                KaoyanScoreLine.major_id.in_(major_ids),
                and_(KaoyanScoreLine.major_id.is_(None), fallback_condition),
            )
        )
        ad_q = ad_q.filter(KaoyanAdmission.major_id.in_(major_ids))

    major_codes = dict(db.query(KaoyanMajor.id, KaoyanMajor.code).filter(KaoyanMajor.school_id == school_id).all())

    scorelines = sl_q.order_by(KaoyanScoreLine.year.desc()).limit(200).all()
    admissions = ad_q.order_by(KaoyanAdmission.year.desc()).limit(200).all()

    # 按年聚合分数线：逐专业院线取最低分为「校门最低院线」，并保留区间
    by_year: Dict[int, list] = defaultdict(list)
    for s in scorelines:
        by_year[s.year].append(s)

    years_detail = []
    for y in sorted(by_year, reverse=True):
        rows = [r for r in by_year[y] if r.total_line is not None]
        if not rows:
            continue
        low = min(rows, key=lambda r: r.total_line)
        totals = [r.total_line for r in rows]
        years_detail.append(
            {
                "year": y,
                "total_line": low.total_line,
                "total_line_min": min(totals),
                "total_line_max": max(totals),
                "total_line_avg": round(sum(totals) / len(totals), 1),
                "politics_line": low.politics_line,
                "english_line": low.english_line,
                "math_line": low.math_line,
                "major_line": low.major_line,
                "national_line": low.national_line,
                "retest_line": low.retest_line,
                "line_type": low.line_type,
                "source": low.source,
                "major_count": len(
                    {
                        str(major_codes.get(r.major_id) or r.major_code)[:4]
                        for r in rows
                        if major_codes.get(r.major_id) or r.major_code
                    }
                ),
            }
        )

    # 按年聚合录取数据；人数缺失不补零，均分只使用有人数权重的完整记录
    adm_by_year: Dict[int, Dict] = {}
    for a in admissions:
        d = adm_by_year.setdefault(
            a.year,
            {
                "year": a.year,
                "enroll_count": None,
                "admit_count": None,
                "retest_count": None,
                "weighted_sum": 0.0,
                "weight": 0.0,
                "_enroll": [],
                "_admit": [],
                "_retest": [],
            },
        )
        d["_enroll"].append(a.enroll_count)
        d["_admit"].append(a.admit_count)
        d["_retest"].append(a.retest_count)
        if a.admit_avg_score is not None and a.admit_count and a.admit_count > 0:
            d["weighted_sum"] += a.admit_avg_score * a.admit_count
            d["weight"] += a.admit_count
    admissions_detail = []
    for y in sorted(adm_by_year, reverse=True):
        d = dict(adm_by_year[y])
        for field, values in (
            ("enroll_count", d.pop("_enroll")),
            ("admit_count", d.pop("_admit")),
            ("retest_count", d.pop("_retest")),
        ):
            d[field] = sum(values) if all(value is not None for value in values) else None
        d["admit_avg_score"] = round(d["weighted_sum"] / d["weight"], 1) if d["weight"] else None
        d.pop("weighted_sum", None)
        d.pop("weight", None)
        d["retest_ratio"] = (
            round(d["retest_count"] / d["admit_count"], 2)
            if d["retest_count"] is not None and d["admit_count"]
            else None
        )
        admissions_detail.append(d)

    # 趋势判定（基于录取均分与总分线）
    avg_seq = [d["admit_avg_score"] for d in reversed(admissions_detail) if d["admit_avg_score"]]
    line_seq = [d["total_line"] for d in reversed(years_detail) if d.get("total_line")]
    trends = {
        "admit_avg_trend": _trend_label(avg_seq),
        "total_line_trend": _trend_label(line_seq),
    }

    # 与国家线差值（最近年）
    line_vs_national = None
    for d in years_detail:
        if d.get("total_line") and d.get("national_line"):
            line_vs_national = {
                "year": d["year"],
                "total_line": d["total_line"],
                "national_line": d["national_line"],
                "diff": d["total_line"] - d["national_line"],
            }
            break

    return {
        "school_id": school_id,
        "school_name": school.name,
        "level": school.level,
        "metric_scope": "major" if code or major_id else "school",
        "subject_code": code,
        "years_detail": years_detail,
        "admissions_detail": admissions_detail,
        "trends": trends,
        "line_vs_national": line_vs_national,
        "data_years": {
            "scoreline": sorted({s.year for s in scorelines}, reverse=True),
            "admission": sorted(adm_by_year, reverse=True),
        },
    }


def estimate_score_position(user_score: int, admit_avg: float) -> Dict:
    """正态经验估计：用户分数在历史录取分布中的相对位置。

    返回 score_position ∈ [0,1]（越大越高于均分）+ 相对位置标签。
    明确标注为「经验估算」，依赖 σ=18 假设，不是录取概率。
    """
    z = (user_score - admit_avg) / _SIGMA
    score_position = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    score_position = round(min(1.0, max(0.0, score_position)), 3)
    if score_position >= 0.85:
        pos = "显著高于历年录取均分"
    elif score_position >= 0.65:
        pos = "高于历年录取均分"
    elif score_position >= 0.45:
        pos = "贴近历年录取均分"
    elif score_position >= 0.2:
        pos = "略低于历年录取均分"
    else:
        pos = "明显低于历年录取均分"
    return {
        "score_position": score_position,
        "position": pos,
        "sigma_assumed": _SIGMA,
        "model": "正态经验估算，非录取概率",
    }


# 分档阈值：gap = 用户分 - 近3年录取均分
RUSH_GAP = (-35.0, -5.0)  # 冲：低均分 5~35 分
STABLE_GAP = (-5.0, 15.0)  # 稳：均分附近
SAFE_GAP = 15.0  # 保：高于均分 15+


def _bucket_of(gap: float) -> Optional[str]:
    if RUSH_GAP[0] <= gap < RUSH_GAP[1]:
        return "rush"
    if STABLE_GAP[0] <= gap <= STABLE_GAP[1]:
        return "stable"
    if gap > SAFE_GAP and gap <= 60:
        return "safe"
    return None  # 差距过大（>60 或 < -35）不推荐


def auto_adjust_recommend(
    db: Session,
    user_score: int,
    subject_code: Optional[str] = None,
    province: Optional[str] = None,
    level: Optional[str] = None,
    years_back: int = 3,
    per_bucket: int = 8,
) -> Dict:
    """自动调整引擎：冲稳保三档 + 可解释理由。

    逻辑：对每所院校取近 N 年录取均分的均值（avg3），
    gap = user_score - avg3 → 分箱。理由由真实数据拼装：
    均分/年份、趋势、层级、复录比、考试科目匹配。
    """
    # 近 N 年；专业过滤必须先作用于招生事实，再决定参考年份窗口
    subject_code = subject_code.strip().upper() if subject_code else None
    metric_scope = "major" if subject_code else "school"
    adm_q = db.query(
        KaoyanAdmission.school_id,
        KaoyanAdmission.year,
        KaoyanAdmission.admit_avg_score,
        KaoyanAdmission.retest_ratio,
        KaoyanAdmission.admit_count,
    ).filter(
        KaoyanAdmission.admit_avg_score.isnot(None),
        KaoyanAdmission.admit_count > 0,
        official_source_condition(KaoyanAdmission.data_source),
    )
    major_ids = []
    if subject_code:
        condition = (
            KaoyanMajor.code.like(f"{subject_code}%") if len(subject_code) <= 4 else KaoyanMajor.code == subject_code
        )
        major_ids = [row[0] for row in db.query(KaoyanMajor.id).filter(condition).all()]
        adm_q = adm_q.filter(KaoyanAdmission.major_id.in_(major_ids))

    recent_years = [
        row[0]
        for row in (
            adm_q.with_entities(KaoyanAdmission.year)
            .distinct()
            .order_by(KaoyanAdmission.year.desc())
            .limit(years_back)
            .all()
        )
    ]
    if not recent_years:
        return {
            "buckets": {"rush": [], "stable": [], "safe": []},
            "method": "无招生数据，无法自动调整",
            "coverage": 0,
            "metric_scope": metric_scope,
            "subject_code": subject_code,
        }
    top_year = recent_years[0]
    year_from = recent_years[-1]

    # 候选院校集合（可选过滤条件）
    q = db.query(KaoyanSchool)
    if province:
        q = q.filter(KaoyanSchool.province == province)
    if level:
        q = q.filter(KaoyanSchool.level == level)
    schools = q.all()
    if not schools:
        return {
            "buckets": {"rush": [], "stable": [], "safe": []},
            "method": "无匹配院校",
            "coverage": 0,
            "metric_scope": metric_scope,
            "subject_code": subject_code,
        }

    # 近 N 年录取均分按校聚合
    adm_rows = adm_q.filter(
        KaoyanAdmission.year >= year_from,
        KaoyanAdmission.year <= top_year,
    ).all()
    agg: Dict[int, Dict] = defaultdict(
        lambda: {
            "weighted_sum": 0.0,
            "weight": 0.0,
            "ratio_weighted_sum": 0.0,
            "ratio_weight": 0.0,
            "ratio_years": set(),
            "years": set(),
        }
    )
    for sid, year, avg, ratio, admit_count in adm_rows:
        info = agg[sid]
        info["weighted_sum"] += avg * admit_count
        info["weight"] += admit_count
        info["years"].add(year)
        if ratio is not None:
            info["ratio_weighted_sum"] += ratio * admit_count
            info["ratio_weight"] += admit_count
            info["ratio_years"].add(year)

    # 最新一年总分数线（用于补充理由；专业口径只取匹配专业的线）
    line_q = db.query(
        KaoyanScoreLine.school_id,
        KaoyanScoreLine.year,
        KaoyanScoreLine.total_line,
        KaoyanScoreLine.national_line,
    ).filter(
        KaoyanScoreLine.year >= year_from,
        KaoyanScoreLine.total_line.isnot(None),
    )
    if subject_code:
        code_condition = (
            KaoyanScoreLine.major_code.like(f"{subject_code}%")
            if len(subject_code) <= 4
            else KaoyanScoreLine.major_code == subject_code
        )
        line_q = line_q.filter(
            or_(
                KaoyanScoreLine.major_id.in_(major_ids),
                and_(KaoyanScoreLine.major_id.is_(None), code_condition),
            )
        )
    line_rows = line_q.order_by(
        KaoyanScoreLine.year.desc(),
        KaoyanScoreLine.total_line.asc(),
        KaoyanScoreLine.id.asc(),
    ).all()
    latest_line: Dict[int, Dict] = {}
    for sid, y, tl, nl in line_rows:
        if sid not in latest_line:
            latest_line[sid] = {"year": y, "total_line": tl, "national_line": nl}

    buckets: Dict[str, List[Dict]] = {"rush": [], "stable": [], "safe": []}
    coverage = 0
    for s in schools:
        info = agg.get(s.id)
        if not info or not info["weight"]:
            continue
        avg3 = round(info["weighted_sum"] / info["weight"], 1)
        gap = user_score - avg3
        bucket = _bucket_of(gap)
        if not bucket:
            continue
        coverage += 1

        score_pos = estimate_score_position(user_score, avg3)
        year_coverage = min(len(info["years"]) / max(years_back, 1), 1.0)
        ratio_coverage = min(len(info["ratio_years"]) / max(len(info["years"]), 1), 1.0)
        line_coverage = 1.0 if s.id in latest_line else 0.0
        retest_ratio = round(info["ratio_weighted_sum"] / info["ratio_weight"], 2) if info["ratio_weight"] else None
        evidence_confidence = round((year_coverage + ratio_coverage + line_coverage) / 3, 2)
        evidence_label = "较完整" if evidence_confidence >= 0.8 else "一般" if evidence_confidence >= 0.5 else "有限"
        reasons = [f"近{len(info['years'])}个有数据年份录取均分 {avg3}（你低/高 {abs(gap):.0f} 分）"]
        if retest_ratio is not None:
            reasons.append(f"复录比约 {retest_ratio}")
        ln = latest_line.get(s.id)
        if ln and ln.get("national_line"):
            reasons.append(
                f"{ln['year']}总分线 {ln['total_line']}（超国家线 {ln['total_line'] - ln['national_line']}）"
            )
        reasons.append(f"分数相对位置 {int(score_pos['score_position'] * 100)}%（{score_pos['position']}；非录取概率）")
        reasons.append(f"证据完整度 {int(evidence_confidence * 100)}%（{evidence_label}）")

        buckets[bucket].append(
            {
                "school_id": s.id,
                "school_name": s.name,
                "level": s.level,
                "province": s.province,
                "avg3": avg3,
                "gap": round(gap, 1),
                "retest_ratio": retest_ratio,
                "score_position": score_pos["score_position"],
                "position": score_pos["position"],
                "score_position_model": score_pos["model"],
                "evidence_confidence": evidence_confidence,
                "evidence_label": evidence_label,
                "metric_scope": metric_scope,
                "subject_code": subject_code,
                "reasons": reasons,
                "years_used": len(info["years"]),
            }
        )

    for k in buckets:
        # 冲刺按 gap 降序（最接近的先），稳/保按分数位置降序
        if k == "rush":
            buckets[k].sort(key=lambda x: -x["gap"])
        else:
            buckets[k].sort(key=lambda x: -x["score_position"])
        buckets[k] = buckets[k][:per_bucket]

    return {
        "user_score": user_score,
        "year_window": [year_from, top_year],
        "buckets": buckets,
        "coverage": coverage,
        "metric_scope": metric_scope,
        "subject_code": subject_code,
        "method": (
            "以近%d个数据年度录取均分按录取人数加权分箱："
            "冲(-35~-5) / 稳(-5~+15) / 保(+15~+60)；"
            "分数位置为正态经验估算(σ=%g)，非录取概率；"
            "证据完整度按年份、复录比与分数线覆盖计算" % (years_back, _SIGMA)
        ),
    }
