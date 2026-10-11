# -*- coding: utf-8 -*-
"""study_stats 独立闭环：从 study_sessions 等明细表聚合写入/更新 study_stats。

- total_duration / subject_durations：按 date 聚合 study_sessions
- task_completed：按 date 统计 tasks（completed_at 当天完成）
- error_count：按 date 统计当日新增错题（error_records.created_at 当天）
- new_knowledge_count：按 date 统计当日新增知识点（knowledge_points.created_at 当天）

用法：python scripts/sync_study_stats.py
可重复运行（按 date 幂等 upsert），适合定时任务或每次会话后手动同步。
"""
import io
import json
import os
import sys
from datetime import date, datetime, timedelta

# 允许从任意 CWD 运行
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from database import SessionLocal
from models import StudySession, StudyStats, Task, ErrorRecord, KnowledgePoint
from sqlalchemy import func


def _day(dt: datetime) -> date:
    return dt.date()


def sync(db) -> dict:
    # 1. 需要覆盖的日期：study_sessions 有数据的全部日期 + 今天（保证今天至少有一行快照）
    session_dates = [
        r[0] for r in db.query(StudySession.date).distinct().all() if r[0]
    ]
    today = date.today()
    all_dates = set(session_dates) | {today}

    # 2. 聚合 study_sessions
    agg = (
        db.query(
            StudySession.date,
            StudySession.subject,
            func.coalesce(func.sum(StudySession.duration), 0),
        )
        .group_by(StudySession.date, StudySession.subject)
        .all()
    )
    per_date_total: dict = {}
    per_date_subject: dict = {}
    for d, sub, dur in agg:
        per_date_total[d] = per_date_total.get(d, 0) + dur
        if sub:
            sub_map = per_date_subject.get(d)
            if sub_map is None:
                sub_map = {}
                per_date_subject[d] = sub_map
            sub_map[sub] = sub_map.get(sub, 0) + dur

    # 3. 聚合 tasks（完成数）、error_records（当日新增错题）、knowledge_points（当日新增）
    tasks_agg = (
        db.query(func.date(Task.completed_at), func.count(Task.id))
        .filter(Task.status == "done", Task.completed_at.isnot(None))
        .group_by(func.date(Task.completed_at))
        .all()
    )
    task_by_date = {r[0]: r[1] for r in tasks_agg}

    errors_agg = (
        db.query(func.date(ErrorRecord.created_at), func.count(ErrorRecord.id))
        .filter(ErrorRecord.status == "active")
        .group_by(func.date(ErrorRecord.created_at))
        .all()
    )
    error_by_date = {r[0]: r[1] for r in errors_agg}

    kp_agg = (
        db.query(func.date(KnowledgePoint.created_at), func.count(KnowledgePoint.id))
        .group_by(func.date(KnowledgePoint.created_at))
        .all()
    )
    kp_by_date = {r[0]: r[1] for r in kp_agg}

    # 4. upsert study_stats
    stats_rows = {r.date: r for r in db.query(StudyStats).all()}
    written, updated = 0, 0
    for d in sorted(all_dates):
        data = dict(
            total_duration=int(per_date_total.get(d, 0)),
            subject_durations=per_date_subject.get(d, {}) or None,
            task_completed=int(task_by_date.get(d.isoformat(), 0)),
            error_count=int(error_by_date.get(d.isoformat(), 0)),
            new_knowledge_count=int(kp_by_date.get(d.isoformat(), 0)),
        )
        if d in stats_rows:
            row = stats_rows[d]
            for k, v in data.items():
                setattr(row, k, v)
            updated += 1
        else:
            db.add(StudyStats(date=d, **data))
            written += 1
    db.commit()

    total_rows = db.query(StudyStats).count()
    return {
        "written": written,
        "updated": updated,
        "total_rows": total_rows,
        "dates": [d.isoformat() for d in sorted(all_dates)],
        "today": today.isoformat(),
        "today_duration": int(per_date_total.get(today, 0)),
        "today_subjects": per_date_subject.get(today, {}),
    }


if __name__ == "__main__":
    # 输出写文件（PowerShell 子进程 stdout 可能被吞）
    out_path = os.path.join(os.environ.get("TEMP_DIR", BASE_DIR), "sync_study_stats_result.json")
    buf = io.StringIO()
    try:
        db = SessionLocal()
        try:
            result = sync(db)
            buf.write(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            db.close()
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print(f"RESULT_WRITTEN {out_path}")
    except Exception as e:
        import traceback
        with open(out_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print(f"ERROR_WRITTEN {out_path}")
