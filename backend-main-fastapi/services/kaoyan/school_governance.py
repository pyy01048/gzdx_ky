# -*- coding: utf-8 -*-
"""C 批次3：院校字段治理（评估报告 #20/#21/#13 的确定性部分）。

- #20 地区双口径拆分：province → exam_region（国家线 A/B 区）+ geo_region（地理七大区）；
  历史混用列 region 归一为考研分区口径（地理大区值迁移到 geo_region，不再同字段混枚举）。
- #21 层级嵌套：level 只保留 985/211/双非 互斥层级；双一流改嵌套布尔标签
  is_double_first_class（985/211 全含 + 原 level='双一流' 的非 211 高校）。
- #13 空章节：不改数据，统计口径与 /api/taxonomy/tree 一致（大纲骨架 chapters_of），
  供端点默认隐藏 + 计数透出。

全部确定性映射、幂等可重跑；无省份证据的行留空登记，不伪造。
"""

from __future__ import annotations

from typing import Any, Dict

from services.dbapi_compat import wrap_conn

# 教育部国家线 B 区十省（其余省份 A 区）
B_PROVINCES = ("内蒙古", "广西", "海南", "贵州", "云南", "西藏", "甘肃", "青海", "宁夏", "新疆")

GEO_REGIONS = {
    "华北": ("北京", "天津", "河北", "山西", "内蒙古"),
    "东北": ("辽宁", "吉林", "黑龙江"),
    "华东": ("上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"),
    "华中": ("河南", "湖北", "湖南"),
    "华南": ("广东", "广西", "海南"),
    "西南": ("重庆", "四川", "贵州", "云南", "西藏"),
    "西北": ("陕西", "甘肃", "青海", "宁夏", "新疆"),
}
_PROVINCE_GEO = {p: g for g, ps in GEO_REGIONS.items() for p in ps}
_GEO_NAMES = set(GEO_REGIONS)


def exam_region_of(province: str | None) -> str | None:
    p = (province or "").strip()
    if not p:
        return None
    return "B区" if p in B_PROVINCES else "A区"


def geo_region_of(province: str | None) -> str | None:
    return _PROVINCE_GEO.get((province or "").strip())


def _snapshot(db) -> Dict[str, Any]:
    conn = wrap_conn(db.connection().connection)
    r = conn.execute(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN exam_region IS NULL OR exam_region='' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN geo_region IS NULL OR geo_region='' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN is_double_first_class THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN level='双一流' THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN region IN ('华东','华北','华中','华南','西南','西北','东北') THEN 1 ELSE 0 END) "
        "FROM kaoyan_schools"
    ).fetchone()
    return dict(zip(("total", "exam_missing", "geo_missing", "dfc", "level_dfc", "region_geo_mixed"), r, strict=False))


def govern_schools(db) -> Dict[str, Any]:
    """地区拆分 + 层级嵌套回写（幂等；manual 无概念，全量确定性）。"""
    conn = wrap_conn(db.connection().connection)
    # 治理列幂等补齐（124 迁移同口径；sqlite 裸 ALTER 兜底）
    for col, typ in (
        ("exam_region", "TEXT"),
        ("geo_region", "TEXT"),
        ("is_double_first_class", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ):
        try:
            conn.execute(f"ALTER TABLE kaoyan_schools ADD COLUMN IF NOT EXISTS {col} {typ}")
        except Exception:  # noqa: BLE001
            try:
                conn.execute(f"ALTER TABLE kaoyan_schools ADD COLUMN {col} {typ}")
            except Exception:  # noqa: BLE001 - 列已存在
                pass
    conn.commit()
    rows = conn.execute("SELECT id, province, region, level FROM kaoyan_schools ORDER BY id").fetchall()
    stats = {
        "total": len(rows),
        "exam_filled": 0,
        "geo_filled": 0,
        "region_normalized": 0,
        "dfc_set": 0,
        "level_dfc_migrated": 0,
        "province_missing": 0,
    }
    for sid, province, region, level in rows:
        ex, geo = exam_region_of(province), geo_region_of(province)
        if not (province or "").strip():
            stats["province_missing"] += 1
        new_region = region
        if (region or "") in _GEO_NAMES:
            new_region = ex  # 混用列归一为考研分区；地理口径已落 geo_region
            stats["region_normalized"] += 1
        elif (region or "") in ("A", "B"):
            new_region = region + "区"
            stats["region_normalized"] += 1
        dfc = level in ("985", "211", "双一流")
        new_level = "双非" if level == "双一流" else level
        if level == "双一流":
            stats["level_dfc_migrated"] += 1
        conn.execute(
            "UPDATE kaoyan_schools SET exam_region=?, geo_region=?, region=?, level=?, "
            "is_double_first_class=? WHERE id=?",
            (ex, geo, new_region, new_level, dfc, sid),
        )
        if ex:
            stats["exam_filled"] += 1
        if geo:
            stats["geo_filled"] += 1
        if dfc:
            stats["dfc_set"] += 1
    conn.commit()
    return stats


def empty_chapter_stats(db) -> Dict[str, Any]:
    """与 /api/taxonomy/tree 同口径的空章节统计（大纲骨架 vs 实际 KP 章节）。"""
    from models import KnowledgePoint
    from services import taxonomy

    taxonomy.load_configured_subjects(db)
    subjects = list(taxonomy.CORE_SUBJECTS) + list(taxonomy.MAJOR_SUBJECTS) + list(taxonomy.EXT_SUBJECTS)
    have: dict[str, set] = {}
    for subj, ch in (
        db.query(KnowledgePoint.subject, KnowledgePoint.chapter)
        .filter(KnowledgePoint.chapter.isnot(None), KnowledgePoint.chapter != "")
        .distinct()
        .all()
    ):
        have.setdefault(taxonomy.normalize_subject(subj), set()).add(ch)
    total = empty = 0
    per_subject = {}
    for s in subjects:
        chs = taxonomy.chapters_of(s)
        e = [c for c in chs if c not in have.get(s, set())]
        total += len(chs)
        empty += len(e)
        if e:
            per_subject[s] = len(e)
    return {"chapters_total": total, "empty": empty, "per_subject": per_subject}


def run_batch3_governance(db, dry_run: bool = False) -> Dict[str, Any]:
    before = _snapshot(db)
    chapters = empty_chapter_stats(db)
    if dry_run:
        return {"before": before, "empty_chapters": chapters, "dry_run": True}
    stats = govern_schools(db)
    return {"before": before, "after": _snapshot(db), "schools": stats, "empty_chapters": chapters}
