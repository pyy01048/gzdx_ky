"""
传输层优化中间件
- GZipApiMiddleware：选择性 gzip 压缩（保护 SSE 流与二进制分段下载）
- StaticCacheControlMiddleware：静态资源缓存头（hashed 资产 immutable / HTML no-cache）

原先这里还有一个 CamelCaseResponseMiddleware（按 X-Response-Camel-Case 请求头把
响应键名改成 camelCase），已删除：前端从不发这个头，而"同一套接口两套键名"会让
接口文档和前端类型各写一份。字段命名约定见 utils/response.py —— 一律 snake_case。
"""
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.gzip import GZipResponder
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# --------------------------------------------------------------------------- #
# GZip 压缩（选择性）
# --------------------------------------------------------------------------- #
# 为什么不直接用 starlette 的 GZipMiddleware（2026-10 实测）：
#   1. **SSE 流会被卡死**：starlette 0.27 的 GZipResponder 对流式响应的每个
#      分块只写 gzip 流、从不 flush，zlib 内部缓冲导致小分块（SSE 事件）
#      在流结束前**一个字节都发不出去**（裸 ASGI 驱动实测：前两个事件的
#      压缩输出为空 body，全部字节直到流关闭才 flush）。/api/ai/chat/stream
#      是长连接，直接套原生中间件等于把 AI 对话打到流末尾才可见。
#   2. **二进制/分段下载会被破坏**：206 分段响应带 Content-Length 与
#      Content-Range，原生实现会删掉 Content-Length 并改码，视频 seek、
#      PDF Range 加载直接错位；PDF/视频等已压缩内容再 gzip 一遍纯耗 CPU。
# 因此这里只对"文本类、非流式事件、非 206"的响应启用压缩，复用 starlette 的
# GZipResponder 完成真正的压缩逻辑（含 minimum_size 判定）。
_GZIP_MEDIA_PREFIXES = (
    "text/",
    "application/json",
    "application/javascript",
    "application/xml",
    "image/svg+xml",
)
#: SSE 长连接：压缩会把事件卡到流末尾，一律放行（与 timeout_guard 同一理由）
_GZIP_EXCLUDED_MEDIA_PREFIXES = ("text/event-stream",)


class _ApiGZipResponder(GZipResponder):
    """带准入判断的 GZipResponder：不压缩的响应原样透传（借父类分支实现）。"""

    async def send_with_gzip(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            media = Headers(raw=message["headers"]).get("content-type", "")
            excluded = media.startswith(_GZIP_EXCLUDED_MEDIA_PREFIXES)
            compressible = media.startswith(_GZIP_MEDIA_PREFIXES)
            if excluded or not compressible or message["status"] == 206:
                # 立即放行起始消息，并置位 content_encoding_set 借用父类的
                # "已设置 Content-Encoding" 透传分支，后续 body 原样转发。
                self.started = True
                self.content_encoding_set = True
                await self.send(message)
                return
        await super().send_with_gzip(message)


class GZipApiMiddleware:
    """选择性 GZip 压缩中间件（裸 ASGI，不缓冲响应体）。

    仅当请求带 ``Accept-Encoding: gzip`` 且响应为文本类、非 SSE、非 206 时
    压缩（``minimum_size`` 以下不压缩）。其余响应（二进制文件流、视频分段、
    SSE 事件流）零开销透传。
    """

    def __init__(self, app: ASGIApp, minimum_size: int = 1000, compresslevel: int = 6):
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and "gzip" in Headers(scope=scope).get("accept-encoding", ""):
            responder = _ApiGZipResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel
            )
            await responder(scope, receive, send)
            return
        await self.app(scope, receive, send)


# --------------------------------------------------------------------------- #
# 静态资源缓存头
# --------------------------------------------------------------------------- #
#: Vite 构建产物的 hashed 资产目录（内容哈希进文件名，内容永不变）
_STATIC_ASSET_PREFIX = "/assets/"


class StaticCacheControlMiddleware:
    """静态资源 Cache-Control 中间件（裸 ASGI，只改响应头、不触碰响应体）。

    - ``/assets/*``（hashed 资产，200）：``public, max-age=31536000, immutable``；
    - HTML 响应（index.html / SPA fallback / docs）：``no-cache``，保证发版后
      浏览器立刻拿到新入口，而不是拿旧的 index.html 指向已删除的资产；
    - 已自带 Cache-Control 的响应（如文档下载的 no-cache）不覆盖。
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_hashed_asset = path.startswith(_STATIC_ASSET_PREFIX)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message["headers"])
                if is_hashed_asset and message["status"] == 200:
                    headers.setdefault(
                        "Cache-Control", "public, max-age=31536000, immutable"
                    )
                elif not headers.get("cache-control") and Headers(
                    raw=message["headers"]
                ).get("content-type", "").startswith("text/html"):
                    headers.setdefault("Cache-Control", "no-cache")
            await send(message)

        await self.app(scope, receive, send_wrapper)
