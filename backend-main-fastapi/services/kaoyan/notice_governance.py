# -*- coding: utf-8 -*-
"""C 批次2：公告/改考清洗与分类治理（评估报告 #12/#14 + P3 去重/标题/关键词）。

- **缺日期打标**：publish_date 缺失 → 标题/URL/正文前段证据解析回填（date_source
  留痕）；无证据 → date_source='unknown' 显式打标（前端显示「日期未知」，不伪造）。
- **标题清洗**：数字日期前缀残留剥离（title_raw 留原文快照）。
- **去重**：同校同清洗标题保留最小 id，其余 review_status='duplicate'。
- **白名单分类器 + 审核队列**：招生主题白名单命中 → ok；节气/部门/人名/超短无主题
  → noise（is_noise 同步）；其余 → pending_review 进人工队列（feed 不展示待审/噪声/重复）。
- **改考置信度分级**：固定 0.8 → 规则基分 + 证据加分（年份/科目代码/官方域名/多命中），
  confidence_basis 留痕；噪声标题（JOINT TRAINING/BRT 测试等）→ review_status='noise'
  出列；year 缺失从关联公告回填；keywords 去模板（重算匹配片段）。
- 人工裁定（review_source='manual'）行重跑不覆盖（幂等红线）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

from services.dbapi_compat import wrap_conn
from services.kaoyan.reform_detector import classify_reform_title, ensure_reforms_schema

# --------------------------------------------------------------------------- #
# 标题清洗 / 日期证据
# --------------------------------------------------------------------------- #
_DATE_PREFIX_RE = re.compile(
    r"^\s*(?:[\[【（(]\s*)?"
    r"(?:20\d{2}\s*[-/年.]\s*\d{1,2}\s*[-/月.]\s*\d{1,2}\s*日?|20\d{6})"
    r"(?:\s*[\]】）)])?\s*[-–—:：.]?\s*"
)
_DATE_IN_TEXT_RE = re.compile(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*日?")


def clean_title(title: str) -> str:
    """剥离标题头部数字日期前缀残留（评估报告 48 条 4.0%）。"""
    if not title:
        return title or ""
    prev = None
    s = title.strip()
    while prev != s:
        prev = s
        s = _DATE_PREFIX_RE.sub("", s, count=1).strip()
    return s or title.strip()


def parse_date_evidence(title: str, url: str, content_head: str) -> Tuple[Optional[str], str]:
    """按 标题 → URL → 正文前段 顺序取发布日期证据；无证据返回 (None,'unknown')。"""
    for text, src in ((title or "", "title"), (url or "", "url"), (content_head or "", "content")):
        m = _DATE_IN_TEXT_RE.search(text)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}", src
    return None, "unknown"


# --------------------------------------------------------------------------- #
# 招生主题白名单 / 噪声黑名单
# --------------------------------------------------------------------------- #
ADMISSION_WHITELIST_RE = re.compile(
    r"招生|硕士|研究生|博士|考试|初试|复试|调剂|录取|推免|保研|夏令营|大纲|参考书|"
    r"专业目录|准考证|成绩|分数线|报录比|报名|确认|考场|拟录取|奖助|学费|学制|"
    r"专项计划|少干|士兵计划|退役|加分|照顾政策|命题|科目"
)
SOLAR_TERMS = {
    "立春",
    "雨水",
    "惊蛰",
    "春分",
    "清明",
    "谷雨",
    "立夏",
    "小满",
    "芒种",
    "夏至",
    "小暑",
    "大暑",
    "立秋",
    "处暑",
    "白露",
    "秋分",
    "寒露",
    "霜降",
    "立冬",
    "小雪",
    "大雪",
    "冬至",
    "小寒",
    "大寒",
    "元宵节",
    "春节",
    "中秋",
    "端午",
    "元旦",
}
NOISE_DEPT_RE = re.compile(
    r"^(组织部|宣传部|财务处|校医院|图书馆|档案馆|信息办|研工部|学工部|团委|工会|"
    r"后勤|保卫处|教务处|人事处|国际处|校友会|基金会|人文复旦|桂电晨曦|.{0,6}部)$"
)
REFORM_NOISE_RE = re.compile(r"JOINT\s*TRAINING|基本制度测试|（BRT）|\(BRT\)|联培专项招生", re.I)


def classify_notice(title: str) -> str:
    """ok / pending_review / noise 三态（白名单优先于长度规则）。"""
    t = (title or "").strip()
    if not t:
        return "noise"
    if ADMISSION_WHITELIST_RE.search(t):
        return "ok"
    if t in SOLAR_TERMS or NOISE_DEPT_RE.match(t):
        return "noise"
    if len(t) <= 4:
        return "noise"
    return "pending_review"


# --------------------------------------------------------------------------- #
# 改考置信度分级
# --------------------------------------------------------------------------- #
_OFFICIAL_HOST_RE = re.compile(r"yjszs|yz\.|graduate|zsxx|yjsy|grs\.", re.I)
_SUBJECT_CODE_RE = re.compile(r"(?<!\d)[89]\d{2}(?!\d)|(?<!\d)[34]\d{2}(?!\d)")


def score_reform_confidence(title: str, url: str, source: str, change_type: str, base: float) -> Tuple[float, str]:
    """规则基分 + 证据加分 → (confidence, basis JSON)。clamp [0.40, 0.95]。"""
    basis = [f"base:{change_type}={base:.2f}"]
    conf = float(base)
    t = title or ""
    if re.search(r"20[12]\d", t):
        conf += 0.05
        basis.append("year_in_title:+0.05")
    if _SUBJECT_CODE_RE.search(t):
        conf += 0.05
        basis.append("subject_code:+0.05")
    if _OFFICIAL_HOST_RE.search(f"{url or ''} {source or ''}"):
        conf += 0.05
        basis.append("official_host:+0.05")
    hits = set()
    from services.kaoyan.reform_detector import REFORM_PATTERNS

    for rule in REFORM_PATTERNS:
        for pat in rule["patterns"]:
            if re.search(pat, t):
                hits.add(rule["change_type"])
                break
    if len(hits) >= 2:
        conf += 0.05
        basis.append("multi_rule_hit:+0.05")
    if REFORM_NOISE_RE.search(t):
        conf -= 0.15
        basis.append("noise_marker:-0.15")
    conf = round(min(0.95, max(0.40, conf)), 2)
    return conf, json.dumps(basis, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 公告治理
# --------------------------------------------------------------------------- #
def govern_notices(db) -> Dict[str, Any]:
    from services.kaoyan.spider_notices import ensure_notices_schema

    ensure_notices_schema(db)
    conn = wrap_conn(db.connection().connection)
    rows = conn.execute(
        "SELECT id, school_name, title, publish_date, url, substr(content,1,600), "
        "is_noise, review_source FROM kaoyan_notices ORDER BY id"
    ).fetchall()
    stats = {
        "total": len(rows),
        "title_cleaned": 0,
        "date_filled": 0,
        "date_unknown": 0,
        "noise": 0,
        "pending": 0,
        "duplicate": 0,
        "ok": 0,
        "manual_skipped": 0,
    }
    seen: Dict[Tuple[str, str], int] = {}
    for rid, school, title, pdate, url, chead, is_noise, rsource in rows:
        if rsource == "manual":
            stats["manual_skipped"] += 1
            continue
        cleaned = clean_title(title or "")
        key = (school or "", cleaned)
        if key in seen:
            # 重复行保留原标题/日期（避免 uq(school,title,publish_date) 冲突），仅出列
            conn.execute(
                "UPDATE kaoyan_notices SET review_status='duplicate', "
                "review_source='auto', title_raw=COALESCE(title_raw, ?) WHERE id=?",
                (title, rid),
            )
            stats["duplicate"] += 1
            continue
        seen[key] = rid
        if cleaned != (title or ""):
            conn.execute("UPDATE kaoyan_notices SET title=?, title_raw=? WHERE id=?", (cleaned, title, rid))
            stats["title_cleaned"] += 1
        if not (pdate or "").strip():
            d, src = parse_date_evidence(title, url, chead)
            if d:
                conn.execute("UPDATE kaoyan_notices SET publish_date=?, date_source=? WHERE id=?", (d, src, rid))
                stats["date_filled"] += 1
            else:
                conn.execute("UPDATE kaoyan_notices SET date_source='unknown' WHERE id=?", (rid,))
                stats["date_unknown"] += 1
        elif not conn.execute("SELECT date_source FROM kaoyan_notices WHERE id=?", (rid,)).fetchone()[0]:
            conn.execute("UPDATE kaoyan_notices SET date_source='original' WHERE id=?", (rid,))
        state = "noise" if is_noise else classify_notice(cleaned)
        conn.execute(
            "UPDATE kaoyan_notices SET review_status=?, review_source='auto', is_noise=? WHERE id=?",
            (state, state == "noise", rid),
        )
        stats[state if state != "pending_review" else "pending"] += 1
    conn.commit()
    return stats


# --------------------------------------------------------------------------- #
# 改考治理
# --------------------------------------------------------------------------- #
def govern_reforms(db) -> Dict[str, Any]:
    ensure_reforms_schema(db)
    conn = wrap_conn(db.connection().connection)
    rows = conn.execute(
        "SELECT r.id, r.title, r.url, r.source, r.change_type, r.confidence, r.year, "
        "r.notice_id, r.review_source FROM kaoyan_reforms r ORDER BY r.id"
    ).fetchall()
    stats = {
        "total": len(rows),
        "rescored": 0,
        "noise": 0,
        "year_filled": 0,
        "keywords_refreshed": 0,
        "manual_skipped": 0,
        "conf_distinct": 0,
    }
    confs = set()
    for rid, title, url, source, ctype, conf, year, notice_id, rsource in rows:
        if rsource == "manual":
            stats["manual_skipped"] += 1
            confs.add(round(float(conf or 0), 2))
            continue
        hit = classify_reform_title(title or "")
        base = hit["confidence"] if hit else 0.6
        new_conf, basis = score_reform_confidence(title, url, source, ctype, base)
        noise = bool(REFORM_NOISE_RE.search(title or ""))
        new_year = year
        if not new_year and hit and hit.get("year"):
            new_year = int(hit["year"])  # 改考标题自身年份=招生年份，优先于公告发布年
            stats["year_filled"] += 1
        elif not new_year and notice_id:
            prow = conn.execute("SELECT publish_date, title FROM kaoyan_notices WHERE id=?", (notice_id,)).fetchone()
            if prow:
                m = re.search(r"20[12]\d", prow[1] or "") or re.search(r"20[12]\d", prow[0] or "")
                if m:
                    new_year = int(m.group(0))
                    stats["year_filled"] += 1
        kw = hit["keywords"] if hit else None
        if kw:
            stats["keywords_refreshed"] += 1
        conn.execute(
            "UPDATE kaoyan_reforms SET confidence=?, confidence_basis=?, "
            "review_status=?, review_source='auto', year=?, keywords=? WHERE id=?",
            (new_conf, basis, "noise" if noise else "ok", new_year or 0, kw, rid),
        )
        stats["rescored"] += 1
        if noise:
            stats["noise"] += 1
        confs.add(new_conf)
    conn.commit()
    stats["conf_distinct"] = len(confs)
    return stats


def _snapshot(db) -> Dict[str, Any]:
    conn = wrap_conn(db.connection().connection)
    n = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN publish_date IS NULL OR publish_date='' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN review_status='noise' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN review_status='pending_review' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN review_status='duplicate' THEN 1 ELSE 0 END) "
        "FROM kaoyan_notices"
    ).fetchone()
    r = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT confidence), "
        "SUM(CASE WHEN review_status='noise' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN year IS NULL OR year=0 THEN 1 ELSE 0 END) "
        "FROM kaoyan_reforms"
    ).fetchone()
    return {
        "notices": {"total": n[0], "missing_date": n[1], "noise": n[2], "pending": n[3], "duplicate": n[4]},
        "reforms": {"total": r[0], "conf_distinct": r[1], "noise": r[2], "year_missing": r[3]},
    }


def run_batch2(db, *, dry_run: bool = False) -> Dict[str, Any]:
    from services.kaoyan.spider_notices import ensure_notices_schema

    ensure_notices_schema(db)
    ensure_reforms_schema(db)  # 两者已幂等补齐治理列（123 迁移同口径）
    before = _snapshot(db)
    if dry_run:
        return {"dry_run": True, "before": before}
    notices = govern_notices(db)
    reforms = govern_reforms(db)
    after = _snapshot(db)
    return {"before": before, "after": after, "notices": notices, "reforms": reforms}
