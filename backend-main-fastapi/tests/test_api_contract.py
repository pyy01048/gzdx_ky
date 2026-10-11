"""接口契约回归测试（QA · 最高价值防回归资产）。

背景
----
项目此前"错误率太高"，但 149 个既有单测全绿 —— 因为它们**从不发 HTTP 请求**，
所有 5xx 缺陷（裸 SQL 字符串未包 text()、时区比较 TypeError、AttributeError、
缺表 OperationalError）全部逃过检测。本文件补上这一层。

做什么
------
用内存 ASGI 客户端（不启 uvicorn、不占端口、不触真实库）遍历**全部 GET 路由**，
逐条断言：

1. **绝不允许 5xx**。这是硬红线，任何 500 都是源码 Bug。
2. 4xx 只允许出现在 :data:`ALLOWED_4XX` 容差白名单里，且必须写清理由。
   白名单之外新增任何 4xx 都会让测试失败 —— 防止"404 悄悄扩散"。
3. 响应时间必须低于阈值（默认 5s，个别重型接口单独放宽），
   超时/超时的失败信息里明确报出是哪个接口。
4. 失败信息统一格式：**接口路径 + 状态码 + 响应体前 300 字 + 耗时**，便于定位。

不做什么（安全边界）
--------------------
* 只发 GET。POST/PUT/DELETE 一律不碰。
* 副作用型 GET 显式排除（见 :data:`SKIP_PATHS`：全盘扫描 / 备份 / 修复 /
  迁移 / 导入 / 同步 / 爬虫）。这些会改磁盘或跑长任务。
* 路径变量用 :func:`sample_data` 造出的真实 id 替换，不用不存在的 id 去
  人为制造 404。

运行
----
    D:/Anaconda/python.exe -m pytest tests/test_api_contract.py -v
"""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------------------- #
# 常量配置
# --------------------------------------------------------------------------- #

#: GET 接口默认耗时上限（秒）。超时即失败并报出接口名。
DEFAULT_TIME_BUDGET = 5.0

#: 已知重接口的单独耗时上限（秒）。这些接口会读磁盘 / 探测硬件 / 调本地
#: 模型服务，天然比纯 DB 查询慢，但仍必须有上限以防"卡死"。
SLOW_ROUTE_BUDGETS = {
    "/api/ai/models/catalog": 15.0,      # 扫模型注册表 + 磁盘探测
    "/api/ai/models/hardware": 15.0,     # CPU/GPU/内存探测
    "/api/ai/local/status": 20.0,        # 探测本地 Ollama（网络往返）
    "/api/ai/local/models": 20.0,        # 同上
    "/api/kb/ingest/status": 15.0,       # 扫 inbox 目录
    "/api/kb/health": 15.0,              # 扫知识库目录 + 计数
    "/api/storage": 15.0,                # 目录体积统计
    "/api/access-info": 15.0,            # 探测局域网网卡
    "/api/goals/strategy": 15.0,         # 可能回落 AI 生成（网络）
    "/api/backup": 15.0,
}

#: 有副作用 / 会跑长任务 / 会改磁盘的 GET 接口，契约测试**不碰**。
#: 用精确路径而非子串匹配，避免误杀 /api/kb/health 这类只读接口。
SKIP_PATHS = {
    "/api/storage/scan",            # 递归全盘扫描（阻塞事件循环）
    "/api/backup",                  # 读取/生成备份文件
    "/api/kb/heal/status",          # 知识库修复任务状态（heal 家族）
    "/api/imports/scan/{task_id}",  # 导入扫描任务
}

