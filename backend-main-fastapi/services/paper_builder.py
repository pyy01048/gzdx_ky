"""组题网：从题库按知识点/难度/题型自动组卷。

支持：
- 结构化筛选组卷（知识点、难度、题型、题数、分值）
- AI 辅助选题：当筛选结果多于需求时，调用模型网关让 LLM 从候选池挑选
- 试卷保存（快照题目内容）与导出（可打印 HTML 讲义）
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Paper, PaperQuestion, QuizQuestion
from schemas import QuizQuestionBase

logger = logging.getLogger(__name__)

try:
    from services.model_gateway import get_gateway
except Exception:  # 导入兜底，避免循环依赖
    get_gateway = None

# 题型分值默认表（可被 rules 覆盖）
DEFAULT_SCORES = {
    "single": 2, "multiple": 4, "judge": 2, "blank": 3,
    "short_answer": 8, "calculation": 10, "essay": 15, "analysis": 10,
}

SUBJECT_ALIAS = {
    "数学": "数学", "数电": "数字电子技术", "数字电子技术": "数字电子技术",
    "模电": "模拟电子技术", "模拟电子技术": "模拟电子技术",
    "英语": "英语", "政治": "政治", "408": "408",
}


def normalize_subject(subject: Optional[str]) -> Optional[str]:
    if not subject:
        return None
    return SUBJECT_ALIAS.get(subject.strip(), subject.strip())


def build_rules(
    subject: Optional[str] = None,
    knowledge_points: Optional[List[str]] = None,
    chapters: Optional[List[str]] = None,
    difficulties: Optional[List[int]] = None,
    question_types: Optional[List[str]] = None,
    counts: Optional[Dict[str, int]] = None,
    total_questions: Optional[int] = None,
    prefer: Optional[str] = None,
) -> Dict[str, Any]:
    """归一化组卷规则。"""
    return {
        "subject": normalize_subject(subject),
        "knowledge_points": [k for k in (knowledge_points or []) if k],
        "chapters": [c for c in (chapters or []) if c],
        "difficulties": [int(d) for d in (difficulties or []) if d],
        "question_types": [t for t in (question_types or []) if t],
        "counts": counts or {},
        "total_questions": total_questions,
        "prefer": prefer,
    }


def _query_candidates(db: Session, rules: Dict[str, Any]):
    q = db.query(QuizQuestion)
    if rules.get("subject"):
        q = q.filter(QuizQuestion.subject == rules["subject"])
    if rules.get("chapters"):
        q = q.filter(QuizQuestion.chapter.in_(rules["chapters"]))
    if rules.get("knowledge_points"):
        # knowledge_point 字段是单个标签，先按 OR 匹配
        conds = [QuizQuestion.knowledge_point == k for k in rules["knowledge_points"]]
        from sqlalchemy import or_
        q = q.filter(or_(*conds))
    if rules.get("difficulties"):
        q = q.filter(QuizQuestion.difficulty.in_(rules["difficulties"]))
    if rules.get("question_types"):
        q = q.filter(QuizQuestion.question_type.in_(rules["question_types"]))
    return q


def _fill_question_type(q: QuizQuestion) -> str:
    return (q.question_type or "single").strip()


def _pick_by_counts(cands: List[QuizQuestion], counts: Dict[str, int], types: Optional[List[str]]) -> List[QuizQuestion]:
    """按题型配额挑题：先保证每种题型满足配额，余量从剩余候选随机补充。"""
    picked: List[QuizQuestion] = []
    remain = [q for q in cands]
    type_used: Dict[str, List[QuizQuestion]] = {}
    total_quota = sum(int(v) for v in counts.values())

    if counts:
        for t, quota in counts.items():
            pool = [q for q in remain if _fill_question_type(q) == t]
            take = pool[: int(quota)]
            type_used[t] = take
            for q in take:
                if q in remain:
                    remain.remove(q)
        picked = [q for t in type_used for q in type_used[t]]
    elif types:
        # 无配额但有题型要求：各题型取 1~2 题兜底
        for t in types:
            pool = [q for q in remain if _fill_question_type(q) == t]
            if pool:
                picked.append(pool[0])
                remain.remove(pool[0])
    else:
        picked = []

    # 补齐到 total_questions（若设置了）
    quota_total = len(picked)
    target = max(quota_total, 1)
    if total := _total_quota(counts):
        target = max(target, total)
    if target > len(picked) and remain:
        need = target - len(picked)
        picked.extend(remain[:need])
    return picked


def _total_quota(counts: Dict[str, int]) -> int:
    return sum(int(v) for v in counts.values())


def ai_assist_select(
    db: Session,
    rules: Dict[str, Any],
    candidates: List[QuizQuestion],
    target: int,
    prefer: Optional[str] = None,
) -> List[QuizQuestion]:
    """AI 辅助选题：让 LLM 从候选池中挑选最合适的一组题目。

    失败时静默回退到随机抽样，保证组卷可用。
    """
    if not candidates or not get_gateway:
        return _pick_by_counts(candidates, rules.get("counts") or {}, rules.get("question_types"))

    sample = candidates[:40]
    payload = {
        "target_count": target,
        "rules": {k: v for k, v in rules.items() if v},
        "candidates": [
            {
                "id": q.id,
                "subject": q.subject,
                "chapter": q.chapter,
                "knowledge_point": q.knowledge_point,
                "difficulty": q.difficulty,
                "type": _fill_question_type(q),
                "content": (q.content or "")[:120],
            }
            for q in sample
        ],
        "要求": "请从候选题目中挑选最合适的 N 道组成一份试卷，返回 JSON 数组：[\"题目id1\", \"题目id2\", ...]。只返回数组，不要额外解释。",
    }
    try:
        res = get_gateway().chat(
            question=json.dumps(payload, ensure_ascii=False),
            subject=rules.get("subject") or "通用",
            task="组卷选题",
            prefer=prefer,
            db=db,
        )
        text = res.get("answer") or ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        ids = [int(x) for x in re.findall(r"\d+", text)]
        id_set = {q.id for q in candidates}
        ordered = [q for q in candidates if q.id in ids][:target]
        if len(ordered) >= target * 0.6:
            return ordered
    except Exception as e:
        logger.warning("AI 辅助选题失败，回退到随机抽样组卷: %s", e, exc_info=True)
    # 回退：按配额 + 随机
    picked = _pick_by_counts(candidates, rules.get("counts") or {}, rules.get("question_types"))
    if len(picked) < target:
        rest = [q for q in candidates if q not in picked]
        picked.extend(rest[: target - len(picked)])
    return picked[:target]


def build_paper(
    db: Session,
    title: str,
    rules: Dict[str, Any],
    use_ai: bool = False,
) -> Dict[str, Any]:
    """核心组卷：筛选候选 → 选题 → 构造试卷数据。"""
    cand_q = _query_candidates(db, rules)
    candidates = cand_q.order_by(func.random()).limit(300).all()

    if not candidates:
        return {"ok": False, "message": "没有匹配条件的题目，请放宽筛选条件"}

    counts = rules.get("counts") or {}
    total_quota = _total_quota(counts)
    total_questions = rules.get("total_questions") or total_quota or min(10, len(candidates))
    target = min(int(total_questions), len(candidates))

    if use_ai:
        chosen = ai_assist_select(db, rules, candidates, target, prefer=rules.get("prefer"))
    else:
        chosen = _pick_by_counts(candidates, counts, rules.get("question_types"))
        if len(chosen) < target:
            rest = [q for q in candidates if q not in chosen]
            chosen.extend(rest[: target - len(chosen)])

    score_map = {**DEFAULT_SCORES, **{k: int(v) for k, v in (rules.get("scores") or {}).items()}}
    items = []
    total_score = 0
    for i, q in enumerate(chosen, start=1):
        qt = _fill_question_type(q)
        score = score_map.get(qt, 5)
        total_score += score
        items.append({
            "seq": i,
            "question_id": q.id,
            "content": q.content,
            "options": q.options,
            "answer": q.answer,
            "analysis": q.analysis,
            "question_type": qt,
            "difficulty": q.difficulty or 3,
            "score": score,
        })
    return {
        "ok": True,
        "title": title,
        "rules": rules,
        "total_score": total_score,
        "items": items,
    }


def save_paper(db: Session, title: str, subject: Optional[str], description: Optional[str],
               rules: Dict[str, Any], items: List[Dict[str, Any]]) -> Paper:
    paper = Paper(
        title=title,
        subject=normalize_subject(subject),
        description=description,
        rules=rules,
        total_score=sum(int(it.get("score") or 0) for it in items),
    )
    db.add(paper)
    db.flush()
    for it in items:
        db.add(PaperQuestion(
            paper_id=paper.id,
            question_id=it.get("question_id"),
            seq=it.get("seq") or 0,
            content=it.get("content") or "",
            options=it.get("options"),
            answer=it.get("answer"),
            analysis=it.get("analysis"),
            question_type=it.get("question_type"),
            difficulty=it.get("difficulty") or 3,
            score=it.get("score") or 5,
        ))
    db.commit()
    db.refresh(paper)
    return paper


def paper_to_lecture_html(paper: Paper, questions: List[PaperQuestion], base_dir: str) -> str:
    """把试卷导出为可打印 HTML（含答案区，KaTeX 公式渲染）。"""
    now = datetime.now()
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{paper.title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body, {{delimiters:[{{left:'$$',right:'$$',display:true}},{{left:'$',right:'$',display:false}}]}});"></script>
<style>
  body {{ font-family: "Microsoft YaHei", sans-serif; max-width: 860px; margin: 32px auto; padding: 0 24px; color:#222; }}
  h1 {{ text-align:center; font-size:22px; margin-bottom:4px; }}
  .meta {{ text-align:center; color:#666; font-size:13px; margin-bottom:24px; }}
  .q {{ border-bottom:1px dashed #ccc; padding:14px 0; page-break-inside: avoid; }}
  .q .head {{ font-weight:600; margin-bottom:8px; }}
  .q .opts {{ margin:6px 0 0 16px; color:#444; }}
  .q .opts div {{ margin:2px 0; }}
  .ans {{ margin-top:8px; background:#f6f9ff; padding:8px 12px; border-radius:6px; font-size:13px; }}
  .ans b {{ color:#1a56db; }}
  .page-break {{ page-break-before: always; }}
  .footer {{ text-align:center; color:#999; font-size:12px; margin:32px 0; }}
</style>
</head>
<body>
<h1>{paper.title}</h1>
<div class="meta">科目：{paper.subject or '综合'} ｜ 总分：{paper.total_score} ｜ 共 {len(questions)} 题 ｜ 生成：{now.strftime("%Y-%m-%d %H:%M")}</div>
"""
    for q in questions:
        opts_html = ""
        if q.options:
            opts_html = '<div class="opts">' + "".join(
                f"<div>{chr(65 + i)}. {o}</div>" for i, o in enumerate(q.options)
            ) + "</div>"
        ans = f'<div class="ans"><b>答案：</b>{q.answer or "—"}　<b>分值：</b>{q.score}分</div>'
        html += f"""<div class="q"><div class="head">{q.seq}. 【{q.question_type or 'single'}·难度{q.difficulty or 3}】{q.content}</div>{opts_html}{ans}</div>\n"""
    html += f"""<div class="footer">由贵大834考研备考系统 · 组题网生成</div>
</body>
</html>"""
    os.makedirs(base_dir, exist_ok=True)
    safe = re.sub(r"[\\/:*?\"<>|]", "_", paper.title)[:40] or "paper"
    path = os.path.join(base_dir, f"试卷_{now.strftime('%Y%m%d_%H%M%S')}_{safe}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
