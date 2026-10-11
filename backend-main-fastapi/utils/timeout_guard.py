"""请求超时守卫中间件（通用保险）。

背景
----
2026-xx 的一次线上事故：`GET /api/storage/scan` 在 async 路由里同步跑全盘扫描，
耗时 77~145 秒，把事件循环完全占满 —— 期间 asyncio 连 `accept` 都做不了，
所有其他请求（包括 `/api/health`）全部超时，表现为"服务假死/看起来崩溃"。

单点修复那个接口只是治标。本中间件是**通用兜底**：任何单个慢接口
都不会再无限拖住请求方，会在阈值到达时主动返回 504 并记录日志。

为什么用「裸 ASGI 中间件」而不是 BaseHTTPMiddleware
---------------------------------------------------
项目里有 SSE 长连接（``routers/ai.py`` 的 ``POST /api/chat/stream``，
``media_type="text/event-stream"``）。``BaseHTTPMiddleware`` 会介入响应体
的传递，历史上多次出现「把流式响应缓冲住 / 破坏分块」的问题。

裸 ASGI 实现可以做到**完全不碰响应体**：
- 本中间件只观察 ``http.response.start`` 消息（即响应头）何时发出；
- 一旦响应头已发出，就说明这是一个（可能是流式的）正常响应，
  守卫立刻退化为「透明放行」，**无限等待也不干预**；
- 只有在「响应头都还没发出去」且「已超阈值」时，才回一个 504。

这样SSE 长连接天然免疫：它的响应头是立即发出的，之后哪怕流持续几十分钟，
守卫也完全不会干预。

阈值配置（环境变量）
--------------------
- ``API_TIMEOUT_GET_SECONDS``  ：GET/HEAD 等读请求，默认 **30** 秒
- ``API_TIMEOUT_WRITE_SECONDS``：POST/PUT/PATCH/DELETE 等写请求，默认 **60** 秒
- ``API_TIMEOUT_EXEMPT_PATHS`` ：逗号分隔的路径前缀白名单，命中则完全豁免
- ``API_TIMEOUT_ENABLED``      ：设为 ``0`` / ``false`` 可整体关闭
"""

import asyncio
import logging
import os
import time
from typing import Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

DEFAULT_GET_TIMEOUT = 30.0
DEFAULT_WRITE_TIMEOUT = 60.0

#: 按路径前缀的专用超时映射（不是完全豁免：仍保留卡死保护，只是阈值更宽）。
#: V11 答疑接口在 CPU 上要跑改写/检索/rerank/生成/自检，默认 60s 会 504。
DEFAULT_PATH_TIMEOUTS = {
    # T4 电路读图链：qwen2.5vl VLM 载入 + OCR + 改写/检索/rerank + 生成，
    # 且本地常与批量答案回填共用 8GB 显存（模型互换挤兑），180s 实测不够 → 放宽到 300s
    "/api/ai/chat/router": 300.0,
    # T5 定向采集：每校 robots 检查 + 列表页 + 栏目跟进 + 2-5s 礼貌延迟，
    # 12 所实测 >60s。采集是后台性质操作，放宽到 10 分钟
    # A6 答案交叉校验：LLM 独立重做，单批 50 题实测 11~509s，60s 默认写超时触发 504 -> 放宽到 600s
    "/api/answers/check-batch": 600.0,
    "/api/kaoyan/collection/refresh": 600.0,
}

# 写方法（比读更宽松：入库/AI 生成等操作本来就慢）
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# 默认豁免前缀：SSE 流式对话、文档流式解析等长连接
_DEFAULT_EXEMPT_PREFIXES = (
    "/api/ai/chat/stream",
    "/api/chat/stream",
)