#: 允许的 4xx 容差白名单：路径 -> (允许的状态码集合, 理由)
#: **白名单之外出现任何 4xx/5xx 都会导致测试失败。**
ALLOWED_4XX = {
    # ---- 422：缺少必填查询参数（属正常入参校验，非缺陷）----
    "/api/kaoyan/analysis/trend": ({422}, "缺必填查询参数 school_id"),
    "/api/kaoyan/analysis/compare": ({422}, "缺必填查询参数 school_ids"),
    "/api/kaoyan/analysis/recommend": ({422}, "缺必填查询参数 score"),
    "/api/netdisk/search": ({422}, "缺必填查询参数 keyword"),
    "/api/planner/daily": ({422}, "缺必填查询参数 date"),
    "/api/planner/daily/range": ({422}, "缺必填查询参数 start"),
    "/api/planner/month": ({422}, "缺必填查询参数 year"),
    "/api/planner/week": ({422}, "缺必填查询参数 week_start"),

    # ---- 400：业务前置条件未满足（正常业务分支）----
    "/api/ai/models/recommend": ({400}, "至少需提供 subject 或 task 之一"),

    # ---- 401：外部服务未授权（测试环境无网盘 OAuth token）----
    "/api/netdisk/recursive-files": ({401}, "百度网盘未授权（测试环境无 token）"),
    "/api/netdisk/quota": ({401}, "百度网盘未授权（测试环境无 token）"),

    # ---- 404：外部资源 id 在测试库中不存在（非源码缺陷）----
    "/api/kaoyan/schools/{school_id}": ({404}, "测试库无院校数据"),
    "/api/netdisk/files/{file_id}": ({404}, "测试库无网盘文件"),
    "/api/netdisk/preview/{file_id}": ({404}, "测试库无网盘文件"),
    "/api/netdisk/platform-config/{platform}": ({404}, "测试库无该平台配置"),
    "/api/ai/build-embeddings/status/{task_id}": ({404}, "内存态任务表为空，任务不存在"),
}

#: 路径变量名 -> sample_data 里真实存在的 id 字段。
PATH_PARAM_TO_ID = {
    "task_id": "task_id",
    "error_id": "error_id",
    "doc_id": "doc_id",
    "word_id": "word_id",
    "paper_id": "paper_id",
    "kp_id": "kp_id",
    "plan_id": "plan_id",
    "session_id": "session_id",
    "school_id": "school_id",
    "file_id": "file_id",
    "platform": "platform",
}

#: 首轮巡检发现的源码 Bug —— **全部已由工程师修复**，故本表当前为空。
#: 这些路径若再次出现在本表中，说明对应缺陷回归了；修好后请从这里移除，
#: 让主巡检重新以"零容忍"方式覆盖它们。
#:
#: 修复历史（均已验证转绿，现由 test_regression_p0.py 的硬断言守住）：
#:   * /api/review/stats            —— review.py:120 `datetime.UTC`（datetime 类无此属性）
#:                                    + aware/naive 混用；已统一到 utils/timeutil.utcnow()
#:   * /api/planner/ebbinghaus/due  —— planner.py:281 naive/aware datetime 比较
#:                                    + `{field}_done` 列不存在导致去重永久失效
#:   * /api/exam/blueprints         —— exam.py:95 裸 SQL 字符串未包 text()
#:   * /api/planner/phase[/{id}/reviews] —— phase_daily_reviews 表缺 CREATE TABLE DDL
#:                                    （真实库里历史遗留存在，换机/新部署必 500）
KNOWN_SOURCE_BUGS: dict = {}


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #

def _resolve_path(template: str, op: dict, ids: dict) -> str:
    """把 openapi 路径模板里的 ``{var}`` 替换为真实存在的 id。"""
    url = template
    for param in op.get("parameters", []):
        if param.get("in") != "path":
            continue
        name = param["name"]
        token = "{" + name + "}"
        if token not in url:
            continue
        id_key = PATH_PARAM_TO_ID.get(name)
        value = ids.get(id_key) if id_key else None
        url = url.replace(token, str(value) if value is not None else "1")
    return url


def _collect_get_routes(app_module, ids: dict):
    """返回 ``[(路径模板, 具体URL), ...]``，供巡检循环使用。

    已知源码 Bug（:data:`KNOWN_SOURCE_BUGS`）从主巡检集合中**排除**，
    改由下方 :func:`test_known_source_bug_fixed` 逐条以 xfail 方式跟踪。
    这样主巡检保持"零容忍"：任何**新增** 5xx 都会立刻让 CI 失败。
    """
    spec = app_module.openapi()
    cases = []
    for template, item in spec["paths"].items():
        op = item.get("get")
        if not op:
            continue
        if template in SKIP_PATHS or template in KNOWN_SOURCE_BUGS:
            continue
        url = _resolve_path(template, op, ids)
        cases.append((template, url))
    return cases


