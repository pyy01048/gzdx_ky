# -*- coding: utf-8 -*-
"""反向接口守卫：前端在调的每个路径，后端必须真的存在（#34）。

``test_api_contract.py`` 走的是**正向**：遍历 OpenAPI 的所有 GET，逐个打，看后端
会不会 500。它挡不住另一半问题——前端还在调一个后端已经改名/删掉的接口，于是
页面拿到 404，而正向巡检永远看不见（那个路径根本不在 OpenAPI 里）。

本文件只做静态对照（不发请求）：

1. 从 ``frontend/src/api/{client,kaoyanApi,sync}.js`` 里抽出所有 ``request(...)``
   的第一参数字面量；
2. 去掉查询串，把 ``${x}`` 与 ``'/' + id`` 拼接尾巴归一为通配段；
3. 每条都必须能匹配到 ``app.openapi()["paths"]`` 里的某个模板；
4. 另全量扫描 ``frontend/src`` 里绕过 api 层的裸 ``fetch('/api/...')`` 字面量
   （SSE 与二进制下载只能用原生 fetch），同样逐条对照 OpenAPI。

``MIN_CALLS`` 是自检：正则一旦因为 client.js 改写而抽不到东西，本文件不能"零命中
全通过"，必须显式报错。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE_API_DIR = ROOT.parent / "frontend" / "src" / "api"
FE_FILES = ("client.js", "kaoyanApi.js", "sync.js")

#: 发起网络请求的封装名（client.js 内部与 kaoyanApi/sync 复用的都是这几个）
CALL_RE = re.compile(
    r"\b(?:request|postJson|getJson|delJson|upload)\(\s*(['\"`])(.+?)\1", re.S
)

#: 抽到的调用条数下限（实测 2026-10-17：224 条去重路径）。低于它说明抽取逻辑失效。
MIN_CALLS = 150

SRC_DIR = ROOT.parent / "frontend" / "src"
#: 测试目录里的 fetch 是断言用的假 URL，不参与守卫
SKIP_PARTS = ("test", "__tests__", "node_modules")

#: 绕过 api 层、在组件/工具里直接写死的 ``fetch('/api/...')`` 字面量。
#: ``fetch(normalizeUrl(...))``（外部 AI provider 直连）与 ``fetch(变量)`` 不匹配，
#: 因为它们的 URL 不是本仓库的接口面。
RAW_FETCH_RE = re.compile(r"\bfetch\(\s*(['\"`])(/api/[^'\"`]*)\1")


def _frontend_calls() -> set[str]:
    """返回前端所有以 ``/api`` 开头的调用路径（已去查询串）。"""
    found: set[str] = set()
    for name in FE_FILES:
        path = FE_API_DIR / name
        if not path.exists():
            continue
        for m in CALL_RE.finditer(path.read_text(encoding="utf-8")):
            raw = m.group(2).split("?")[0].strip()
            if not raw.startswith("/"):
                continue
            found.add(raw)
    return found


def _raw_fetch_literals() -> set[str]:
    """扫描整个 ``frontend/src``，找出绕过 client.js 的裸 ``/api`` 字面量。"""
    found: set[str] = set()
    for path in SRC_DIR.rglob("*"):
        if path.suffix not in (".js", ".jsx") or any(p in SKIP_PARTS for p in path.parts):
            continue
        for m in RAW_FETCH_RE.finditer(path.read_text(encoding="utf-8")):
            found.add(m.group(2).split("?")[0].strip())
    return found


#: 前端侧的"变量段"占位符
WILD = "\u0000wild"


def _segments(value: str) -> list[str]:
    return [s for s in value.split("/") if s]


def _seg_variants(call: str) -> list[list[str]]:
    """前端路径的可能分段形态。

    ``request('/kaoyan/analysis/score-detail/' + id, ...)`` 这类拼接写法里，正则只吃到
    引号内的字面量，于是路径以 ``/`` 结尾。split 会把这个尾巴空段丢掉，长度就对不上
    后端的 ``/{id}`` 模板。这里补一个显式通配段；同时保留"不带尾巴"的形态，
    万一后端注册的就是这个以斜杠结尾的精确路径也仍能命中。
    """
    base = _segments("/api" + call)
    if call.endswith("/"):
        return [base, base + [WILD]]
    return [base]


def _is_wildcard(seg: str) -> bool:
    """前端侧的"变量段"：``${id}`` 模板插值，或拼接尾巴补出来的占位段。"""
    return seg.startswith("${") or seg == WILD


def _matches_any(call: str, templates: list[str]) -> bool:
    for segs in _seg_variants(call):
        for tpl in templates:
            tsegs = _segments(tpl)
            if len(tsegs) != len(segs):
                continue
            for a, b in zip(segs, tsegs):
                if b.startswith("{") and b.endswith("}"):
                    continue  # 后端路径参数：任意前端段都算命中
                if _is_wildcard(a):
                    continue  # 前端插值段：与后端任何具名段配对
                if a != b:
                    break
            else:
                return True
    return False


def test_frontend_extraction_is_alive():
    calls = _frontend_calls()
    assert len(calls) >= MIN_CALLS, (
        f"只从 {FE_FILES} 抽出 {len(calls)} 条调用（基线 ≥{MIN_CALLS}）——"
        "抽取正则失效会让本守卫变成空转，请同步修改 CALL_RE。"
    )


def test_matcher_rejects_unknown_paths():
    """守卫不能只会放行：造假路径必须判死，否则 404 照样漏。"""
    templates = ["/api/kaoyan/notices/{id}", "/api/dashboard/summary"]
    assert _matches_any("/kaoyan/notices/123", templates)
    assert _matches_any("/kaoyan/notices/", templates)        # '/x/' + id 的拼接尾巴
    assert _matches_any("/kaoyan/notices/${id}", templates)   # 模板字符串插值
    assert not _matches_any("/kaoyan/noticez", templates)     # 拼写漂移
    assert not _matches_any("/kaoyan/notices/123/extra", templates)
    assert not _matches_any("/nope", templates)


def test_every_frontend_call_has_a_live_route(app_module):
    calls = _frontend_calls()
    templates = list(app_module.openapi()["paths"].keys())
    assert templates, "OpenAPI 里一个路径都没有，测试环境异常"
    dead = sorted(c for c in calls if not _matches_any(c, templates))
    assert not dead, (
        "前端在调、后端 OpenAPI 里没有的接口（页面会拿到 404）：\n"
        + "\n".join(f"  /api{c}" for c in dead)
    )


def test_raw_fetch_literals_are_live(app_module):
    """绕过 api 层、裸写 ``fetch('/api/...')`` 的路径也必须真实存在。

    ``utils/api.js`` 里 AI 的 chat/stream 就是这类：走的是原生 fetch（SSE 需要读
    ReadableStream，不能套 client.js 的 JSON 壳），因此只能靠静态对照守住它。
    """
    literals = _raw_fetch_literals()
    templates = list(app_module.openapi()["paths"].keys())
    dead = sorted(c for c in literals if not _matches_any(c[len("/api"):], templates))
    assert not dead, (
        "组件/工具里写死的 fetch 路径在 OpenAPI 中不存在（会 404）：\n"
        + "\n".join(f"  {c}" for c in dead)
    )


def test_api_base_prefix_is_single_source():
    """BASE 只在 client.js 定义一次；其它文件不得自己再拼 '/api' 前缀。"""
    src = (FE_API_DIR / "client.js").read_text(encoding="utf-8")
    assert re.search(r"^const BASE = '/api'$", src, re.M), "client.js 的 BASE 定义变了，请同步本守卫"
    for name in ("kaoyanApi.js", "sync.js"):
        path = FE_API_DIR / name
        if path.exists():
            assert "const BASE" not in path.read_text(encoding="utf-8"), (
                f"{name} 里出现了第二个 BASE 定义——前缀口径必须单一来源"
            )
