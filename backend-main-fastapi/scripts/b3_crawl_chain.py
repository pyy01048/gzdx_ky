# -*- coding: utf-8 -*-
"""C 批次3 补爬链（服务器后台执行，分段可续跑）：

  stage notices   全量公告采集（crawl_school_notices 不限校数；robots+2-5s 礼貌延迟）
  stage govern    批次2 治理复跑（新公告清洗/三态/去重 + 改考重打分）
  stage admission 录取名单通用采集器全量（limit 不限、每校至多 10 条名单通知）
  stage stats     覆盖率全量统计（非抽样）

用法：python scripts/b3_crawl_chain.py [notices|govern|admission|stats|all]
日志建议：nohup ... > data/b3_crawl.log 2>&1 &
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def stage_notices():
    from database import SessionLocal
    from services.kaoyan.spider_notices import crawl_school_notices

    db = SessionLocal()
    try:
        rep = crawl_school_notices(db_session=db, max_schools=100000)
        log("NOTICES_DONE " + json.dumps(rep, ensure_ascii=False, default=str)[:3000])
    finally:
        db.close()


def stage_govern():
    from database import SessionLocal
    from services.kaoyan.notice_governance import run_batch2

    db = SessionLocal()
    try:
        rep = run_batch2(db)
        log("GOVERN_DONE " + json.dumps(rep, ensure_ascii=False, default=str)[:3000])
    finally:
        db.close()


def stage_admission():
    from pipeline.admission_general_crawler import run

    rep = run(limit=100000, max_per_school=10)
    log("ADMISSION_DONE " + json.dumps(rep, ensure_ascii=False, default=str)[:4000])


def stage_stats():
    from database import SessionLocal
    from services.dbapi_compat import wrap_conn

    db = SessionLocal()
    try:
        c = wrap_conn(db.connection().connection)
        total = c.execute("SELECT COUNT(*) FROM kaoyan_schools").fetchone()[0]
        cov = c.execute("SELECT COUNT(DISTINCT school_id) FROM kaoyan_admissions").fetchone()[0]
        avg = c.execute(
            "SELECT COUNT(DISTINCT school_id) FROM kaoyan_admissions WHERE admit_avg_score IS NOT NULL"
        ).fetchone()[0]
        ratio = c.execute(
            "SELECT COUNT(DISTINCT school_id) FROM kaoyan_admissions "
            "WHERE retest_count IS NOT NULL AND admit_count IS NOT NULL"
        ).fetchone()[0]
        rows = c.execute("SELECT COUNT(*) FROM kaoyan_admissions").fetchone()[0]
        details = c.execute("SELECT COUNT(*) FROM kaoyan_admission_details").fetchone()[0]
        notices = c.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
        log(
            "STATS "
            + json.dumps(
                {
                    "schools_total": total,
                    "admission_rows": rows,
                    "detail_rows": details,
                    "schools_with_admission": cov,
                    "schools_with_avg": avg,
                    "schools_with_ratio": ratio,
                    "notices_total": notices,
                    "coverage_pct": round(100.0 * avg / total, 1) if total else 0,
                },
                ensure_ascii=False,
            )
        )
    finally:
        db.close()


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    stages = ["notices", "govern", "admission", "stats"] if stage == "all" else [stage]
    for s in stages:
        log(f"STAGE_BEGIN {s}")
        {"notices": stage_notices, "govern": stage_govern, "admission": stage_admission, "stats": stage_stats}[s]()
        log(f"STAGE_END {s}")


if __name__ == "__main__":
    main()
