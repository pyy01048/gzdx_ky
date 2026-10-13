"""题库写入侧闸门收口（docx/16 §1.5-H）。

实测背景：quiz_questions 里 8099/9096 行的 options 是 JSON null、316 行是切碎
的选项残片，「题目格式没有统一标准」的两个源头是两条**没接 quiz_content_gate**
的写入路径 —— `documents.py::generate_quiz`（模型返回的 JSON 直接 db.add，且不填
subject）和 `qbank_upgrade.py::generate_variants`（ai:variant）。两条已补闸。

本文件用 AST 把口径钉死，防止以后再开出第 3 条裸写路径：

1. 任何构造 `QuizQuestion(...)` 的函数，必须要么在同函数体内调用内容闸门
   （admit / gate_admit / admit_or_raise），要么调用已登记的「接闸写入helper」
   （`_gate_rows`），要么出现在人工入口白名单里。
2. 白名单条目必须仍然命中真实函数——条目失效即红，避免注释腐烂。
3. 调用了闸门名字的文件必须真的能解析到那个名字（上一轮踩过「写了调用没写
   import，被外层 except 吞成一行日志」的 BLOCKER）。

红线：全程只做静态解析，不 import 生产路由、不连库，绝不碰
D:\\平台\\database\\kaoyan.db。
"""
from __future__ import annotations

import ast
import os

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_NAME = "QuizQuestion"
GATE_CALLS = {"admit", "gate_admit", "admit_or_raise"}

# 已登记的「接闸写入 helper」：函数体本身不叫 admit，但把逐条判定委托给了
# 一个内部已接闸的公共函数。新增此类 helper 时同步登记，否则守卫会红。
GATED_WRITER_HELPERS = {"_gate_rows"}

# 人工入口白名单：这些函数构造题目时**故意**不过内容闸门——写入者是有判断力
# 的人（或已在上游接闸），闸门的最小长度/题征词阈值会误杀合法的手录短题。
# 每条必须注明理由，并由 test_manual_whitelist_is_still_live 钉住。
MANUAL_WHITELIST = {
    "routers/quiz.py::add_question":
        "人工单题录入（POST /api/quiz/questions），用户所见即所写",
    "routers/quiz.py::import_confirm":
        "M6-4 人工确认闭环第二步，人已逐条预览过",
    "scripts/rebuild_knowledge_base.py::main":
        "题目源自 qbank_builder.extract_questions，该函数体内已接闸",
    "scripts/verify_rebuild_no_recur.py::main":
        "本地回归验证脚本，不面向生产库的导入通道",
    "scripts/test_cross_source_dedupe.py::_ingest":
        "跨来源判重验证脚本的自建夹具题",
    "scripts/test_cross_source_dedupe.py::main":
        "跨来源判重验证脚本的自建夹具题",
}


LIVE_DB = os.path.join(os.path.dirname(BACKEND), "database", "kaoyan.db")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _guard_real_db_untouched():
    """本文件只读源码，不该碰生产库；碰了就红。"""
    if not os.path.exists(LIVE_DB):
        yield
        return
    stat = os.stat(LIVE_DB)
    before = (stat.st_mtime, stat.st_size)
    yield
    stat = os.stat(LIVE_DB)
    assert (stat.st_mtime, stat.st_size) == before, "只读静态测试改动了生产库"


def _iter_py():
    for d in ("routers", "services", "scripts"):
        base = os.path.join(BACKEND, d)
        for root, _dirs, files in os.walk(base):
            if any(part in root for part in (os.sep + "tests", "__pycache__", "static")):
                continue
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(root, f)


def _rel(path: str) -> str:
    return os.path.relpath(path, BACKEND).replace("\\", "/")


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _sites():
    """返回 {`文件::函数`: {"quiz": [行号], "gate": bool, "helper": [名字]}}。

    构造点归属到**最内层** enclosing 函数，避免父函数替子函数背锅。
    模块级构造（不在任何函数内）以 `<module>` 记录，同样必须接闸。
    """
    out: dict[str, dict] = {}
    for path in _iter_py():
        with open(path, encoding="utf-8-sig") as fh:
            tree = ast.parse(fh.read(), filename=path)
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        def owner(node):
            cur = parents.get(node)
            while cur is not None:
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return cur
                cur = parents.get(cur)
            return None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            nm = _call_name(node)
            if nm not in ({MODEL_NAME} | GATE_CALLS | GATED_WRITER_HELPERS):
                continue
            f = owner(node)
            key = f"{_rel(path)}::{f.name if f else '<module>'}"
            rec = out.setdefault(key, {"quiz": [], "gate": False, "helper": []})
            if nm == MODEL_NAME:
                rec["quiz"].append(node.lineno)
            elif nm in GATE_CALLS:
                rec["gate"] = True
            else:
                rec["helper"].append(nm)
    return {k: v for k, v in out.items() if v["quiz"]}


def test_quiz_construct_sites_are_gated_or_whitelisted():
    sites = _sites()
    assert sites, "AST 扫描没找到任何 QuizQuestion 构造点，扫描口径可能已失效"
    bad = []
    for key, rec in sorted(sites.items()):
        if rec["gate"] or rec["helper"]:
            continue
        if key in MANUAL_WHITELIST:
            continue
        bad.append(f"{key} 行{rec['quiz']} 构造 QuizQuestion 但未接内容闸门")
    assert not bad, "；".join(bad)


def test_manual_whitelist_is_still_live():
    """白名单不能留死条目：登记的入口必须真的还在构造题目。"""
    sites = _sites()
    stale = [k for k in MANUAL_WHITELIST if k not in sites]
    assert not stale, f"白名单条目已失效，请删除：{stale}"


def test_gate_helpers_resolve_the_name():
    """调用闸门/接闸 helper 的文件必须真的解析得到那个名字。"""
    bad = []
    for path in _iter_py():
        with open(path, encoding="utf-8-sig") as fh:
            tree = ast.parse(fh.read(), filename=path)
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in (GATE_CALLS | GATED_WRITER_HELPERS):
                    used.add(node.func.id)
        if not used:
            continue
        bound = _bound_names(tree)
        for name in sorted(used - bound):
            bad.append(f"{_rel(path)}: 调用了 {name} 但名字无法解析")
    assert not bad, "；".join(bad)


def _bound_names(tree: ast.Module) -> set:
    """本文件可见的名字：import 进来的 + 顶层定义的。"""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def test_the_two_fixed_paths_now_call_the_gate():
    """回归：本轮补闸的两条路径必须真的接上，别只是改了文档。"""
    sites = _sites()
    for key in ("routers/documents.py::generate_quiz",
                "scripts/qbank_upgrade.py::generate_variants"):
        rec = sites.get(key)
        assert rec, f"{key} 已不在构造 QuizQuestion，请同步更新守卫与 docx/16 §1.5-H"
        assert rec["gate"], f"{key} 未调用内容闸门"
