# -*- coding: utf-8 -*-
"""408 代码合规静态检查（落地方案 §4.5，纯函数·零执行·零沙箱）。

管道：1) 剥离注释与字符串字面量（保留行号）→ 2) token 级匹配。
模式：
- exam（默认）：C 基础库 + C++ 标准子集允许（官方 C++ 视同 C）；
- strict：仅 C 白名单头文件；
- 函数黑名单两模式通用（gets/qsort/bsearch/system/popen/fork/exec*/文件 I/O）。
输出 grade=hard_fact 的 ComplianceReport（EvidenceRecord 对齐）。
误报红线：注释/字符串里的违禁词一律不算违规（先剥离再匹配保证）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from kernel.config_loader import ComplianceConfig

MODE_EXAM = "exam"
MODE_STRICT = "strict"

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[">]')
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Violation:
    line: int            # 1-based 源码行号
    token: str           # 命中的标识符/头文件名
    rule: str            # banned_function | file_io | header_not_allowed
    reason: str


@dataclass(frozen=True)
class ComplianceReport:
    mode: str
    violations: Tuple[Violation, ...]
    grade: str = "hard_fact"     # 确定性硬事实层（总方案 §6.4）
    compliant: bool = True

    def to_dict(self) -> Dict:
        return {
            "mode": self.mode,
            "compliant": self.compliant,
            "grade": self.grade,
            "violations": [
                {"line": v.line, "token": v.token, "rule": v.rule,
                 "reason": v.reason}
                for v in self.violations
            ],
        }


def strip_comments_and_strings(source: str) -> str:
    """把 // 注释、/* */ 注释、字符串/字符字面量内容替换为空格（保留换行与行号）。

    注意处理：转义引号 \\" 、跨行块注释、单引号字符常量（含 '\\' 与 '\''）。
    """
    out: List[str] = []
    i, n = 0, len(source)
    state = "code"       # code | line_comment | block_comment | string | char
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                state = "line_comment"
                out.append("  ")
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block_comment"
                out.append("  ")
                i += 2
                continue
            if c == '"':
                state = "string"
                out.append('"')
                i += 1
                continue
            if c == "'":
                state = "char"
                out.append("'")
                i += 1
                continue
            out.append(c)
            i += 1
            continue
        if state == "line_comment":
            if c == "\n":
                state = "code"
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue
        if state == "block_comment":
            if c == "*" and nxt == "/":
                state = "code"
                out.append("  ")
                i += 2
                continue
            out.append("\n" if c == "\n" else " ")
            i += 1
            continue
        # string / char
        quote = '"' if state == "string" else "'"
        if c == "\\" and i + 1 < n:
            out.append("  ")
            i += 2
            continue
        if c == quote:
            state = "code"
            out.append(quote)
            i += 1
            continue
        out.append("\n" if c == "\n" else " ")   # 字符串内换行理论上非法，保守保留行号
        i += 1
    return "".join(out)


def check(source: str, cfg: ComplianceConfig, mode: str = MODE_EXAM) -> ComplianceReport:
    """对提交源码做合规静态检查。

    Args:
        source: 原始 C/C++ 代码文本。
        cfg: 冻结白/黑名单配置。
        mode: exam | strict；其它值显式报错（不静默降级）。
    """
    if mode not in (MODE_EXAM, MODE_STRICT):
        raise ValueError(f"未知合规模式: {mode!r}（可用: exam|strict）")
    clean = strip_comments_and_strings(source)
    allowed_headers = set(cfg.c_whitelist_headers)
    if mode == MODE_EXAM:
        allowed_headers |= set(cfg.cpp_subset_headers)
    banned = set(cfg.banned_functions)
    file_io = set(cfg.file_io_functions)

    violations: List[Violation] = []
    lines = clean.splitlines()

    # 1) 头文件检查
    for idx, line in enumerate(lines, start=1):
        m = _INCLUDE_RE.match(line)
        if not m:
            continue
        header = m.group(1).strip()
        if header not in allowed_headers:
            why = ("不在 C 白名单（strict 模式不允许 C++ 头）"
                   if mode == MODE_STRICT else
                   "不在 C 基础库/C++ 标准子集白名单")
            violations.append(Violation(idx, header, "header_not_allowed",
                                        f"#include <{header}> {why}"))

    # 2) 函数调用 token 检查（exec* 前缀匹配；其余精确匹配）
    for idx, line in enumerate(lines, start=1):
        for tok_m in _IDENT_RE.finditer(line):
            tok = tok_m.group(0)
            # 排除声明流名 stdin/stdout/stderr
            if tok in cfg.allowed_streams:
                continue
            # include 行已在上面处理，避免把 stdio 之类宏名重复计
            if _INCLUDE_RE.match(line):
                continue
            if tok in banned or tok.startswith("exec"):
                if tok.startswith("exec") and tok != "exec" and not re.match(
                        r"^exec[lv][ep]*$", tok):
                    continue
                violations.append(Violation(idx, tok, "banned_function",
                                            f"{tok}() 为考场禁用函数（考点要求手写/安全原因）"))
            elif tok in file_io:
                violations.append(Violation(idx, tok, "file_io",
                                            f"{tok}() 属文件 I/O，考试禁止（stdin/stdout/stderr 除外）"))

    # 去重（同一行同一 token 只报一次），保持稳定顺序
    seen = set()
    uniq: List[Violation] = []
    for v in sorted(violations, key=lambda x: (x.line, x.token, x.rule)):
        k = (v.line, v.token, v.rule)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(v)
    return ComplianceReport(mode=mode, violations=tuple(uniq),
                            grade="hard_fact", compliant=not uniq)
