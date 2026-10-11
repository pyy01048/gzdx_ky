# -*- coding: utf-8 -*-
"""改考信息检测引擎（V10 新增）。

目标：从 kaoyan_notices 公告流中自动识别「改考 / 停招 / 新增 / 大纲调整 /
参考书变更」等对考生决策有实质影响的事件，结构化落 ``kaoyan_reforms`` 表，
供前端「通知中心 · 改考雷达」与院校详情页「改考提醒」展示。

设计原则：
- 与 spider_notices 相同套路：原生 DDL 幂等建表，不动 ORM 基线。
- 纯标题规则引擎（零网络依赖），可测试、可解释；URL 正文抓取作为可选增强。
- 去重键：(school_name, change_type, year, change_detail 指纹)，
  INSERT OR IGNORE，重复扫描不产生重复事件。
- 每条事件附 confidence（0-1）与匹配到的关键词，可审计、可人工复核。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Dict, List, Optional

# 规则优先级（同标题多命中时取信息量最大的类型）
_REFORM_PRIORITY = ["改考科目", "停招", "恢复招生", "新增专业",
                    "参考书变更", "大纲调整", "复试调整", "学制/学费调整"]

# --------------------------------------------------------------------------- #
# 规则库：change_type → (正则模式列表, 基础置信度)
# 按优先级排序：一次命中多个类型时取「信息量最大」的改考科目类优先。
# --------------------------------------------------------------------------- #
REFORM_PATTERNS: List[Dict] = [
    {
        "change_type": "改考科目",
        "confidence": 0.92,
        "patterns": [
            r"改考.{0,12}(?:科目|专业课|综合)",
            r"(?:初试|考试)(?:科目|专业课).{0,8}(?:调整|变更|改|更新)",
            r"(?:不再|停止|取消).{0,6}自命题",
            r"改用.{0,6}(?:统考|全国统考|311|312|313|396|408|306|307)",
            r"自命题.{0,6}(?:改为|调整为).{0,8}(?:统考|311|312|313|408|306)",
            r"(?:311|312|313|396|408|306|307|教育学专业基础|心理学专业基础|历史学专业基础|计算机学科专业基础|经济类综合能力|临床医学综合能力).{0,10}(?:统考|命题)",
        ],
    },
    {
        "change_type": "停招",
        "confidence": 0.9,
        "patterns": [
            r"(?:暂停|停止|取消|不再).{0,10}(?:招生|接收|招收)",
            r"停招",
            r"(?:撤销|终止).{0,8}学位点",
        ],
    },
    {
        "change_type": "恢复招生",
        "confidence": 0.85,
        "patterns": [r"恢复(?:招生|招收)", r"重新(?:招生|招收|启动)"],
    },
    {
        "change_type": "新增专业",
        "confidence": 0.8,
        "patterns": [
            r"新增.{0,14}(?:硕士|博士|学位|专业)",
            r"(?:首次|开始).{0,6}招收?.{0,8}(?:硕士|研究生)",
            r"新设.{0,8}学位点",
        ],
    },
    {
        "change_type": "参考书变更",
        "confidence": 0.82,
        "patterns": [
            r"参考(?:书|书目|教材).{0,8}(?:变更|调整|更新|改|修订)",
            r"(?:指定|推荐)参考书",
        ],
    },
    {
        "change_type": "大纲调整",
        "confidence": 0.8,
        "patterns": [
            r"考试大纲.{0,8}(?:调整|变更|修订|更新|发布)",
            r"(?:初试|复试)大纲",
        ],
    },
    {
        "change_type": "复试调整",
        "confidence": 0.75,
        "patterns": [
            r"复试.{0,8}(?:科目|形式|方案|办法).{0,6}(?:调整|变更|改革)",
            r"复试改革",
        ],
    },
    {
        "change_type": "学制/学费调整",
        "confidence": 0.7,
        "patterns": [
            r"(?:学制|学费|培养年限).{0,8}(?:调整|变更|延长|改为)",
            r"(?:专硕|专业学位).{0,6}(?:三年|3年|两年|2年)制",
        ],
    },
]

_REFORM_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS kaoyan_reforms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER,
    school_name TEXT NOT NULL,
    notice_id INTEGER,
    notice_type TEXT,
    title TEXT,
    year INTEGER,
    change_type TEXT NOT NULL,
    change_detail TEXT,
    keywords TEXT,
    confidence REAL DEFAULT 0.5,
    url TEXT,
    source TEXT,
    created_at TEXT,
    detail_hash TEXT,
    UNIQUE(school_name, change_type, year, detail_hash)
)
"""
_REFORM_IDX_DDL = """
CREATE INDEX IF NOT EXISTS idx_reforms_school
ON kaoyan_reforms(school_id);
CREATE INDEX IF NOT EXISTS idx_reforms_type
ON kaoyan_reforms(change_type);
"""

NOTICE_YEAR_RE = re.compile(r"(20[12]\d)")


def ensure_reforms_schema(db_session) -> None:
    """幂等建表（与 notices 同套路，不动 ORM）。"""
    conn = db_session.connection().connection
    conn.executescript(_REFORM_TABLE_DDL)
    conn.executescript(_REFORM_IDX_DDL)
    conn.commit()


