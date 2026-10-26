# -*- coding: utf-8 -*-
"""轻量状态机编排器：多 Agent 答疑协作（55 号 DeepTutor 升级方案 P1-E）。

把一次答疑拆成四个可观测阶段，输出完整轨迹供前端展示
「AI 是如何一步步得出答案的」：

    retrieve → solve → verify → remedy

设计约定：
- **不引入复杂 Agent 框架**：四个阶段由本模块顺序编排，各自 try/except，
  任一阶段失败都降级为 ``{"status": "degraded", "error": ...}`` 并继续，
  绝不让整个请求 500。
- **模型调用全部走 AIService.chat**：它自带 本地→API→offline 降级链，
  返回 dict 含 content / provider / route。
- **verify 阶段成本控制**：只有 ``question_type in ("calc", "fill")`` 的
  客观计算题才执行沙箱验算（``sandbox_verify``）；其它题型跳过沙箱，
  直接基于答案一致性做规则校验，**不调用** ``verify_score`` 的大模型，
  避免每次答疑都多付一次 LLM 调用。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from services.ai_service import AIService
from services import subjective_grader

logger = logging.getLogger(__name__)

#: 需要做沙箱验算的题型（与 subjective_grader.sandbox_verify 内部口径对齐）
_CALC_TYPES = ("calc", "fill")

#: 默认知识库检索条数
_RETRIEVE_LIMIT = 3

#: 参考答案关键数字/关键词的提取长度上限
_ANSWER_PROBE_LEN = 200


def _stage(
    stage: str,
    status: str = "ok",
    data: Optional[Dict[str, Any]] = None,
    elapsed_ms: Optional[float] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """构造单条轨迹记录。"""
    entry: Dict[str, Any] = {"stage": stage, "status": status}
    if elapsed_ms is not None:
        entry["elapsed_ms"] = int(elapsed_ms)
    if error:
        entry["error"] = str(error)[:500]
    entry["data"] = data or {}
    return entry


def _question_type(question: Any) -> str:
    """兼容 ORM 与 dict 两种题目形态，读取 question_type。"""
    if isinstance(question, dict):
        return str(question.get("question_type") or "")
    return str(getattr(question, "question_type", None) or "")


def _consistency_check(
    question: Any,
    my_answer: Optional[str],
    reference_answer: Optional[str],
    sandbox_value: Optional[float] = None,
) -> Dict[str, Any]:
    """规则级答案一致性校验（不调用 LLM）。

    客观题：参考答案通常是选项字母（如 "B"）或短语；学生答案若包含
    参考答案的关键数字/关键词，视为一致。
    主观题：参考答案关键数字/关键词出现在学生答案中即视为部分一致，
    否则标记为不一致（提示学生对照解析）。

    若传入 ``sandbox_value``（沙箱验算出的数值），优先比较学生答案数字
    是否与验算值相等——这比"参考数字子串匹配"更可靠，避免学生答案里
    的 100 被误判为包含参考答案里的 1。
    """
    student = (my_answer or "").strip()
    ref = (reference_answer or "").strip()
    if not student:
        return {
            "consistent": False,
            "summary": "学生答案为空，无法做一致性校验",
            "detail": "missing_student_answer",
        }
    if not ref:
        return {
            "consistent": None,
            "summary": "参考答案为空，跳过一致性校验",
            "detail": "missing_reference_answer",
        }

    student_numbers = _extract_numbers(student)

    # 优先：沙箱验算值比对（calc/fill 且验算通过时）
    if sandbox_value is not None:
        for n in student_numbers:
            try:
                if abs(float(n) - float(sandbox_value)) < 1e-6:
                    return {
                        "consistent": True,
                        "summary": f"学生答案数字 {n} 与沙箱验算值 {sandbox_value:g} 一致",
                        "detail": "sandbox_value_hit",
                        "matched": {"numbers": [n], "keywords": []},
                    }
            except (TypeError, ValueError):
                continue

    # 参考答案关键数字/关键词提取
    numbers = _extract_numbers(ref)
    keywords = _extract_keywords(ref)

    # 数字用完整 token 交集判断（避免 "100" 被当成包含 "1"）
    hit_numbers = [n for n in numbers if n in student_numbers]
    hit_keywords = [k for k in keywords if k in student]

    if hit_numbers:
        return {
            "consistent": True,
            "summary": f"学生答案包含参考答案关键数字 {'/'.join(hit_numbers[:3])}，判定一致",
            "detail": "number_hit",
            "matched": {"numbers": hit_numbers[:5], "keywords": hit_keywords[:5]},
        }
    if hit_keywords:
        return {
            "consistent": True,
            "summary": f"学生答案包含参考答案关键词 {'/'.join(hit_keywords[:3])}，判定一致",
            "detail": "keyword_hit",
            "matched": {"numbers": [], "keywords": hit_keywords[:5]},
        }
    if numbers:
        return {
            "consistent": False,
            "summary": f"学生答案未包含参考答案关键数字（如 {numbers[0]}），判定不一致",
            "detail": "number_miss",
            "expected": {"numbers": numbers[:5], "keywords": keywords[:5]},
        }
    if keywords:
        return {
            "consistent": False,
            "summary": f"学生答案未包含参考答案关键词（如 {keywords[0]}），判定不一致",
            "detail": "keyword_miss",
            "expected": {"numbers": [], "keywords": keywords[:5]},
        }
    return {
        "consistent": None,
        "summary": "参考答案无可提取的关键数字/关键词，跳过一致性判定",
        "detail": "no_probe",
    }


def _extract_numbers(text: str) -> List[str]:
    """提取文本中的关键数字（整数/小数/负数/百分数），去重保序。"""
    import re

    found = re.findall(r"-?\d+(?:\.\d+)?%?", text[:_ANSWER_PROBE_LEN])
    out: List[str] = []
    for n in found:
        if n not in out:
            out.append(n)
    return out


def _extract_keywords(text: str) -> List[str]:
    """提取文本中的 2~8 字中文关键词（去停用词），去重保序。"""
    import re

    cjk = re.findall(r"[\u4e00-\u9fff]{2,8}", text[:_ANSWER_PROBE_LEN])
    stop = {
        "答案", "正确", "解析", "参考", "因为", "所以", "因此", "根据",
        "可以", "就是", "这个", "一个", "以及", "得到", "可知", "则",
    }
    out: List[str] = []
    for w in cjk:
        if w in stop:
            continue
        if w not in out:
            out.append(w)
    return out


def _score_estimate(verification: Dict[str, Any], max_score: float = 10.0) -> Optional[float]:
    """基于验证结果估算得分（0~max_score），用于校验 solve 是否跑偏。

    规则：沙箱验算通过且答案一致 → 高分区间；不一致 → 低分区；
    无法判定 → None（不估算）。
    """
    math_verified = verification.get("math_verified")
    consistency = verification.get("consistency")
    if math_verified is True:
        return round(max_score * 0.9, 1)
    if consistency is True:
        return round(max_score * 0.8, 1)
    if consistency is False:
        return round(max_score * 0.3, 1)
    return None


def _verify_stage(question: Any, my_answer: Optional[str], reference_answer: Optional[str]) -> Dict[str, Any]:
    """verify 阶段：沙箱验算（仅 calc/fill）+ 规则一致性校验。

    按规格**不调用** ``verify_score`` 的大模型：其它题型跳过沙箱，
    直接基于答案一致性做规则校验，控制成本与延迟。
    任何异常都 try/except 降级为 ``{"verification": {..., "summary": "验证不可用"},
    "degraded": True}``，绝不向上抛。
    """
    qtype = _question_type(question)
    math_verified: Optional[bool] = None
    sandbox: Dict[str, Any] = {}

    if qtype in _CALC_TYPES:
        try:
            sandbox = subjective_grader.sandbox_verify(question, reference_answer or "")
            math_verified = bool(sandbox.get("verified") and sandbox.get("usable"))
        except Exception as exc:  # noqa: BLE001 - 沙箱异常降级，绝不向上抛
            logger.warning("沙箱验算失败（已降级）: %s", exc)
            return {
                "verification": {
                    "math_verified": False,
                    "consistency": None,
                    "summary": "验证不可用",
                    "score_estimate": None,
                },
                "degraded": True,
            }

    consistency: Optional[bool] = None
    consistency_detail = ""
    try:
        sandbox_value = sandbox.get("value") if sandbox.get("usable") else None
        cc = _consistency_check(question, my_answer, reference_answer, sandbox_value=sandbox_value)
        consistency = cc.get("consistent")
        consistency_detail = cc.get("summary") or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("一致性校验失败（已降级）: %s", exc)
        return {
            "verification": {
                "math_verified": False,
                "consistency": None,
                "summary": "验证不可用",
                "score_estimate": None,
            },
            "degraded": True,
        }

    verification: Dict[str, Any] = {
        "math_verified": math_verified,
        "consistency": consistency,
        "summary": consistency_detail or "验证不可用",
        "score_estimate": None,
    }
    verification["score_estimate"] = _score_estimate(verification)
    if sandbox:
        verification["sandbox"] = sandbox
    return {"verification": verification, "degraded": False}


async def _retrieve_stage(db, question: Any, subject: Optional[str]) -> Dict[str, Any]:
    """retrieve 阶段：检索知识库相关讲义片段。"""
    hits: List[Dict[str, Any]] = []
    try:
        query = (question.content if not isinstance(question, dict) else question.get("content")) or ""
        hits = AIService(db).search_knowledge_base(
            query=query[:500] or "",
            limit=_RETRIEVE_LIMIT,
            subject=subject,
        ) or []
    except Exception as exc:  # noqa: BLE001 - 检索失败不阻断后续阶段
        logger.warning("知识库检索失败（已降级）: %s", exc)
        return {
            "hits": [],
            "degraded": True,
            "error": str(exc)[:300],
        }
    return {"hits": hits[: _RETRIEVE_LIMIT], "degraded": False}


def _build_solve_messages(
    question: Any,
    my_answer: Optional[str],
    subject: Optional[str],
    knowledge_point: Optional[str],
    hits: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """组装 solve 阶段的 messages。"""
    if isinstance(question, dict):
        content = question.get("content") or ""
        reference_answer = question.get("answer") or ""
        analysis = question.get("analysis") or ""
    else:
        content = getattr(question, "content", None) or ""
        reference_answer = getattr(question, "answer", None) or ""
        analysis = getattr(question, "analysis", None) or ""

    kb_blocks: List[str] = []
    if hits:
        for i, h in enumerate(hits, 1):
            kb_blocks.append(
                f"[片段{i}｜来源：{h.get('source')}｜{h.get('title') or ''}]\n{h.get('content') or ''}"
            )
    kb_text = "\n\n".join(kb_blocks) if kb_blocks else "（未检索到相关讲义片段）"

    lines = [
        f"【题目】{content}",
        f"【正确答案】{reference_answer}",
        f"【学生答案】{my_answer or '（未作答）'}",
        f"【检索到的讲义片段】\n{kb_text}",
        f"【考点】{knowledge_point or getattr(question, 'knowledge_point', None) or subject or '未标注'}",
    ]
    if analysis:
        lines.append(f"【参考解析】{str(analysis)[:600]}")

    return [
        {
            "role": "system",
            "content": (
                "你是考研讲师，结合检索到的讲义上下文与学生作答，分步解答。"
                "请先点破本题考点，再分步骤给出正确解法；"
                "若学生答案有误，指出错在哪一步；回答精炼，不超过 500 字。"
            ),
        },
        {"role": "user", "content": "\n".join(lines)},
    ]


async def _solve_stage(
    db,
    question: Any,
    my_answer: Optional[str],
    subject: Optional[str],
    knowledge_point: Optional[str],
    hits: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """solve 阶段：调用 AIService.chat 得到解答。"""
    messages = _build_solve_messages(question, my_answer, subject, knowledge_point, hits)
    try:
        result = await AIService(db).chat(messages, kb_hit_count=len(hits))
    except Exception as exc:  # noqa: BLE001 - 模型调用失败降级
        logger.warning("AI 解答调用失败（已降级）: %s", exc)
        return {
            "content": "",
            "provider": "local-fallback",
            "route": "offline",
            "degraded": True,
            "error": str(exc)[:300],
        }

    content = (result.get("content") or "").strip()
    route = result.get("route") or ""
    degraded = (not content) or route == "offline"
    return {
        "content": content,
        "provider": result.get("provider") or "",
        "route": route,
        "route_reason": result.get("route_reason") or "",
        "model": result.get("model"),
        "degraded": degraded,
    }


def _remedy_stage(
    verification: Dict[str, Any],
    knowledge_point: Optional[str],
    solve_confidence: str,
) -> Dict[str, Any]:
    """remedy 阶段：根据验证结果与知识点给出补救建议。"""
    suggestions: List[str] = []
    consistency = verification.get("consistency")
    math_verified = verification.get("math_verified")
    score_estimate = verification.get("score_estimate")
    kp = knowledge_point or "本题考点"

    if consistency is False:
        suggestions.append(
            f"你的答案与参考答案不一致，建议回到「{kp}」重新复习概念与标准步骤，"
            "再练 2~3 道同类题巩固。"
        )
    elif consistency is True and math_verified is not True:
        suggestions.append(
            f"本题思路基本正确，建议再练 2~3 道同考点（{kp}）题，提升熟练度与准确率。"
        )
    else:
        suggestions.append(
            f"建议围绕「{kp}」做一次知识点梳理，并用 2~3 道同类题检验是否真正掌握。"
        )

    if solve_confidence == "low":
        suggestions.append("本次解答置信度较低，建议结合参考解析逐步骤核对，或向老师追问。")
    elif score_estimate is not None and score_estimate < 5:
        suggestions.append("预估得分偏低，建议把错因记录到错题本，安排短期滚动复习。")

    return {
        "suggestions": suggestions[:4],
        "knowledge_point": kp,
    }


def _fallback_answer(question: Any) -> str:
    """最坏情况（连 solve 都失败）的本地兜底文案。"""
    if isinstance(question, dict):
        analysis = question.get("analysis") or ""
        answer = question.get("answer") or ""
    else:
        analysis = getattr(question, "analysis", None) or ""
        answer = getattr(question, "answer", None) or ""
    ref = str(analysis or answer or "").strip()
    if ref:
        return f"本地兜底：参考解析如下，请对照自己的步骤核对。\n{ref[:800]}"
    return "本地兜底：当前未能生成 AI 解答，请参考题目解析或向老师提问。"


async def orchestrate_tutoring(
    db,
    user_id: Optional[int],
    question_id: int,
    my_answer: Optional[str] = None,
    subject: Optional[str] = None,
    question: Any = None,
    knowledge_point: Optional[str] = None,
) -> Dict[str, Any]:
    """编排多 Agent 答疑：retrieve → solve → verify → remedy。

    Args:
        db: SQLAlchemy Session
        user_id: 当前用户 id（用于记忆轨迹归属；可为 None）
        question_id: 题目 id
        my_answer: 学生答案（可选）
        subject: 科目（可选，缺省从题目派生）
        question: QuizQuestion ORM 行（可选；由路由层传入，缺省时按 question_id 查询）
        knowledge_point: 考点（可选，缺省从题目派生）

    Returns:
        供前端渲染的完整轨迹 dict（永不抛异常）。
    """
    start = time.time()
    trace: List[Dict[str, Any]] = []

    # ---- 题目上下文解析（若路由未传入则按 id 查询）----
    if question is None:
        from models import QuizQuestion

        question = db.query(QuizQuestion).filter(QuizQuestion.id == question_id).first()
    if question is None:
        return {
            "question_id": question_id,
            "trace": [
                _stage("retrieve", "degraded", {"error": "题目不存在"}, error="题目不存在")
            ],
            "answer": "本地兜底：题目不存在或已被删除。",
            "confidence": "low",
            "degraded": True,
            "provider": "local-rules",
            "route": "offline",
        }

    if isinstance(question, dict):
        q_subject = subject or question.get("subject")
        q_kp = knowledge_point or question.get("knowledge_point")
    else:
        q_subject = subject or getattr(question, "subject", None)
        q_kp = knowledge_point or getattr(question, "knowledge_point", None)
    q_content = question.get("content") if isinstance(question, dict) else getattr(question, "content", None)
    q_answer = question.get("answer") if isinstance(question, dict) else getattr(question, "answer", None)

    # ---- retrieve ----
    t0 = time.time()
    try:
        retrieve_data = await _retrieve_stage(db, question, q_subject)
    except Exception as exc:  # noqa: BLE001
        retrieve_data = {"hits": [], "degraded": True, "error": str(exc)[:300]}
    trace.append(_stage("retrieve", "degraded" if retrieve_data.get("degraded") else "ok",
                        data={"hits": retrieve_data.get("hits", [])},
                        elapsed_ms=(time.time() - t0) * 1000,
                        error=retrieve_data.get("error")))
    hits = retrieve_data.get("hits", []) or []

    # ---- solve ----
    t0 = time.time()
    solve_data = await _solve_stage(db, question, my_answer, q_subject, q_kp, hits)
    solve_degraded = bool(solve_data.get("degraded"))
    trace.append(_stage("solve",
                        "degraded" if solve_degraded else "ok",
                        data={
                            "provider": solve_data.get("provider"),
                            "route": solve_data.get("route"),
                            "route_reason": solve_data.get("route_reason"),
                            "model": solve_data.get("model"),
                            "preview": (solve_data.get("content") or "")[:200],
                        },
                        elapsed_ms=(time.time() - t0) * 1000,
                        error=solve_data.get("error")))
    answer = solve_data.get("content") or _fallback_answer(question)

    # ---- verify ----
    t0 = time.time()
    try:
        verify_data = _verify_stage(question, my_answer, q_answer)
        verify_degraded = bool(verify_data.get("degraded"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("verify 阶段异常（已降级）: %s", exc)
        verify_data = {
            "verification": {
                "math_verified": False,
                "consistency": None,
                "summary": "验证不可用",
                "score_estimate": None,
            },
            "degraded": True,
        }
        verify_degraded = True
    trace.append(_stage("verify",
                        "degraded" if verify_degraded else "ok",
                        data={"verification": verify_data.get("verification", {})},
                        elapsed_ms=(time.time() - t0) * 1000,
                        error="验证不可用" if verify_degraded else None))

    # ---- 置信度汇总 ----
    consistency = verify_data.get("verification", {}).get("consistency")
    math_verified = verify_data.get("verification", {}).get("math_verified")
    if solve_degraded:
        confidence = "low"
    elif not answer:
        confidence = "low"
    elif consistency is False:
        confidence = "low"
    elif math_verified is True or consistency is True:
        confidence = "high"
    else:
        confidence = "medium"

    # ---- remedy ----
    t0 = time.time()
    try:
        remedy_data = _remedy_stage(verify_data.get("verification", {}), q_kp, confidence)
        remedy_degraded = False
    except Exception as exc:  # noqa: BLE001
        logger.warning("remedy 阶段异常（已降级）: %s", exc)
        remedy_data = {"suggestions": ["建议对照参考解析核对本题步骤。"], "knowledge_point": q_kp or "本题考点"}
        remedy_degraded = True
    trace.append(_stage("remedy",
                        "degraded" if remedy_degraded else "ok",
                        data=remedy_data,
                        elapsed_ms=(time.time() - t0) * 1000,
                        error="补救建议不可用" if remedy_degraded else None))

    # ---- 旁路记录 L1 记忆轨迹（失败静默忽略）----
    try:
        if user_id is not None:
            from services import memory_service

            memory_service.record_trace(
                user_id=user_id,
                trace_type="tutoring",
                title=f"多Agent答疑：{(q_content or '')[:60]}",
                payload={
                    "kind": "orchestrated",
                    "question_id": question_id,
                    "question_content": (q_content or "")[:1500],
                    "my_answer": (my_answer or "")[:1500],
                    "answer": (answer or "")[:3000],
                    "confidence": confidence,
                    "degraded": bool(solve_degraded),
                },
                subject=q_subject or None,
                question_id=question_id,
                db=db,
            )
    except Exception:  # noqa: BLE001 - 埋点旁路
        pass

    return {
        "question_id": int(question_id),
        "trace": trace,
        "answer": answer,
        "confidence": confidence,
        "degraded": bool(solve_degraded),
        "provider": solve_data.get("provider") or "local-rules",
        "route": "offline" if solve_degraded else (solve_data.get("route") or "hybrid"),
    }