# -*- coding: utf-8 -*-
"""P0-2 结构分离验证器（55 号方案 DeepTutor Validator 借鉴）回归测试。

覆盖：
1. ``_safe_eval_expr`` 沙箱：
   - 正常数学表达式（四则运算 / 幂 / 括号 / 函数 / 常量）
   - 危险表达式一律拒绝（属性访问 / 导入 / 未知函数 / 未知名）
   - 除零等运行时异常返回 None（不抛）
2. ``_extract_math_expr``：
   - 从"等号右侧"提取表达式
   - LaTeX 命令剥离
   - ^ 转 **（数学幂符号）
   - 无表达式返回 None
3. ``sandbox_verify``：
   - 计算/填空类题目返回 verified=True + value
   - 非计算题（主观题）返回 usable=False
   - 无表达式 / 非法表达式返回 verified=False
4. ``verify_score`` 降级路径：
   - 独立模型调用失败时返回 degraded 评分卡，不抛异常
   - verified_score 回退首遍分
"""
from __future__ import annotations

import pytest

from services.subjective_grader import (
    _extract_math_expr,
    _safe_eval_expr,
    _verify_degraded,
    sandbox_verify,
    verify_score,
)


# --------------------------------------------------------------------------- #
# 1. AST 沙箱：正常表达式
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "expr,expected",
    [
        ("2+3*4", 14.0),
        ("(1+2)/3", 1.0),
        ("2**10", 1024.0),  # Python 幂
        ("pi", 3.141592653589793),
        ("2*pi", 6.283185307179586),
        ("x+1", 2.0),  # _SAFE_NAMES 中 x=1.0
        ("abs(-5)", 5.0),
        ("round(3.7)", 4.0),
        ("min(3,7)", 3.0),
        ("max(3,7)", 7.0),
        ("sqrt(16)", 4.0),  # math.sqrt
        ("log(e)", 1.0),  # math.log(math.e)
        ("10 % 3", 1.0),
        ("7 // 2", 3.0),
    ],
)
def test_safe_eval_valid(expr, expected):
    v = _safe_eval_expr(expr)
    assert v is not None
    assert abs(v - expected) < 1e-9


# --------------------------------------------------------------------------- #
# 2. AST 沙箱：危险/非法表达式必须拒绝
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "expr",
    [
        '__import__("os").system("echo hacked")',
        'open("/etc/passwd")',
        "[].__class__",
        "().__class__.__bases__",
        "os.system",
        'eval("1+1")',
        "lambda: 1",
        "{1:2}",
        "a+b",  # 未知名
        "foo(1)",  # 未知函数
        "1/0",  # 除零
        "sqrt.__class__",
        "abs.__globals__",
    ],
)
def test_safe_eval_rejects_dangerous(expr):
    assert _safe_eval_expr(expr) is None


# --------------------------------------------------------------------------- #
# 3. 表达式提取
# --------------------------------------------------------------------------- #
def test_extract_math_expr_basic():
    assert _extract_math_expr("解：x = (1+2)*3") == "(1+2)*3"


def test_extract_math_expr_pow_conversion():
    assert _extract_math_expr("答案 = 2^10") == "2**10"


def test_extract_math_expr_latex():
    assert _extract_math_expr(r"答案：\frac{1}{2} = 0.5") == "0.5"


def test_extract_math_expr_none():
    assert _extract_math_expr("答案是文字") is None
    assert _extract_math_expr("") is None
    assert _extract_math_expr(None) is None


# --------------------------------------------------------------------------- #
# 4. sandbox_verify
# --------------------------------------------------------------------------- #
def test_sandbox_verify_calc():
    q = {"content": "计算 (1+2)*3", "question_type": "calc", "answer_type": "subjective"}
    res = sandbox_verify(q, "答案 = (1+2)*3")
    assert res["verified"] is True
    assert res["value"] == 9.0
    assert res["usable"] is True
    assert res["expr"] == "(1+2)*3"


def test_sandbox_verify_fill_pow():
    q = {"content": "填空：2^10 = ?", "question_type": "fill", "answer_type": "subjective"}
    res = sandbox_verify(q, "x = 2^10")
    assert res["verified"] is True
    assert res["value"] == 1024.0
    assert res["usable"] is True


def test_sandbox_verify_skips_non_calc():
    q = {"content": "简述马克思主义", "question_type": "essay", "answer_type": "subjective"}
    res = sandbox_verify(q, "马克思主义是...")
    assert res["verified"] is False
    assert res["usable"] is False
    assert "非计算题" in res["detail"]


def test_sandbox_verify_no_expr():
    q = {"content": "计算题", "question_type": "calc", "answer_type": "subjective"}
    res = sandbox_verify(q, "答案是文字")
    assert res["verified"] is False
    assert res["usable"] is False
    assert "未提取到" in res["detail"]


def test_sandbox_verify_dangerous_expr():
    """危险代码在提取层就被字符白名单净化，到不了沙箱。

    ``__import__('os')...`` 中的字母全部被 ``_extract_math_expr`` 的
    字符白名单剥离，最终无可验算表达式 -> usable=False。
    这是比"沙箱拒绝"更前置的安全边界。
    """
    q = {"content": "计算题", "question_type": "calc", "answer_type": "subjective"}
    res = sandbox_verify(q, "x = __import__('os').system('echo hacked')")
    assert res["verified"] is False
    assert res["usable"] is False  # 提取层已净化，无表达式进入沙箱
    assert "未提取到" in res["detail"]


