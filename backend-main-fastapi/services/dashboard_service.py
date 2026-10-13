"""
Dashboard 业务逻辑服务层
- 从 routers/dashboard.py 移入业务逻辑
- 路由层只做参数接收和响应格式化
"""
import datetime
from collections import Counter
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from models import Task, QuizQuestion, ErrorRecord, StudySession, StudyStats, Word, Flashcard, Goal


class DashboardService:
    """仪表盘数据聚合服务"""

    @staticmethod
    def get_countdown(db: Session, exam_date: Optional[datetime.date] = None) -> dict:
        """获取考研倒计时。

        初试日期与届数**一律走 services.exam_calendar**（唯一权威出口），
        绝不在这里写死 12/21 —— 此前这里写死、routers/plan.py 按"12 月倒数第二个周六"
        推导、真库存的是 2027-12-25，三处给出三个答案，用户数的是哪一天都搞不清。

        ``exam_date`` 入参保留为"显式覆盖"（仅当 Goal 未配置时生效），
        供需要按指定日期预览的调用方使用。
        """
        from services import exam_calendar

        goal = db.query(Goal).first()
        info = exam_calendar.resolve_for_db(goal)

        # 显式入参可覆盖（Goal 未配置时）
        if goal is None and exam_date is not None:
            if isinstance(exam_date, datetime.datetime):
                exam_date = exam_date.date()
            days = (exam_date - datetime.date.today()).days
            info = {
                **info,
                "exam_date": exam_date.isoformat(),
                "exam_year": exam_calendar.exam_year_of(exam_date),
                "days_left": days,
                "is_estimated": False,
                "source": "调用方显式指定",
            }

        days_left = info["days_left"]
        return {
            "days": max(0, days_left),
            "exam_date": info["exam_date"],
            "exam_year": info["exam_year"],
            "is_official": info["is_official"],
            "source": info["source"],
            "university": getattr(goal, "university", None),
            "major": getattr(goal, "major", None),
            "total_score_target": getattr(goal, "total_score_target", None),
            "is_passed": days_left < 0,
            # 未配置 Goal 时给出的是推算值，前端必须标成「预估」而不是当成官方日期
            "is_default": info["is_estimated"],
            "signup_hint": info["signup_hint"],
        }

    @staticmethod
    def get_today_tasks(db: Session, limit: int = 20) -> dict:
        """获取今日任务（仅今日到期或进行中的任务）"""
        today = datetime.date.today()

        # 修复：只返回今日到期 + 进行中的任务，不是所有 pending/doing
        tasks = (
            db.query(Task)
            .filter(
                ((Task.due_date == today) & (Task.status.in_(["pending", "doing"])))
                | (Task.status == "doing")
            )
            .order_by(Task.priority.desc(), Task.due_date.asc())
            .all()
        )

        pending = [t for t in tasks if t.status == "pending"]
        doing = [t for t in tasks if t.status == "doing"]
        done = [t for t in tasks if t.status == "done"]

        return {
            "total": len(tasks),
            "pending": len(pending),
            "doing": len(doing),
            "done": len(done),
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "subject": t.subject,
                    "task_type": t.task_type,
                    "stage": t.stage,
                    "status": t.status,
                    "priority": t.priority,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                }
                for t in tasks[:limit]
            ],
        }

    @staticmethod
    def get_stats(db: Session) -> dict:
        """学习统计（使用 SQL 聚合优化，避免 N+1）"""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        # 1. 本周学习总时长（SQL 聚合）
        total_duration = (
            db.query(func.coalesce(func.sum(StudySession.duration), 0))
            .filter(StudySession.date >= week_ago)
            .scalar()
        ) or 0

        # 2. 按科目统计学习时长（SQL GROUP BY）
        subject_rows = (
            db.query(StudySession.subject, func.coalesce(func.sum(StudySession.duration), 0))
            .filter(StudySession.date >= week_ago, StudySession.subject != None)
            .group_by(StudySession.subject)
            .all()
        )
        subject_durations = {sub: dur for sub, dur in subject_rows if sub}

        # 3. 7 天趋势（SQL GROUP BY date）
        daily_rows = (
            db.query(StudySession.date, func.coalesce(func.sum(StudySession.duration), 0))
            .filter(StudySession.date >= week_ago)
            .group_by(StudySession.date)
            .all()
        )
        daily_map = {d.isoformat(): dur for d, dur in daily_rows}
        daily_durations = []
        for i in range(6, -1, -1):
            day = today - datetime.timedelta(days=i)
            day_str = day.isoformat()
            daily_durations.append({
                "date": day_str,
                "duration": daily_map.get(day_str, 0),
            })

        # 4. 今日学习时长
        #    ⚠️ 原实现读 StudyStats 表，但**全项目没有任何地方写这张表** ——
        #    导致 today_duration 永远是 0。改为与 week_duration 一致，
        #    直接从 study_sessions 聚合，不依赖预先物化的统计表。
        today_duration = (
            db.query(func.coalesce(func.sum(StudySession.duration), 0))
            .filter(StudySession.date == today)
            .scalar()
        ) or 0

        # 5. 错题数（唯一口径：services/error_linker.error_stats）
        #    修复：错题相关计数此前在仪表盘、/api/review/stats、错题本页面
        #    各算一套（同一个"今日待复习错题"三个页面三个数）。现统一走
        #    error_stats，与 GET /api/errors/stats 完全同源。
        from services import error_linker

        estats = error_linker.error_stats(db)
        error_count = estats["active_errors"]
        due_errors = estats["due_errors"]

        # 6. 本周任务完成数（SQL 直接过滤）
        weekly_completed = (
            db.query(func.count(Task.id))
            .filter(
                Task.status == "done",
                Task.completed_at != None,
                func.date(Task.completed_at) >= week_ago,
            )
            .scalar()
        ) or 0

        return {
            "today_duration": int(today_duration),
            "week_duration": total_duration,
            "subject_durations": subject_durations,
            "weekly_completed_tasks": weekly_completed,
            "active_errors": error_count,
            "due_errors": due_errors,
            "daily_trend": daily_durations,
        }

    @staticmethod
    def get_weakness(db: Session) -> dict:
        """分析错题数据，生成薄弱项预警"""
        errors = db.query(ErrorRecord).filter(ErrorRecord.status == "active").all()

        if not errors:
            return {
                "has_weakness": False,
                "message": "暂无错题数据，继续保持！",
                "weak_subjects": [],
                "weak_chapters": [],
                "common_reasons": [],
            }

        # 按科目统计错题数
        subject_counter = Counter()
        reason_counter = Counter()
        for e in errors:
            if e.subject:
                subject_counter[e.subject] += 1
            if e.error_reason:
                reason_counter[e.error_reason] += 1

        weak_subjects = [
            {"subject": s, "count": c, "level": "high" if c >= 10 else "medium" if c >= 5 else "low"}
            for s, c in subject_counter.most_common(5)
        ]

        common_reasons = [
            {"reason": r, "count": c}
            for r, c in reason_counter.most_common(5)
        ]

        return {
            "has_weakness": True,
            "total_errors": len(errors),
            "weak_subjects": weak_subjects,
            "common_reasons": common_reasons,
            "suggestion": (
                "建议重点复习薄弱科目，针对常见错误原因进行专项训练。"
                if weak_subjects else "错题分布较均匀，保持全面复习。"
            ),
        }

    @staticmethod
    def get_overview(db: Session) -> dict:
        """获取总览数据"""
        today = datetime.date.today()

        return {
            "total_tasks": db.query(Task).count(),
            "completed_tasks": db.query(Task).filter(Task.status == "done").count(),
            "total_errors": db.query(ErrorRecord).count(),
            "active_errors": db.query(ErrorRecord).filter(ErrorRecord.status == "active").count(),
            "total_words": db.query(Word).count(),
            "mastered_words": db.query(Word).filter(Word.status == "mastered").count(),
            "total_flashcards": db.query(Flashcard).count(),
            "today": today.isoformat(),
        }
