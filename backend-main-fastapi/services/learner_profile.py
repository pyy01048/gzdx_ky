# -*- coding: utf-8 -*-
"""学习画像聚合（T7）。

把分散在各表的学习行为拼成一张「学习者画像」：
  1. 总览：答题量/正确率/学习天数/连续天数/模考均分（exam_sessions）
  2. 科目掌握度：按科目聚合正确率 + 错题存量 + 掌握度分级（强/稳/弱/危）
  3. 薄弱知识点 TOP：error_records + kp 关联（复用 6288 条 kp_links）
  4. 复习节奏：error_records next_review 到期分布（SM-2 队列健康度）
  5. 近 N 天活跃趋势：答题/错题/任务日序列（复用 learning_traces 口径）
  6. 行为洞察建议：规则生成（不调 LLM，确定性），如错题积压/复习逾期提醒

诚实口径：study_sessions 真实时长优先，无记录的天用行为量估算
（沿用 learning_analytics_service 的 30min/任务、5min/题口径）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional


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
    from sqlalchemy import text

    conn = db_session.connection().connection
    today = datetime.now().date()
    start = (today - timedelta(days=days - 1)).isoformat()

    # ---------- 1. 总览 ----------
    ar = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(is_correct),0) FROM answer_records"
    ).fetchone()
    total_answers, total_correct = ar[0], ar[1]
    err_stock = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status IN ('active','submitted')"
    ).fetchone()[0]
    err_resolved = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status = 'resolved'"
    ).fetchone()[0]
    exam_stats = conn.execute(
        "SELECT COUNT(*), COALESCE(AVG(score),0) FROM exam_sessions WHERE status='submitted'"
    ).fetchone()
    # 学习天数：answer_records/error_records/tasks 有行为的去重日
    study_days = conn.execute(
        """
        SELECT COUNT(DISTINCT substr(created_at,1,10)) FROM (
            SELECT created_at FROM answer_records
            UNION ALL SELECT created_at FROM error_records
            UNION ALL SELECT updated_at FROM tasks WHERE status='done'
        ) WHERE substr(created_at,1,10) IS NOT NULL
        """
    ).fetchone()[0]

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
            "SELECT subject, COUNT(*), COALESCE(SUM(is_correct),0)"
            " FROM answer_records WHERE subject IS NOT NULL GROUP BY subject"
        )
    }
    subj_err = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT subject, COUNT(*) FROM error_records"
            " WHERE status IN ('active','submitted') AND subject IS NOT NULL GROUP BY subject"
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
    # 优先用 kp 关联（P0-2 建的 6288 条链）聚合错题；无关联的按 error 表自带 kp 字段兜底
    # DISTINCT 防同题多链翻倍；GROUP BY 名称合并同名知识点（早期 KP 抽取存在重名行）
    weak_kps = conn.execute(
        """
        SELECT kp.name, MIN(kp.subject), COUNT(DISTINCT e.id) AS errs
        FROM error_records e
        JOIN question_knowledge_links l ON l.question_id = e.question_id AND l.role='primary'
        JOIN knowledge_points kp ON kp.id = l.knowledge_point_id
        WHERE e.status IN ('active','submitted')
        GROUP BY kp.name ORDER BY errs DESC LIMIT 10
        """
    ).fetchall()
    if not weak_kps:
        weak_kps = conn.execute(
            """
            SELECT COALESCE(knowledge_point_id, '未标注'), COALESCE(subject,''), COUNT(*)
            FROM error_records WHERE status IN ('active','submitted')
            GROUP BY 1 ORDER BY 3 DESC LIMIT 10
            """
        ).fetchall()
    weak_points = [
        {"knowledge_point": r[0], "subject": r[1], "error_count": r[2]}
        for r in weak_kps
    ]

    # ---------- 4. 复习队列健康度（SM-2） ----------
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    overdue = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status='active' AND next_review IS NOT NULL AND next_review < ?",
        (now_str,),
    ).fetchone()[0]
    due_today = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status='active' AND next_review IS NOT NULL"
        " AND next_review >= ? AND next_review < ?",
        (now_str, (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchone()[0]
    scheduled = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE status='active' AND next_review IS NOT NULL"
    ).fetchone()[0]
    review_queue = {
        "scheduled": scheduled,
        "overdue": overdue,
        "due_today": due_today,
        "no_schedule": conn.execute(
            "SELECT COUNT(*) FROM error_records WHERE status='active'"
            " AND (next_review IS NULL OR next_review='')"
        ).fetchone()[0],
    }

    # ---------- 5. 近 N 天活跃趋势 ----------
    daily = conn.execute(
        f"""
        SELECT substr(created_at,1,10) AS d,
               SUM(CASE WHEN src='ans' THEN 1 ELSE 0 END) AS answers,
               SUM(CASE WHEN src='ans' THEN is_correct ELSE 0 END) AS correct,
               SUM(CASE WHEN src='err' THEN 1 ELSE 0 END) AS errors
        FROM (
            SELECT created_at, is_correct, 'ans' AS src FROM answer_records
            WHERE created_at >= '{start}'
            UNION ALL
            SELECT created_at, 0, 'err' FROM error_records WHERE created_at >= '{start}'
        ) GROUP BY d ORDER BY d
        """
    ).fetchall()
    trend = [
        {"date": r[0], "answers": r[1], "correct": r[2], "errors": r[3]}
        for r in daily
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
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "overview": overview,
        "subjects": subjects,
        "weak_points": weak_points,
        "review_queue": review_queue,
        "trend": trend,
        "suggestions": suggestions,
    }
