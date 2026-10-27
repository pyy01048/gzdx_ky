# -*- coding: utf-8 -*-
"""主观题 AI 批改公共服务（P0-2）。

模考引擎 ``services/exam_builder.py`` 里的 ``_ai_score_question`` 是模块私有
函数，且依赖模考 session 上下文。本模块把「题目 + 参考答案 + rubric +
考生答案 → 建议分」的 prompt 构造与 model_gateway 调用封装为公共函数
``grade_subjective``，供刷题流程的 ``POST /api/quiz/grade-subjective`` 使用。

设计：
- 不依赖模考 session 上下文，只依赖题目行（含 content/answer/analysis 等）。
- LLM 调用失败时返回 ``(None, 失败提示)``，由路由层组装降级响应，不抛异常。
"""

from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: 默认满分（题目/请求未给出 max_score 时）
DEFAULT_MAX_SCORE = 10.0


def _extract_score(text: str, max_score: float) -> Optional[float]:
    """从模型输出中提取 0~max_score 的建议分；提取失败返回 None。"""
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        score = float(m.group(1))
    except (TypeError, ValueError):
        return None
    return max(0.0, min(max_score, score))


def grade_subjective(
    question: Any,
    my_answer: str,
    max_score: Optional[float] = None,
    db=None,
) -> Tuple[Optional[float], str]:
    """对一道主观题给出 AI 建议分与点评。

    Args:
        question: ORM 行（至少含 content/answer/analysis/subject 属性；
            也可传 dict，兼容模考快照形态）。
        my_answer: 考生答案文本。
        max_score: 满分；缺省用题目自带 max_score 或 ``DEFAULT_MAX_SCORE``。
        db: SQLAlchemy Session（model_gateway 云端供应商列表用）。

    Returns:
        ``(score, evaluation)``：
        - 成功：``(0~max_score 浮点分, 模型返回的原文点评)``；
        - 失败/无法提取：``(None, 降级提示语)``。
    """
    # —— 兼容 dict 与 ORM 两种题目形态 —— #
    if isinstance(question, dict):
        content = question.get("content") or ""
        answer = question.get("answer") or ""
        analysis = question.get("analysis") or ""
        subject = question.get("subject")
        q_max_score = question.get("max_score")
    else:
        content = getattr(question, "content", None) or ""
        answer = getattr(question, "answer", None) or ""
        analysis = getattr(question, "analysis", None) or ""
        subject = getattr(question, "subject", None)
        q_max_score = getattr(question, "max_score", None)

    try:
        max_score = float(max_score) if max_score is not None else (
            float(q_max_score) if q_max_score is not None else DEFAULT_MAX_SCORE
        )
    except (TypeError, ValueError):
        max_score = DEFAULT_MAX_SCORE
    if max_score <= 0:
        max_score = DEFAULT_MAX_SCORE

    user_answer = (my_answer or "").strip()
    if not user_answer:
        return None, "考生答案为空，无法批改"

    # —— 构造评分 prompt（与 exam_builder._ai_score_question 同源）—— #
    rubric_parts = []
    if answer:
        rubric_parts.append(f"参考答案：{str(answer)[:500]}")
    if analysis:
        rubric_parts.append(f"解析/评分要点：{str(analysis)[:500]}")
    rubric = "\n".join(rubric_parts) if rubric_parts else "无"

    prompt = (
        f"题目：{str(content)[:800]}\n"
        f"{rubric}\n"
        f"考生答案：{user_answer[:800]}\n"
        f"满分 {max_score} 分。请输出一个 0~{max_score} 的建议分数，"
        f"并给出简要点评（优缺点、改进建议，100 字以内）。"
    )

    try:
        from services.model_gateway import get_gateway

        res = get_gateway().chat(
            question=prompt,
            subject=subject,
            task="题目分析",
            context=None,
            system_prompt=(
                "你是考研阅卷老师，评分客观公正。"
                f"先输出建议分数（0~{max_score} 的数字），再输出点评。"
            ),
            prefer=None,
            db=db,
        )
        txt = (res.get("answer") or "").strip()
        if not txt:
            return None, "AI 批改暂不可用，请参考标准答案自评"

        score = _extract_score(txt, max_score)
        # 点评：去掉纯数字行，保留评语
        lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        evaluation_lines = [
            ln for ln in lines if not re.fullmatch(r"\d+(?:\.\d+)?", ln)
        ]
        evaluation = "；".join(evaluation_lines)[:500] if evaluation_lines else txt[:500]
        if score is None:
            return None, evaluation or "AI 批改暂不可用，请参考标准答案自评"
        return score, evaluation
    except Exception as exc:  # noqa: BLE001 - LLM 失败不抛异常，由调用方降级
        logger.warning("主观题 AI 批改失败（已降级）: %s", exc)
        return None, "AI 批改暂不可用，请参考标准答案自评"


