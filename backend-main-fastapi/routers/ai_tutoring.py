# -*- coding: utf-8 -*-
"""场景化 AI 讲题（V14 · 对标 gitgraduate「错题与复盘」体验）。

两个端点，全部自动注入题目上下文（练习页内一键提问，无需用户粘贴题干）：
- POST /api/ai/tutoring/explain  三视角讲题：why_wrong（为什么我错）/
  solution（解题思路）/ method（举一反三）
- POST /api/ai/tutoring/followup 追问链：同一题目下多轮追问（history 由前端携带）

M0-103②：区分「真题 / 教材题」两种作答风格——
  * 模式来源优先**从题目自身派生**（复用 services.quiz_query.source_kind_of，
    与刷题列表同一份规则，不重复实现），也允许请求显式传入覆盖；
  * exam（真题）：评审视角——踩分点、常见失分步骤、答题规范/书写、时间分配；
  * textbook（教材题）：理解视角——把原理讲透、推导链、与相邻概念辨析；
  * 讲师身份按题目**实际科目**动态生成（不再写死"数电/模电"）。

降级约定：AIService.chat 自带 本地→API→offline-kb 链；当 route=="offline"
或 LLM 输出为空时，叠加「本地讲解包」（题目+解析+错因分类+相似题指向），
保证无模型环境下答疑依然有用——这是与大平台"断网即哑巴"的差异点。
"""
from __future__ import annotations

import json as _json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import QuizQuestion
from services.ai_service import AIService
from services.error_analyzer import _guess_category, _practice_questions
from services.quiz_query import source_kind_of, normalize_source_kind

router = APIRouter(prefix="/api/ai/tutoring", tags=["AI 讲题"])

# 讲题视角（与模式正交：视角决定"讲什么"，模式决定"用什么立场讲"）
_ANGLES = {
    "why_wrong": "学生做错了这道题。请：1) 指出他最可能错在哪一步/哪个概念；2) 给出正确思路的分步讲解；3) 用一句话总结这个题的易错坑。语言直接、面向备考。",
    "solution": "请分步讲解这道题的解法：先点破考点，再一步步推到答案，最后标注每一步用到的知识点。",
    "method": "请提炼这道题的题型方法：1) 这类题的通用解题模板；2) 2~3 个判断该用此模板的信号词/特征；3) 一道口述变式练习建议。",
}

# 两种模式的**实质差异**提示词（不是换说法：立场、关注点、输出结构都不同）
_MODE_STYLE = {
    "exam": (
        "【真题模式】按**阅卷评分视角**讲解：1) 先给出本题的分值构成与踩分点；"
        "2) 指出考生最常见的失分步骤（错在哪、扣几分）；3) 给出规范的答题书写/步骤模板；"
        "4) 提示本类题的时间分配与考场取舍。允许只讲关键得分动作，不必从头推导。"
    ),
    "textbook": (
        "【教材模式】按**概念理解视角**讲解：1) 把题目背后的原理讲透（为什么这样做是对的）；"
        "2) 给出完整推导链，逐步说明每一步的依据；3) 与相邻/易混概念做辨析（何时用 A、何时用 B）；"
        "4) 指出该原理在教材中的位置与常见变式。"
    ),
    "general": "按备考讲解视角分步作答，条理清晰、面向考场。",
}

# 视角 × 模式的组合语境（frontend 会显示当前模式，这里同步给模型）
_MODE_LABEL = {"exam": "真题模式（评分视角）", "textbook": "教材模式（理解视角）", "general": "通用模式"}


class ExplainReq(BaseModel):
    question_id: int
    angle: str = Field("why_wrong", description="why_wrong/solution/method")
    my_answer: Optional[str] = Field(None, description="学生答案（结果页自动带入）")
    source_kind: Optional[str] = Field(
        None,
        description="讲题模式来源：exam(真题)/textbook(教材)/custom。不传则从题目 source 自动派生；显式传入可覆盖",
    )


