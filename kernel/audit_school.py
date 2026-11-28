# -*- coding: utf-8 -*-
"""择校确定性风险审计（落地方案 §4.6，纯函数）。

五风险：推免挤压 / 缩招 / 爆热 / 复试线虚低 / 改考（目录 diff 由 shell 提供）。
硬标准（规范 §6.2-4）：
- 阈值等号归属全部"达到即触发"（>=），入测试断言；heat_abs_ratio 为严格大于；
- 数据不足项 → "无法审计(缺X)"，**绝不输出"无风险"**；
- is_sample=True 的行一律 grade=demo 隔离，不参与真审计。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from kernel.config_loader import AuditConfig

RISK_TUIMIAN = "推免挤压"
RISK_SHRINK = "缩招"
RISK_HEAT = "爆热"
RISK_FAKE_LOW_LINE = "复试线虚低"
RISK_EXAM_CHANGE = "改考"
ALL_RISKS = (RISK_TUIMIAN, RISK_SHRINK, RISK_HEAT, RISK_FAKE_LOW_LINE, RISK_EXAM_CHANGE)

DISCLAIMER = "本审计不预测录取概率，只标识可观测的风险信号"


@dataclass(frozen=True)
class AdmissionRow:
    """db.json 适配后的 DTO（字段对齐总方案 §3.6 admission_data）。"""

    school_id: str
    program_code: str
    year: int
    total_plan: Optional[int] = None
    recommended_exempt: Optional[int] = None
    actual_exam_quota: Optional[int] = None
    applicants: Optional[int] = None
    first_choice_admitted: Optional[int] = None
    retest_count: Optional[int] = None
    retest_line: Optional[float] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    access_date: Optional[str] = None  # ISO 日期串
    missing_fields: Tuple[str, ...] = ()
    confidence: str = "low"
    is_sample: bool = False


@dataclass(frozen=True)
class RiskFinding:
    risk: str
    verdict: str  # hit | insufficient
    detail: str
    missing: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditResult:
    school_id: str
    program_code: str
    base_year: int
    risks: Tuple[RiskFinding, ...]
    evidence_quality: str  # high | medium | low（参与审计行的最差档）
    missing: Tuple[str, ...]
    stale_review_needed: bool  # access_date 超招生季 → 待复核
    disclaimer: str = DISCLAIMER
    demo_isolated_rows: int = 0  # 被隔离的 sample 行数


def _by_year(rows: Sequence[AdmissionRow]) -> Dict[int, AdmissionRow]:
    out: Dict[int, AdmissionRow] = {}
    for r in rows:
        out[r.year] = r  # 同年多行取最后一行（shell 保证已按闸门过滤去重）
    return out


def _ratio_or_none(num: Optional[int], den: Optional[int]) -> Optional[float]:
    if num is None or den is None or den == 0:
        return None
    return num / den


def audit(
    rows: List[AdmissionRow],
    base_year: int,
    cfg: AuditConfig,
    *,
    catalog_diff: Optional[str] = None,
    today: Optional[str] = None,
) -> AuditResult:
    """对某校某专业做五风险审计。

    Args:
        rows: 该校该专业的年度行（含 base_year-3..base_year-1）。
        base_year: 审计基准年（考生目标入学年）。
        cfg: 冻结阈值配置。
        catalog_diff: shell 提供的当年 vs 上年目录 diff 文本；None=未提供。
        today: 时效判定基准日（ISO 串），默认今天（naive UTC 口径）。
    """
    real = [r for r in rows if not r.is_sample]
    demo_n = len(rows) - len(real)
    by = _by_year(real)
    years = [base_year - 3, base_year - 2, base_year - 1]
    findings: List[RiskFinding] = []

    # ---- 推免挤压：三年累计上升 >= 10pp ----
    rates = []
    miss_t: List[str] = []
    for y in years:
        r = by.get(y)
        if r is None:
            miss_t.append(f"{y}年行缺失")
            continue
        rate = _ratio_or_none(r.recommended_exempt, r.total_plan)
        if rate is None:
            miss_t.append(f"{y}年推免/计划数")
        else:
            rates.append((y, rate))
    if len(rates) >= 2 and not miss_t:
        rise_pp = (rates[-1][1] - rates[0][1]) * 100.0
        if rise_pp >= cfg.tuimian_cum_pp:
            findings.append(
                RiskFinding(
                    RISK_TUIMIAN,
                    "hit",
                    f"推免占比 {rates[0][0]}→{rates[-1][0]} 上升 {rise_pp:.1f}pp ≥ {cfg.tuimian_cum_pp}pp",
                )
            )
        else:
            findings.append(
                RiskFinding(
                    RISK_TUIMIAN, "hit" if False else "insufficient", f"三年累计上升 {rise_pp:.1f}pp，未达阈值", ()
                )
            )
            # 未达阈值不是"无风险"结论——保留为已审计通过项由 UI 呈现 🟢
            findings[-1] = RiskFinding(
                RISK_TUIMIAN, "checked_pass", f"推免占比变化 {rise_pp:+.1f}pp，低于 {cfg.tuimian_cum_pp}pp 阈值"
            )
    else:
        findings.append(
            RiskFinding(
                RISK_TUIMIAN, "insufficient", f"无法审计(缺{'、'.join(miss_t) or '连续两年数据'})", tuple(miss_t)
            )
        )

    # ---- 缩招：统考真实名额同比降 >= 20% ----
    prev, cur = by.get(base_year - 2), by.get(base_year - 1)

    def _quota(r: Optional[AdmissionRow]) -> Optional[int]:
        if r is None:
            return None
        if r.actual_exam_quota is not None:
            return r.actual_exam_quota
        if r.total_plan is not None and r.recommended_exempt is not None:
            return r.total_plan - r.recommended_exempt
        return None

    q_prev, q_cur = _quota(prev), _quota(cur)
    if q_prev is None or q_cur is None or q_prev == 0:
        miss = []
        if q_prev is None:
            miss.append(f"{base_year - 2}年统考名额")
        if q_cur is None:
            miss.append(f"{base_year - 1}年统考名额")
        findings.append(
            RiskFinding(RISK_SHRINK, "insufficient", f"无法审计(缺{'、'.join(miss) or '分母为零'})", tuple(miss))
        )
    else:
        drop_pct = (q_prev - q_cur) / q_prev * 100.0
        if drop_pct >= cfg.shrink_pct:
            findings.append(
                RiskFinding(
                    RISK_SHRINK, "hit", f"统考名额 {q_prev}→{q_cur}，同比降 {drop_pct:.1f}% ≥ {cfg.shrink_pct}%"
                )
            )
        else:
            findings.append(RiskFinding(RISK_SHRINK, "checked_pass", f"同比变化 {-drop_pct:+.1f}%，未达缩招阈值"))

    # ---- 爆热：报录比升 >=30% 且绝对值 >8 ----
    def _apply_ratio(r: Optional[AdmissionRow]) -> Optional[float]:
        if r is None:
            return None
        return _ratio_or_none(r.applicants, r.actual_exam_quota if r.actual_exam_quota is not None else _quota(r))

    a_prev, a_cur = _apply_ratio(prev), _apply_ratio(cur)
    if a_prev is None or a_cur is None or a_prev == 0:
        findings.append(
            RiskFinding(
                RISK_HEAT, "insufficient", "无法审计(缺报考人数或同口径统考名额)", ("applicants", "actual_exam_quota")
            )
        )
    else:
        rise_pct = (a_cur - a_prev) / a_prev * 100.0
        if rise_pct >= cfg.heat_rise_pct and a_cur > cfg.heat_abs_ratio:
            findings.append(
                RiskFinding(
                    RISK_HEAT, "hit", f"报录比 {a_prev:.1f}→{a_cur:.1f}，升 {rise_pct:.1f}% 且 >{cfg.heat_abs_ratio}"
                )
            )
        else:
            findings.append(RiskFinding(RISK_HEAT, "checked_pass", f"报录比变化 {rise_pct:+.1f}%（当前 {a_cur:.1f}）"))

    # ---- 复试线虚低：线低 + 复录比高 ----
    r_last = cur
    if r_last is None or r_last.retest_line is None:
        findings.append(RiskFinding(RISK_FAKE_LOW_LINE, "insufficient", "无法审计(缺复试线)", ("retest_line",)))
    else:
        rr = _ratio_or_none(r_last.retest_count, r_last.first_choice_admitted)
        if rr is None:
            findings.append(
                RiskFinding(
                    RISK_FAKE_LOW_LINE,
                    "insufficient",
                    "无法审计(缺进复试/一志愿录取数)",
                    ("retest_count", "first_choice_admitted"),
                )
            )
        elif rr >= cfg.retest_ratio_high:
            findings.append(
                RiskFinding(
                    RISK_FAKE_LOW_LINE,
                    "hit",
                    f"复试线 {r_last.retest_line} 但复录比 {rr:.2f} ≥ {cfg.retest_ratio_high}",
                )
            )
        else:
            findings.append(RiskFinding(RISK_FAKE_LOW_LINE, "checked_pass", f"复录比 {rr:.2f} 正常"))

    # ---- 改考：目录 diff（shell 提供）----
    if catalog_diff is None:
        findings.append(
            RiskFinding(RISK_EXAM_CHANGE, "insufficient", "无法审计(缺专业目录 diff，需 shell 提供)", ("catalog_diff",))
        )
    elif catalog_diff.strip():
        findings.append(RiskFinding(RISK_EXAM_CHANGE, "hit", f"专业目录存在变更：{catalog_diff.strip()[:120]}"))
    else:
        findings.append(RiskFinding(RISK_EXAM_CHANGE, "checked_pass", "目录无 diff"))

    # ---- 证据质量与时效 ----
    conf_rank = {"low": 0, "medium": 1, "high": 2}
    worst = min((r.confidence for r in real), key=lambda c: conf_rank.get(c, 0), default="low")
    all_missing = sorted({m for r in real for m in r.missing_fields})
    t0 = datetime.date.fromisoformat(today) if today else datetime.datetime.now(datetime.timezone.utc).date()
    stale = any(
        r.access_date and (t0 - datetime.date.fromisoformat(r.access_date)).days > cfg.stale_seasons * 365 for r in real
    )
    return AuditResult(
        school_id=rows[0].school_id if rows else "",
        program_code=rows[0].program_code if rows else "",
        base_year=base_year,
        risks=tuple(findings),
        evidence_quality=worst if real else "demo_only",
        missing=tuple(all_missing),
        stale_review_needed=stale,
        demo_isolated_rows=demo_n,
    )
