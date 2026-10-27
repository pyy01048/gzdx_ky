# -*- coding: utf-8 -*-
"""学习画像聚合（T7）。

把分散在各表的学习行为拼成一张「学习者画像」：
  1. 总览：答题量/正确率/学习天数/连续天数/模考均分（exam_sessions）
  2. 科目掌握度：按科目聚合正确率 + 错题存量 + 掌握度分级（强/稳/弱/危）
  3. 薄弱知识点 TOP：error_records + kp 关联（复用 6288 条 kp_links）
  4. 复习节奏：error_records next_review 到期分布（SM-2 队列健康度）
  5. 近 N 天活跃趋势：答题/错题/任务日序列（复用 learning_traces 口径）
  6. 行为洞察建议：规则生成（不调 LLM，确定性），如错题积压/复习逾期提醒
  7. 知识点掌握度三态：未学/薄弱/已掌握（口径见 services/kp_mastery.py）

诚实口径：study_sessions 真实时长优先，无记录的天用行为量估算
（沿用 learning_analytics_service 的 30min/任务、5min/题口径）。
"""
from __future__ import annotations

from datetime import timedelta
from utils.timeutil import (  # P1-C2
    day_bucket_expr,
    iso_utc_z,
    local_range_utc,
    local_today,
    utcnow,
)
from typing import Dict, List, Optional

from services import error_linker, kp_mastery
from services.dbapi_compat import wrap_conn


#: 画像页「薄弱知识点 TOP」名额。评分与排序不在这里，见
#: services/error_linker.weak_knowledge_points（仪表盘 D-10 用同一出口的 Top3）。
WEAK_POINTS_ON_PROFILE = 10


def _pct(ok: int, total: int) -> Optional[float]:
    return round(ok / total * 100, 1) if total else None


def _mastery_level(acc: Optional[float], error_stock: int) -> str:
    """科目掌握度分级（规则确定性）。

    危：正确率<50% 或错题积压>20；弱：<65%；稳：<80%；强：≥80%。
    无答题记录但有错题积压 → 危（只错没对过）。
    """
    if acc is None:
        return "危" if error_stock >= 10 else "未开始"
    if acc < 50 or error_stock > 20:
        return "危"
    if acc < 65:
        return "弱"
    if acc < 80:
        return "稳"
    return "强"