class FollowupReq(BaseModel):
    question_id: int
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[Dict[str, str]] = Field(default_factory=list, description="追问历史")
    source_kind: Optional[str] = Field(None, description="同 explain：不传则从题目自动派生")


def _load_question(db: Session, question_id: int) -> QuizQuestion:
    q = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    return q


def _resolve_mode(q: QuizQuestion, override: Optional[str]) -> str:
    """解析讲题模式：显式覆盖优先，否则从题目 source 派生（复用共享规则）。

    返回 'exam' / 'textbook' / 'general'（custom 与无来源归为 general）。
    """
    sk = normalize_source_kind(override)
    if sk is not None:
        if sk not in ("exam", "textbook", "custom"):
            raise HTTPException(
                status_code=422,
                detail="source_kind 需为 exam/textbook/custom",
            )
        derived = sk
    else:
        derived = source_kind_of(q.source)
    return derived if derived in ("exam", "textbook") else "general"


def _tutor_role(q: QuizQuestion) -> str:
    """按题目**实际科目**生成讲师身份（不再写死数电/模电）。"""
    subj = (q.subject or "").strip()
    if subj:
        return f"你是考研 {subj} 的私人讲师"
    return "你是考研辅导讲师（本题未标注科目，请依据题干自行判断学科）"


def _format_options(raw) -> str:
    """选项格式化：兼容 dict / list / JSON 字符串三种存法。

    历史缺陷：ORM JSON 列反序列化后 `options` 是 **list**，旧代码只处理 dict，
    于是 `json.loads(list)` 抛错被兜底成 `str(list)`，把 Python repr（带方括号引号）
    喂给模型，直接拉低答疑质量。此处按类型分派，list 按顺序拼成 A．… B．…。
    """
    if not raw:
        return ""
    data = raw
    if isinstance(raw, str):
        try:
            data = _json.loads(raw)
        except Exception:
            return raw.strip()[:200]
    if isinstance(data, dict):
        return "；".join(f"{k}.{v}" for k, v in data.items())
    if isinstance(data, (list, tuple)):
        parts: List[str] = []
        for i, v in enumerate(data):
            s = "" if v is None else str(v).strip()
            if not s:
                continue
            # 选项可能自带 "A．" / "B、" 前缀，避免重复编号
            if len(s) > 1 and s[0] in "ABCDEFGHIJKLMN" and s[1] in ".．、:：":
                parts.append(s)
            else:
                parts.append(f"{chr(65 + i)}.{s}")
        return " ".join(parts)
    return str(data).strip()[:200]


def _context_text(q: QuizQuestion, my_answer: Optional[str]) -> str:
    opts = _format_options(q.options)
    lines = [f"【题目】{q.content}"]
    if opts:
        lines.append(f"【选项】{opts}")
    if q.answer:
        lines.append(f"【正确答案】{q.answer}")
    if my_answer:
        lines.append(f"【学生答案】{my_answer}")
    if q.analysis:
        lines.append(f"【参考解析】{str(q.analysis)[:600]}")
    # 来源大类 + 真题年份：给模型判断"这是真题还是教材题"的显式线索
    kind = source_kind_of(q.source)
    kind_cn = {"exam": "历年真题", "textbook": "教材/讲义题", "custom": "自建/模拟题"}[kind]
    src_extra = []
    if getattr(q, "year", None):
        src_extra.append(f"{q.year}年")
    if getattr(q, "paper", None):
        src_extra.append(str(q.paper)[:40])
    src_line = f"【题目来源】{kind_cn}" + (f"（{' '.join(src_extra)}）" if src_extra else "")
    lines.append(src_line)
    lines.append(f"【知识点】{q.knowledge_point or '未标注'}｜科目 {q.subject or '未标注'}")
    return "\n".join(lines)


