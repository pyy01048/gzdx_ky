"""接口响应约定（P1-底座C · #19）。

三条契约在这一处实现，378 个端点不必各写一遍。

1. **时间格式**：可解析的时间一律 ISO 8601、UTC、带 ``Z``；纯日期是 ``YYYY-MM-DD``。
   库里存的是 naive UTC 瞬时（:mod:`utils.timeutil`），FastAPI 默认编码出来是
   ``2026-10-16T16:00:00`` —— 不带偏移。JS 的 ``Date`` 按规范把这种"无偏移的
   date-time"当**本地时间**解析，于是北京用户看到的"下次复习时间"比真实值早
   8 小时（``frontend/src/pages/ErrorReview.jsx`` 的
   ``new Date(v).toLocaleString('zh-CN')`` 就踩在这条路上）。
   在渲染层统一补 ``Z``，比逐个端点改序列化器可靠：漏一个就是线上错 8 小时。
   只补"形状像 ISO date-time 且没有偏移"的串；``2026-10-17 08:00:00`` 这类
   空格分隔的展示串不匹配，不会被误标成 UTC。

2. **分页壳**：``{items, total, page, page_size, total_pages}``，入参一律
   ``page`` / ``page_size``（从 1 起）且带上下限校验 —— 原先十几处
   ``page_size: int = 20`` 裸默认值不校验，传 ``page_size=100000`` 就能把库拖穿。

3. **字段命名**：一律 snake_case。原先按 ``X-Response-Camel-Case`` 请求头切换的
   camelCase 中间件已删除：前端从不发这个头，留一套"隐藏的第二命名"只会让接口
   文档和前端类型各写两份。

错误响应壳在 :mod:`utils.exceptions`（``{code, message, detail}``）。成功 = 资源本体
或分页壳，失败 = 固定三键。这里**不再**提供 ``success_response`` / ``data`` 信封 ——
两套成功壳并存等于没有壳。
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable, List, Optional

from fastapi import Query
from fastapi.responses import JSONResponse

# --------------------------------------------------------------------------- #
# 1. 时间格式：给无偏移的 ISO date-time 补 Z
# --------------------------------------------------------------------------- #

#: ``YYYY-MM-DDTHH:MM[:SS[.ffffff]]``，尾部既没有 Z 也没有 +HH:MM。
_NAIVE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d{1,6})?$")

#: TIMESTAMPTZ 列（``users.last_login_at`` 等）经 FastAPI 默认编码后带 ``+00:00``
#: 零偏移而非 ``Z``，与上面的 naive 补 Z 混用会让"全站时间统一"约定破功
#: （同一字段族两种形状）。这里把 UTC 零偏移一并收敛成 ``Z``。
#: 非零偏移（如 +08:00）是真实本地时区，语义不同，**不**改写，避免篡改时刻。
_ISO_UTC_OFFSET_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d{1,6})?)\+00:00$"
)


def to_utc_z(value: str) -> str:
    """单个字符串补 ``Z``；不是 naive/UTC-零偏移 ISO date-time 就原样返回。"""
    m = _ISO_UTC_OFFSET_RE.match(value)
    if m:
        return f"{m.group(1)}Z"
    return f"{value}Z" if _NAIVE_ISO_RE.match(value) else value


def stamp_utc_z(node: Any) -> Any:
    """递归处理已 jsonable 化的响应树（dict / list / str），只改值不改键。"""
    if isinstance(node, str):
        return to_utc_z(node)
    if isinstance(node, dict):
        return {key: stamp_utc_z(val) for key, val in node.items()}
    if isinstance(node, list):
        return [stamp_utc_z(val) for val in node]
    return node


class UtcZJSONResponse(JSONResponse):
    """本项目所有 JSON 响应的默认类：渲染前把 naive UTC 串标成 ``Z``。"""

    def render(self, content: Any) -> bytes:
        return super().render(stamp_utc_z(content))


# --------------------------------------------------------------------------- #
# 2. 分页
# --------------------------------------------------------------------------- #

#: ``page_size`` 上限：接口层的硬闸，防止一次请求把整表拉进内存。
MAX_PAGE_SIZE = 200


def page_params(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE, description="每页条数"),
) -> dict:
    """分页入参唯一入口：``params: dict = Depends(page_params)``。

    返回 ``{"page", "page_size", "offset", "limit"}``，路由里直接用，
    ge/le 校验不再各写一遍。配合 :func:`paginate_query` 时记得摊开成关键字：
    ``paginate_query(q, **params)``（``offset``/``limit`` 会被它忽略）。
    """
    return {
        "page": page,
        "page_size": page_size,
        "offset": (page - 1) * page_size,
        "limit": page_size,
    }


class PaginatedResponse:
    """分页响应包装器。

    ``items`` 必须是**已序列化**的 dict 列表：SQLAlchemy 行对象直接塞进来，
    JSON 渲染会当场报错 —— 这也是本工具长期没被路由采用的原因。需要换算就用
    :func:`paginate_query` 的 ``serialize`` 参数。
    """

    def __init__(self, items: List[Any], total: int, page: int = 1, page_size: int = 20):
        self.items = items
        self.total = total
        self.page = page
        self.page_size = page_size
        self.total_pages = math.ceil(total / page_size) if page_size > 0 else 0

    def dict(self) -> dict:
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
        }


def paginate_query(
    query,
    page: int = 1,
    page_size: int = 20,
    max_page_size: int = MAX_PAGE_SIZE,
    serialize: Optional[Callable[[Any], Any]] = None,
) -> PaginatedResponse:
    """对 SQLAlchemy 查询分页，给出统一壳。

    Args:
        query: SQLAlchemy 查询对象
        page: 页码（从 1 起，非法值收敛到 1）
        page_size: 每页数量（收敛到 ``1..max_page_size``）
        max_page_size: 每页上限
        serialize: 行对象 → 可 JSON 化的 dict；不传则原样交出
    """
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), max_page_size))

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [serialize(r) for r in rows] if serialize else list(rows)
    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)
