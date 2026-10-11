# -*- coding: utf-8 -*-
"""
A2 公式识别服务（services/formula_service.py）
================================================
VLM + MathFormula2Tex 改造版强约束 prompt → LaTeX → 编译校验。
仅借鉴 MathFormula2Tex 思路，prompt 为考研版自研实现。

双通道：
  - 全页文本 OCR 由现有 ocr_router 保留（不动）
  - 本服务只处理公式区：detect_formula_regions 启发式检测
    （孤立符号密度 / 高度错落 / 置信度低）→ crop → VLM → LaTeX

LaTeX 编译校验：优先 tectonic / xelatex（探测系统可用编译器），
失败回退检查（括号配对 / 环境闭合），输出校验状态与 [待核对] 标记计数。

接口：recognize_formula(image_path) -> {latex, validated, compile_ok, pending_flags, error}
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# 强约束 prompt（MathFormula2Tex system_prompt 改造版，考研版）
# --------------------------------------------------------------------------- #
FORMULA_SYSTEM_PROMPT = """\
你是考研数学/电子技术题目的 LaTeX 转写工程师。
你的任务是将图片中的公式与题目转换为符合指定规范的 LaTeX 代码。
你不进行解释。/ 你不输出 Markdown。/ 你只输出纯 LaTeX。
如果规则与常规排版冲突，以规则为准。

# 1. 数学环境规范（直接消灭工程符号乱码）
1.1 行内公式统一 \\( ... \\)，禁止使用 $...$
1.2 独立成行公式用 \\[ ... \\]
1.3 填空横线用 \\underline{\\quad\\quad}，禁止裸 \\_\\_
1.4 题间距用宏 \\ltwo，小问间距用 \\lfive

# 2. 视觉模型转写错误防控清单（逐项自检）
2.1 形近字符：1/l/I、0/O、5/S、8/B、2/Z
2.2 运算符：±/∓、·/×/⋅、≤/≥、×/✗、→/↔
2.3 希腊字母：α/λ、β/ϐ、θ/ϑ、μ/µ、ω/Ω
2.4 求和/连乘/积分/微分：∑/∏、∫/∮、∂/δ、d/∂
2.5 分式与指数的大括号配对；根号覆盖范围；上下标归属
2.6 电路符号：R/C/L/D/Q/M，↑↓ 箭头，⊥ 接地，⏚

# 3. 考研题型排版规范
3.1 单选：\\item 题干（\\quad）+\\begin{enumerate}\\item[A.] ...
3.2 多选：题干后标注"（多选）"
3.3 填空：\\item ... = \\underline{\\quad\\quad} .
3.4 解答/小问：\\item + \\begin{enumerate}\\item[(1)] ...
3.5 题号由 LaTeX 自动生成，不使用图片中的题号

# 4. 严格禁止事项
不解题；不写答案；不添加解析；不改动题意；不优化题目语言；
不补充额外内容；不增加视觉装饰；只输出插入后的 LaTeX 代码块或修改片段