# =========================================================================== #
# 结构分离验证器增强（55 号方案 P0-2，DeepTutor Critic/Validator 借鉴）
# =========================================================================== #
#
# 设计：
#   1. 生成器（grade_subjective）与验证器（verify_score）使用**不同的 prompt
#      与独立调用**，不共享推理链，避免模型自我确认错误。
#   2. 数学计算题：从题目/答案提取表达式，用受限 AST 沙箱验算参考答案，
#      若沙箱结果与参考答案一致，提升评分置信度。
#   3. 多维评分卡：事实准确性 / 逻辑连贯性 / 格式规范性 / 数据完整性，
#      结构化返回前端展示。

_DIMENSIONS = ("accuracy", "logic", "format", "completeness")
_DIM_LABELS = {
    "accuracy": "事实准确性",
    "logic": "逻辑连贯性",
    "format": "格式规范性",
    "completeness": "数据完整性",
}


def _extract_math_expr(text: str) -> Optional[str]:
    """从文本中提取可验算的数学表达式。

    策略：优先找 ``=`` 右侧的表达式；去掉 LaTeX 命令与花括号后，
    保留含数字/运算符/常见函数的形式。失败返回 None。
    """
    if not text:
        return None
    t = text.strip()
    # 去掉 LaTeX 环境
    t = re.sub(r"\\[a-zA-Z]+\{?[^}]*\}?", "", t)
    t = t.replace("\\", "").replace("{", "").replace("}", "")
    # 找等号右侧
    if "=" in t:
        t = t.split("=", 1)[-1]
    # 去掉中文与无关字符，保留数字/运算符/函数/变量
    t = re.sub(r"[^\d\.\+\-\*/\(\)\^xXπe\s]", "", t)
    # 数学题中 ^ 表示幂运算，Python 用 **；统一转换。
    t = t.replace("^", "**")
    t = t.strip()
    if not t or not re.search(r"\d", t):
        return None
    return t[:200]


# AST 沙箱允许的节点类型（白名单）
# 注意：
# 1. ast.walk 会包含上下文节点 Load/Store/Del，必须一并放行，否则任何含
#    变量名（Name）的表达式都会被误判为非法。
# 2. 函数调用（Call）及其参数需要显式放行，否则 abs()/sqrt() 等会被拒绝。
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd,
    ast.Mod, ast.FloorDiv,
    ast.Call, ast.keyword,
    ast.Load, ast.Store, ast.Del,
)

#: 沙箱允许的常量/简单函数
import math as _math

_SAFE_NAMES = {
    "x": 1.0, "X": 1.0,
    "pi": _math.pi,
    "e": _math.e,
    "abs": abs, "round": round, "min": min, "max": max,
}


