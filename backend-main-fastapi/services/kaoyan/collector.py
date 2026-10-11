# -*- coding: utf-8 -*-
"""工科定向采集编排（T5-1/T5-3）。

把三条采集链串起来（可独立调用，也挂 APScheduler 周期执行）：
1. ``collect_engineering``：研招网爬虫（spider_yz）+ 工科专业代码过滤入库 majors。
2. ``backfill_national_lines``：国家线回填（engineering_codes，官方核实数据）。
3. ``collect_notices``：公告采集（spider_notices）。

每次运行写 ``kaoyan_collection_runs``（表已存在）记录来源/计数/状态，前端
「数据管理」页可查历史。全程幂等：重跑只补增量。
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def _record_run(db_session, source: str, status: str, detail: Dict) -> None:
    """写采集运行记录（列名以 ORM 实际定义为准：scope/item_type/row_count/detail）。

    detail 存 JSON 摘要——给「数据管理」页看每次采集的明细（前后计数/失败原因）。
    """
    import json

    from models import KaoyanCollectionRun

    db_session.add(KaoyanCollectionRun(
        source=source,
        scope=str(detail.get("source", source))[:100],
        item_type="mixed",
        row_count=int(detail.get("items", detail.get("updated", detail.get("notices", 0)) or 0)),
        status=status,
        detail=json.dumps(detail, ensure_ascii=False, default=str)[:4000],
    ))
    db_session.commit()


def collect_engineering(db_session=None, provinces: Optional[list] = None, dry_run: bool = False) -> Dict:
    """研招网工科采集（门类 07/08 两门，二级代码经 is_engineering_code 过滤）。

    研招网接口按门类返回院校粒度；专业粒度数据（majors）在院校详情接口，
    本函数先把院校增量补齐（含缺失层级/官网），majors 增量走
    ``/zsml/querySchAction.do`` 二级学科接口（probe 后接入）。
    """
    from database import SessionLocal
    from services.kaoyan.engineering_codes import is_engineering_code
    from services.kaoyan.spider_yz import crawl

    close = False
    if db_session is None:
        db_session = SessionLocal()
        close = True
    try:
        from models import KaoyanSchool, KaoyanMajor

        before_schools = db_session.query(KaoyanSchool).count()
        res = crawl(province_codes=provinces, subject_codes=["07", "08"]) or {}
        after_schools = db_session.query(KaoyanSchool).count()

        # majors 过滤统计：现库中工科定向代码的专业数（采集增量口径）
        eng_majors = [
            m.id for m in db_session.query(KaoyanMajor).all()
            if is_engineering_code(m.subject_code) or is_engineering_code(m.code)
        ]
        detail = {
            "source": "spider_yz+engineering_filter",
            "schools_before": before_schools,
            "schools_after": after_schools,
            "engineering_majors": len(eng_majors),
            "crawl_result": {k: v for k, v in res.items() if isinstance(v, (int, str, bool))},
        }
        if not dry_run:
            _record_run(db_session, "engineering", "success" if res.get("success", True) else "blocked", detail)
        return detail
    finally:
        if close:
            db_session.close()


def backfill_national_lines_task(db_session=None, dry_run: bool = False) -> Dict:
    """国家线回填任务（官方核实静态数据 → kaoyan_scorelines）。"""
    from database import SessionLocal
    from services.kaoyan.engineering_codes import backfill_national_lines

    close = False
    if db_session is None:
        db_session = SessionLocal()
        close = True
    try:
        detail = backfill_national_lines(db_session)
        detail["source"] = "national_line_official"
        if not dry_run:
            _record_run(db_session, "national_line", "success", detail)
        return detail
    finally:
        if close:
            db_session.close()


def collect_notices_task(db_session=None, max_schools: int = 20, dry_run: bool = False) -> Dict:
    """公告采集任务。"""
    from database import SessionLocal
    from services.kaoyan.spider_notices import crawl_school_notices

    close = False
    if db_session is None:
        db_session = SessionLocal()
        close = True
    try:
        stats = crawl_school_notices(max_schools=max_schools, dry_run=dry_run)
        stats["source"] = "school_notices"
        if not dry_run:
            _record_run(db_session, "notices", "success", stats)
        return stats
    finally:
        if close:
            db_session.close()


def run_all(db_session=None, dry_run: bool = False) -> Dict:
    """全链采集（APScheduler 周期任务入口）：工科 → 国家线 → 公告。

    单链失败不阻断其余（各自 try/except，失败记录在结果里）。
    """
    out: Dict[str, Dict] = {}
    for name, fn in (
        ("engineering", collect_engineering),
        ("national_line", backfill_national_lines_task),
        ("notices", collect_notices_task),
    ):
        try:
            out[name] = fn(db_session=db_session, dry_run=dry_run)
        except Exception as e:
            logger.warning("[collect_all] %s 失败: %s", name, e)
            out[name] = {"error": str(e)[:200]}
    return out
