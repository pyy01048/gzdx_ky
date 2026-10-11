# -*- coding: utf-8 -*-
"""
A8 错题四段式错因分析（services/error_analyzer.py）
====================================================
错因分类 → 考点归因 → 四段式讲解 → 对策与复练建议，输出写 error_records.analysis，
evidence 落 misconceptions 表。

四段式协议（ZavionWang/exam-knowledge-base 思路，代码自研）：
  1. 考点定位     → 引用 knowledge_points 真实 ID
  2. 大纲依据     → 引用考纲条目（文本）
  3. 思路拆解     → 分步推导
  4. 干扰项解析   → 强制逐个错误选项说明为什么错

错因分类：概念混淆 / 审题失误 / 计算错误 / 记忆缺失 / 方法没想到 / 时间不足
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

CATEGORIES = ("概念混淆", "审题失误", "计算错误", "记忆缺失", "方法没想到", "时间不足")
DEFAULT_CATEGORY = "概念混淆"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _strip_think(text: str) -> str:
    if not text:
        return text
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return t.strip()


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    t = re.sub(r"```(?:json)?\s*", "", text).strip()
    t = re.sub(r"```", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    body = t[start:end + 1]
    try:
        return json.loads(body)
    except Exception:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", body))
        except Exception:
            return None


def _guess_category(error_reason: str, content: str, my_answer: str, correct_answer: str) -> str:
    """启发式错因兜底（LLM 不可用时）。"""
    s = ((error_reason or "") + (content or "") + (my_answer or "")).lower()
    if any(k in s for k in ("计算", "算错", "粗心", "符号")):
        return "计算错误"
    if any(k in s for k in ("没看清", "审题", "漏看", "误读")):
        return "审题失误"
    if any(k in s for k in ("忘了", "记不住", "记忆")):
        return "记忆缺失"
    if any(k in s for k in ("没想", "方法", "不会做", "无从下手")):
        return "方法没想到"
    if any(k in s for k in ("时间", "没做完")):
        return "时间不足"
    return DEFAULT_CATEGORY


_FOUR_PART_PROMPT = """你是考研辅导老师。请对下面这道错题做四段式错因分析，严格按 JSON 输出（```json 包裹，不输出其他文字）：
{
  "category": "概念混淆|审题失误|计算错误|记忆缺失|方法没想到|时间不足（单选）",
  "pattern": "一句话概括错因模式",
  "knowledge_point_id": 数字或 null（若能对应到给定知识点ID）,
  "knowledge_point": "本题考点名称（引用 knowledge_points 真实ID）",
  "outline_basis": "大纲依据/考纲条目（1-2句）",
  "steps": [{"title": "步骤名", "content": "推导内容"}],
  "distractor_analysis": [{"option": "选项/干扰项", "why_wrong": "为什么错"}],
  "suggestion": "纠正建议（针对category）",
  "evidence": "错因证据摘要（1-3句）"
}
题目：{content}
我的答案：{my_answer}
正确答案：{correct_answer}
错误原因：{error_reason}
考点提示：{kp_hint}
要求：考点定位必须引用真实 knowledge_points ID；干扰项解析必须逐个说明；思路拆解分步清晰。"""


def analyze_error(db, error_record_id: int, *, use_llm: bool = True) -> Dict[str, Any]:
    """四段式错因分析入口（供 routers/errors.py ai-analyze 增强调用）。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection

    row = conn.execute(
        "SELECT id, question_id, content, my_answer, correct_answer, error_reason, subject, "
        "knowledge_point_id, analysis FROM error_records WHERE id = ?",
        (error_record_id,),
    ).fetchone()
    if not row:
        return {"error": "error_record not found", "analysis": "", "message": "错题不存在"}

    (rid, question_id, content, my_answer, correct_answer, error_reason,
     subject, kp_id, old_analysis) = row

    # 1) 确定知识点 ID（优先显式字段，其次 error_knowledge_links / 文本）
    kp_hint = ""
    if kp_id:
        kp_row = conn.execute(
            "SELECT name, chapter FROM knowledge_points WHERE id = ?", (kp_id,)
        ).fetchone()
        if kp_row:
            kp_hint = f"{kp_row[0]}（章节：{kp_row[1] or ''}，ID={kp_id}）"
    else:
        link = conn.execute(
            "SELECT knowledge_point_id FROM error_knowledge_links WHERE error_id = ? LIMIT 1",
            (rid,),
        ).fetchone()
        if link:
            kp_id = link[0]
            kp_row = conn.execute(
                "SELECT name, chapter FROM knowledge_points WHERE id = ?", (kp_id,)
            ).fetchone()
            if kp_row:
                kp_hint = f"{kp_row[0]}（章节：{kp_row[1] or ''}，ID={kp_id}）"

    # 2) LLM 生成四段式
    result: Dict[str, Any] = {}
    if use_llm:
        try:
            from services.model_gateway import get_gateway

            prompt = _FOUR_PART_PROMPT.format(
                content=(content or "")[:1200],
                my_answer=(my_answer or "")[:400],
                correct_answer=(correct_answer or "")[:400],
                error_reason=(error_reason or "")[:400],
                kp_hint=kp_hint or "（未提供）",
            )
            res = get_gateway().chat(
                question=prompt,
                subject=subject,
                task="错因分析",
                context=None,
                system_prompt="你是考研错题诊断专家，输出严谨、针对性强。",
                prefer=None,
                db=db,
            )
            parsed = _extract_json(_strip_think(res.get("answer") or ""))
            if parsed:
                result = parsed
        except Exception:
            result = {}

    # 3) 错因分类（LLM 输出兜底启发式）
    category = result.get("category") or _guess_category(error_reason, content, my_answer, correct_answer)
    if category not in CATEGORIES:
        category = DEFAULT_CATEGORY
    if result.get("knowledge_point_id") and kp_id is None:
        kp_id = result["knowledge_point_id"]

    # 4) 组装四段式文本
    steps = result.get("steps") or []
    steps_text = "\n".join(
        f"步骤{i + 1}｜{s.get('title', '')}：{s.get('content', '')}"
        for i, s in enumerate(steps)
    ) or "（模型未返回分步，以下为整体思路）"
    distractors = result.get("distractor_analysis") or []
    distractor_text = "\n".join(
        f"- {d.get('option', '干扰项')}：{d.get('why_wrong', '')}" for d in distractors
    ) or "- （无选项类题目，跳过干扰项解析）"
    analysis_text = (
        f"【四段式错因分析】\n"
        f"1. 考点定位：{result.get('knowledge_point', '未识别')}"
        + (f"（knowledge_points ID={kp_id}）" if kp_id else "")
        + "\n"
        f"2. 大纲依据：{result.get('outline_basis', '（未给出考纲条目）')}\n"
        f"3. 思路拆解：\n{steps_text}\n"
        f"4. 干扰项解析：\n{distractor_text}\n"
        f"错因分类：{category}\n"
        f"错因模式：{result.get('pattern', '')}\n"
        f"纠正建议：{result.get('suggestion', '')}"
    )

    # 5) 写回 error_records
    from services.db_retry import exec_retry

    exec_retry(
        conn,
        "UPDATE error_records SET analysis = ?, knowledge_point_id = ?, error_category = ? WHERE id = ?",
        (analysis_text, kp_id, category, rid),
    )

    # 6) 落 misconceptions（幂等：同 error_record_id 更新）
    exists = conn.execute(
        "SELECT id FROM misconceptions WHERE error_record_id = ?", (rid,)
    ).fetchone()
    evidence = result.get("evidence") or analysis_text[:500]
    if exists:
        exec_retry(
            conn,
            """
            UPDATE misconceptions SET question_id = ?, knowledge_point_id = ?, pattern = ?,
            category = ?, suggestion = ?, evidence = ?, synced_at = ? WHERE id = ?
            """,
            (question_id, kp_id, result.get("pattern", ""), category,
             result.get("suggestion", ""), evidence, _now_str(), exists[0]),
        )
    else:
        exec_retry(
            conn,
            """
            INSERT INTO misconceptions
            (question_id, error_record_id, knowledge_point_id, pattern, category, suggestion, evidence, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (question_id, rid, kp_id, result.get("pattern", ""), category,
             result.get("suggestion", ""), evidence, _now_str()),
        )

    # 7) 复练建议：同知识点未做错题抽取（weakest 反哺）
    practice = _practice_questions(db, conn, question_id, kp_id, subject, limit=3)

    db.commit()
    return {
        "analysis": analysis_text,
        "message": "AI 分析完成",
        "category": category,
        "pattern": result.get("pattern", ""),
        "knowledge_point_id": kp_id,
        "knowledge_point": result.get("knowledge_point", ""),
        "suggestion": result.get("suggestion", ""),
        "practice_questions": practice,
    }


def _practice_questions(db, conn, question_id, kp_id, subject, limit: int = 3) -> List[Dict[str, Any]]:
    """从 quiz_questions 同知识点/章节未做错题抽取复练题。"""
    try:
        rows = []
        # 优先经 question_knowledge_links 精确关联（kp_id 为 knowledge_points 真实 ID）
        if kp_id:
            rows = conn.execute(
                """
                SELECT q.id, q.content, q.options, q.answer, q.analysis
                FROM quiz_questions q
                JOIN question_knowledge_links qkl ON qkl.question_id = q.id
                WHERE q.id != ? AND qkl.knowledge_point_id = ?
                ORDER BY RANDOM() LIMIT ?
                """,
                (question_id or 0, kp_id, int(limit)),
            ).fetchall()
        if not rows and kp_id:
            # 退化：按知识点名称文本匹配
            kp_name = conn.execute(
                "SELECT name FROM knowledge_points WHERE id = ?", (kp_id,)
            ).fetchone()
            if kp_name and kp_name[0]:
                rows = conn.execute(
                    """
                    SELECT id, content, options, answer, analysis FROM quiz_questions
                    WHERE id != ? AND knowledge_point LIKE ?
                    ORDER BY RANDOM() LIMIT ?
                    """,
                    (question_id or 0, f"%{kp_name[0]}%", int(limit)),
                ).fetchall()
        if not rows:
            rows = conn.execute(
                """
                SELECT id, content, options, answer, analysis FROM quiz_questions
                WHERE id != ? AND subject IS ?
                ORDER BY RANDOM() LIMIT ?
                """,
                (question_id or 0, subject, int(limit)),
            ).fetchall()
        if not rows:
            rows = conn.execute(
                """
                SELECT id, content, options, answer, analysis FROM quiz_questions
                WHERE id != ? ORDER BY RANDOM() LIMIT ?
                """,
                (question_id or 0, int(limit)),
            ).fetchall()
        return [
            {
                "question_id": r[0],
                "content": (r[1] or "")[:300],
                "options": r[2] or "",
                "answer": r[3] or "",
                "analysis": (r[4] or "")[:200],
            }
            for r in rows
        ]
    except Exception:
        return []


def stats(db) -> Dict[str, Any]:
    """错因统计。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection
    rows = conn.execute(
        "SELECT category, COUNT(*) AS n FROM misconceptions GROUP BY category ORDER BY n DESC"
    ).fetchall()
    return {
        "by_category": [{"category": r[0], "count": int(r[1])} for r in rows],
        "total": int(conn.execute("SELECT COUNT(*) FROM misconceptions").fetchone()[0]),
    }


if __name__ == "__main__":  # pragma: no cover
    print("CATEGORIES:", CATEGORIES)
