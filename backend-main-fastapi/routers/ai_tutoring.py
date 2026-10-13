# -*- coding: utf-8 -*-
"""场景化 AI 讲题（V14 · 对标 gitgraduate「错题与复盘」体验）。

两个端点，全部自动注入题目上下文（练习页内一键提问，无需用户粘贴题干）：
- POST /api/ai/tutoring/explain  三视角讲题：why_wrong（为什么我错）/
  solution（解题思路）/ method（举一反三）
- POST /api/ai/tutoring/followup 追问链：同一题目下多轮追问（history 由前端携带）

降级约定：AIService.chat 自带 本地→API→offline-kb 链；当 route=="offline"
或 LLM 输出为空时，叠加「本地讲解包」（题目+解析+错因分类+相似题指向），
保证无模型环境下答疑依然有用——这是与大平台"断网即哑巴"的差异点。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import QuizQuestion
from services.ai_service import AIService
from services.error_analyzer import _guess_category, _practice_questions

router = APIRouter(prefix="/api/ai/tutoring", tags=["AI 讲题"])

_ANGLES = {
    "why_wrong": "学生做错了这道题。请：1) 指出他最可能错在哪一步/哪个概念；2) 给出正确思路的分步讲解；3) 用一句话总结这个题的易错坑。语言直接、面向备考。",
    "solution": "请分步讲解这道题的解法：先点破考点，再一步步推到答案，最后标注每一步用到的知识点。",
    "method": "请提炼这道题的题型方法：1) 这类题的通用解题模板；2) 2~3 个判断该用此模板的信号词/特征；3) 一道口述变式练习建议。",
}


class ExplainReq(BaseModel):
    question_id: int
    angle: str = Field("why_wrong", description="why_wrong/solution/method")
    my_answer: Optional[str] = Field(None, description="学生答案（结果页自动带入）")


class FollowupReq(BaseModel):
    question_id: int
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[Dict[str, str]] = Field(default_factory=list, description="追问历史")


def _load_question(db: Session, question_id: int) -> QuizQuestion:
    q = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    return q


def _context_text(q: QuizQuestion, my_answer: Optional[str]) -> str:
    opts = ""
    if q.options:
        try:
            import json as _json
            o = q.options if isinstance(q.options, dict) else _json.loads(q.options)
            opts = "；".join(f"{k}.{v}" for k, v in o.items())
        except Exception:
            opts = str(q.options)[:200]
    lines = [f"【题目】{q.content}"]
    if opts:
        lines.append(f"【选项】{opts}")
    if q.answer:
        lines.append(f"【正确答案】{q.answer}")
    if my_answer:
        lines.append(f"【学生答案】{my_answer}")
    if q.analysis:
        lines.append(f"【参考解析】{str(q.analysis)[:600]}")
    lines.append(f"【知识点】{q.knowledge_point or '未标注'}｜科目 {q.subject or '未标注'}")
    return "\n".join(lines)


def _local_fallback(db: Session, q: QuizQuestion, my_answer: Optional[str], angle: str) -> Dict:
    """无模型环境下的结构化讲解包（错因分类 + 参考解析 + 相似题指向）。"""
    cat = _guess_category("答题错误", q.content or "", my_answer or "", q.answer or "")
    similar = _practice_questions(db, db.connection().connection, q.id,
                                 None, q.subject, limit=3)
    steps = {
        "why_wrong": [
            f"错因初判：{cat}",
            f"正确答案是 {q.answer}；对照解析回看你卡住的步骤。",
            f"本题考点：{q.knowledge_point or '见解析'}——同考点建议再练 2~3 题。",
        ],
        "solution": [f"参考解析：{str(q.analysis)[:400]}" if q.analysis else "暂无解析，参考答案自行推导。",
                     f"考点：{q.knowledge_point or '见题干'}"],
        "method": [f"题型归类：{cat}；同考点集中练到连对 3 题即可过关。"],
    }
    return {
        "content": "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps.get(angle, steps["solution"]))),
        "provider": "local-rules",
        "route": "local",
        "similar": [{"id": s["id"], "content": str(s["content"])[:120]} for s in similar],
    }


@router.post("/explain")
async def explain(req: ExplainReq, db: Session = Depends(get_db)):
    q = _load_question(db, req.question_id)
    if req.angle not in _ANGLES:
        raise HTTPException(status_code=422, detail="angle 需为 why_wrong/solution/method")
    ctx = _context_text(q, req.my_answer)
    messages = [
        {"role": "system", "content": "你是考研数电/模电的私人讲师，回答精炼分步，不超过 300 字。"},
        {"role": "user", "content": f"{_ANGLES[req.angle]}\n\n{ctx}"},
    ]
    try:
        r = await AIService(db).chat(messages)
        content, route = r.get("content"), r.get("route", "")
        if not content or route == "offline":
            fallback = _local_fallback(db, q, req.my_answer, req.angle)
            if content:
                fallback["content"] = f"{content}\n\n——\n本地讲解包：\n{fallback['content']}"
            return {"question_id": q.id, "angle": req.angle, **fallback}
        return {"question_id": q.id, "angle": req.angle, "content": content,
                "provider": r.get("provider"), "route": route}
    except Exception:
        return {"question_id": q.id, "angle": req.angle, **_local_fallback(db, q, req.my_answer, req.angle)}


@router.post("/followup")
async def followup(req: FollowupReq, db: Session = Depends(get_db)):
    """追问链：题目上下文始终在 system 中，history 由前端携带（个人单机，无需服务端会话存储）。"""
    q = _load_question(db, req.question_id)
    ctx = _context_text(q, None)
    messages = [{"role": "system",
                 "content": f"你是考研讲师，正在为学生讲解下面这道题，回答不超过 200 字。\n{ctx}"}]
    for h in req.history[-6:]:  # 最多携带 6 轮，防上下文爆炸
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": str(h["content"])[:1500]})
    messages.append({"role": "user", "content": req.message})
    try:
        r = await AIService(db).chat(messages)
        if not r.get("content"):
            raise ValueError("empty")
        return {"question_id": q.id, "content": r["content"],
                "provider": r.get("provider"), "route": r.get("route")}
    except Exception:
        return {"question_id": q.id,
                "content": ("当前处于离线模式，无法追问。可用的本地线索：\n"
                            f"· 参考解析：{str(q.analysis)[:300] or '无'}\n"
                            f"· 考点：{q.knowledge_point or '见题干'}\n"
                            "· 建议：回到解析逐步对照自己的步骤。"),
                "provider": "local-rules", "route": "local"}
