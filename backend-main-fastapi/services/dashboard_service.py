"""
Dashboard 业务逻辑服务层
- 从 routers/dashboard.py 移入业务逻辑
- 路由层只做参数接收和响应格式化
- 首屏聚合的唯一出口是 :meth:`DashboardService.get_summary`（01-仪表盘 §2.6），
  所有"哪天学了多少"的数字都从 ``services.study_calendar`` 的同一份日活台账派生
"""
import datetime
import re
from collections import Counter
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    ErrorRecord,
    Flashcard,
    Goal,
    KaoyanSchool,
    KaoyanScoreLine,
    QuizQuestion,
    StudySession,
    StudyStats,
    Task,
    Word,
)
from services import study_calendar
from services import error_linker
from utils.timeutil import (
    KAOYAN_TZ_NAME,
    day_bucket_expr,
    iso_utc_z,
    local_today,
    local_window_for_day,
    utcnow,
)

#: 趋势折线回看天数（D-09 固定 14 天）
TREND_DAYS = 14

#: 首屏薄弱知识点条数（01-仪表盘 §2.1 D-10「知识点 Top3」）。
#: 数字放在这里而不是前端切片，因为「Top」由谁决定必须是后端：
#: 界面 ``slice(0,3)`` 会让我看不到第 4 名其实更薄弱。
WEAK_POINTS_ON_DASHBOARD = 3

#: 从目标专业串里取专业代码：「电子信息（0854）」→「0854」。
#: 分数线表按 major_code 逐专业存储，只有代码能稳定对上名称写法各异的专业。
_MAJOR_CODE_RE = re.compile(r"[（(]\s*(\d{4,6})\s*[）)]")

#: 首屏进度环 / KPI 卡的"今日完成数"取自日活台账的哪个字段。
#: 键 = 对外的 module 名（与前端跳转路由同一套命名），值 = (台账字段, 中文标签, 单位)。
#: ``None`` 表示该模块**当前没有事件源**，必须如实标 not_tracked / not_available，
#: 绝不用 0 冒充"今天没做"——那会把"还没接入"渲染成"用户摆烂"。
_PROGRESS_MODULES = (
    ("focus", "focus_minutes", "专注时长", "分钟"),
    ("word", "words_done", "单词复习", "个"),
    ("new_word", None, "今日新词", "个"),
    ("question", "questions_done", "刷题", "道"),
    ("realexam", "exams_done", "真题模考", "套"),
    ("wrongbook", "errors_done", "错题复习", "道"),
    ("coding", None, "代码上机", "题"),
)

#: 目标值出处：goals 表的四个每日目标列（core/sql/101，全部可空 = 未设目标）
_MODULE_TARGETS = {
    "focus": "daily_focus_minutes",
    "word": "daily_review_words",
    "new_word": "daily_new_words",
    "question": "daily_questions",
}

#: 无事件源模块的说明（前端原样展示，避免用户以为是自己没学）
_MODULE_NOTES = {
    "new_word": "新学/复习要等 FSRS 调度器分流（#12）后才有事件源",
    "coding": "代码上机判题表未建（#16 OJ）",
}

#: 今日任务清单（D-03）的模块表：(module, 到期键, 台账完成字段, 标签, 单位)。
#: ``module`` 与 :data:`_PROGRESS_MODULES` 同一套命名，两个面板说的是同一件事。
#: 到期键 = ``None`` 表示该模块**没有排程源**，如实给 ``due=None`` /
#: ``not_tracked``——写 0 会把"调度器还没接入"渲染成"今天没有待办"。
_DUE_ROLLUP = (
    ("word", "words", "words_done", "单词复习", "个"),
    ("card", "flashcards", "cards_done", "记忆卡片", "张"),
    ("wrongbook", "errors", "errors_done", "错题复习", "道"),
    ("task", "tasks", "tasks_done", "任务待办", "项"),
    ("question", None, "questions_done", "刷题", "道"),
    ("realexam", None, "exams_done", "真题模考", "套"),
)