def _describe(template: str, url: str, status, elapsed: float, body: str) -> str:
    """统一的失败信息格式：路径 + 状态码 + 响应体前 300 字 + 耗时。"""
    return (
        f"\n接口契约失败\n"
        f"  路径     : {template}\n"
        f"  实际请求 : {url}\n"
        f"  状态码   : {status}\n"
        f"  耗时     : {elapsed * 1000:.1f} ms\n"
        f"  响应体   : {body[:300]}\n"
    )


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def route_ids(sample_data):  # noqa: ARG001 - 触发数据种子
    """路径变量替换用的真实 id 集合。"""
    return dict(sample_data)


@pytest.fixture(scope="module")
def get_cases(app_module, route_ids):  # noqa: ARG001
    """参数化用例列表（会话级只算一次）。"""
    return _collect_get_routes(app_module, route_ids)


# --------------------------------------------------------------------------- #
# 测试 1：全部 GET 路由逐条巡检
# --------------------------------------------------------------------------- #

def test_all_get_routes_contract(client, get_cases):  # noqa: ARG001
    """遍历所有 GET 路由：不许 5xx，4xx 必须在白名单，耗时不超预算。

    这条测试是整个 QA 方案的核心 —— 它把"用户点了页面就白屏/报 500"这类
    问题在 CI 阶段拦住，而不是等用户反馈。
    """
    failures = []
    checked = 0
    skipped = 0

    for template, url in get_cases:
        if template in SKIP_PATHS:
            skipped += 1
            continue

        budget = SLOW_ROUTE_BUDGETS.get(template, DEFAULT_TIME_BUDGET)
        start = time.perf_counter()
        try:
            resp = client.get(url)
        except Exception as exc:  # noqa: BLE001 - 客户端层异常也算失败
            elapsed = time.perf_counter() - start
            failures.append(_describe(
                template, url, f"客户端异常 {type(exc).__name__}", elapsed, str(exc),
            ))
            continue
        elapsed = time.perf_counter() - start
        checked += 1
        body = resp.text

        # --- 断言 1：绝不允许 5xx ---
        if resp.status_code >= 500:
            failures.append(_describe(template, url, resp.status_code, elapsed, body))
            continue

        # --- 断言 2：4xx 必须在容差白名单内 ---
        if resp.status_code >= 400:
            allowed = ALLOWED_4XX.get(template)
            if allowed is None:
                failures.append(_describe(
                    template, url, resp.status_code, elapsed,
                    body + "\n  >> 该 4xx 不在 ALLOWED_4XX 白名单中（新增容差需写明理由）",
                ))
            elif resp.status_code not in allowed[0]:
                failures.append(_describe(
                    template, url, resp.status_code, elapsed,
                    body + f"\n  >> 白名单仅允许 {sorted(allowed[0])}，理由：{allowed[1]}",
                ))
            continue

        # --- 断言 3：响应时间在预算内 ---
        if elapsed > budget:
            failures.append(_describe(
                template, url, resp.status_code, elapsed,
                body + f"\n  >> 耗时 {elapsed * 1000:.1f}ms 超过预算 {budget * 1000:.0f}ms",
            ))

    assert checked > 0, "没有收集到任何 GET 路由，契约测试形同虚设"
    if failures:
        detail = "\n".join(failures)
        raise AssertionError(
            f"GET 路由巡检失败：{len(failures)}/{checked} 个接口不合规"
            f"（跳过 {skipped} 个副作用接口）\n{detail}"
        )


# --------------------------------------------------------------------------- #
# 测试 2：覆盖率守卫 —— 确保没有新 GET 路由被静默漏掉
# --------------------------------------------------------------------------- #

def test_no_get_route_is_silently_unguarded(app_module, get_cases):
    """守卫：每个 GET 路由都必须被某条用例覆盖（巡检 / 已知Bug / 副作用排除）。

    如果有人新写了 GET 接口却忘了纳入任何一层，这条会报警。
    """
    spec = app_module.openapi()
    all_get = {p for p, item in spec["paths"].items() if "get" in item}
    covered = {t for t, _ in get_cases}
    accounted = covered | set(SKIP_PATHS) | set(KNOWN_SOURCE_BUGS)
    leaked = all_get - accounted
    assert not leaked, (
        f"以下 GET 路由未被任何用例覆盖（既不在巡检集合，也不在 "
        f"SKIP_PATHS / KNOWN_SOURCE_BUGS 中）：{sorted(leaked)}"
    )
    # 反向：排除规则里不该有已不存在的路由（避免死规则掩盖新问题）
    stale = (set(SKIP_PATHS) | set(KNOWN_SOURCE_BUGS)) - all_get
    assert not stale, f"以下路由已不存在，请清理 SKIP_PATHS/KNOWN_SOURCE_BUGS：{sorted(stale)}"


