# -*- coding: utf-8 -*-
"""依赖方向守卫（docs/完善方案/04-后端架构与代码质量.md §3.6）。

规则：
  - services/** 不得 import routers/**
  - utils/** 不得 import services/**、routers/**
  - models/** 不得 import services/routers
  - routers 可以 import services/models/utils（正确方向）

白名单显式列出历史豁免并逐迭代清空。
沿用项目 test_quiz_gate_ast 的 AST 扫描模式（不靠文本 grep，避免误伤字符串）。
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# 历史豁免：显式列出，逐迭代清空（当前首批为空——先立规矩再清存量）
ALLOWLIST = {
    # "services/xxx.py": ["routers.yyy"],  # 填写豁免时附原因与退场迭代
}


def _imports_of(tree: ast.AST) -> list[str]:
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.append(node.module)
    return mods


def _check(direction: str, top: str, forbidden: tuple[str, ...]) -> list[str]:
    problems = []
    for py in (BACKEND / top).rglob("*.py"):
        rel = py.relative_to(BACKEND).as_posix()
        if rel.startswith("scripts/") or "/data/" in rel:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue  # 数据目录里的第三方 py 不在本测试范围
        for mod in _imports_of(tree):
            if mod.startswith(forbidden):
                allowed = ALLOWLIST.get(rel, [])
                if mod not in allowed:
                    problems.append(f"{rel} -> {mod}")
    return problems


def test_services_do_not_import_routers():
    assert _check("services", "services", ("routers",)) == []


def test_utils_do_not_import_services_or_routers():
    assert _check("utils", "utils", ("services", "routers")) == []
