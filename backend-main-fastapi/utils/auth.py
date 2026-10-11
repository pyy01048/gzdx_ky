"""
简单认证系统（可选启用）
- 默认不启用（保持向后兼容）
- 在 .env 中配置 APP_PASSWORD 后启用
- 前端登录页面输入密码，存储到 localStorage
- 所有 API 请求携带 X-App-Password 头
"""
import os
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware


# 从环境变量读取密码（为空则不启用认证）
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
AUTH_ENABLED = bool(APP_PASSWORD)

# 不需要认证的路径（白名单）
PUBLIC_PATHS = [
    "/api/auth/login",
    "/api/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
    "/",
]


def is_public_path(path: str) -> bool:
    """判断路径是否在白名单中"""
    for public in PUBLIC_PATHS:
        if path == public or path.startswith(public + "/"):
            return True
    # 静态文件
    if path.startswith("/assets/") or path.endswith((".js", ".css", ".png", ".jpg", ".ico", ".svg")):
        return True
    return False


def verify_password(password: str) -> bool:
    """验证密码"""
    if not AUTH_ENABLED:
        return True
    return password == APP_PASSWORD


class SimpleAuthMiddleware(BaseHTTPMiddleware):
    """简单密码认证中间件（可选启用）"""

    async def dispatch(self, request: Request, call_next):
        # 认证未启用，直接放行
        if not AUTH_ENABLED:
            return await call_next(request)

        path = request.url.path

        # 白名单路径放行
        if is_public_path(path):
            return await call_next(request)

        # 非 API 路径（前端页面）放行，由前端路由处理认证
        if not path.startswith("/api/"):
            return await call_next(request)

        # 验证密码
        password = request.headers.get("X-App-Password", "")
        if not password:
            # 也支持 query 参数
            password = request.query_params.get("password", "")

        if not verify_password(password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="密码错误或未提供认证，请先登录",
            )

        return await call_next(request)


def get_auth_status() -> dict:
    """获取认证状态（供前端查询）"""
    return {
        "enabled": AUTH_ENABLED,
        "message": "认证已启用，请输入密码登录" if AUTH_ENABLED else "认证未启用，可直接使用",
    }