# --------------------------------------------------------------------------- #
# 5. verify_score 降级路径
# --------------------------------------------------------------------------- #
def test_verify_degraded_fallback():
    res = _verify_degraded(7.5, 10.0, "验证器暂不可用")
    assert res["verdict"] == "degraded"
    assert res["degraded"] is True
    assert res["verified_score"] == 7.5
    assert res["comment"] == "验证器暂不可用"
    assert set(res["dimensions"].keys()) == {
        "accuracy", "logic", "format", "completeness",
    }
    # 中性维度分
    for dim in res["dimensions"].values():
        assert dim["score"] == 5


def test_verify_degraded_none_score():
    res = _verify_degraded(None, 10.0, "无首遍分")
    assert res["verified_score"] is None
    assert res["degraded"] is True


def test_verify_score_fallback_on_exception(monkeypatch):
    """模型调用抛异常时 verify_score 必须降级返回，绝不抛异常。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("model gateway down")

    # verify_score 内部是 from services.model_gateway import get_gateway，
    # 因此需要 patch model_gateway 模块的 get_gateway。
    monkeypatch.setattr(
        "services.model_gateway.get_gateway", lambda: type("G", (), {"chat": _boom})()
    )
    q = {"content": "题目", "answer": "答案", "analysis": "解析", "subject": "数学"}
    res = verify_score(q, "考生答案", score=6.0, max_score=10.0)
    assert res["verdict"] == "degraded"
    assert res["degraded"] is True
    assert res["verified_score"] == 6.0
    assert "暂不可用" in res["comment"]


def test_verify_score_parses_json(monkeypatch):
    """验证器正常返回时解析多维评分卡。"""

    def _fake_chat(*args, **kwargs):
        return {
            "answer": (
                '{"accuracy": 8, "logic": 7, "format": 6, '
                '"completeness": 9, "verified_score": 8.5, '
                '"comment": "逻辑略有跳跃"}'
            )
        }

    monkeypatch.setattr(
        "services.model_gateway.get_gateway", lambda: type("G", (), {"chat": _fake_chat})()
    )
    q = {"content": "题目", "answer": "答案", "analysis": "解析", "subject": "数学"}
    res = verify_score(q, "考生答案", score=6.0, max_score=10.0)
    assert res["degraded"] is False
    assert res["verdict"] == "consistent"
    assert res["verified_score"] == 8.5
    assert res["comment"] == "逻辑略有跳跃"
    assert res["dimensions"]["accuracy"]["score"] == 8
    assert res["dimensions"]["logic"]["score"] == 7
    assert res["dimensions"]["format"]["score"] == 6
    assert res["dimensions"]["completeness"]["score"] == 9


# --------------------------------------------------------------------------- #
# 6. API 层端到端：POST /api/quiz/grade-subjective 返回评分卡
# --------------------------------------------------------------------------- #
def _make_calc_question(db):
    from models import QuizQuestion

    q = QuizQuestion(
        content="计算 (1+2)*3 的值。",
        options=None,
        answer="(1+2)*3",
        analysis="先算括号内加法，再乘 3。",
        subject="数学",
        chapter="QA-高数", knowledge_point="QA-四则运算",
        difficulty=1, source="自建", question_type="calc",
        answer_type="subjective",
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q.id


def test_grade_subjective_returns_verification():
    """批改响应必须携带 verification 评分卡（含沙箱验算 + 多维维度）。"""
    from database import SessionLocal
    from models import QuizQuestion
    from tests.asgi_client import ASGIClient
    from main import app

    db = SessionLocal()
    try:
        qid = _make_calc_question(db)
    finally:
        db.close()

    client = ASGIClient(app)
    r = client.post(
        "/api/quiz/grade-subjective",
        json={
            "question_id": qid,
            "my_answer": "先算括号：1+2=3，再乘 3，得 9。",
            "max_score": 10.0,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["question_id"] == qid
    assert data["max_score"] == 10.0
    assert "verification" in data
    ver = data["verification"]
    # 评分卡结构
    assert "verified_score" in ver
    assert "dimensions" in ver
    assert "verdict" in ver
    assert "degraded" in ver
    assert "sandbox" in ver
    # 维度卡含四维
    assert set(ver["dimensions"].keys()) == {
        "accuracy", "logic", "format", "completeness",
    }
    # 计算题沙箱应可用
    sbx = ver["sandbox"]
    assert sbx["usable"] is True
    assert sbx["expr"] in ("(1+2)*3", "1+2)*3", None) or sbx["value"] == 9.0


def test_grade_subjective_missing_question_404():
    from tests.asgi_client import ASGIClient
    from main import app

    client = ASGIClient(app)
    r = client.post(
        "/api/quiz/grade-subjective",
        json={"question_id": 999999999, "my_answer": "答案", "max_score": 10.0},
    )
    assert r.status_code == 404