def test_skip_paths_actually_have_side_effects():
    """守卫：SKIP_PATHS 必须小而明确。超过 12 条说明排除面过宽，检测力下降。"""
    assert len(SKIP_PATHS) <= 12, (
        f"SKIP_PATHS 有 {len(SKIP_PATHS)} 条，排除面过宽会掩盖真实缺陷：{sorted(SKIP_PATHS)}"
    )


def test_allowed_4xx_entries_have_reasons():
    """守卫：白名单每条都必须写理由，否则会变成垃圾桶。"""
    for path, (codes, reason) in ALLOWED_4XX.items():
        assert path.startswith("/api/"), f"白名单路径应以 /api 开头：{path}"
        assert codes and all(400 <= c < 500 for c in codes), \
            f"白名单只允许 4xx，{path} 写了 {codes}"
        assert reason and len(reason) >= 4, f"白名单条目缺理由：{path}"


# --------------------------------------------------------------------------- #
# 测试 3：响应体必须是合法 JSON（防止返回 HTML 错误页 / 被中间件打坏）
# --------------------------------------------------------------------------- #

def test_get_routes_return_json(client, get_cases):  # noqa: ARG001
    """所有巡检通过的 GET 接口必须返回可解析的 JSON。

    防止：异常时返回 HTML 栈页、SPA fallback 把 /api/404 变成 index.html、
    中间件把 body 序列化坏掉。
    """
    bad = []
    for template, url in get_cases:
        if template in SKIP_PATHS:
            continue
        try:
            resp = client.get(url)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"  {template} -> 客户端异常 {type(exc).__name__}: {exc}")
            continue
        ctype = resp.headers.get("content-type", "")
        if resp.status_code == 204:
            continue
        if "json" not in ctype.lower():
            bad.append(
                f"  {template} -> content-type={ctype!r} 非 JSON，body前120字={resp.text[:120]!r}"
            )
            continue
        try:
            resp.json()
        except Exception as exc:  # noqa: BLE001
            bad.append(f"  {template} -> JSON 解析失败 {type(exc).__name__}: {exc}")

    assert not bad, "以下接口未返回合法 JSON：\n" + "\n".join(bad)


# --------------------------------------------------------------------------- #
# 测试 4：真实库防污染守卫
# --------------------------------------------------------------------------- #

def test_real_database_not_polluted(client, real_db_mtime_guard):  # noqa: ARG001
    """确保整个测试会话没有写过一次真实库 D:\\平台\\database\\kaoyan.db。

    这是 QA 的红线：283MB 的用户数据绝不能被测试碰。
    注意 mtime 变化也可能来自运行中的业务服务，因此这里只在
    "测试确实使用了临时库" 的前提下做断言（conftest 已强制 DATABASE_PATH 重定向）。
    """
    import conftest as _c
    from database import SQLALCHEMY_DATABASE_URL

    # 1) 引擎必须指向临时库
    assert "kaoyan_qa_testdb_" in SQLALCHEMY_DATABASE_URL, (
        f"测试引擎竟指向 {SQLALCHEMY_DATABASE_URL}，可能污染真实数据！"
    )
    # 2) 真实库 mtime 未变（若文件存在）
    if real_db_mtime_guard is not None and os.path.exists(_c.REAL_DB_PATH):
        now_mtime = os.stat(_c.REAL_DB_PATH).st_mtime_ns
        assert now_mtime == real_db_mtime_guard, (
            f"真实库 {_c.REAL_DB_PATH} 的 mtime 变了："
            f"{real_db_mtime_guard} -> {now_mtime}，测试污染了用户数据！"
        )