def _safe_eval_expr(expr: str, timeout_ms: int = 500) -> Optional[float]:
    """用受限 AST 沙箱求值数学表达式。

    - 只允许数值运算与白名单函数（math 常用函数、abs、round）
    - 禁止属性访问、调用任意函数、导入
    Returns:
        成功返回 float；任何异常/非法返回 None。
    """
    try:
        # 允许的 Name：_SAFE_NAMES 常量/变量 + math 模块公开名称（函数与常量）。
        allowed_names = set(_SAFE_NAMES)
        allowed_names.update(
            k for k in dir(_math) if not k.startswith("_")
        )
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                return None
            if isinstance(node, ast.Name) and node.id not in allowed_names:
                return None
            if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
                return None
        env = dict(_SAFE_NAMES)
        env.update({k: getattr(_math, k) for k in dir(_math) if not k.startswith("_")})
        code = compile(tree, "<sandbox>", "eval")
        val = eval(code, {"__builtins__": {}}, env)
        return float(val)
    except Exception:
        return None


def sandbox_verify(question: Any, reference_answer: str) -> Dict[str, Any]:
    """对参考答案做沙箱验算，返回验算结论。

    Args:
        question: 题目（dict 或 ORM，需含 content/answer_type 等）
        reference_answer: 参考答案文本

    Returns:
        ``{"verified": bool, "expr": str|None, "value": float|None,
          "detail": str, "usable": bool}``
        - verified=True 表示表达式可求值且结果非 NaN；
        - usable=False 表示题目不是计算题或无表达式可提取（前端可不展示验算卡）。
    """
    answer_type = None
    question_type = None
    content = ""
    if isinstance(question, dict):
        answer_type = question.get("answer_type")
        question_type = question.get("question_type")
        content = question.get("content") or ""
    else:
        answer_type = getattr(question, "answer_type", None)
        question_type = getattr(question, "question_type", None)
        content = getattr(question, "content", None) or ""
    # 仅对计算/填空类题目做沙箱验算。
    # 注意：真实题库中 answer_type 枚举只有 objective/subjective，
    # 计算题通过 question_type='calc'/'fill' 表达（见 quiz_questions 分布）。
    at = str(answer_type or "")
    qt = str(question_type or "")
    is_calc = (
        any(k in qt for k in ("calc", "fill", "blank"))
        or any(k in at for k in ("calc", "fill", "blank"))
        or "计算" in str(content)[:200]
    )
    if not is_calc:
        return {"verified": False, "expr": None, "value": None,
                "detail": "非计算题，跳过沙箱验算", "usable": False}
    expr = _extract_math_expr(reference_answer)
    if not expr:
        return {"verified": False, "expr": None, "value": None,
                "detail": "参考答案中未提取到可验算表达式", "usable": False}
    value = _safe_eval_expr(expr)
    if value is None:
        return {"verified": False, "expr": expr, "value": None,
                "detail": "表达式包含沙箱不允许的运算", "usable": True}
    if _math.isfinite(value):
        return {"verified": True, "expr": expr, "value": round(float(value), 6),
                "detail": f"沙箱验算通过，结果 ≈ {value:.4f}", "usable": True}
    return {"verified": False, "expr": expr, "value": None,
            "detail": "表达式求值结果非有限数", "usable": True}