def classify_reform_title(title: str) -> Optional[Dict]:
    """对单条公告标题做改考分类。命中返回结构化结果，未命中返回 None。

    返回: {change_type, confidence, keywords, year}
    """
    if not title:
        return None
    text = title.strip()
    best: Optional[Dict] = None
    for rule in REFORM_PATTERNS:
        for pat in rule["patterns"]:
            m = re.search(pat, text)
            if m:
                kw = m.group(0)
                cand = {
                    "change_type": rule["change_type"],
                    "confidence": rule["confidence"],
                    "keywords": kw,
                }
                # 同标题多命中时取信息量大的（模块级 _REFORM_PRIORITY）
                if best is None or _REFORM_PRIORITY.index(cand["change_type"]) < _REFORM_PRIORITY.index(best["change_type"]):
                    best = cand
                break
    if best:
        years = NOTICE_YEAR_RE.findall(text)
        best["year"] = int(years[0]) if years else None
    return best


def _detail_hash(school_name: str, change_type: str, year, detail: str) -> str:
    raw = f"{school_name}|{change_type}|{year or ''}|{detail or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def scan_notices_for_reforms(
    db_session,
    school_ids: Optional[List[int]] = None,
    limit: int = 5000,
    dry_run: bool = False,
) -> Dict:
    """扫描 kaoyan_notices 全量标题，产出改考事件并入库。

    返回: {scanned, detected, inserted, by_type, sample}
    """
    ensure_reforms_schema(db_session)
    conn = db_session.connection().connection

    sql = ("SELECT id, school_id, school_name, title, notice_type, url, source "
           "FROM kaoyan_notices")
    args: list = []
    if school_ids:
        sql += " WHERE school_id IN (%s)" % ",".join("?" * len(school_ids))
        args.extend(school_ids)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)

    rows = conn.execute(sql, args).fetchall()
    detected: List[Dict] = []
    for r in rows:
        notice_id, sch_id, sch_name, title, notice_type, url, source = r
        hit = classify_reform_title(title or "")
        if not hit:
            continue
        detected.append({
            "school_id": sch_id,
            "school_name": sch_name,
            "notice_id": notice_id,
            "notice_type": notice_type,
            "title": title,
            "url": url,
            "source": source,
            **hit,
            "detail_hash": _detail_hash(sch_name or "", hit["change_type"],
                                        hit.get("year"), title or ""),
        })

    inserted = 0
    if not dry_run:
        now = datetime.utcnow().isoformat()
        for d in detected:
            cur = conn.execute(
                "INSERT OR IGNORE INTO kaoyan_reforms (school_id, school_name, "
                "notice_id, notice_type, title, year, change_type, change_detail, "
                "keywords, confidence, url, source, created_at, detail_hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (d["school_id"], d["school_name"], d["notice_id"], d["notice_type"],
                 d["title"], d.get("year") or 0, d["change_type"], d["title"],
                 d["keywords"], d["confidence"], d["url"], d["source"], now,
                 d["detail_hash"]),
            )
            inserted += cur.rowcount
        conn.commit()

    by_type: Dict[str, int] = {}
    for d in detected:
        by_type[d["change_type"]] = by_type.get(d["change_type"], 0) + 1
    return {
        "scanned": len(rows),
        "detected": len(detected),
        "inserted": inserted,
        "by_type": by_type,
        "sample": detected[:5],
    }


def list_reforms(db_session, school_id: Optional[int] = None,
                 change_type: Optional[str] = None,
                 year: Optional[int] = None,
                 limit: int = 100) -> List[Dict]:
    """改考事件查询（前端改考雷达 / 院校详情提醒）。"""
    ensure_reforms_schema(db_session)
    conn = db_session.connection().connection
    sql = ("SELECT id, school_id, school_name, notice_id, title, year, "
           "change_type, keywords, confidence, url, source, created_at "
           "FROM kaoyan_reforms WHERE 1=1")
    args: list = []
    if school_id:
        sql += " AND school_id = ?"
        args.append(school_id)
    if change_type:
        sql += " AND change_type = ?"
        args.append(change_type)
    if year:
        sql += " AND (year = ? OR year = 0 OR year IS NULL)"
        args.append(year)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    args.append(limit)
    cols = ["id", "school_id", "school_name", "notice_id", "title", "year",
            "change_type", "keywords", "confidence", "url", "source", "created_at"]
    out = []
    for r in conn.execute(sql, args).fetchall():
        d = dict(zip(cols, r))
        if d.get("year") == 0:  # 0 = 年份未知（入库占位，规避 UNIQUE 对 NULL 不去重）
            d["year"] = None
        out.append(d)
    return out


def reform_stats(db_session) -> Dict:
    """改考事件统计（按类型 / 按院校 top10）。"""
    ensure_reforms_schema(db_session)
    conn = db_session.connection().connection
    by_type = dict(conn.execute(
        "SELECT change_type, COUNT(*) FROM kaoyan_reforms GROUP BY change_type"
    ).fetchall())
    top_schools = [
        {"school": r[0], "count": r[1]}
        for r in conn.execute(
            "SELECT school_name, COUNT(*) c FROM kaoyan_reforms "
            "GROUP BY school_name ORDER BY c DESC LIMIT 10"
        ).fetchall()
    ]
    total = sum(by_type.values())
    return {"total": total, "by_type": by_type, "top_schools": top_schools}