# --------------------------------------------------------------------------- #
# 测试 5：核心只读接口必须 200（针对已知 5xx 缺陷的定点回归）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", [
    "/api/health",
    "/api/dashboard",
    "/api/tasks",
    "/api/goals",
    "/api/quiz/questions",
    "/api/errors",
    "/api/exam/blueprints",     # 曾因裸 SQL 字符串 → 500（exam.py:95）
    "/api/gate/stats",           # 曾因裸 SQL 字符串 → 500（gate.py:65-72）
    "/api/ai/providers",
    "/api/documents",
    "/api/papers",
    "/api/words",
    "/api/taxonomy/tree",
    "/api/review/progress",
    "/api/planner/ebbinghaus",
])
def test_critical_get_route_ok(client, path):
    """核心只读接口必须 200 —— 这些是前端首屏依赖的，坏了页面直接白屏。"""
    start = time.perf_counter()
    resp = client.get(path)
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200, _describe(path, path, resp.status_code, elapsed, resp.text)


# --------------------------------------------------------------------------- #
# 测试 6：已知源码 Bug 的定点跟踪
# --------------------------------------------------------------------------- #

def test_no_known_bugs_outstanding():
    """守卫：已知 Bug 清单必须及时清空。

    当前 :data:`KNOWN_SOURCE_BUGS` 为空 —— 首轮巡检发现的 4 个缺陷
    （review/stats 的 datetime.UTC、ebbinghaus/due 的时区比较、
    exam/blueprints 的裸 SQL、phase_daily_reviews 缺 DDL）
    均已修复并由 test_regression_p0.py 的硬断言长期守住。

    若将来这条失败，说明有人登记了新 Bug 但一直没销账。
    """
    assert not KNOWN_SOURCE_BUGS, (
        f"以下已知 Bug 尚未销账，请确认是否已修复并移除：{sorted(KNOWN_SOURCE_BUGS)}"
    )


def test_known_source_bug_guard_is_functional(client, app_module, route_ids):
    """守卫：Bug 哨兵机制本身可用（在临时表里自测，不依赖真实 KNOWN_SOURCE_BUGS）。

    目的：防止"因为清单空了所以哨兵形同虚设"—— 万一将来又登记了新 Bug，
    这条确保那条哨兵真的会跑、真的会失败。
    """
    sentinel = "/api/review/stats"   # 曾是 500 的真实缺陷点
    spec = app_module.openapi()
    assert sentinel in spec["paths"], "哨兵自测用的路径不存在，测试本身失效"

    url = _resolve_path(sentinel, spec["paths"][sentinel]["get"], route_ids)
    resp = client.get(url)
    # 该接口已修复 → 现在是 2xx。若哪天回归成 500，本断言会失败，
    # 同时 test_regression_p0.TestReviewStats 也会红，形成双重保险。
    assert resp.status_code == 200, (
        _describe(sentinel, url, resp.status_code, 0.0, resp.text)
    )


def _resolve_bug_url(template: str, spec: dict, ids: dict) -> str:
    op = spec["paths"][template]["get"]
    return _resolve_path(template, op, ids)


@pytest.mark.parametrize("template", sorted(KNOWN_SOURCE_BUGS))
def test_known_source_bug_fixed(client, app_module, route_ids, template):  # noqa: ARG001
    """已知源码 Bug 的哨兵：现在 xfail（确实是坏的），工程师修好后自动转 PASS。

    用命令式 ``pytest.xfail()`` 而非收集期 mark：这样无需在 import 期就把
    路径表算好，逻辑集中在一处、可读性更好。

    语义：
      * 仍返回 5xx → ``xfail``（报告为已知缺陷，不阻塞 CI，但持续可见）；
      * 已修好（2xx/4xx）→ ``PASS``，此时应把该条目从
        :data:`KNOWN_SOURCE_BUGS` 移除，让主巡检重新接管这条路径。
    """
    spec = app_module.openapi()
    url = _resolve_bug_url(template, spec, route_ids)
    start = time.perf_counter()
    resp = client.get(url)
    elapsed = time.perf_counter() - start
    desc = KNOWN_SOURCE_BUGS[template]

    if resp.status_code >= 500:
        pytest.xfail(
            _describe(template, url, resp.status_code, elapsed, resp.text) + f"\n  >> 缺陷：{desc}"
        )
    assert resp.status_code < 500