def _env_float(name: str, default: float) -> float:
    """读取 float 型环境变量，非法值回退到 default。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"{name}={raw!r} 不是合法数字，回退默认值 {default}")
        return default
    return value if value > 0 else default


def _env_bool(name: str, default: bool = True) -> bool:
    """读取 bool 型环境变量，接受 1/0/true/false/yes/no/on/off（大小写不敏感）。"""
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def load_exempt_prefixes() -> Set[str]:
    """加载豁免路径前缀集合。"""
    extra: Iterable[str] = (os.getenv("API_TIMEOUT_EXEMPT_PATHS", "") or "").split(",")
    return {p.strip() for p in extra if p.strip()} | set(_DEFAULT_EXEMPT_PREFIXES)


class TimeoutGuardMiddleware:
    """裸 ASGI 请求超时守卫。

    用法::

        app.add_middleware(TimeoutGuardMiddleware)
    """

    def __init__(
        self,
        app,
        get_timeout: Optional[float] = None,
        write_timeout: Optional[float] = None,
        exempt_prefixes: Optional[Set[str]] = None,
    ) -> None:
        self.app = app
        self.get_timeout = (
            get_timeout if get_timeout is not None else _env_float(
                "API_TIMEOUT_GET_SECONDS", DEFAULT_GET_TIMEOUT)
        )
        self.write_timeout = (
            write_timeout if write_timeout is not None else _env_float(
                "API_TIMEOUT_WRITE_SECONDS", DEFAULT_WRITE_TIMEOUT)
        )
        self.exempt_prefixes = exempt_prefixes if exempt_prefixes is not None else load_exempt_prefixes()
        self.path_timeouts = dict(DEFAULT_PATH_TIMEOUTS)
        self._load_env_path_timeouts()
        self.enabled = _env_bool("API_TIMEOUT_ENABLED", True)

    def _load_env_path_timeouts(self) -> None:
        """读 ``API_TIMEOUT_PATH_MAP``（形如 ``/api/ai/chat/router=180,/x=30``）覆盖默认映射。"""
        raw = (os.getenv("API_TIMEOUT_PATH_MAP", "") or "").strip()
        if not raw:
            return
        for item in raw.split(","):
            item = item.strip()
            if "=" not in item:
                continue
            path, _, val = item.partition("=")
            path = path.strip()
            try:
                secs = float(val)
            except ValueError:
                continue
            if path and secs > 0:
                self.path_timeouts[path] = secs

    def _timeout_for(self, method: str, path: str = "") -> float:
        """先按路径前缀取专用阈值；否则按 HTTP 方法选择。未知方法按读请求处理。"""
        if path:
            for prefix, secs in self.path_timeouts.items():
                if path == prefix or path.startswith(prefix):
                    return secs
        return self.write_timeout if method.upper() in WRITE_METHODS else self.get_timeout

    @staticmethod
    def _is_exempt(path: str, prefixes: Set[str]) -> bool:
        """路径是否命中豁免前缀（支持前缀与精确匹配）。"""
        return any(path == p or path.startswith(p) for p in prefixes)

    async def __call__(self, scope, receive, send) -> None:
        # 非 HTTP 范围（lifespan / websocket）直接透传
        if scope.get("type") != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if self._is_exempt(path, self.exempt_prefixes):
            await self.app(scope, receive, send)
            return

        timeout = self._timeout_for(scope.get("method", "GET"), path)
        method: str = scope.get("method", "GET")
        started_at = time.monotonic()
        # 是否已经发出过响应头。一旦为 True，守卫立刻退化为透明放行，
        # 绝不打断已经开始输出的响应（尤其是 SSE 流）。
        response_started = False

        async def send_wrapper(message) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        app_task = asyncio.ensure_future(self.app(scope, receive, send_wrapper))
        try:
            await asyncio.wait_for(asyncio.shield(app_task), timeout=timeout)
        except asyncio.TimeoutError:
            if response_started:
                # 响应头已经发出（很可能是长连接/SSE），此时无法再改成 504，
                # 只能继续等待——这正是 SSE 需要的行为。
                logger.warning(
                    f"请求超时但响应已开始传输，跳过超时中断: {method} {path}"
                )
                await app_task
                return

            # 响应尚未开始：取消下游任务并回 504
            app_task.cancel()
            try:
                await app_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            elapsed = (time.monotonic() - started_at) * 1000
            logger.error(
                f"请求超时，已中断并返回 504: {method} {path} - "
                f"超过阈值 {timeout:.0f}s（实际 {elapsed:.1f}ms）"
            )
            await self._send_gateway_timeout(send, method, path, timeout, elapsed)
        except asyncio.CancelledError:
            # 客户端主动断开：透传取消
            app_task.cancel()
            raise
        except Exception:
            # 下游异常：确保不留下悬挂任务
            if not app_task.done():
                app_task.cancel()
            raise

    @staticmethod
    async def _send_gateway_timeout(send, method: str, path: str, timeout: float, elapsed_ms: float) -> None:
        """发送一个符合 HTTP 规范的 504 Gateway Timeout 响应。"""
        import json

        body = json.dumps({
            "detail": (
                f"请求处理超时（阈值 {timeout:.0f}秒），已中断。"
                "该接口耗时异常，请查看服务端日志定位慢查询。"
            ),
            "error": "request_timeout",
            "method": method,
            "path": path,
            "timeout_seconds": timeout,
            "elapsed_ms": round(elapsed_ms, 1),
        }, ensure_ascii=False).encode("utf-8")

        await send({
            "type": "http.response.start",
            "status": 504,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("latin-1")),
                (b"connection", b"close"),
            ],
        })
        await send({"type": "http.response.body", "body": body})


def timeout_for_method(method: str, path: str = "") -> float:
    """对外暴露：查询某方法/路径对应的超时阈值（诊断/测试用）。"""
    guard = TimeoutGuardMiddleware(app=None)
    return guard._timeout_for(method, path)  # noqa: SLF001