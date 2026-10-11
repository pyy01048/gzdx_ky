"""版本无关的同步 ASGI 测试客户端。

为什么不用 ``fastapi.testclient.TestClient``：
    本机环境 starlette==0.27.0 搭配 httpx==0.28.1，而 starlette 0.27 的
    ``TestClient.__init__`` 会向 ``httpx.Client.__init__`` 传 ``app=`` 参数，
    该参数在 httpx 0.28 中已被移除，于是实例化直接抛
    ``TypeError: Client.__init__() got an unexpected keyword argument 'app'``。
    requirements.txt 里锁的是 httpx==0.25.2，实际装的是 0.28.1（版本漂移）。

本模块用 httpx 官方推荐的 ``ASGITransport`` + ``AsyncClient`` 自己实现一个
**同步** 门面，因此：
  * 不需要改动用户环境（不降级 / 不升级任何依赖）；
  * httpx >= 0.21 均可工作，未来升级 starlette/httpx 也不会再次失效。

用法::

    client = ASGIClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional

import httpx

__all__ = ["ASGIClient", "ASGIResponse"]


# httpx.Response 的别名，仅为可读性
ASGIResponse = httpx.Response

# 单个请求的默认超时（秒）。契约测试另有更严格的耗时断言，这里只兜底"别卡死"。
_DEFAULT_TIMEOUT = 30.0


class ASGIClient:
    """同步门面，内部用 ``httpx.AsyncClient`` + ``ASGITransport`` 直连 ASGI 应用。

    与 ``starlette.testclient.TestClient`` 的差异：
      * **不触发 lifespan / startup 事件**（不启后台调度器、不做每日备份）——
        契约测试只关心"路由能否正确响应"，副作用越少越好；
      * ``raise_app_exceptions=False``：未捕获异常会被应用的全局异常处理器
        转成 500 JSON 响应返回，而不是把异常抛到测试里，便于断言"不许有 5xx"。
    """

    def __init__(
        self,
        app: Any,
        base_url: str = "http://qa-testserver",
        raise_server_exceptions: bool = False,
        timeout: float = _DEFAULT_TIMEOUT,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.app = app
        self.base_url = base_url
        self.raise_server_exceptions = raise_server_exceptions
        self.timeout = timeout
        self._extra_headers = dict(headers or {})
        self._loop = asyncio.new_event_loop()
        self._lock = threading.Lock()
        self._closed = False

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _run(self, coro):
        """在专用事件循环里执行协程（加锁，避免并发调用同一个 loop）。"""
        with self._lock:
            return self._loop.run_until_complete(coro)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        content: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """发起一次同步请求并返回 ``httpx.Response``。"""
        if self._closed:
            raise RuntimeError("ASGIClient 已关闭")

        merged_headers = {"user-agent": "qa-contract-test"}
        merged_headers.update(self._extra_headers)
        merged_headers.update(headers or {})

        transport = httpx.ASGITransport(
            app=self.app,
            raise_app_exceptions=self.raise_server_exceptions,
        )

        async def _do() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=transport,
                base_url=self.base_url,
                timeout=self.timeout,
                headers=merged_headers,
                follow_redirects=True,
            ) as client:
                return await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    content=content,
                )

        return self._run(_do())

    # ------------------------------------------------------------------ #
    # HTTP 动词快捷方式
    # ------------------------------------------------------------------ #
    def get(self, url: str, **kw) -> httpx.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> httpx.Response:
        return self.request("POST", url, **kw)

    def put(self, url: str, **kw) -> httpx.Response:
        return self.request("PUT", url, **kw)

    def delete(self, url: str, **kw) -> httpx.Response:
        return self.request("DELETE", url, **kw)

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._loop.close()
            except Exception:  # noqa: BLE001 - loop 可能已在别处关闭
                pass

    def __enter__(self) -> "ASGIClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