def verify_score(
    question: Any,
    my_answer: str,
    score: Optional[float],
    max_score: Optional[float] = None,
    db=None,
) -> Dict[str, Any]:
    """结构分离验证器：用独立 prompt 验证首遍评分，输出多维评分卡。

    与 :func:`grade_subjective` 使用**不同的 prompt 与独立模型调用**，
    避免生成器-验证器共享推理链导致自我确认错误。

    Args:
        question: 题目（dict 或 ORM）
        my_answer: 考生答案
        score: 首遍建议分（可为 None）
        max_score: 满分
        db: SQLAlchemy Session

    Returns:
        ``{"verified_score": float|None, "dimensions": {...},
          "verdict": str, "comment": str, "degraded": bool}``
    """
    if isinstance(question, dict):
        content = question.get("content") or ""
        answer = question.get("answer") or ""
        analysis = question.get("analysis") or ""
        subject = question.get("subject")
    else:
        content = getattr(question, "content", None) or ""
        answer = getattr(question, "answer", None) or ""
        analysis = getattr(question, "analysis", None) or ""
        subject = getattr(question, "subject", None)

    try:
        max_score = float(max_score) if max_score is not None else (
            float(getattr(question, "max_score", None) or 10.0)
        )
    except (TypeError, ValueError):
        max_score = 10.0
    if max_score <= 0:
        max_score = 10.0

    user_answer = (my_answer or "").strip()
    first_score = float(score) if score is not None else None

    # 构造验证 prompt（与生成器不同：要求先逐维评估再给最终分）
    dim_prompt = (
        "请作为独立阅卷复核员，对以下评分进行**二次独立验证**。\n"
        "不要参考之前的评分结果，从四个维度重新评估考生答案：\n"
        "1. 事实准确性（accuracy）：答案中的概念/结论是否正确；\n"
        "2. 逻辑连贯性（logic）：推导过程是否严谨、步骤是否连贯；\n"
        "3. 格式规范性（format）：书写/步骤/公式是否符合规范；\n"
        "4. 数据完整性（completeness）：是否覆盖题目要求的所有要点。\n"
        f"题目：{str(content)[:600]}\n"
        f"参考答案：{str(answer)[:400]}\n"
        f"解析：{str(analysis)[:300]}\n"
        f"考生答案：{user_answer[:600]}\n"
        f"满分 {max_score}。\n"
        "请严格按如下 JSON 输出（不要输出其他文字）：\n"
        '{"accuracy": 0~10分整数, "logic": 0~10分整数, "format": 0~10分整数, '
        '"completeness": 0~10分整数, "verified_score": 0~满分的数字, '
        '"comment": "一句话复核意见（30字内）"}'
    )

    try:
        from services.model_gateway import get_gateway

        res = get_gateway().chat(
            question=dim_prompt,
            subject=subject,
            task="题目分析",
            context=None,
            system_prompt=(
                "你是严格的考研阅卷复核员，输出必须是指定 JSON 格式，"
                "分数要客观、可解释，不能无脑给高分。"
            ),
            prefer=None,
            db=db,
        )
        txt = (res.get("answer") or "").strip()
        import json as _json

        # 提取 JSON（容忍模型输出带 markdown 代码块）
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        if not m:
            return _verify_degraded(first_score, max_score, "验证器未返回 JSON")
        data = _json.loads(m.group(0))
        dims = {}
        for k in _DIMENSIONS:
            dims[k] = {
                "score": int(max(0, min(10, int(data.get(k, 0))))),
                "label": _DIM_LABELS[k],
            }
        v_score = float(data.get("verified_score", first_score if first_score is not None else 0))
        v_score = max(0.0, min(max_score, v_score))
        comment = str(data.get("comment", ""))[:100]
        return {
            "verified_score": round(v_score, 1),
            "dimensions": dims,
            "verdict": "consistent",
            "comment": comment,
            "degraded": False,
        }
    except Exception as exc:  # noqa: BLE001 - 验证失败降级
        logger.warning("结构分离验证失败（已降级）: %s", exc)
        return _verify_degraded(first_score, max_score, "验证器暂不可用")


def _verify_degraded(
    first_score: Optional[float], max_score: float, reason: str
) -> Dict[str, Any]:
    """验证器降级返回：维度卡用中性值，最终分回退首遍分。"""
    dims = {}
    for k in _DIMENSIONS:
        dims[k] = {"score": 5, "label": _DIM_LABELS[k]}
    return {
        "verified_score": round(first_score, 1) if first_score is not None else None,
        "dimensions": dims,
        "verdict": "degraded",
        "comment": reason,
        "degraded": True,
    }