#: 无排程源模块的说明（前端原样展示）
_DUE_NOTES = {
    "question": "题库没有排程字段，到期量要等知识点调度（#12/#14）接入",
    "realexam": "真题按套卷手动开考，没有到期队列",
}


class DashboardService:
    """仪表盘数据聚合服务"""

    @staticmethod
    def _due_counts(
        db: Session, day: datetime.date, user_id: Optional[int] = None
    ) -> dict:
        """某一北京自然日的**累计到期量**（含此前欠下的复习债），切点为该日 24:00。

        这是到期口径的唯一出处：未来负荷三档（:meth:`_future_load`）和今日任务清单
        （:meth:`_today_task_rollup`）都调它，两边因此不可能给出两个"今日到期"。
        判定规则与 ``services.review_scheduler`` 一致（``next_review`` 非空且 <= 切点，
        错题另加 ``status='active'``），切点走 ``local_window_for_day``——
        不引入第二套日界。B4：传入 ``user_id`` 时只统计该用户的到期量。
        """
        cutoff = local_window_for_day(day)[1]

        def _u(model):
            return () if user_id is None else (model.user_id == user_id,)

        def _sched(model, extra=()):
            return int(
                db.query(func.count(model.id))
                .filter(model.next_review != None, model.next_review <= cutoff, *extra)  # noqa: E711
                .scalar()
                or 0
            )

        out = {
            "flashcards": _sched(Flashcard, _u(Flashcard)),
            "tasks": _sched(Task, _u(Task)),
            "errors": _sched(ErrorRecord, (ErrorRecord.status == "active", *_u(ErrorRecord))),
            # 单词走 due_date（date 列，无时间部分），因此直接和自然日比，不换算成 UTC
            "words": int(
                db.query(func.count(Word.id))
                .filter(Word.due_date != None, Word.due_date <= day, *_u(Word))  # noqa: E711
                .scalar()
                or 0
            ),
        }
        out["total"] = sum(out.values())
        out["cutoff"] = iso_utc_z(cutoff)
        return out

    @staticmethod
    def get_countdown(
        db: Session,
        exam_date: Optional[datetime.date] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """获取考研倒计时。

        初试日期与届数**一律走 services.exam_calendar**（唯一权威出口），
        绝不在这里写死 12/21 —— 此前这里写死、routers/plan.py 按"12 月倒数第二个周六"
        推导、真库存的是 2027-12-25，三处给出三个答案，用户数的是哪一天都搞不清。

        ``exam_date`` 入参保留为"显式覆盖"（仅当 Goal 未配置时生效），
        供需要按指定日期预览的调用方使用。B4：传入 ``user_id`` 时只读本人 Goal。
        """
        from services import exam_calendar

        goal_q = db.query(Goal)
        if user_id is not None:
            goal_q = goal_q.filter(Goal.user_id == user_id)
        goal = goal_q.order_by(Goal.id.asc()).first()
        info = exam_calendar.resolve_for_db(goal)

        # 显式入参可覆盖（Goal 未配置时）
        if goal is None and exam_date is not None:
            if isinstance(exam_date, datetime.datetime):
                exam_date = exam_date.date()
            days = (exam_date - local_today()).days
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
            "days_left": days_left,
            "exam_date": info["exam_date"],
            "exam_year": info["exam_year"],
            # 阶段（base/intensify/warning/sprint/passed）唯一出处：见 exam_calendar.phase_of
            "phase": exam_calendar.phase_of(days_left),
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
    def _today_task_rollup(
        day: study_calendar.DayActivity, due: Optional[dict]
    ) -> list:
        """今日任务清单（D-03）：按模块给出「现在到期多少 / 今天已做多少」。

        刻意**不给 percent**：``due`` 是此刻仍在队列里的到期量（做过即出队），
        ``done`` 是今天已经完成的量，两条独立的事相除只会编出"进度 120%"或
        "还剩 0"这类假答案。``due=None`` 表示该模块没有排程源，状态如实为
        ``not_tracked``，绝不写成 0（那等于告诉用户"你今天没欠东西"）。

        输出字段 ``{module, label, unit, due, done, status, note}``；跳转目标由
        前端按 ``module`` 决定（路由是前端的所有权，不进数据契约）。
        """
        out = []
        for module, due_key, field, label, unit in _DUE_ROLLUP:
            due_n = due.get(due_key) if (due and due_key) else None
            done = getattr(day, field) if field else None
            if due_n is None:
                status = "not_tracked"
            elif due_n == 0:
                status = "clear"
            else:
                status = "pending"
            out.append({
                "module": module,
                "label": label,
                "unit": unit,
                "due": due_n,
                "done": done,
                "status": status,
                "note": _DUE_NOTES.get(module),
            })
        return out

    @staticmethod
    def get_today_tasks(
        db: Session,
        limit: int = 20,
        *,
        day: Optional[study_calendar.DayActivity] = None,
        due: Optional[dict] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """今日任务：Task 行明细 + 按模块的到期汇总（D-03）。

        ``day`` / ``due`` 是"调用方已有这两份数据时别再查一遍"的复用入口
        （``get_summary`` 会传）；单独调用本接口时才就地派生。
        B4：传入 ``user_id`` 时只统计该用户的任务与到期量。
        """
        today = local_today()

        # 只返回今日到期（任意状态）+ 进行中的任务，不是所有 pending/doing。
        # 今日到期必须**连 done 一起取**：清单要显示"完成 3 / 共 7 个"，
        # 把已完成的挑出列表会让进度环永远显示 0%（说了谎的进度条比没有进度条更糟）。
        tq = db.query(Task)
        if user_id is not None:
            tq = tq.filter(Task.user_id == user_id)
        tasks = (
            tq.filter(
                (Task.due_date == today)
                | (Task.status == "doing")
            )
            .order_by(Task.priority.desc(), Task.due_date.asc())
            .all()
        )

        pending = [t for t in tasks if t.status == "pending"]
        doing = [t for t in tasks if t.status == "doing"]
        done = [t for t in tasks if t.status == "done"]

        if day is None:
            day = (
                study_calendar.day_ledger(db, user_id=user_id).get(today.isoformat())
                or study_calendar.DayActivity(date=today)
            )
        if due is None:
            due = DashboardService._due_counts(db, today, user_id=user_id)

        return {
            "total": len(tasks),
            "pending": len(pending),
            "doing": len(doing),
            "done": len(done),
            "modules": DashboardService._today_task_rollup(day, due),
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
    def get_stats(db: Session, user_id: Optional[int] = None) -> dict:
        """学习统计（使用 SQL 聚合优化，避免 N+1）。B4：传入 ``user_id`` 时只看本人。"""
        today = local_today()
        week_ago = today - datetime.timedelta(days=6)

        def _u(model):
            return () if user_id is None else (model.user_id == user_id,)

        # 1. 本周学习总时长（SQL 聚合）
        total_duration = (
            db.query(func.coalesce(func.sum(StudySession.duration), 0))
            .filter(StudySession.date >= week_ago, *_u(StudySession))
            .scalar()
        ) or 0

        # 2. 按科目统计学习时长（SQL GROUP BY）
        subject_rows = (
            db.query(StudySession.subject, func.coalesce(func.sum(StudySession.duration), 0))
            .filter(StudySession.date >= week_ago, StudySession.subject != None, *_u(StudySession))  # noqa: E711
            .group_by(StudySession.subject)
            .all()
        )
        subject_durations = {sub: dur for sub, dur in subject_rows if sub}

        # 3. 7 天趋势（SQL GROUP BY date）
        daily_rows = (
            db.query(StudySession.date, func.coalesce(func.sum(StudySession.duration), 0))
            .filter(StudySession.date >= week_ago, *_u(StudySession))
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
            .filter(StudySession.date == today, *_u(StudySession))
            .scalar()
        ) or 0

        # 5. 错题数（唯一口径：services/error_linker.error_stats）
        #    修复：错题相关计数此前在仪表盘、/api/review/stats、错题本页面
        #    各算一套（同一个"今日待复习错题"三个页面三个数）。现统一走
        #    error_stats，与 GET /api/errors/stats 完全同源。
        estats = error_linker.error_stats(db, user_id=user_id)
        error_count = estats["active_errors"]
        due_errors = estats["due_errors"]

        # 6. 本周任务完成数（SQL 直接过滤）
        weekly_completed = (
            db.query(func.count(Task.id))
            .filter(
                Task.status == "done",
                Task.completed_at != None,
                day_bucket_expr(Task.completed_at, db) >= week_ago,
                *_u(Task),
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
    def get_weakness(db: Session, user_id: Optional[int] = None) -> dict:
        """分析错题数据，生成薄弱项预警。

        性能优化（2026-10）：原实现 ``query(ErrorRecord).filter(...).all()``
        把全部活跃错题的 ORM 实体（含 content / my_answer 等大字段）拉进内存
        再 Counter。改为三条聚合查询（总数 + 科目分布 + 错因分布），
        输出结构与阈值口径完全不变。B4：传入 ``user_id`` 时只看本人错题。
        """
        def _u():
            return () if user_id is None else (ErrorRecord.user_id == user_id,)

        total_errors = (
            db.query(func.count(ErrorRecord.id))
            .filter(ErrorRecord.status == "active", *_u())
            .scalar()
        ) or 0

        if not total_errors:
            return {
                "has_weakness": False,
                "total_errors": 0,
                "message": "暂无错题数据，继续保持！",
                "weak_subjects": [],
                "weak_points": [],
                "common_reasons": [],
                "suggestion": None,
            }

        subject_counter = Counter(
            {
                s: c
                for s, c in db.query(
                    ErrorRecord.subject, func.count(ErrorRecord.id)
                )
                .filter(ErrorRecord.status == "active", *_u())
                .group_by(ErrorRecord.subject)
                .all()
                if s
            }
        )
        reason_counter = Counter(
            {
                r: c
                for r, c in db.query(
                    ErrorRecord.error_reason, func.count(ErrorRecord.id)
                )
                .filter(ErrorRecord.status == "active", *_u())
                .group_by(ErrorRecord.error_reason)
                .all()
                if r
            }
        )

        weak_subjects = [
            {"subject": s, "count": c, "level": "high" if c >= 10 else "medium" if c >= 5 else "low"}
            for s, c in subject_counter.most_common(5)
        ]

        common_reasons = [
            {"reason": r, "count": c}
            for r, c in reason_counter.most_common(5)
        ]

        # 一条错题都没挂上知识点时这里就是空列表：首屏据此显示「知识点还没归集」，
        # 不拿科目名去冒充考点。
        weak_points = error_linker.weak_points_view(db, limit=WEAK_POINTS_ON_DASHBOARD, user_id=user_id)

        return {
            "has_weakness": True,
            "total_errors": total_errors,
            "weak_subjects": weak_subjects,
            "weak_points": weak_points,
            "common_reasons": common_reasons,
            "suggestion": (
                "建议重点复习薄弱科目，针对常见错误原因进行专项训练。"
                if weak_subjects else "错题分布较均匀，保持全面复习。"
            ),
        }

    @staticmethod
    def get_overview(db: Session) -> dict:
        """获取总览数据"""
        today = local_today()

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

    # ------------------------------------------------------------------ #
    # 今日复习队列（唯一出口：路由层不再自己拼一份）
    # ------------------------------------------------------------------ #
    @staticmethod
    def get_review_queue(db: Session, limit: int = 50, user_id: Optional[int] = None) -> dict:
        """今日到期复习队列（卡片 / 任务 / 错题），口径完全沿用 review_scheduler。"""
        from services.review_scheduler import ReviewScheduler

        cards = ReviewScheduler.get_due_flashcards(db, limit, user_id=user_id)
        tasks = ReviewScheduler.get_due_tasks(db, limit, user_id=user_id)
        errors = ReviewScheduler.get_due_errors(db, limit, user_id=user_id)
        return {
            "generated_at": iso_utc_z(utcnow()),
            "source": "review_scheduler",
            "total": len(cards) + len(tasks) + len(errors),
            "limit": limit,
            # 某一类恰好取满 limit 就是"后面还有"，用 max 判断；
            # 用 min 会在"卡片取满、任务只有 2 条"时谎报"没截断"。
            "truncated": max(len(cards), len(tasks), len(errors)) >= limit,
            "cards": [
                {
                    "id": x.id,
                    "kind": "flashcard",
                    "next_review": iso_utc_z(x.next_review),
                }
                for x in cards
            ],
            "tasks": [
                {"id": x.id, "kind": "task", "title": x.title, "subject": x.subject}
                for x in tasks
            ],
            "errors": [
                {"id": x.id, "kind": "error", "subject": x.subject, "question_id": x.question_id}
                for x in errors
            ],
        }

    # ------------------------------------------------------------------ #
    # 首屏聚合（D-01…D-11）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _goal_block(db: Session, goal: Optional[Goal]) -> dict:
        """目标卡（D-02）：目标只描述"要考什么、每天要学多少"，一个字段都不编。

        ``daily_*`` 四列可空，NULL = 未设目标；这里**不回填默认值**，
        前端拿到 null 就渲染"未设目标 + 去设置"，而不是凭空出现 50/20/120。
        """
        targets = {
            "focus_minutes": getattr(goal, "daily_focus_minutes", None),
            "new_words": getattr(goal, "daily_new_words", None),
            "review_words": getattr(goal, "daily_review_words", None),
            "questions": getattr(goal, "daily_questions", None),
        }
        return {
            "configured": bool(goal and goal.exam_date),
            "university": getattr(goal, "university", None) if goal else None,
            "major": getattr(goal, "major", None) if goal else None,
            "subjects": (getattr(goal, "subject_codes", None) or []) if goal else [],
            "support_subjects": (getattr(goal, "support_subject_codes", None) or []) if goal else [],
            "score_targets": {
                "total": getattr(goal, "total_score_target", None) if goal else None,
                "politics": getattr(goal, "politics_target", None) if goal else None,
                "english": getattr(goal, "english_target", None) if goal else None,
                "math": getattr(goal, "math_target", None) if goal else None,
                "major": getattr(goal, "major_target", None) if goal else None,
            },
            "daily_targets": targets,
            "targets_set": any(v is not None for v in targets.values()),
            "recent_score_lines": DashboardService._recent_score_lines(
                db, getattr(goal, "university", None), getattr(goal, "major", None)
            ),
        }

    @staticmethod
    def _recent_score_lines(
        db: Session, university: Optional[str], major: Optional[str] = None, limit: int = 3
    ) -> list:
        """目标院校近年复试线：一年一根柱。查不到就返回空数组，不编数字。

        同一院校同一年会命中多个专业/方向的分数线，直接按年份排序取行会让
        ``limit`` 全部落在同一年（图表出现三根相同年份的柱子）。这里先按目标
        专业过滤且每年取最低线；对不上专业时退回全校最低线，并用 ``scope``
        标明口径，前端据此决定怎么标注，而不是把"全校最低"冒充成"你的专业线"。
        """
        if not university:
            return []
        school = (
            db.query(KaoyanSchool)
            .filter(KaoyanSchool.name == university)
            .first()
        )
        if not school:
            return []

        def per_year(*conditions):
            return (
                db.query(
                    KaoyanScoreLine.year,
                    func.min(KaoyanScoreLine.total_line).label("total_line"),
                )
                .filter(
                    KaoyanScoreLine.school_id == school.id,
                    KaoyanScoreLine.total_line != None,  # noqa: E711
                    *conditions,
                )
                .group_by(KaoyanScoreLine.year)
                .order_by(KaoyanScoreLine.year.desc())
                .limit(limit)
                .all()
            )

        scope = "school"
        rows = []
        major_text = (major or "").strip()
        if major_text:
            code = _MAJOR_CODE_RE.search(major_text)
            if code:
                rows = per_year(KaoyanScoreLine.major_code.like(f"{code.group(1)}%"))
            else:
                rows = per_year(KaoyanScoreLine.major_name.like(f"%{major_text}%"))
            if rows:
                scope = "major"
        if not rows:
            rows = per_year()
        return [
            {"year": int(y), "total_line": int(tl), "scope": scope}
            for y, tl in reversed(rows)
        ]

    @staticmethod
    def _module_progress(goal: Optional[Goal], day: study_calendar.DayActivity) -> list:
        """4~7 个模块进度环（D-06）。

        - ``percent`` 在**未设目标时为 None**（不是 0）：0% 意味着"今天一点没学"，
          null 才是"你还没定目标"，两者对用户是两件事。
        - ``status`` 是前端渲染分支的唯一依据：
          ok / no_target（有完成数但没目标）/ not_tracked / not_available。
        """
        out = []
        for module, field, label, unit in _PROGRESS_MODULES:
            target_attr = _MODULE_TARGETS.get(module)
            target = getattr(goal, target_attr, None) if (goal and target_attr) else None
            done = getattr(day, field) if field else None
            if done is None:
                # 没有事件源：既不是 0% 也不是"没学"，note 说明缺的是哪一块
                status = "not_tracked"
            elif target:
                status = "reached" if done >= target else "ok"
            else:
                status = "no_target"
            out.append({
                "module": module,
                "label": label,
                "unit": unit,
                "done": done,
                "target": target,
                "percent": round(100.0 * done / target) if (target and done is not None) else None,
                "status": status,
                "note": _MODULE_NOTES.get(module),
            })
        return out

    @staticmethod
    def _future_load(
        db: Session,
        today: Optional[datetime.date] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """未来负荷（D-11，Anki Future Due 口径）：**累计**到期量，含今天之前欠下的。

        到期口径的唯一实现是 :meth:`_due_counts`，这里只负责把切点推成三档。
        """
        today = today or local_today()
        cuts = {
            # 「今日到期」= 到今天 24:00 为止（含此前欠下的复习债），与后两档同一条规则，
            # 三档因此可直接比大小；"现在立刻能做多少"看 review_queue，不在这张卡里。
            "due_today": today,
            "due_tomorrow": today + datetime.timedelta(days=1),
            "due_this_week": today + datetime.timedelta(days=6),
        }
        out = {key: DashboardService._due_counts(db, day, user_id=user_id) for key, day in cuts.items()}
        out["rule"] = "累计到期量（含此前未清的复习债），切点为对应北京自然日 24:00"
        return out

    @staticmethod
    def get_summary(db: Session, user_id: Optional[int] = None) -> dict:
        """仪表盘首屏**唯一**聚合出口（01-仪表盘 §2.6）。

        契约（snake_case，与 #19 接口规范一致；标准文档里的 camelCase 骨架只做语义参考）：
        ``generated_at / timezone / countdown / goal / kpi / module_progress /
        today_tasks / review_queue / heatmap / trend / weakness / future_load /
        data_coverage``。

        一次 ``day_ledger`` 构建（6 条 ``GROUP BY 本地日`` 聚合）供 streak、热力图、
        趋势、KPI 四处共用 —— 这是"同一应用三个 streak 答案"问题的根治点。
        全量历史聚合在天级粒度上做，行数等于有学习痕迹的天数，成本与历史长度无关。
        B4：传入 ``user_id`` 时，目标、行为流水、待办、复习队列全部只看该用户。
        """
        today = local_today()
        goal_q = db.query(Goal)
        if user_id is not None:
            goal_q = goal_q.filter(Goal.user_id == user_id)
        goal = goal_q.order_by(Goal.id.asc()).first()
        stats = DashboardService.get_stats(db, user_id=user_id)

        ledger = study_calendar.day_ledger(db, user_id=user_id)
        streak = study_calendar.streak_summary(ledger, today=today)
        yesterday = today - datetime.timedelta(days=1)
        t = ledger.get(today.isoformat()) or study_calendar.DayActivity(date=today)
        y = ledger.get(yesterday.isoformat()) or study_calendar.DayActivity(date=yesterday)

        def _kpi(d: study_calendar.DayActivity) -> dict:
            return {
                "date": d.date.isoformat(),
                "focus_minutes": d.focus_minutes,
                "words_done": d.words_done,
                "questions_done": d.questions_done,
                "correct_rate": d.correct_rate,
                "tasks_done": d.tasks_done,
                "exams_done": d.exams_done,
                "errors_done": d.errors_done,
                "effective": d.is_effective,
            }

        diff_keys = ("focus_minutes", "words_done", "questions_done", "tasks_done", "errors_done")
        delta = {k: getattr(t, k) - getattr(y, k) for k in diff_keys}
        delta["correct_rate_pp"] = (
            round(t.correct_rate - y.correct_rate, 1)
            if (t.correct_rate is not None and y.correct_rate is not None)
            else None
        )

        trend_series = study_calendar.fill_series(
            ledger, today - datetime.timedelta(days=TREND_DAYS - 1), today
        )
        # 先算未来负荷：它的 due_today 就是今日任务清单的到期口径，一次查询两处用
        future_load = DashboardService._future_load(db, today, user_id=user_id)

        return {
            "generated_at": iso_utc_z(utcnow()),
            "timezone": KAOYAN_TZ_NAME,
            "countdown": DashboardService.get_countdown(db, user_id=user_id),
            "goal": DashboardService._goal_block(db, goal),
            "kpi": {
                "today": _kpi(t),
                "yesterday": _kpi(y),
                "delta": delta,
                "streak": streak,
            },
            "module_progress": DashboardService._module_progress(goal, t),
            "today_tasks": DashboardService.get_today_tasks(
                db, day=t, due=future_load["due_today"], user_id=user_id
            ),
            "review_queue": DashboardService.get_review_queue(db, user_id=user_id),
            "heatmap": {
                "weeks": study_calendar.HEATMAP_WEEKS,
                "value_field": "focus_minutes",
                "levels": [0, 30, 90, 180],
                "days": study_calendar.effective_activity_days(ledger, today=today),
            },
            "trend": {
                "days": TREND_DAYS,
                "series": [d.to_dict() for d in trend_series],
                "week_focus_minutes": stats["week_duration"],
                "subject_durations": stats["subject_durations"],
                "weekly_completed_tasks": stats["weekly_completed_tasks"],
            },
            "weakness": DashboardService.get_weakness(db, user_id=user_id),
            "future_load": future_load,
            "errors": {
                "active": stats["active_errors"],
                "due": stats["due_errors"],
                "source": "services.error_linker.error_stats",
            },
            "data_coverage": {
                "days_with_activity": len(ledger),
                "first_day": streak["first_day"],
                "today_effective": t.is_effective,
                "is_empty": not ledger,
                "empty_hint": (
                    "还没有学习记录，先去完成一次专注或复习 10 个词，今天的第一格就亮了。"
                    if not ledger else None
                ),
            },
        }
