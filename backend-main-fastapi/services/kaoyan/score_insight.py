# -*- coding: utf-8 -*-
"""分数深度分析与择校自动调整引擎（V10 新增）。

三个能力：
1. ``school_score_detail``：院校多年分数全景 —— 总分/单科线明细、录取
   均分趋势、复录比、国家线差值，支撑「具体分数展示」。
2. ``estimate_admit_confidence``：用户分数 vs 历史录取均分的正态置信
   估计（经验模型，结果标注"估算"，绝不冒充精确位次）。
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

from sqlalchemy.orm import Session

from models import KaoyanAdmission, KaoyanMajor, KaoyanSchool, KaoyanScoreLine

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


def school_score_detail(db: Session, school_id: int,
                        major_id: Optional[int] = None) -> Optional[Dict]:
    """院校（或指定专业）多年分数全景。"""
    school = db.query(KaoyanSchool).filter(KaoyanSchool.id == school_id).first()
    if not school:
        return None

    sl_q = db.query(KaoyanScoreLine).filter(KaoyanScoreLine.school_id == school_id)
    ad_q = db.query(KaoyanAdmission).filter(KaoyanAdmission.school_id == school_id)
    if major_id:
        sl_q = sl_q.filter(KaoyanScoreLine.major_id == major_id)
        ad_q = ad_q.filter(KaoyanAdmission.major_id == major_id)

    scorelines = sl_q.order_by(KaoyanScoreLine.year.desc()).limit(200).all()
    admissions = ad_q.order_by(KaoyanAdmission.year.desc()).limit(200).all()

    # 按年聚合分数线（同一年取 major_id 为空的全校线优先，否则取第一条）
    by_year: Dict[int, Dict] = defaultdict(dict)
    for s in scorelines:
        y = s.year
        if y not in by_year or s.major_id is None:
            by_year[y].update({
                "year": y,
                "total_line": s.total_line,
                "politics_line": s.politics_line,
                "english_line": s.english_line,
                "math_line": s.math_line,
                "major_line": s.major_line,
                "national_line": s.national_line,
                "retest_line": s.retest_line,
                "line_type": s.line_type,
                "source": s.source,
            })
    years_detail = [by_year[y] for y in sorted(by_year, reverse=True)]

    # 按年聚合录取数据（全校口径：所有 admission 记录求和/均值）
    adm_by_year: Dict[int, Dict] = {}
    for a in admissions:
        d = adm_by_year.setdefault(a.year, {
            "year": a.year, "enroll_count": 0, "admit_count": 0,
            "retest_count": 0, "avg_scores": [], "retest_ratios": [],
        })
        d["enroll_count"] += a.enroll_count or 0
        d["admit_count"] += a.admit_count or 0
        d["retest_count"] += a.retest_count or 0
        if a.admit_avg_score:
            d["avg_scores"].append(a.admit_avg_score)
        if a.retest_ratio:
            d["retest_ratios"].append(a.retest_ratio)
    admissions_detail = []
    for y in sorted(adm_by_year, reverse=True):
        d = dict(adm_by_year[y])
        d["admit_avg_score"] = (round(sum(d["avg_scores"]) / len(d["avg_scores"]), 1)
                                if d["avg_scores"] else None)
        d["retest_ratio"] = (round(sum(d["retest_ratios"]) / len(d["retest_ratios"]), 2)
                             if d["retest_ratios"] else None)
        for k in ("avg_scores", "retest_ratios"):
            d.pop(k, None)
        admissions_detail.append(d)

    # 趋势判定（基于录取均分与总分线）
    avg_seq = [d["admit_avg_score"] for d in reversed(admissions_detail)
               if d["admit_avg_score"]]
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
        "years_detail": years_detail,
        "admissions_detail": admissions_detail,
        "trends": trends,
        "line_vs_national": line_vs_national,
        "data_years": {
            "scoreline": sorted({s.year for s in scorelines}, reverse=True),
            "admission": sorted(adm_by_year, reverse=True),
        },
    }


def estimate_admit_confidence(user_score: int, admit_avg: float) -> Dict:
    """正态经验估计：用户分数在历史录取分布中的相对位置。

    返回 confidence ∈ [0,1]（越大越有把握）+ 相对位置标签。
    明确标注为「经验估算」，依赖 σ=18 假设。
    """
    z = (user_score - admit_avg) / _SIGMA
    confidence = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    confidence = round(min(1.0, max(0.0, confidence)), 3)
    if confidence >= 0.85:
        pos = "显著高于历年录取均分"
    elif confidence >= 0.65:
        pos = "高于历年录取均分"
    elif confidence >= 0.45:
        pos = "贴近历年录取均分"
    elif confidence >= 0.2:
        pos = "略低于历年录取均分"
    else:
        pos = "明显低于历年录取均分"
    return {"confidence": confidence, "position": pos, "sigma_assumed": _SIGMA}


# 分档阈值：gap = 用户分 - 近3年录取均分
RUSH_GAP = (-35.0, -5.0)   # 冲：低均分 5~35 分
STABLE_GAP = (-5.0, 15.0)  # 稳：均分附近
SAFE_GAP = 15.0            # 保：高于均分 15+


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
    # 近 N 年
    latest_year = (db.query(KaoyanAdmission.year)
                   .order_by(KaoyanAdmission.year.desc()).first())
    if not latest_year:
        return {"buckets": {"rush": [], "stable": [], "safe": []},
                "method": "无招生数据，无法自动调整", "coverage": 0}
    top_year = latest_year[0]
    year_from = top_year - years_back + 1

    # 候选院校集合（可选过滤条件）
    q = db.query(KaoyanSchool)
    if province:
        q = q.filter(KaoyanSchool.province == province)
    if level:
        q = q.filter(KaoyanSchool.level == level)
    schools = q.all()
    if not schools:
        return {"buckets": {"rush": [], "stable": [], "safe": []},
                "method": "无匹配院校", "coverage": 0}

    # 学科过滤：有该学科专业的 school_id 集合
    subject_schools = None
    if subject_code:
        subject_schools = {
            r[0] for r in db.query(KaoyanMajor.school_id)
            .filter(KaoyanMajor.subject_code == subject_code).all()
        }

    # 近 N 年录取均分按校聚合
    adm_rows = (db.query(KaoyanAdmission.school_id, KaoyanAdmission.year,
                         KaoyanAdmission.admit_avg_score, KaoyanAdmission.retest_ratio)
                .filter(KaoyanAdmission.year >= year_from,
                        KaoyanAdmission.year <= top_year,
                        KaoyanAdmission.admit_avg_score.isnot(None))
                .all())
    agg: Dict[int, Dict] = defaultdict(lambda: {"avgs": [], "ratios": []})
    for sid, _y, avg, ratio in adm_rows:
        agg[sid]["avgs"].append(avg)
        if ratio:
            agg[sid]["ratios"].append(ratio)

    # 最新一年总分数线（用于补充理由）
    line_rows = (db.query(KaoyanScoreLine.school_id, KaoyanScoreLine.year,
                          KaoyanScoreLine.total_line, KaoyanScoreLine.national_line)
                 .filter(KaoyanScoreLine.year >= year_from - 1,
                         KaoyanScoreLine.total_line.isnot(None))
                 .order_by(KaoyanScoreLine.year.desc()).all())
    latest_line: Dict[int, Dict] = {}
    for sid, y, tl, nl in line_rows:
        if sid not in latest_line:
            latest_line[sid] = {"year": y, "total_line": tl, "national_line": nl}

    buckets: Dict[str, List[Dict]] = {"rush": [], "stable": [], "safe": []}
    coverage = 0
    for s in schools:
        if subject_schools is not None and s.id not in subject_schools:
            continue
        info = agg.get(s.id)
        if not info or not info["avgs"]:
            continue
        avg3 = round(sum(info["avgs"]) / len(info["avgs"]), 1)
        gap = user_score - avg3
        bucket = _bucket_of(gap)
        if not bucket:
            continue
        coverage += 1

        conf = estimate_admit_confidence(user_score, avg3)
        reasons = [f"近{years_back}年录取均分 {avg3}（你低/高 {abs(gap):.0f} 分）"]
        if len(info["ratios"]):
            r = round(sum(info["ratios"]) / len(info["ratios"]), 2)
            reasons.append(f"复录比约 {r}")
        ln = latest_line.get(s.id)
        if ln and ln.get("national_line"):
            reasons.append(f"{ln['year']}总分线 {ln['total_line']}（超国家线 {ln['total_line'] - ln['national_line']}）")
        reasons.append(f"分数信心估算 {int(conf['confidence'] * 100)}%（{conf['position']}）")

        buckets[bucket].append({
            "school_id": s.id,
            "school_name": s.name,
            "level": s.level,
            "province": s.province,
            "avg3": avg3,
            "gap": round(gap, 1),
            "confidence": conf["confidence"],
            "position": conf["position"],
            "reasons": reasons,
            "years_used": len(info["avgs"]),
        })

    for k in buckets:
        # 冲刺按 gap 降序（最接近的先），稳/保按信心降序
        if k == "rush":
            buckets[k].sort(key=lambda x: -x["gap"])
        else:
            buckets[k].sort(key=lambda x: -x["confidence"])
        buckets[k] = buckets[k][:per_bucket]

    return {
        "user_score": user_score,
        "year_window": [year_from, top_year],
        "buckets": buckets,
        "coverage": coverage,
        "method": ("以近%d年录取均分基准分箱：冲(-35~-5) / 稳(-5~+15) / "
                   "保(+15~+60)；信心为正态经验估算(σ=%g)，非精确位次"
                   % (years_back, _SIGMA)),
    }
