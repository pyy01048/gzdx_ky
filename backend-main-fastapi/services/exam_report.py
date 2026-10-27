# -*- coding: utf-8 -*-
"""
A5 模考考后报告（services/exam_report.py）
==========================================
基于 exam_answers 逐题作答 + 题目快照**现算聚合**，不新增表。
由 ``GET /api/exam/sessions/{session_id}/report`` 调用。

报告结构：
  overview            总分/满分/正确率/总用时/题量/题型分布
  section_scores      按题型分组得分/满分/题数/正确率
  knowledge_weakness  按知识点聚合正确率，取最低 Top 5（正确率升序）
  time_analysis       总用时/平均每题用时/最耗时 5 题
  wrong_questions   错题列表（复盘入口）

字段口径与 ``session_detail`` 完全一致（exam_answers 列名）：
  is_correct / time_spent / ai_score / self_score / final_score / scored_by
题目快照（question_snapshot JSON）由 build_paper 冻结，含：
  content / options / answer / analysis / subject / chapter /
  knowledge_point / question_type / answer_type / rubric / max_score
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from services.dbapi_compat import wrap_conn


def _snap(row: Any) -> Dict[str, Any]:
    """解析 exam_answers.question_snapshot（JSON 文本），失败返回空 dict。"""
    try:
        return json.loads(row["question_snapshot"] or "{}")
    except (TypeError, ValueError):
        return {}


def _qtype(snap: Dict[str, Any]) -> str:
    """题目题型（快照的 question_type；缺失时退回 other）。"""
    return snap.get("question_type") or "other"


def _max_score(snap: Dict[str, Any]) -> float:
    try:
        return float(snap.get("max_score") or 0)
    except (TypeError, ValueError):
        return 0.0


def session_report(db, session_id: int) -> Optional[Dict[str, Any]]:
    """生成模考考后报告。

    Returns:
        报告 dict；session 不存在时返回 None。
    """
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = wrap_conn(db.connection().connection)

    sess = conn.execute(
        "SELECT id, subject, paper, status FROM exam_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not sess:
        return None

    rows = conn.execute(
        "SELECT id, question_id, question_snapshot, section, order_no, user_answer,"
        " is_correct, time_spent, ai_score, self_score, final_score, scored_by"
        " FROM exam_answers WHERE session_id = ? ORDER BY order_no",
        (session_id,),
    ).fetchall()
    a_cols = ["id", "question_id", "question_snapshot", "section", "order_no", "user_answer",
              "is_correct", "time_spent", "ai_score", "self_score", "final_score", "scored_by"]
    answers = []
    for r in rows:
        a = dict(zip(a_cols, r))
        a["question_snapshot"] = _snap(a)
        answers.append(a)

    return _build_report(sess, answers)


def _build_report(sess, answers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """由会话行 + 作答列表现算聚合。answers 为空时返回空报告结构。"""
    # ---- overview 基础量 ----
    total_score = 0.0      # 实际得分（final_score 之和）
    max_score = 0.0        # 实际作答满分（快照 max_score 之和）
    total_time = 0         # 总用时（秒）
    correct_count = 0      # 客观题正确数
    objective_count = 0     # 客观题总数（有 is_correct 判分）
    judged_count = 0        # 有判分的题数（is_correct 非 NULL）
    type_dist: Dict[str, int] = defaultdict(int)

    # ---- section_scores 聚合 ----
    sec_acc: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"score": 0.0, "max_score": 0.0, "count": 0, "correct": 0}
    )

    # ---- knowledge 聚合 ----
    kp_acc: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"correct": 0, "judged": 0, "count": 0}
    )

    # ---- time / wrong ----
    time_items: List[Dict[str, Any]] = []
    wrong_questions: List[Dict[str, Any]] = []

    for a in answers:
        snap = a.get("question_snapshot") or {}
        qtype = _qtype(snap)
        max_s = _max_score(snap)
        final = a.get("final_score")
        is_correct = a.get("is_correct")
        time_spent = int(a.get("time_spent") or 0)
        kp = snap.get("knowledge_point") or "未分类"

        max_score += max_s
        total_time += time_spent
        type_dist[qtype] += 1

        # 得分：final_score 非 NULL 才累计
        if final is not None:
            try:
                total_score += float(final)
            except (TypeError, ValueError):
                pass

        # 正确率：is_correct 非 NULL 才算判分
        if is_correct is not None:
            judged_count += 1
            if qtype in ("single", "multiple", "judge", "fill"):
                objective_count += 1
                if int(is_correct) == 1:
                    correct_count += 1

        # section_scores
        sec = sec_acc[qtype]
        sec["count"] += 1
        sec["max_score"] += max_s
        if final is not None:
            try:
                sec["score"] += float(final)
            except (TypeError, ValueError):
                pass
        if is_correct is not None:
            if int(is_correct) == 1:
                sec["correct"] += 1

        # knowledge_weakness
        kacc = kp_acc[kp]
        kacc["count"] += 1
        if is_correct is not None:
            kacc["judged"] += 1
            if int(is_correct) == 1:
                kacc["correct"] += 1

        # time_analysis
        if time_spent > 0:
            time_items.append({
                "order_no": a.get("order_no"),
                "question_id": a.get("question_id"),
                "question_type": qtype,
                "time_spent": time_spent,
            })

        # wrong_questions
        if is_correct is not None and int(is_correct) == 0:
            wrong_questions.append({
                "id": a.get("id"),
                "question_id": a.get("question_id"),
                "order_no": a.get("order_no"),
                "question_type": qtype,
                "content": (snap.get("content") or "")[:100],
                "user_answer": a.get("user_answer") or "",
                "correct_answer": snap.get("answer") or "",
                "final_score": final,
                "max_score": max_s,
            })

    # ---- 组装 ----
    overview = {
        "session_id": sess[0],
        "subject": sess[1],
        "paper": sess[2],
        "status": sess[3],
        "total_score": round(total_score, 2),
        "max_score": round(max_score, 2),
        "accuracy": round(correct_count / objective_count, 4) if objective_count else 0.0,
        "total_time_spent": total_time,
        "question_count": len(answers),
        "judged_count": judged_count,
        "question_type_distribution": dict(type_dist),
    }

    section_scores = []
    for qtype in sorted(sec_acc.keys()):
        s = sec_acc[qtype]
        section_scores.append({
            "question_type": qtype,
            "count": s["count"],
            "score": round(s["score"], 2),
            "max_score": round(s["max_score"], 2),
            "accuracy": round(s["correct"] / s["count"], 4) if s["count"] else 0.0,
        })

    # 知识点正确率：judged=0 视为薄弱（正确率 0），参与排序
    knowledge_weakness = []
    for kp, acc in kp_acc.items():
        rate = acc["correct"] / acc["judged"] if acc["judged"] else 0.0
        knowledge_weakness.append({
            "knowledge_point": kp,
            "correct_rate": round(rate, 4),
            "correct_count": acc["correct"],
            "question_count": acc["count"],
        })
    knowledge_weakness.sort(key=lambda x: (x["correct_rate"], x["correct_count"]))
    knowledge_weakness = knowledge_weakness[:5]

    time_analysis = {
        "total_time_spent": total_time,
        "average_time_per_question": round(total_time / len(answers), 2) if answers else 0.0,
        "top_slowest_questions": sorted(
            time_items, key=lambda x: x["time_spent"], reverse=True
        )[:5],
    }

    return {
        "overview": overview,
        "section_scores": section_scores,
        "knowledge_weakness": knowledge_weakness,
        "time_analysis": time_analysis,
        "wrong_questions": wrong_questions,
    }