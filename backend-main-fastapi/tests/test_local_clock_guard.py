# -*- coding: utf-8 -*-
"""静态守卫：应用层不得裸用本机时钟（#19 时间口径 / #32 写库时间戳统一）。

缺陷类（本会话实测过的原样）：``datetime.now()`` 给的是**本机墙钟**，本项目
所有 DB 时间列按 **naive UTC** 口径存储（见 ``utils/timeutil`` 模块 docstring）。
两者混用会同时错三处：

* 存进去的值比真实 UTC 早/晚 8 小时，与任何 UTC 窗口比较都偏一天；
* ``strftime("%Y-%m-%d %H:%M:%S")`` 出来的空格分隔串**不匹配**
  ``utils/response.py`` 的补 ``Z`` 正则，前端 ``new Date()`` 按本地时区解析，
  于是「看起来对、其实是本地时间伪装成 UTC」；
* 换一台非 +08:00 的机器（或 CI 设了 TZ=UTC）就跑出不同结果。

所以 ``routers`` / ``services`` / ``core`` 里只允许四个出口：
``utcnow()``（与 DB 列比较/写 ORM datetime）、``naive_utc_iso()``（写 TEXT 时间列）、
``local_today()`` / ``local_date_of()``（北京自然日口径）。

本文件不检查这些出口用得对不对（那是 ``test_day_window_call_sites.py`` 与各模块
行为用例的职责），只挡住「直接抓本机时钟」这一入口。文件名/人类可读展示等**确实
该用本地墙钟**的场景在 :data:`ALLOWED_LOCAL_CLOCK` 里逐条点名并写清理由；新增一条
必须先说明为什么不能用 UTC。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 扫描范围：应用层。``scripts`` / ``tools`` / ``tests`` 是一次性运维代码，不在此列。
SCAN_DIRS = ("routers", "services", "core")

#: 禁止的"裸本机时钟"调用（点号路径 + 无位置参数）。
BANNED_PATHS = {
    ("datetime", "now"),
    ("datetime", "datetime", "now"),
    ("date", "today"),
    ("datetime", "date", "today"),
    ("datetime", "utcnow"),
    ("datetime", "datetime", "utcnow"),
    ("time", "localtime"),
}

#: 允许点：``相对路径::所属函数`` -> 为什么必须是本地墙钟。
ALLOWED_LOCAL_CLOCK = {
    # —— 文件名/目录名时间戳：只要求唯一 + 人类可读，不参与任何时间列比较 ——
    "routers/ai.py::upload_chat_image": "落盘文件名时间戳",
    "services/analysis_engine.py::save_lecture": "导出文件名时间戳",
    "services/backup_service.py::_unique_backup_path": "备份文件名时间戳（含同秒去重）",
    "services/backup_service.py::restore_backup": "还原前快照文件名时间戳",
    "services/backup_service.py::should_backup_today": '「今天备过没有」按备份文件名判，文件名就是本地时钟，两侧必须同源',
    "services/delete_guard.py::_build_backup_name": "删除前落盘文件名时间戳",
    "services/delete_guard.py::backup_before_delete": "同上",
    # —— 与文件系统 mtime 比年龄：mtime 本身就是操作系统本地时钟 ——
    "services/delete_guard.py::rollback_window": "展示「多少分钟内可回滚」，输入是文件 mtime",
    # —— 面向人阅读的展示串 ——
    "services/paper_builder.py::paper_to_lecture_html": "试卷导出 HTML 的打印页眉时间",
    "services/scheduler.py::_netdisk_sync_job": "定时通知文案里的完成时刻",
    "services/scheduler.py::_completion_selfcheck_job": "定时通知文案里的自检时刻",
    "services/scheduler.py::_review_reminder_job": "定时通知文案里的提醒时刻",
}

REMEDY = (
    "改走 utils.timeutil 的出口：写 ORM datetime 列用 utcnow()，写 TEXT 时间列用 "
    "naive_utc_iso()，「今天/哪一天」用 local_today() / local_date_of()。"
)


def _dotted(node: ast.AST) -> tuple[str, ...] | None:
    """把 ``a.b.c`` 形式的调用目标拍平成元组；不是纯点号链则返回 None。"""
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return tuple(reversed(parts))


def _enclosing_calls(tree: ast.AST) -> list[tuple[str, int, str]]:
    """返回 ``[(所属函数名, 行号, 点号路径)]``，函数名缺失时记为 ``<module>``。"""

    found: list[tuple[str, int, str]] = []

    def walk(node: ast.AST, func_name: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name)
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{func_name}.{child.name}" if func_name != "<module>" else child.name)
            elif isinstance(child, ast.Call):
                path = _dotted(child.func)
                if (
                    path in BANNED_PATHS
                    and not child.args
                    and not child.keywords
                ):
                    found.append((func_name, child.lineno, ".".join(path)))
                walk(child, func_name)
            else:
                walk(child, func_name)

    walk(tree, "<module>")
    return found


def _scan() -> list[str]:
    hits: list[str] = []
    for dirname in SCAN_DIRS:
        for py in sorted((ROOT / dirname).rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(ROOT).as_posix()
            try:
                tree = ast.parse(py.read_text(encoding="utf-8-sig"), filename=str(py))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for func_name, lineno, call in _enclosing_calls(tree):
                if f"{rel}::{func_name}" in ALLOWED_LOCAL_CLOCK:
                    continue
                hits.append(f"{rel}:{lineno} 在 {func_name}() 里裸用 {call}()")
    return hits


def test_no_bare_local_clock_in_app_layer():
    hits = _scan()
    assert not hits, (
        "应用层禁止裸用本机时钟（datetime.now() / date.today() / datetime.utcnow()）。"
        f"\n{REMEDY}\n命中：\n" + "\n".join(hits)
    )


def test_local_clock_allowlist_is_not_stale():
    """允许点必须逐条真实存在：改名/删掉调用点后要在这里报错，而不是悄悄留着。"""
    live = {f"{rel}::{func_name}" for rel, func_name, _call in _live_entries()}
    stale = sorted(set(ALLOWED_LOCAL_CLOCK) - live)
    assert not stale, (
        "以下允许点在当前代码里已经不存在，请从 ALLOWED_LOCAL_CLOCK 删除：" + ", ".join(stale)
    )


def _live_entries() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for dirname in SCAN_DIRS:
        for py in sorted((ROOT / dirname).rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(ROOT).as_posix()
            try:
                tree = ast.parse(py.read_text(encoding="utf-8-sig"), filename=str(py))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for func_name, _lineno, call in _enclosing_calls(tree):
                out.append((rel, func_name, call))
    return out
