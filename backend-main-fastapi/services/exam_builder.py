# -*- coding: utf-8 -*-
"""
A5 组卷-模考引擎（services/exam_builder.py）
=============================================
蓝图组卷 → 模考会话（试卷冻结）→ 交卷判分 → 错题回流 + 盲区池联动。

复用：services/paper_builder.py 保留原样，本模块独立实现 exam 体系。
数据表：exam_blueprints / exam_sessions / exam_answers（module_a_schema 已建）。

组卷：
  build_paper(subject, paper, *, year, mode=normal|weakest|random,
              kp_ids, question_source=all|error, exclude_recent_days)
  跨章节均匀采样（按 chapter 分组轮转）；weakest 按错题/盲区薄弱点排序取题。
试卷冻结：exam_sessions.config 存抽中题号 JSON；exam_answers.question_snapshot 存题目快照。
判分：客观题自动判分（scored_by=auto）；主观题按 rubric/max_score 走 AI 建议分+自评
      （scored_by=ai|self），统计只认 auto+self。
错题回流：交卷后错误题写入 error_records（去重），并联动 A4 盲区池记录弱知识点。
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from services.db_retry import exec_retry


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# 蓝图
# --------------------------------------------------------------------------- #
def load_blueprints(db, subject: str, paper: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
    from services.module_a_schema import ensure_module_a_schema, ensure_blueprints

    ensure_module_a_schema(db)
    ensure_blueprints(db)
    conn = db.connection().connection
    rows = conn.execute(
        "SELECT id, subject, paper, year, section, question_type, count, score_per_question,"
        " time_limit_minutes, sort_order, kp_filters FROM exam_blueprints"
        " WHERE subject = ? AND paper = ? AND is_active = 1 ORDER BY sort_order",
        (subject, paper),
    ).fetchall()
    cols = ["id", "subject", "paper", "year", "section", "question_type", "count",
            "score_per_question", "time_limit_minutes", "sort_order", "kp_filters"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        if year is not None and d["year"] is not None and d["year"] != year:
            continue
        try:
            d["kp_filters"] = json.loads(d["kp_filters"]) if d["kp_filters"] else None
        except Exception:
            d["kp_filters"] = None
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# 候选题目
# --------------------------------------------------------------------------- #
def _question_base_sql(extra_where: str = "", params: Optional[List[Any]] = None) -> tuple[str, List[Any]]:
    sql = (
        "SELECT id, content, options, answer, analysis, subject, chapter, knowledge_point,"
        " difficulty, question_type, answer_type, is_available, year, paper, external_id,"
        " rubric, max_score"
        " FROM quiz_questions WHERE 1=1"
    )
    return sql + extra_where, list(params or [])


def _query_candidates(
    db,
    bp: Dict[str, Any],
    *,
    kp_ids: Optional[List[int]] = None,
    question_source: str = "all",
    exclude_question_ids: Optional[List[int]] = None,
    subject: str,
    paper: str,
) -> List[Dict[str, Any]]:
    conn = db.connection().connection
    where = " AND is_available = 1"
    params: List[Any] = []

    # 题型映射
    qt_map = {
        "single": "single",
        "multi_choice": "multi",
        "blank": "blank",
        "solve": "solve",
        "comprehensive": "comprehensive",
        "choice": "single",
    }
    qt = qt_map.get(bp["question_type"], bp["question_type"])
    if qt in ("single", "multi", "blank", "solve", "comprehensive"):
        where += " AND question_type = ?"
        params.append(qt)

    # 知识点筛选（kp_ids 经 question_knowledge_links 精确关联）
    if kp_ids:
        placeholders = ",".join("?" * len(kp_ids))
        where += (
            " AND id IN (SELECT question_id FROM question_knowledge_links"
            f" WHERE knowledge_point_id IN ({placeholders}))"
        )
        params.extend(kp_ids)
    elif bp.get("kp_filters"):
        filters = bp["kp_filters"]
        if isinstance(filters, dict) and filters.get("chapters"):
            chs = filters["chapters"]
            placeholders = ",".join("?" * len(chs))
            where += f" AND chapter IN ({placeholders})"
            params.extend(chs)

    # 题库来源
    if question_source == "error":
        where += " AND id IN (SELECT DISTINCT question_id FROM error_records WHERE question_id IS NOT NULL)"
    elif question_source == "ai_generated":
        where += " AND ai_generated = 1"

    # 排除近期考过题
    if exclude_question_ids:
        placeholders = ",".join("?" * len(exclude_question_ids))
        where += f" AND id NOT IN ({placeholders})"
        params.extend(exclude_question_ids)

    sql, params = _question_base_sql(where, params)
    rows = conn.execute(sql, params).fetchall()
    cols = ["id", "content", "options", "answer", "analysis", "subject", "chapter",
            "knowledge_point", "difficulty", "question_type", "answer_type", "is_available",
            "year", "paper", "external_id", "rubric", "max_score"]
    return [dict(zip(cols, r)) for r in rows]


def recent_question_ids(db, exclude_recent_days: int = 14) -> List[int]:
    """近 N 天考过的题（来自 exam_answers）。"""
    conn = db.connection().connection
    cutoff = (datetime.now() - timedelta(days=exclude_recent_days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT DISTINCT question_id FROM exam_answers ea"
        " JOIN exam_sessions es ON es.id = ea.session_id"
        " WHERE es.created_at >= ?",
        (cutoff,),
    ).fetchall()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- #
# 均匀采样
# --------------------------------------------------------------------------- #
def uniform_sample_by_chapter(candidates: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """按 chapter 分组 → 组内随机 → 按组轮转取题直到满 n（pigking0606 算法）。"""
    if n <= 0:
        return []
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for q in candidates:
        groups[q.get("chapter") or "未分章"].append(q)
    for g in groups.values():
        random.shuffle(g)
    picked: List[Dict[str, Any]] = []
    chapters = list(groups.keys())
    rounds = 0
    max_rounds = max((len(v) for v in groups.values()), default=0)
    while len(picked) < n and rounds < max_rounds:
        for ch in chapters:
            if groups[ch] and len(picked) < n:
                picked.append(groups[ch].pop(0))
        rounds += 1
    return picked[:n]


def mastery_score(q: Dict[str, Any], conn) -> float:
    """weakest 模式排序：错题/mastery 低/盲区薄弱 → 排前（分数低 = 更弱）。"""
    score = 50.0
    err = conn.execute(
        "SELECT mastery_level, repetitions, lapses FROM error_records"
        " WHERE question_id = ? AND status IN ('active','submitted') ORDER BY id DESC LIMIT 1",
        (q["id"],),
    ).fetchone()
    if err:
        level = err[0] or "not_mastered"
        if level == "not_mastered":
            score -= 30
        elif level == "partially_mastered":
            score -= 15
        score += (err[2] or 0) * 2 - (err[1] or 0)
    return max(0.0, min(100.0, score))


def _weakest_pick(candidates: List[Dict[str, Any]], n: int, conn) -> List[Dict[str, Any]]:
    """按薄弱度排序取题（错题/盲区薄弱点优先）。"""
    if n <= 0:
        return []
    ranked = sorted(candidates, key=lambda q: (mastery_score(q, conn), random.random()))
    return ranked[:n]


# --------------------------------------------------------------------------- #
# 组卷入口
# --------------------------------------------------------------------------- #
def build_paper(
    db,
    subject: str,
    paper: str,
    *,
    year: Optional[int] = None,
    mode: str = "normal",
    count_override: Optional[int] = None,
    kp_ids: Optional[List[int]] = None,
    question_source: str = "all",
    exclude_recent_days: int = 14,
) -> Dict[str, Any]:
    """组卷 → 建 exam_sessions 会话（试卷冻结）。

    Returns:
        {"session_id", "blueprint_key", "subject", "paper", "mode", "total_count",
         "total_score", "sections": [...], "status": "ongoing", "expires_at"}
    """
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)

    if mode not in ("normal", "weakest", "random"):
        mode = "normal"
    if question_source not in ("all", "error", "ai_generated"):
        question_source = "all"

    blueprints = load_blueprints(db, subject, paper, year)
    if not blueprints:
        return {"error": f"no blueprint for {subject}/{paper}"}
    # load_blueprints 内部会 commit（ensure schema/blueprints），须在其后获取底层连接
    conn = db.connection().connection

    exclude_ids = recent_question_ids(db, exclude_recent_days)
    sections: List[Dict[str, Any]] = []
    picked_question_ids: List[int] = []
    total_score = 0.0
    total_count = 0

    for bp in blueprints:
        n = count_override or bp["count"]
        if n <= 0:
            continue
        candidates = _query_candidates(
            db, bp, kp_ids=kp_ids, question_source=question_source,
            exclude_question_ids=exclude_ids, subject=subject, paper=paper,
        )
        if mode == "weakest":
            picked = _weakest_pick(candidates, n, conn)
        elif mode == "random":
            picked = random.sample(candidates, min(n, len(candidates)))
        else:
            picked = uniform_sample_by_chapter(candidates, n)

        sec = {
            "section": bp["section"],
            "question_type": bp["question_type"],
            "score_per_question": bp["score_per_question"],
            "questions": [
                {
                    "question_id": q["id"],
                    "order_no": idx + 1,
                    "content": q["content"],
                    "options": q["options"],
                    "answer": q["answer"],
                    "analysis": q["analysis"],
                    "subject": q["subject"],
                    "chapter": q["chapter"],
                    "knowledge_point": q["knowledge_point"],
                    "question_type": q["question_type"],
                    "answer_type": q.get("answer_type") or "objective",
                    "year": q.get("year"),
                    "external_id": q.get("external_id"),
                    "rubric": q.get("rubric"),
                    "max_score": q.get("max_score"),
                }
                for idx, q in enumerate(picked)
            ],
        }
        sections.append(sec)
        picked_question_ids.extend(q["question_id"] for q in sec["questions"])
        total_score += len(sec["questions"]) * bp["score_per_question"]
        total_count += len(sec["questions"])

    if total_count == 0:
        return {"error": "no questions matched the blueprint; try relaxing filters"}

    config = {
        "blueprint_key": f"{paper}:{year or 'general'}",
        "mode": mode,
        "question_source": question_source,
        "sections": sections,
        "picked_question_ids": picked_question_ids,
        "built_at": _now_str(),
    }
    blueprint_key = f"{paper}:{year or 'general'}"
    time_limit = blueprints[0].get("time_limit_minutes") or 180
    expires_at = (datetime.now() + timedelta(minutes=time_limit)).strftime("%Y-%m-%d %H:%M:%S")

    cur = conn.execute(
        """
        INSERT INTO exam_sessions
        (blueprint_key, subject, paper, mode, question_source, config, total_count,
         total_score, time_limit_minutes, expires_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ongoing')
        """,
        (blueprint_key, subject, paper, mode, question_source, json.dumps(config, ensure_ascii=False),
         total_count, total_score, time_limit, expires_at),
    )
    session_id = int(cur.lastrowid)

    # 试卷冻结：题目快照写 exam_answers（ongoing，无作答）
    order_no = 0
    for sec in sections:
        for q in sec["questions"]:
            order_no += 1
            conn.execute(
                """
                INSERT INTO exam_answers
                (session_id, question_id, question_snapshot, section, order_no, scored_by)
                VALUES (?, ?, ?, ?, ?, 'auto')
                """,
                (session_id, q["question_id"], json.dumps(q, ensure_ascii=False),
                 sec["section"], order_no),
            )
    db.commit()

    return {
        "session_id": session_id,
        "blueprint_key": blueprint_key,
        "subject": subject,
        "paper": paper,
        "mode": mode,
        "total_count": total_count,
        "total_score": total_score,
        "sections": sections,
        "status": "ongoing",
        "expires_at": expires_at,
        "time_limit_minutes": time_limit,
    }


# --------------------------------------------------------------------------- #
# 判分
# --------------------------------------------------------------------------- #
def _norm(s: Any) -> str:
    if s is None:
        return ""
    return "".join(str(s).split()).strip().lower()


def _grade_objective(user_answer: Any, correct_answer: Any) -> bool:
    return _norm(user_answer) == _norm(correct_answer)


def _trusted_answer(conn, question_id: int, snap_answer: str) -> tuple:
    """T6-1：判分答案可信度分层。

    返回 (判分用答案, 可信度标签)：
    - ai_generated 且未 verified 的题库答案 → 优先取 answer_candidates 里
      used_for_grading=1 的高置信候选（A6 交叉校验过的）；无候选则判分
      照用快照答案但标 ai_unverified——结果里透传，前端可提示"答案为 AI 生成"。
    - 普通答案（人工/原卷）→ trusted。
    """
    try:
        row = conn.execute(
            "SELECT ai_generated, verified FROM quiz_questions WHERE id = ?", (question_id,)
        ).fetchone()
        if not row or not row[0] or row[1]:
            return snap_answer, "trusted"
        # AI 生成未核验：找交叉校验高置信候选
        cand = conn.execute(
            "SELECT answer FROM answer_candidates"
            " WHERE question_id = ? AND used_for_grading = 1 AND confidence >= 0.7"
            " ORDER BY confidence DESC LIMIT 1",
            (question_id,),
        ).fetchone()
        if cand and (cand[0] or "").strip():
            return cand[0], "cross_checked"
        return snap_answer, "ai_unverified"
    except Exception:
        # answer_candidates 表可能未建（module_a_schema 未跑过）——按快照答案判
        return snap_answer, "trusted"


def _ai_score_question(db, q_snap: Dict[str, Any], user_answer: str) -> Optional[float]:
    """主观题 AI 建议分（按 rubric/max_score），失败返回 None。"""
    try:
        from services.model_gateway import get_gateway

        max_score = float(q_snap.get("max_score") or 10.0)
        rubric = q_snap.get("rubric")
        prompt = (
            f"题目：{(q_snap.get('content') or '')[:800]}\n"
            f"参考答案：{(q_snap.get('answer') or '')[:500]}\n"
            f"评分标准(rubric)：{rubric or '无'}\n"
            f"考生答案：{user_answer[:800]}\n"
            f"满分 {max_score} 分。请只输出一个 0~{max_score} 的建议分数（数字，不要文字）。"
        )
        res = get_gateway().chat(
            question=prompt,
            subject=q_snap.get("subject"),
            task="题目分析",
            context=None,
            system_prompt="你是考研阅卷老师，评分客观公正，只输出数字。",
            prefer=None,
            db=db,
        )
        txt = (res.get("answer") or "").strip()
        import re
        m = re.search(r"(\d+(?:\.\d+)?)", txt)
        if not m:
            return None
        score = float(m.group(1))
        return max(0.0, min(max_score, score))
    except Exception:
        return None


def submit_session(db, session_id: int, answers) -> Dict[str, Any]:
    """交卷判分。

    answers 兼容两种形态（路由层是 list[ExamAnswerItem]，历史调用方有 dict）：
      - dict: {question_id | str(question_id): {user_answer, self_score?, time_spent?}}
      - list: [{question_id, user_answer, self_score?, time_spent?}]
    判分规则：
      - 客观题（answer_type=objective）：自动判分 scored_by=auto
      - 主观题：AI 建议分（scored_by=ai）+ 用户自评（scored_by=self），
        统计只认 auto+self；final_score 优先自评分
    错题回流：错误题写入 error_records（去重），联动盲区池记录弱知识点。
    """
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection

    # 归一化为 dict 索引（str/int 双 key 都放，查询处已兼容）
    if isinstance(answers, list):
        _norm_answers: Dict[Any, Dict[str, Any]] = {}
        for it in answers:
            qid = (it or {}).get("question_id")
            if qid is not None:
                _norm_answers[str(qid)] = it
                _norm_answers[qid] = it
        answers = _norm_answers

    sess = conn.execute(
        "SELECT id, subject, paper, config, status FROM exam_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not sess:
        return {"error": "session not found"}
    if sess[4] == "submitted":
        return {"error": "session already submitted"}

    config = json.loads(sess[3] or "{}")
    subject = sess[1]

    rows = conn.execute(
        "SELECT id, question_id, question_snapshot, section, order_no FROM exam_answers"
        " WHERE session_id = ? ORDER BY order_no",
        (session_id,),
    ).fetchall()

    correct_count = 0
    score_sum = 0.0
    stats_count = 0
    wrong_questions: List[Dict[str, Any]] = []
    ai_unverified_count = 0  # T6-1：答案为 AI 生成未核验的判分题数（结果透传）

    for (ea_id, qid, snap_json, section, order_no) in rows:
        snap = json.loads(snap_json or "{}")
        ans_info = answers.get(str(qid)) or answers.get(qid) or {}
        user_answer = (ans_info.get("user_answer") or "").strip()
        time_spent = int(ans_info.get("time_spent") or 0)
        answer_type = snap.get("answer_type") or "objective"

        # T6-1：判分答案经可信度分层（AI 未核验答案优先取交叉校验候选）
        correct_answer, trust = _trusted_answer(conn, qid, snap.get("answer") or "")
        if trust == "ai_unverified":
            ai_unverified_count += 1

        is_correct = None
        ai_score = None
        self_score = None
        final_score = None
        scored_by = "auto"
        error_category = None

        if answer_type == "objective":
            is_correct = 1 if _grade_objective(user_answer, correct_answer) else 0
            if is_correct:
                correct_count += 1
                score_sum += float(snap.get("max_score") or 0)
            stats_count += 1
            if not is_correct:
                wrong_questions.append({"question_id": qid, "snapshot": snap, "user_answer": user_answer})
        else:
            # 主观题：AI 建议分 + 自评；final 取 self（若无 self 取 ai）
            max_score = float(snap.get("max_score") or 0)
            ai_score = _ai_score_question(db, snap, user_answer)
            if "self_score" in ans_info:
                try:
                    self_score = max(0.0, min(max_score, float(ans_info["self_score"])))
                except (TypeError, ValueError):
                    self_score = None
            final_score = self_score if self_score is not None else ai_score
            scored_by = "self" if self_score is not None else ("ai" if ai_score is not None else "self")
            if self_score is not None:
                score_sum += self_score
                stats_count += 1
                is_correct = 1 if self_score >= max_score * 0.6 else 0
                if not is_correct:
                    wrong_questions.append({"question_id": qid, "snapshot": snap, "user_answer": user_answer})
            elif ai_score is not None:
                # ai 只单列，不污染统计
                is_correct = 1 if ai_score >= max_score * 0.6 else 0

        exec_retry(
            conn,
            """
            UPDATE exam_answers SET user_answer = ?, is_correct = ?, time_spent = ?,
            ai_score = ?, self_score = ?, final_score = ?, scored_by = ?, error_category = ?
            WHERE id = ?
            """,
            (user_answer, is_correct, time_spent, ai_score, self_score, final_score,
             scored_by, error_category, ea_id),
        )

    # 错题回流 error_records（去重：同 question_id 未解决不重复插入）
    blind_spot_calls: List[Dict[str, Any]] = []
    for wq in wrong_questions:
        qid = wq["question_id"]
        snap = wq["snapshot"]
        exists = conn.execute(
            "SELECT id FROM error_records WHERE question_id = ? AND status IN ('active','submitted')"
            " ORDER BY id DESC LIMIT 1",
            (qid,),
        ).fetchone()
        if not exists:
            # T6-2：模考错题与刷题错题同待遇——插入即挂首次复习排期。
            # V12 同族修复：首间隔按掌握度给 ≥1 天，不再 20 分钟后即当日到期
            # （那会让模考新错题当天全部涌入"今日复习队列"）。
            from services.review_scheduler import ReviewScheduler

            next_review = ReviewScheduler.first_review_at()
            exec_retry(
                conn,
                """
                INSERT INTO error_records
                (question_id, content, my_answer, correct_answer, error_reason, subject, status, analysis, next_review, review_count)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, 0)
                """,
                (qid, snap.get("content") or "", wq["user_answer"] or "", snap.get("answer") or "",
                 "模考判错（自动/自评）", subject, "",
                 next_review.strftime("%Y-%m-%d %H:%M:%S") if next_review else None),
            )
        # 联动 A4 盲区池：记录弱知识点（gap_type=no_answer，建议强化练习）
        # 延后到 db.commit() 后执行，避免内部 commit 使本函数持有的底层连接失效
        try:
            kp_name = snap.get("knowledge_point") or ""
            if kp_name:
                blind_spot_calls.append({
                    "question": f"【模考薄弱】{kp_name}",
                    "subject": subject,
                    "basis": f"题目#{qid}: {(snap.get('content') or '')[:100]}",
                    "basis_ids": [qid],
                    "gap_type": "no_answer",
                    "suggestion": f"强化练习知识点：{kp_name}",
                    "suggested_action": "add_kp",
                })
        except Exception:
            pass

    submitted_at = _now_str()
    exec_retry(
        conn,
        """
        UPDATE exam_sessions SET correct_count = ?, score = ?, submitted_at = ?, status = 'submitted'
        WHERE id = ?
        """,
        (correct_count, round(score_sum, 2), submitted_at, session_id),
    )
    db.commit()

    # 盲区池联动（延迟执行：record_abstain 内部会 commit，不能再持有 conn）
    for call in blind_spot_calls:
        try:
            from services.blind_spot_pool import record_abstain

            record_abstain(db, **call)
        except Exception:
            pass

    # —— 错题 ↔ 知识点联动（2026-10）—— #
    # 模考回流此前只插 error_records、不挂知识点，导致模考错题在复盘页成「孤岛」
    # （联调实测：20 条模考错题 0 条有链路）。此处与刷题/手动收录对齐。
    try:
        from services import error_linker
        from models import ErrorRecord

        qids = [wq["question_id"] for wq in wrong_questions]
        if qids:
            refluxed = (
                db.query(ErrorRecord)
                .filter(
                    ErrorRecord.question_id.in_(qids),
                    ErrorRecord.error_reason == "模考判错（自动/自评）",
                )
                .all()
            )
            for e in refluxed:
                try:
                    error_linker.auto_link_error(db, e, top_k=3)
                except Exception:
                    pass
    except Exception:
        pass

    # —— 学习行为埋点（2026-10）—— #
    # 模考交卷此前完全不产事件，导致学习科学/成长体系拿不到模考维度数据。
    try:
        from services.study_event_service import record_event

        record_event(
            db,
            "exam_submit",
            subject=subject,
            payload={
                "session_id": session_id,
                "total_count": len(rows),
                "correct_count": correct_count,
                "wrong_count": len(wrong_questions),
                "score": round(score_sum, 2),
            },
        )
    except Exception:
        pass

    return {
        "session_id": session_id,
        "status": "submitted",
        "correct_count": correct_count,
        "score": round(score_sum, 2),
        "stats_count": stats_count,
        "total_count": len(rows),
        "wrong_count": len(wrong_questions),
        # T6-1：答案可信度透传——判分依据含未核验 AI 答案的题数，
        # 前端据此提示"本次判分中 N 题答案为 AI 生成，待交叉校验"
        "ai_unverified_count": ai_unverified_count,
        "scored_at": submitted_at,
    }


def list_sessions(db, subject: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection
    sql = "SELECT id, blueprint_key, subject, paper, mode, total_count, total_score, correct_count, score, status, started_at, submitted_at, expires_at FROM exam_sessions WHERE 1=1"
    params: List[Any] = []
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    cols = ["id", "blueprint_key", "subject", "paper", "mode", "total_count", "total_score",
            "correct_count", "score", "status", "started_at", "submitted_at", "expires_at"]
    return [dict(zip(cols, r)) for r in rows]


def session_detail(db, session_id: int) -> Dict[str, Any]:
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection
    sess = conn.execute(
        "SELECT id, blueprint_key, subject, paper, mode, config, total_count, total_score,"
        " correct_count, score, time_limit_minutes, status, started_at, submitted_at, expires_at"
        " FROM exam_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not sess:
        return {"error": "session not found"}
    cols = ["id", "blueprint_key", "subject", "paper", "mode", "config", "total_count",
            "total_score", "correct_count", "score", "time_limit_minutes", "status",
            "started_at", "submitted_at", "expires_at"]
    d = dict(zip(cols, sess))
    try:
        d["config"] = json.loads(d["config"] or "{}")
    except Exception:
        d["config"] = {}
    rows = conn.execute(
        "SELECT id, question_id, question_snapshot, section, order_no, user_answer, is_correct,"
        " time_spent, ai_score, self_score, final_score, scored_by, error_category"
        " FROM exam_answers WHERE session_id = ? ORDER BY order_no",
        (session_id,),
    ).fetchall()
    a_cols = ["id", "question_id", "question_snapshot", "section", "order_no", "user_answer",
              "is_correct", "time_spent", "ai_score", "self_score", "final_score", "scored_by",
              "error_category"]
    answers = []
    for r in rows:
        a = dict(zip(a_cols, r))
        try:
            a["question_snapshot"] = json.loads(a["question_snapshot"] or "{}")
        except Exception:
            a["question_snapshot"] = {}
        answers.append(a)
    d["answers"] = answers
    return d


if __name__ == "__main__":  # pragma: no cover
    print("exam_builder loaded")