def build_profile(db_session, days: int = 30) -> Dict:
    """聚合学习者画像。"""

    conn = wrap_conn(db_session.connection().connection)
    today = local_today()
    # 区间起点必须是北京日的 UTC 瞬时，不能是本地零点字符串
    start_dt, _end_dt = local_range_utc(
        today - timedelta(days=days - 1), today + timedelta(days=1)
    )

    # ---------- 1. 总览 ----------
    ar = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(CAST(is_correct AS INTEGER)),0) FROM answer_records"
    ).fetchone()
    total_answers, total_correct = ar[0], ar[1]
    # error_records 的状态词表只有 active / graduated（models.py:292 注释 +
    # routers/errors.py:261 唯一非默认写点）。此前写的 'submitted' 属于
    # exam_sessions（core/sql/041_papers_exams.sql:113 CHECK 约束），
    # 'resolved' 从来没有一处写入点 —— 于是「错题已解决」恒为 0，
    # 用户把错题全部毕业移出后那个数字还是 0。
    err_stock = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status = 'active'"
    ).fetchone()[0]
    err_resolved = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status = 'graduated'"
    ).fetchone()[0]
    exam_stats = conn.execute(
        "SELECT COUNT(*), COALESCE(AVG(score),0) FROM exam_sessions WHERE status='submitted'"
    ).fetchone()
    # 学习天数：answer_records/error_records/tasks 有行为的去重**北京自然日**。
    # 旧写法 substring(CAST(ts AS text),1,10) 切的是 UTC 日（PG 会话时区钉在 UTC），
    # 北京 00:00~08:00 的学习因此记在前一天；分桶的唯一出口是 day_bucket_expr。
    from sqlalchemy import func as sa_func, select as sa_select, union_all

    from models import AnswerRecord, ErrorRecord, Task

    active_days_q = union_all(
        sa_select(day_bucket_expr(AnswerRecord.created_at, db_session).label("d")),
        sa_select(day_bucket_expr(ErrorRecord.created_at, db_session).label("d")),
        sa_select(day_bucket_expr(Task.updated_at, db_session).label("d")).where(
            Task.status == "done"
        ),
    ).subquery()
    study_days = db_session.execute(
        sa_select(sa_func.count(sa_func.distinct(active_days_q.c.d))).select_from(active_days_q)
    ).scalar() or 0

    overview = {
        "total_answers": total_answers,
        "overall_accuracy": _pct(total_correct, total_answers),
        "error_stock": err_stock,
        "error_resolved": err_resolved,
        "exam_count": exam_stats[0],
        "exam_avg_score": round(exam_stats[1], 1) if exam_stats[0] else None,
        "study_days": study_days,
        "days_window": days,
    }

    # ---------- 2. 科目掌握度 ----------
    # 正确率来自 answer_records；错题存量来自 error_records；模考均分来自 sessions
    subj_acc = {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "SELECT subject, COUNT(*), COALESCE(SUM(CAST(is_correct AS INTEGER)),0)"
            " FROM answer_records WHERE subject IS NOT NULL GROUP BY subject"
        )
    }
    subj_err = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT subject, COUNT(*) FROM error_records"
            " WHERE status = 'active' AND subject IS NOT NULL GROUP BY subject"
        )
    }
    subj_exam = {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "SELECT subject, COUNT(*), COALESCE(AVG(score),0) FROM exam_sessions"
            " WHERE status='submitted' AND subject IS NOT NULL GROUP BY subject"
        )
    }
    all_subjects = set(subj_acc) | set(subj_err) | set(subj_exam)
    subjects = []
    for s in sorted(all_subjects):
        n, ok = subj_acc.get(s, (0, 0))
        stock = subj_err.get(s, 0)
        acc = _pct(ok, n)
        ec, es = subj_exam.get(s, (0, 0))
        subjects.append({
            "subject": s,
            "answered": n,
            "accuracy": acc,
            "error_stock": stock,
            "exam_count": ec,
            "exam_avg": round(es, 1) if ec else None,
            "mastery": _mastery_level(acc, stock),
        })
    subjects.sort(key=lambda x: ({"危": 0, "弱": 1, "稳": 2, "强": 3, "未开始": 4}.get(x["mastery"], 9), -(x["error_stock"])))

    # ---------- 3. 薄弱知识点 TOP ----------
    # 评分与截断的唯一出口是 services/error_linker.weak_knowledge_points：
    # 仪表盘 D-10（Top3）、/api/review/weak-points、这里（Top10）共用同一打分
    # 「错题数×2 + 考频 − 掌握度/20」。这里此前另有一套 SQL——按
    # question_knowledge_links 数错题、只按 errs DESC 排，于是同一个人在两个
    # 页面能看到两份不同的「薄弱 TOP」，谁也不认错。
    # 一条错题都没挂上知识点时返回空列表，界面显示「还没归集」；
    # 不再退回 error_records.knowledge_point_id 分组——那会把「未标注」当成
    # 一个考点名显示，是凭空造出来的标签。
    weak_points = error_linker.weak_points_view(db_session, limit=WEAK_POINTS_ON_PROFILE)

    # ---------- 3.5 知识点掌握度三态 ----------
    # 口径见 services/kp_mastery.py：未学（无任何学习记录）= 灰，不计入薄弱；
    # 上面 weak_points 来自 error_records，必然有记录，全部按薄弱处理。
    learned_ids = kp_mastery.learned_kp_ids_raw(conn)
    kp_state_counts = {"total": 0, "unlearned": 0, "learning": 0, "weak": 0, "mastered": 0}
    for kp_id, kp_mastery_val in conn.execute(
        "SELECT id, mastery FROM knowledge_points"
    ).fetchall():
        kp_state_counts["total"] += 1
        kp_state_counts[
            kp_mastery.classify_state(kp_mastery_val, kp_id in learned_ids)
        ] += 1
    knowledge_points = {
        **kp_state_counts,
        "labels": kp_mastery.STATE_LABELS,
    }

    # ---------- 4. 复习队列健康度（SM-2） ----------
    now_str = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    overdue = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status='active' AND next_review IS NOT NULL AND next_review < ?",
        (now_str,),
    ).fetchone()[0]
    due_today = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status='active' AND next_review IS NOT NULL"
        " AND next_review >= ? AND next_review < ?",
        (now_str, (utcnow() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchone()[0]
    scheduled = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status='active' AND next_review IS NOT NULL"
    ).fetchone()[0]
    review_queue = {
        "scheduled": scheduled,
        "overdue": overdue,
        "due_today": due_today,
        # 只判 IS NULL：next_review 在 PG 下是 timestamptz，空字符串不是合法值，
        # `next_review=''` 会报 invalid input syntax for type timestamp（实测踩坑）。
        # SQLite 时代用空串表示"未排程"，迁移时若残留空串已在数据清洗阶段转为 NULL。
        "no_schedule": conn.execute(
            "SELECT COUNT(*) FROM error_records WHERE status='active'"
            " AND next_review IS NULL"
        ).fetchone()[0],
    }

    # ---------- 5. 近 N 天活跃趋势 ----------
    # 同样按北京自然日分桶（day_bucket_expr 是唯一出口），并且用绑定参数而不是
    # 把日期拼进 SQL 字符串。
    from sqlalchemy import case, literal

    trend_src = union_all(
        sa_select(
            day_bucket_expr(AnswerRecord.created_at, db_session).label("d"),
            literal(1).label("a"),
            case((AnswerRecord.is_correct.is_(True), 1), else_=0).label("c"),
            literal(0).label("e"),
        ).where(AnswerRecord.created_at >= start_dt),
        sa_select(
            day_bucket_expr(ErrorRecord.created_at, db_session).label("d"),
            literal(0).label("a"),
            literal(0).label("c"),
            literal(1).label("e"),
        ).where(ErrorRecord.created_at >= start_dt),
    ).subquery()
    daily = db_session.execute(
        sa_select(
            trend_src.c.d,
            sa_func.sum(trend_src.c.a),
            sa_func.sum(trend_src.c.c),
            sa_func.sum(trend_src.c.e),
        ).select_from(trend_src).group_by(trend_src.c.d).order_by(trend_src.c.d)
    ).fetchall()
    trend = [
        {
            # PG 给 date 对象、SQLite 给字符串，出口统一成 ISO 日
            "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
            "answers": int(a or 0),
            "correct": int(c or 0),
            "errors": int(e or 0),
        }
        for d, a, c, e in daily
    ]

    # ---------- 6. 行为洞察（规则，不调 LLM） ----------
    suggestions: List[str] = []
    if review_queue["overdue"] > 5:
        suggestions.append(f"复习队列已逾期 {review_queue['overdue']} 条，先清逾期错题再刷新题（SM-2 间隔会被打乱）")
    elif review_queue["due_today"] > 0:
        suggestions.append(f"今日有 {review_queue['due_today']} 条错题到期待复习")
    danger = [s for s in subjects if s["mastery"] == "危"]
    if danger:
        suggestions.append(f"『{danger[0]['subject']}』处于危险区（正确率 {danger[0]['accuracy'] if danger[0]['accuracy'] is not None else '无'}%，错题积压 {danger[0]['error_stock']}），建议今天专项突破")
    if total_answers > 0 and err_stock > total_answers * 0.3:
        suggestions.append("错题增速偏高：答 3 题错 1 题以上，考虑降难度或先复习再刷")
    if overview["exam_avg_score"] is not None and overview["exam_avg_score"] < 60:
        suggestions.append(f"模考均分 {overview['exam_avg_score']}（满分90的834卷），限时训练不足，建议每周一次全真模考")
    if not suggestions:
        suggestions.append("节奏健康：保持当前学习频率，优先清空到期复习")

    return {
        "generated_at": iso_utc_z(utcnow()),
        "overview": overview,
        "subjects": subjects,
        "weak_points": weak_points,
        "knowledge_points": knowledge_points,
        "review_queue": review_queue,
        "trend": trend,
        "suggestions": suggestions,
    }
