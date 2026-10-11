"""
统一异常处理
- 全局异常处理器
- 统一错误响应格式
- 业务错误码定义
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Any, Optional


# 业务错误码
class ErrorCode:
    # 通用错误 1000-1999
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"

    # AI 相关 2000-2999
    AI_PROVIDER_NOT_FOUND = "AI_PROVIDER_NOT_FOUND"
    AI_PROVIDER_DISABLED = "AI_PROVIDER_DISABLED"
    AI_REQUEST_FAILED = "AI_REQUEST_FAILED"
    AI_TIMEOUT = "AI_TIMEOUT"

    # 知识库相关 3000-3999
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    DOCUMENT_PARSE_FAILED = "DOCUMENT_PARSE_FAILED"
    CHUNK_NOT_FOUND = "CHUNK_NOT_FOUND"

    # 学习相关 4000-4999
    WORD_NOT_FOUND = "WORD_NOT_FOUND"
    DECK_NOT_FOUND = "DECK_NOT_FOUND"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    ERROR_NOT_FOUND = "ERROR_NOT_FOUND"
    CARD_NOT_FOUND = "CARD_NOT_FOUND"

    # 网盘相关 5000-5999
    NETDISK_NOT_AUTHORIZED = "NETDISK_NOT_AUTHORIZED"
    NETDISK_SYNC_FAILED = "NETDISK_SYNC_FAILED"
    NETDISK_FILE_NOT_FOUND = "NETDISK_FILE_NOT_FOUND"


class BusinessException(Exception):
    """业务异常基类"""
    def __init__(
        self,
        code: str = ErrorCode.UNKNOWN_ERROR,
        message: str = "未知错误",
        detail: Optional[Any] = None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ):
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code
        super().__init__(message)


def create_error_response(
    code: str,
    message: str,
    detail: Optional[Any] = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> JSONResponse:
    """创建统一错误响应"""
    body = {
        "code": code,
        "message": message,
    }
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app):
    """注册全局异常处理器"""

    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        """业务异常处理"""
        from utils.logger import error as log_error
        log_error(f"业务异常 [{exc.code}]: {exc.message} | path={request.url.path}")
        return create_error_response(
            code=exc.code,
            message=exc.message,
            detail=exc.detail,
            status_code=exc.status_code,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """HTTP 异常处理"""
        code_map = {
            400: ErrorCode.INVALID_PARAMETER,
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.RESOURCE_NOT_FOUND,
            409: ErrorCode.CONFLICT,
            429: ErrorCode.RATE_LIMITED,
        }
        code = code_map.get(exc.status_code, ErrorCode.UNKNOWN_ERROR)
        # 结构化 detail 要原样保留（如网盘返回的
        # {message, errno, action:"reauthorize"}）——
        # 之前一律 str() 会把字典压成一个字符串，前端只能看到一坨文本，
        # 无法据此判断"需要重新授权"并引导用户。
        if isinstance(exc.detail, str):
            message = exc.detail
            detail = None
        elif isinstance(exc.detail, dict):
            message = exc.detail.get("message") or exc.detail.get("detail") or str(exc.detail)
            detail = exc.detail
        else:
            message = str(exc.detail)
            detail = None

        if exc.status_code >= 500:
            from utils.logger import error as log_error
            log_error(f"HTTP异常 [{exc.status_code}]: {message} | path={request.url.path}")

        return create_error_response(
            code=code,
            message=message,
            status_code=exc.status_code,
            detail=detail,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """请求参数校验异常处理"""
        from utils.logger import warning as log_warning
        errors = []
        for err in exc.errors():
            errors.append({
                "field": ".".join(str(loc) for loc in err.get("loc", []) if loc != "body"),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            })

        log_warning(f"参数校验失败: {errors} | path={request.url.path}")
        return create_error_response(
            code=ErrorCode.INVALID_PARAMETER,
            message="请求参数校验失败",
            detail={"errors": errors},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """未处理异常兜底"""
        from utils.logger import exception as log_exception
        log_exception(f"未处理异常 | path={request.url.path} | method={request.method}")
        return create_error_response(
            code=ErrorCode.UNKNOWN_ERROR,
            message="服务器内部错误",
            detail={"type": type(exc).__name__},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