def _local_fallback(db: Session, q: QuizQuestion, my_answer: Optional[str], angle: str,
                    mode: str = "general") -> Dict:
    """无模型环境下的结构化讲解包（错因分类 + 参考解析 + 相似题指向）。"""
    cat = _guess_category("答题错误", q.content or "", my_answer or "", q.answer or "")
    similar = _practice_questions(db, db.connection().connection, q.id,
                                 None, q.subject, limit=3)
    head = {"exam": "（真题模式 · 按评分视角）", "textbook": "（教材模式 · 按概念理解）",
            "general": ""}[mode]
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
    body = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps.get(angle, steps["solution"])))
    return {
        "content": (head + "\n" + body) if head else body,
        "provider": "local-rules",
        "route": "local",
        "mode": mode,
        "source_kind": source_kind_of(q.source),
        "similar": [{"id": s["id"], "content": str(s["content"])[:120]} for s in similar],
    }


def _build_system_prompt(q: QuizQuestion, mode: str) -> str:
    return f"{_tutor_role(q)}。当前模式：{_MODE_LABEL[mode]}。{_MODE_STYLE[mode]}回答精炼分步，不超过 300 字。"


@router.post("/explain")
async def explain(req: ExplainReq, db: Session = Depends(get_db)):
    q = _load_question(db, req.question_id)
    if req.angle not in _ANGLES:
        raise HTTPException(status_code=422, detail="angle 需为 why_wrong/solution/method")
    mode = _resolve_mode(q, req.source_kind)
    sk = source_kind_of(q.source)
    ctx = _context_text(q, req.my_answer)
    messages = [
        {"role": "system", "content": _build_system_prompt(q, mode)},
        {"role": "user", "content": f"{_ANGLES[req.angle]}\n\n{ctx}"},
    ]
    try:
        r = await AIService(db).chat(messages)
        content, route = r.get("content"), r.get("route", "")
        if not content or route == "offline":
            fallback = _local_fallback(db, q, req.my_answer, req.angle, mode)
            if content:
                fallback["content"] = f"{content}\n\n——\n本地讲解包：\n{fallback['content']}"
            return {"question_id": q.id, "angle": req.angle, **fallback}
        return {"question_id": q.id, "angle": req.angle, "content": content,
                "provider": r.get("provider"), "route": route,
                "mode": mode, "source_kind": sk}
    except HTTPException:
        raise
    except Exception:
        return {"question_id": q.id, "angle": req.angle,
                **_local_fallback(db, q, req.my_answer, req.angle, mode)}


@router.post("/followup")
async def followup(req: FollowupReq, db: Session = Depends(get_db)):
    """追问链：题目上下文始终在 system 中，history 由前端携带（个人单机，无需服务端会话存储）。"""
    q = _load_question(db, req.question_id)
    mode = _resolve_mode(q, req.source_kind)
    sk = source_kind_of(q.source)
    ctx = _context_text(q, None)
    messages = [{"role": "system",
                 "content": f"{_tutor_role(q)}。当前模式：{_MODE_LABEL[mode]}。"
                            f"{_MODE_STYLE[mode]}\n正在为学生讲解下面这道题，回答不超过 200 字。\n{ctx}"}]
    for h in req.history[-6:]:  # 最多携带 6 轮，防上下文爆炸
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": str(h["content"])[:1500]})
    messages.append({"role": "user", "content": req.message})
    try:
        r = await AIService(db).chat(messages)
        if not r.get("content"):
            raise ValueError("empty")
        return {"question_id": q.id, "content": r["content"],
                "provider": r.get("provider"), "route": r.get("route"),
                "mode": mode, "source_kind": sk}
    except Exception:
        return {"question_id": q.id,
                "content": ("当前处于离线模式，无法追问。可用的本地线索：\n"
                            f"· 参考解析：{str(q.analysis)[:300] or '无'}\n"
                            f"· 考点：{q.knowledge_point or '见题干'}\n"
                            "· 建议：回到解析逐步对照自己的步骤。"),
                "provider": "local-rules", "route": "local",
                "mode": mode, "source_kind": sk}
