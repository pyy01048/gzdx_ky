# -*- coding: utf-8 -*-
"""
P2-M5 代码上机 OJ：轻量级判题引擎

⚠️ 警告：此为开发/测试环境的简化实现，仅支持 Python 且无沙箱隔离。
生产环境必须替换为基于 Docker/Podman 的安全沙箱执行器。

2026-10-25 安全加固（P0）：
- 默认关闭判题服务（环境变量 CODE_JUDGE_ENABLED=1 才启用），
  公网部署在接入 go-judge 沙箱前不执行用户代码；
- 静态危险代码检测（禁止 os/sys/subprocess/socket 等危险模块与
  eval/exec/compile/open/__import__ 等危险调用）；
- POSIX 下通过 resource 限制 CPU/内存/进程数/文件数；
- 用户代码在独立临时目录运行，不共享项目文件。

支持的判题状态：
- AC (Accepted): 答案正确
- WA (Wrong Answer): 答案错误
- TLE (Time Limit Exceeded): 超时
- MLE (Memory Limit Exceeded): 超内存（暂未实现）
- CE (Compilation Error): 编译错误（Python 无编译阶段，跳过）
- RE (Runtime Error): 运行时错误
- SE (System Error): 系统错误
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 判题状态常量
STATUS_AC = "ac"
STATUS_WA = "wa"
STATUS_TLE = "tle"
STATUS_MLE = "mle"
STATUS_CE = "ce"
STATUS_RE = "re"
STATUS_SE = "se"

# 安全开关：公网部署未接入 go-judge 沙箱前默认关闭判题执行
CODE_JUDGE_ENABLED = os.getenv("CODE_JUDGE_ENABLED", "0") == "1"

# 危险模块（静态检测，命中即拒绝执行）
_BLOCKED_IMPORTS = (
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "importlib",
    "ctypes", "pickle", "pty", "fcntl", "multiprocessing", "threading",
    "signal", "resource", "platform", "tempfile", "shlex", "builtins",
    "inspect", "traceback", "pdb", "code", "codeop", "runpy", "pkgutil",
    "site", "requests", "urllib", "http", "ftplib", "smtplib", "telnetlib",
    "ssl", "asyncio", "aiohttp", "webbrowser", "xmlrpc", "jsonpickle",
)

# 危险调用（静态检测，命中即拒绝执行）
_BLOCKED_CALL_RE = re.compile(
    r"\b(__import__|eval|exec|compile|open|breakpoint|__builtins__|"
    r"__subclasses__|__bases__|__mro__|getattr|setattr|delattr|globals|locals|vars)\s*\("
)
_BLOCKED_ATTR_RE = re.compile(r"\b(os|sys|subprocess|socket|shutil|pathlib)\.[A-Za-z_]")


def _check_unsafe_code(code: str) -> Optional[str]:
    """静态检测危险代码。返回错误消息，合法返回 None。

    注意：这是过渡性加固，不是完整沙箱；恶意代码仍可能通过编码/混淆绕过。
    公网上线前必须替换为 go-judge / Docker 沙箱。
    """
    # 逐行检查 import（支持 import os / from os import xxx / import os.path）
    for lineno, line in enumerate(code.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # import os / import os.path / import os as o
        m = re.match(r"^import\s+([A-Za-z_][A-Za-z0-9_]*)", s)
        if m:
            mod = m.group(1)
            if mod in _BLOCKED_IMPORTS:
                return f"代码包含被禁止的模块 '{mod}'（第 {lineno} 行）"
        # from os import ... / from os.path import ...
        m = re.match(r"^from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import", s)
        if m:
            mod = m.group(1).split(".")[0]
            if mod in _BLOCKED_IMPORTS:
                return f"代码包含被禁止的模块 '{mod}'（第 {lineno} 行）"

    if _BLOCKED_CALL_RE.search(code):
        return "代码包含被禁止的危险调用（eval/exec/open/__import__ 等）"
    if _BLOCKED_ATTR_RE.search(code):
        return "代码包含被禁止的危险模块访问（os./sys./subprocess. 等）"
    return None


def _posix_limits():
    """POSIX 下设置子进程资源限制（CPU/内存/进程数/文件数）。"""
    try:
        import resource

        def _apply_limits():
            resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
            resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
        return _apply_limits
    except Exception:
        return None


def judge_python_code(
    code: str,
    testcases: List[Dict[str, str]],
    time_limit_ms: int = 1000,
    memory_limit_kb: int = 256000,
) -> Dict[str, Any]:
    """判 Python 代码（简化版，无沙箱）。

    Args:
        code: 用户提交的 Python 代码
        testcases: 测试用例列表 [{"input": "...", "expected_output": "..."}, ...]
        time_limit_ms: 时限（毫秒）
        memory_limit_kb: 内存限制（KB，暂未强制限制）

    Returns:
        {
            "status": "ac" | "wa" | "tle" | "re" | "se",
            "passed": 通过的测试点数,
            "total": 总测试点数,
            "details": [{"testcase_id": ..., "status": ..., "time_ms": ..., "actual_output": ...}, ...],
            "max_time_ms": 最大耗时,
            "error_message": 错误信息（如有）
        }
    """
    if not CODE_JUDGE_ENABLED:
        return {
            "status": STATUS_SE,
            "passed": 0,
            "total": len(testcases),
            "details": [],
            "max_time_ms": 0,
            "error_message": "判题服务未启用（沙箱部署后开放）",
        }

    # 静态危险代码检测（过渡加固）
    unsafe = _check_unsafe_code(code)
    if unsafe:
        return {
            "status": STATUS_SE,
            "passed": 0,
            "total": len(testcases),
            "details": [],
            "max_time_ms": 0,
            "error_message": unsafe,
        }

    results = []
    passed = 0
    max_time = 0
    compile_error = None

    # 步骤 1：语法检查（模拟编译）
    try:
        compile(code, "<submission>", "exec")
    except SyntaxError as e:
        compile_error = f"SyntaxError: {e.msg} (line {e.lineno})"
        return {
            "status": STATUS_CE,
            "passed": 0,
            "total": len(testcases),
            "details": [],
            "max_time_ms": 0,
            "compile_error": compile_error,
        }

    # 步骤 2：逐测试点执行
    for i, tc in enumerate(testcases):
        testcase_result = _run_single_testcase(code, tc["input"], tc["expected_output"], time_limit_ms)
        results.append(testcase_result)

        if testcase_result["status"] == STATUS_AC:
            passed += 1

        if testcase_result["time_ms"]:
            max_time = max(max_time, testcase_result["time_ms"])

        # 遇到非 AC 立即停止（可选策略）
        if testcase_result["status"] in (STATUS_RE, STATUS_SE):
            break

    # 步骤 3：汇总判定
    if passed == len(testcases):
        overall_status = STATUS_AC
    elif any(r["status"] == STATUS_TLE for r in results):
        overall_status = STATUS_TLE
    elif any(r["status"] == STATUS_RE for r in results):
        overall_status = STATUS_RE
    else:
        overall_status = STATUS_WA

    score = (passed / len(testcases) * 100) if testcases else 0.0

    return {
        "status": overall_status,
        "passed": passed,
        "total": len(testcases),
        "score": round(score, 1),
        "details": results,
        "max_time_ms": max_time,
        "error_message": next((r.get("error_message") for r in results if r.get("error_message")), None),
    }


def _run_single_testcase(
    code: str,
    input_data: str,
    expected_output: str,
    time_limit_ms: int,
) -> Dict[str, Any]:
    """运行单个测试用例。"""
    start_time = time.time()

    try:
        # 创建隔离临时目录（不共享项目文件）与临时文件
        with tempfile.TemporaryDirectory(prefix="oj_", dir=tempfile.gettempdir()) as tmpdir:
            script_path = Path(tmpdir) / "main.py"
            script_path.write_text(code, encoding="utf-8")

            # 执行代码（超时 + 资源限制 + 隔离工作目录）
            time_limit_sec = max(0.5, time_limit_ms / 1000.0)
            env = {
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
                "HOME": tmpdir,
            }
            preexec = _posix_limits() if os.name == "posix" else None
            result = subprocess.run(
                [sys.executable, "-I", str(script_path)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=time_limit_sec,
                encoding="utf-8",
                cwd=tmpdir,
                env=env,
                preexec_fn=preexec,
            )
            elapsed_ms = int((time.time() - start_time) * 1000)

        # 检查运行时错误
        if result.returncode != 0:
            return {
                "status": STATUS_RE,
                "time_ms": elapsed_ms,
                "memory_kb": None,
                "actual_output": None,
                "error_message": result.stderr[:500] if result.stderr else "Runtime Error",
            }

        # 对比输出（忽略首尾空白和行末换行）
        actual_output = result.stdout.strip()
        expected_clean = expected_output.strip()

        if actual_output == expected_clean:
            return {
                "status": STATUS_AC,
                "time_ms": elapsed_ms,
                "memory_kb": None,  # 简化版不统计内存
                "actual_output": None,  # AC 时不返回实际输出
                "error_message": None,
            }
        else:
            return {
                "status": STATUS_WA,
                "time_ms": elapsed_ms,
                "memory_kb": None,
                "actual_output": actual_output[:500],  # 截断避免过大
                "error_message": None,
            }

    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "status": STATUS_TLE,
            "time_ms": elapsed_ms,
            "memory_kb": None,
            "actual_output": None,
            "error_message": f"Time Limit Exceeded ({time_limit_ms}ms)",
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "status": STATUS_SE,
            "time_ms": elapsed_ms,
            "memory_kb": None,
            "actual_output": None,
            "error_message": f"System Error: {str(e)[:200]}",
        }