# 5. 不确定性处理
任何无法确定的符号，输出 \\text{[待核对:...]} 标记，禁止猜测。
"""

FORMULA_USER_PROMPT = (
    "请将图片中的公式/题目区域转写为 LaTeX。仅输出 LaTeX 代码，"
    "不确定处使用 [待核对:原因] 标记。"
)

_PENDING_RE = re.compile(r"\[待核对[^\]]*\]")
# 公式环境成对检查
_ENV_PAIRS = {
    r"\(": r"\)",
    r"\[": r"\]",
    r"\begin{enumerate}": r"\end{enumerate}",
    r"\begin{cases}": r"\end{cases}",
    r"\begin{aligned}": r"\end{aligned}",
    r"\begin{array}": r"\end{array}",
    r"\begin{frac}": r"\end{frac}",
    r"\frac{": r"}",
}


# --------------------------------------------------------------------------- #
# LaTeX 编译校验
# --------------------------------------------------------------------------- #
def _find_compiler() -> Optional[str]:
    """探测系统可用 LaTeX 编译器：tectonic > xelatex > pdflatex。"""
    for name in ("tectonic", "xelatex", "pdflatex"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _balance_check(latex: str) -> List[str]:
    """失败回退检查：括号/环境配对粗检。"""
    problems: List[str] = []
    if latex.count(r"\(") != latex.count(r"\)"):
        problems.append("行内公式 \\(...\\) 未配对")
    if latex.count(r"\[") != latex.count(r"\]"):
        problems.append("独立公式 \\[...\\] 未配对")
    opens = latex.count("{")
    closes = latex.count("}")
    if opens != closes:
        problems.append(f"花括号不配对: {{ {opens} / }} {closes}")
    for beg, end in (("\\begin{enumerate}", "\\end{enumerate}"),
                     ("\\begin{cases}", "\\end{cases}"),
                     ("\\begin{aligned}", "\\end{aligned}"),
                     ("\\begin{array}", "\\end{array}")):
        if latex.count(beg) != latex.count(end):
            problems.append(f"环境 {beg} / {end} 未闭合")
    return problems


def validate_latex(latex: str) -> Dict[str, Any]:
    """LaTeX 编译校验：优先真实编译，失败回退结构检查。

    Returns:
        {"compile_ok": bool, "compiler": str|None, "validator": "compiler"|"fallback",
         "problems": [...], "pending_flags": int}
    """
    latex = (latex or "").strip()
    pending_flags = len(_PENDING_RE.findall(latex))
    if not latex:
        return {"compile_ok": False, "compiler": None, "validator": "fallback",
                "problems": ["空 LaTeX"], "pending_flags": 0}

    compiler = _find_compiler()
    if compiler:
        try:
            with tempfile.TemporaryDirectory(prefix="formula_val_") as td:
                tex_path = os.path.join(td, "doc.tex")
                tex = (
                    "\\documentclass{article}\n"
                    "\\usepackage{amsmath,amssymb}\n"
                    "\\usepackage{geometry}\\geometry{margin=1cm}\n"
                    "\\newcommand{\\ltwo}{\\vspace{2em}}\n"
                    "\\newcommand{\\lfive}{\\vspace{0.5em}}\n"
                    "\\pagestyle{empty}\n"
                    "\\begin{document}\n"
                    f"{latex}\n"
                    "\\end{document}\n"
                )
                with open(tex_path, "w", encoding="utf-8") as f:
                    f.write(tex)
                if "tectonic" in compiler:
                    proc = subprocess.run(
                        [compiler, "--keep-logs", tex_path],
                        capture_output=True, text=True, timeout=120,
                    )
                else:
                    proc = subprocess.run(
                        [compiler, "-interaction=nonstopmode", "-halt-on-error", tex_path],
                        capture_output=True, text=True, timeout=120,
                    )
                ok = proc.returncode == 0
                problems = [] if ok else [line.strip() for line in (proc.stderr or proc.stdout or "").splitlines() if line.strip()][-5:]
                return {"compile_ok": ok, "compiler": os.path.basename(compiler),
                        "validator": "compiler", "problems": problems,
                        "pending_flags": pending_flags}
        except Exception as e:
            pass  # 编译失败回退检查

    problems = _balance_check(latex)
    return {"compile_ok": len(problems) == 0, "compiler": None,
            "validator": "fallback", "problems": problems,
            "pending_flags": pending_flags}


# --------------------------------------------------------------------------- #
# 公式区启发式检测（轻量，不替换 ocr_router）
# --------------------------------------------------------------------------- #
_MATH_SYMBOLS = set("∫∑∏√≤≥λθμπ∞±×÷∂∇∈∀∃∧∨→↔≡≅≈≠⋅")


def detect_formula_regions(ocr_text: str) -> Dict[str, Any]:
    """启发式判断文本是否含公式区。

    启发式：孤立符号密度 / 高度错落（上下标特征）/ 置信度低（乱码比例）。
    返回 {"is_formula": bool, "reason": str, "symbol_density": float}
    """
    text = (ocr_text or "").strip()
    if not text:
        return {"is_formula": False, "reason": "empty", "symbol_density": 0.0}
    total = len(text)
    sym_count = sum(1 for ch in text if ch in _MATH_SYMBOLS)
    density = sym_count / max(total, 1)
    # 上下标/错落特征：数字字母混合 + 大量运算符
    op_count = len(re.findall(r"[=+*/−()\[\],.。:;]", text))
    height_hint = len(re.findall(r"[A-Za-z0-9]\^|_[A-Za-z0-9{]", text)) > 0
    if density >= 0.06 or (op_count >= 6 and density >= 0.02) or height_hint:
        return {"is_formula": True, "reason": "symbol_density_or_layout",
                "symbol_density": round(density, 4)}
    return {"is_formula": False, "reason": "plain_text", "symbol_density": round(density, 4)}


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def recognize_formula(
    image_path: str,
    *,
    prefer: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """公式区识别：OCR 启发式检测 → VLM 强约束 prompt → LaTeX → 编译校验。

    Args:
        image_path: 图片绝对路径
        prefer: local / cloud / None(auto)
        db: SQLAlchemy Session（透传 model_gateway）

    Returns:
        {latex, validated, compile_ok, pending_flags, error, engine, provider, model}
    """
    if not image_path or not os.path.exists(image_path):
        return {"latex": "", "validated": False, "compile_ok": False,
                "pending_flags": 0, "error": "图片不存在"}
    try:
        # 1) 全页 OCR（复用 ocr_router，仅用于公式区检测，不返回给用户做全文）
        from services.ocr_router import recognize_file

        ocr = recognize_file(image_path, prefer=prefer)
        ocr_text = getattr(ocr, "text", "") or ""
        region = detect_formula_regions(ocr_text)
        if not region["is_formula"]:
            # 仍尝试转写，但标记可能非公式区
            pass

        # 2) VLM 强约束转写
        from services.model_gateway import get_gateway

        gateway = get_gateway()
        result = gateway.chat(
            question=FORMULA_USER_PROMPT,
            subject="数学",
            task="公式识别",
            context=f"OCR 辅助文本（仅供参考，请以图片为准）：{ocr_text[:500]}",
            system_prompt=FORMULA_SYSTEM_PROMPT,
            prefer=prefer,
            db=db,
        )
        raw = result.get("answer", "") or ""
        # 去除 ```latex 围栏
        latex = re.sub(r"```(?:latex|tex)?\s*", "", raw).strip()
        latex = re.sub(r"```", "", latex).strip()
        if not latex:
            return {"latex": "", "validated": False, "compile_ok": False,
                    "pending_flags": 0, "error": "模型未返回 LaTeX",
                    "engine": result.get("engine"), "provider": result.get("provider"),
                    "model": result.get("model")}

        # 3) 编译校验
        val = validate_latex(latex)
        return {
            "latex": latex,
            "validated": val["compile_ok"],
            "compile_ok": val["compile_ok"],
            "compiler": val.get("compiler"),
            "validator": val.get("validator"),
            "problems": val.get("problems", []),
            "pending_flags": val.get("pending_flags", 0),
            "formula_region": region,
            "error": None,
            "engine": result.get("engine", ""),
            "provider": result.get("provider", ""),
            "model": result.get("model", ""),
        }
    except Exception as e:
        return {"latex": "", "validated": False, "compile_ok": False,
                "pending_flags": 0, "error": str(e)}


def batch_recognize(image_paths: List[str], prefer: Optional[str] = None, db=None) -> List[Dict[str, Any]]:
    """批量公式识别。"""
    return [recognize_formula(p, prefer=prefer, db=db) for p in image_paths]


if __name__ == "__main__":  # pragma: no cover
    import sys

    sample = r"\(\int_0^1 x^2 dx = \frac{1}{3}\)"
    print(json.dumps(validate_latex(sample), ensure_ascii=False, indent=2))
    print(json.dumps(detect_formula_regions("求积分 ∫(0,1) x^2 dx"), ensure_ascii=False, indent=2))
