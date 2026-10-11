"""
全局 HTTP 客户端单例 V3.0
解决：每次请求新建 httpx.AsyncClient 导致连接池失效、延迟增加 100-300ms
"""
import httpx
from contextlib import asynccontextmanager

# 全局单例客户端，连接池复用
_global_client = None
_global_async_client = None

# 连接池配置
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
DEFAULT_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30.0,
)


def get_client() -> httpx.Client:
    """获取同步 HTTP 客户端单例"""
    global _global_client
    if _global_client is None:
        _global_client = httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            limits=DEFAULT_LIMITS,
            follow_redirects=True,
        )
    return _global_client


def get_async_client() -> httpx.AsyncClient:
    """获取异步 HTTP 客户端单例"""
    global _global_async_client
    if _global_async_client is None:
        _global_async_client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=DEFAULT_LIMITS,
            follow_redirects=True,
        )
    return _global_async_client


@asynccontextmanager
async def async_client():
    """异步客户端上下文管理器（复用全局单例，不关闭）"""
    client = get_async_client()
    try:
        yield client
    finally:
        # 不关闭全局客户端，保持连接池
        pass


def close_clients():
    """应用关闭时关闭所有客户端"""
    global _global_client, _global_async_client
    if _global_client is not None:
        _global_client.close()
        _global_client = None
    if _global_async_client is not None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_global_async_client.aclose())
            else:
                loop.run_until_complete(_global_async_client.aclose())
        except Exception:
            pass
        _global_async_client = None
