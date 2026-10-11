"""
字段命名自动转换中间件
- 请求头 X-Response-Camel-Case: true 时，响应字段自动转为 camelCase
- 默认不启用（保持向后兼容），新接口可逐步迁移
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import json

from utils.response import to_camel


class CamelCaseResponseMiddleware(BaseHTTPMiddleware):
    """响应字段自动转为 camelCase 的中间件。

    使用方式：
    - 请求头添加 `X-Response-Camel-Case: true`
    - 响应中的 JSON 字段会自动从 snake_case 转为 camelCase

    注意：
    - 仅对 application/json 响应生效
    - 默认不启用，保持向后兼容
    - 前端逐步迁移后可默认启用
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 检查请求头是否要求 camelCase
        use_camel = request.headers.get("X-Response-Camel-Case", "").lower() == "true"
        if not use_camel:
            return response

        # 仅处理 JSON 响应
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # 读取响应体
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            data = json.loads(body.decode("utf-8"))
            # 递归转换键名
            converted = to_camel(data)
            new_body = json.dumps(converted, ensure_ascii=False).encode("utf-8")

            # 构建新响应
            new_response = Response(
                content=new_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="application/json",
            )
            # 更新 content-length
            new_response.headers["content-length"] = str(len(new_body))
            return new_response

        except (json.JSONDecodeError, UnicodeDecodeError):
            # 解析失败，返回原始响应
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=content_type,
            )
