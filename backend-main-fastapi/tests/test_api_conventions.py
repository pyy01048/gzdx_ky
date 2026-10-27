"""接口约定巡检（P1-底座C · #19）：时间格式 / 字段命名 / 分页壳 / 错误壳。

与 :mod:`tests.test_api_contract` 的分工：那份管「接口活着吗」（5xx、耗时、响应能否
解析成 JSON），本份管「响应的形状合规吗」。路由枚举、跳过清单、路径变量替换全部
**复用**那边的，免得两份清单各漂一份。

四条硬约定（正文写在 utils/response.py 与 utils/exceptions.py）：

1. **时间**：响应里出现的可解析时间必须是 ISO 8601 且**带时区标记**（``Z`` 或
   ``±HH:MM``）。裸串 ``2026-10-16T16:00:00`` 会被 JS 的 ``Date`` 当本地时间解析，
   北京用户看「下次复习时间」就早 8 小时 —— 这是本条存在的唯一理由。
2. **命名**：键一律 snake_case。camelCase 转换中间件已删除，本条防回潮。
3. **分页**：声明了 ``page``/``page_size`` 的端点，``page_size`` 必须有上限
   （裸 ``page_size: int = 20`` 传 100000 就能把库拖穿）；响应给了 ``items``
   就必须给 ``total``，否则前端无法判断还有没有下一页。
4. **错误**：非 2xx 响应体必须是 ``{code, message}``（utils/exceptions.py 的壳），
   不许再吐裸 ``{"detail": ...}``。

只发 GET、只读，副作用接口沿用 :data:`test_api_contract.SKIP_PATHS`。
"""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api_contract import SKIP_PATHS, _collect_get_routes  # noqa: E402


# --------------------------------------------------------------------------- #
# to_utc_z：naive 补 Z + TIMESTAMPTZ 的 +00:00 零偏移收敛成 Z（同一字段族同形状）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    # TIMESTAMPTZ 列（users.last_login_at 等）默认编码出的零偏移 → 收敛成 Z
    ("2026-10-18T07:41:11.881661+00:00", "2026-10-18T07:41:11.881661Z"),
    ("2026-10-18T07:41:11+00:00", "2026-10-18T07:41:11Z"),
    # naive UTC 瞬时（库里的裸时间）→ 补 Z
    ("2026-10-18T07:41:11", "2026-10-18T07:41:11Z"),
    ("2026-10-18T07:41:11.881661", "2026-10-18T07:41:11.881661Z"),
    # 非零偏移是真实本地时区，语义不同，不改写（防篡改时刻）
    ("2026-10-18T07:41:11+08:00", "2026-10-18T07:41:11+08:00"),
    # 非 date-time 一律原样
    ("2026-10-17 08:00:00", "2026-10-17 08:00:00"),  # 空格分隔展示串
    ("2026-10-18", "2026-10-18"),                       # 纯日期
    ("abc", "abc"),
])
def test_to_utc_z_normalizes_naive_and_utc_offset(raw, expected):
    from utils.response import to_utc_z
    assert to_utc_z(raw) == expected

from utils.response import MAX_PAGE_SIZE  # noqa: E402

#: 抓出响应串里所有「像日期时间」的片段，先看它是否自带时区标记。
#: 必须把可选的 ``Z`` / ``±HH:MM`` 也吃进同一个匹配里 —— 早先版本用负向查
#: 断实现，``2026-10-16T19:19:40.070585Z`` 会因为小数秒组可选而只匹配到秒，
#: 后一个字符是 ``.``（不在排除类里），于是**合规的 Z 串被误判成裸串**，一次
#: 刷出 900 条假违规。改成「贪婪吃掉尾巴再判断」就没有这个歧义。
_TS_TOKEN_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
#: 带时区标记才算合规。空格分隔的 ``2026-10-16 16:00:00`` 不是 ISO 8601，
#: JS 解析行为依引擎而异，同样算违规。
_TZ_MARK_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$", re.IGNORECASE)


def _naive_ts_tokens(text: str) -> list[str]:
    """返回 text 里所有**缺时区标记**的日期时间片段。"""
    return [m.group() for m in _TS_TOKEN_RE.finditer(text) if not _TZ_MARK_RE.search(m.group())]
_CAMEL_KEY_RE = re.compile(r"[a-z0-9][A-Z]")


def _walk(node, path="$"):
    """深度优先交出 ``(路径, 键, 值)``，路径用 ``$.items[0].created_at`` 形式便于定位。"""
    if isinstance(node, dict):
        for key, val in node.items():
            yield f"{path}.{key}", key, val
            yield from _walk(val, f"{path}.{key}")
    elif isinstance(node, list):
        for idx, val in enumerate(node):
            yield from _walk(val, f"{path}[{idx}]")


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def conventions_cases(app_module, sample_data):  # noqa: ARG001
    """复用契约测试的枚举：同样的 SKIP_PATHS、同样的真实 id 替换。"""
    return _collect_get_routes(app_module, sample_data)


@pytest.fixture(scope="module")
def get_ops(app_module):
    """``路径模板 -> openapi get 操作``，分页参数校验要用。"""
    spec = app_module.openapi()
    return {tpl: item["get"] for tpl, item in spec["paths"].items() if item.get("get")}


def _call(client, url):
    resp = client.get(url)
    body = None
    if "json" in (resp.headers.get("content-type") or "").lower():
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = None
    return resp, body


# --------------------------------------------------------------------------- #
# 1. 时间格式
# --------------------------------------------------------------------------- #

def test_no_naive_timestamp_in_any_get_response(client, conventions_cases):
    """全部 GET 响应里不许出现「无时区标记的 ISO 日期时间」。"""
    hits: dict[tuple[str, str], str] = {}
    for template, url in conventions_cases:
        if template in SKIP_PATHS:
            continue
        resp, body = _call(client, url)
        if body is None or resp.status_code >= 400:
            continue
        for path, _key, value in _walk(body):
            if not isinstance(value, str):
                continue
            for token in _naive_ts_tokens(value):
                # 同一字段只报一次：一个列表端点能重复上千条，刷屏会淹掉别的违规。
                hits.setdefault((template, path), token)
    assert not hits, (
        f"{len(hits)} 个响应字段是裸时间戳：前端 new Date() 会按本地时间解析（北京早 8 小时）。\n"
        + "\n".join(f"  {tpl} {path} = {token!r}" for (tpl, path), token in sorted(hits.items()))
    )


def test_utc_z_response_class_is_installed(app_module):
    """兜住这条约定的机制本身也要有守卫：默认响应类被换掉，上面那条会静默失去意义。

    注意属性位置：``FastAPI(default_response_class=...)`` 存的是
    ``app.router.default_response_class``，**app 对象上没有这个属性**（早先按
    ``app.default_response_class`` 断言直接 AttributeError，看着像约定崩了其实
    是守卫写错）。这里再让 render() 实跑一次，防止「类换对了但没补 Z」。
    """
    import json

    from utils.response import UtcZJSONResponse

    assert app_module.router.default_response_class is UtcZJSONResponse
    payload = {"items": [{"created_at": "2026-10-16T16:00:00"}]}
    assert json.loads(UtcZJSONResponse(payload).render(payload)) == {
        "items": [{"created_at": "2026-10-16T16:00:00Z"}]
    }


# --------------------------------------------------------------------------- #
# 2. 字段命名：snake_case
# --------------------------------------------------------------------------- #

#: 允许的大写键：真缩写与技术标识不是 camelCase。
_CAMEL_ALLOW = {
    "id", "fs_id", "API", "URL", "OCR", "AI", "PDF", "GPS", "HTTP", "LLM",
}


def test_no_camel_case_keys_in_get_responses(client, conventions_cases):
    bad = []
    for template, url in conventions_cases:
        if template in SKIP_PATHS:
            continue
        resp, body = _call(client, url)
        if body is None or resp.status_code >= 400:
            continue
        for path, key, _value in _walk(body):
            if key in _CAMEL_ALLOW or not isinstance(key, str):
                continue
            if _CAMEL_KEY_RE.search(key):
                bad.append(f"  {template} {path}")
    assert not bad, "响应键名出现 camelCase，违反 snake_case 约定：\n" + "\n".join(sorted(set(bad)))


# --------------------------------------------------------------------------- #
# 3. 分页
# --------------------------------------------------------------------------- #

def _query_params(op, names):
    return [
        p for p in op.get("parameters", [])
        if p.get("in") == "query" and p.get("name") in names
    ]


def test_page_size_always_capped(app_module, get_ops):
    """凡是 page_size / limit 入参，必须有上限，且不超过 MAX_PAGE_SIZE。"""
    bad = []
    for template, op in get_ops.items():
        for param in _query_params(op, {"page_size", "limit", "num", "size"}):
            schema = param.get("schema") or {}
            maximum = schema.get("maximum")
            if maximum is None:
                bad.append(f"  {template}?{param['name']} 无上限校验")
            elif maximum > MAX_PAGE_SIZE:
                bad.append(f"  {template}?{param['name']} 上限 {maximum} > {MAX_PAGE_SIZE}")
    assert not bad, (
        f"{len(bad)} 处分页入参可被拖穿（page_size=100000 直接进 SQL LIMIT）：\n"
        + "\n".join(sorted(set(bad)))
    )


def test_items_always_paired_with_total(client, conventions_cases, get_ops):
    """返回 items 列表的端点必须同时给 total，前端才知道有没有下一页。"""
    bad = []
    for template, url in conventions_cases:
        if template in SKIP_PATHS:
            continue
        if not _query_params(get_ops[template], {"page", "page_size", "limit", "offset"}):
            continue
        resp, body = _call(client, url)
        if body is None or resp.status_code >= 400 or not isinstance(body, dict):
            continue
        if "items" in body and "total" not in body:
            bad.append(f"  {template} 有 items 无 total")
    assert not bad, "翻页响应缺 total：\n" + "\n".join(sorted(set(bad)))


# --------------------------------------------------------------------------- #
# 4. 错误壳
# --------------------------------------------------------------------------- #

def test_error_responses_use_code_message_shell(client, conventions_cases):
    """非 2xx 必须是 {code, message}，不许裸 detail —— 前端要能按 code 分支。"""
    bad = []
    for template, url in conventions_cases:
        if template in SKIP_PATHS:
            continue
        resp, body = _call(client, url)
        if resp.status_code < 400:
            continue
        if not isinstance(body, dict) or "code" not in body or "message" not in body:
            bad.append(f"  {template} -> {resp.status_code} {str(body)[:120]}")
    assert not bad, f"{len(bad)} 个错误响应不合错误壳：\n" + "\n".join(sorted(set(bad)))
