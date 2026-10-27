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
    #: 网关级超时：中间件在路由之外直接写 ASGI 响应，异常处理器接不到。
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    #: 依赖不可用导致请求被**主动拒绝**（如写前备份做不成）。
    #: 503 原先落进 UNKNOWN_ERROR，前端无法区分"服务坏了"和"服务故意挡下"。
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

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


#: HTTP 状态码 -> 业务错误码。
_CODE_BY_STATUS = {
    400: ErrorCode.INVALID_PARAMETER,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.RESOURCE_NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.INVALID_PARAMETER,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.SERVICE_UNAVAILABLE,
    504: ErrorCode.REQUEST_TIMEOUT,
}


def http_error_response(
    status_code: int,
    detail: Any,
    *,
    headers: Optional[dict] = None,
) -> JSONResponse:
    """把 HTTP 层的 ``detail`` 归一成错误壳 ``{code, message, detail?}``。

    为什么单列一个函数：404 由 main.py 的 SPA fallback 处理器自己返回（要给
    前端路由吐 index.html），416 由 documents.py 自己返回（要带 Content-Range
    头，而全局处理器传不了头）。两处原先各写一份 ``{"detail": ...}``，于是
    「同一个接口体系两种错误壳」——前端只能 ``data.detail || data.message``
    两个都试。收敛到这里后，任何绕过全局处理器的返回点也天然合规。

    结构化 detail（如网盘的 ``{message, errno, action:"reauthorize"}``）原样
    保留在 ``detail`` 里，只把其中的 ``message`` 提到顶层，不重复一份。
    """
    code = _CODE_BY_STATUS.get(status_code, ErrorCode.UNKNOWN_ERROR)
    if isinstance(detail, str):
        message, extra = detail, None
    elif isinstance(detail, dict):
        message = detail.get("message") or detail.get("detail") or str(detail)
        extra = {k: v for k, v in detail.items() if k != "message"} or None
    elif detail is None:
        message, extra = f"HTTP {status_code}", None
    else:
        message, extra = str(detail), None
    body: dict = {"code": code, "message": message}
    if extra is not None:
        body["detail"] = extra
    return JSONResponse(status_code=status_code, content=body, headers=headers)


# 疑似泄露内部实现的错误文案标记。命中这些的子串说明 detail 里混进了
# 数据库驱动/ORM 的原始报错（含 SQL、表名、列名、连接信息、traceback），
# 必须脱敏后再回前端——否则等于把库结构免费送给任何能调接口的人。
_SQL_LEAK_MARKERS = (
    "psycopg", "asyncpg", "sqlalchemy", "DETAIL:", "relation ",
    "violates", "duplicate key", "foreign key constraint", "unique constraint",
    "Traceback", "IntegrityError", "ProgrammingError", "OperationalError",
    "UndefinedTable", "UndefinedColumn", "could not connect",
    "connection refused", "FATAL:", "SSL error", "server closed",
    "deadlock detected", "operator does not exist",
)


def _looks_like_internal_error(text: str) -> bool:
    low = text.lower()
    return any(marker.lower() in low for marker in _SQL_LEAK_MARKERS)


def sanitize_error_detail(detail: Any) -> tuple[Any, bool]:
    """对外错误详情脱敏。

    返回 ``(safe_detail, was_redacted)``。若 ``detail`` 是字符串且疑似含内部
    实现（SQL/表名/驱动栈），替换为中性文案；同时标记需要把原文写进服务端日志，
    便于事后关联，但不回前端。

    业务层用 :class:`BusinessException` 主动抛的友好文案不含这些标记，原样保留。
    """
    if not isinstance(detail, str):
        return detail, False
    if not _looks_like_internal_error(detail):
        return detail, False
    return "操作失败，请检查输入或稍后重试", True


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

    # 写前备份不可用 → 503。写点直接调 services.kb_service.ensure_write_backup()
    # 即可，失败由这里统一转成**可机读**的拒绝响应：没有回滚点的写一律不执行，
    # 也不许在每个路由里各写一遍 try/except（当年就是这么吞成静默放行的）。
    from services.kb_service import WriteBackupBlocked

    @app.exception_handler(WriteBackupBlocked)
    async def write_backup_blocked_handler(request: Request, exc: WriteBackupBlocked):
        from utils.logger import error as log_error
        log_error(f"写前备份闸门 [{exc.__class__.__name__}]: {exc} | path={request.url.path}")
        return create_error_response(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=str(exc),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # 物理删除保护闸门（delete_guard.PhysicalDeleteBlocked，继承 RuntimeError）：
    # quiz_questions / knowledge_chunks 的物理删除不可逆，默认必须显式设置
    # KAOYAN_ALLOW_PHYSICAL_DELETE=1 才放行。原本该异常没被专用 handler 接住，
    # 会落到最底部的 Exception 兜底，返回 500 + {"type":"PhysicalDeleteBlocked"}，
    # 管理员看到的是「服务器内部错误」，既泄露了内部类型名，又不清楚如何解除。
    # 这里转成 403 业务拒绝 + 固定友好文案（不回显内部 message，避免泄露表名/历史事故）。
    from services.delete_guard import PhysicalDeleteBlocked

    @app.exception_handler(PhysicalDeleteBlocked)
    async def physical_delete_blocked_handler(request: Request, exc: PhysicalDeleteBlocked):
        from utils.logger import warning as log_warning
        log_warning(f"物理删除被拦截 [{exc.__class__.__name__}]: {exc} | path={request.url.path}")
        return create_error_response(
            code=ErrorCode.FORBIDDEN,
            message=(
                "删除保护已启用：该数据受物理删除保护，本次操作被拦截。"
                "物理删除不可逆（真题等核心数据一旦删除难以恢复）。"
                "如确需删除，请在服务器设置环境变量 KAOYAN_ALLOW_PHYSICAL_DELETE=1 "
                "后重试，并确保此前已完成数据库备份。"
            ),
            detail={"type": "PhysicalDeleteBlocked"},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """HTTP 异常处理：一律走错误壳，不在这里另立格式。

        显式 ``raise HTTPException(detail=str(e))`` 的 ``e`` 经常是数据库底层异常，
        含 SQL/表名/列名——必须脱敏后再回前端，不能原样透传。
        """
        safe_detail, redacted = sanitize_error_detail(exc.detail)
        if redacted:
            from utils.logger import warning as log_warning
            log_warning(
                f"已脱敏对外错误详情 [HTTP {exc.status_code}]: {exc.detail} "
                f"| path={request.url.path}"
            )
        if exc.status_code >= 500:
            from utils.logger import error as log_error
            log_error(f"HTTP异常 [{exc.status_code}]: {exc.detail} | path={request.url.path}")
        return http_error_response(exc.status_code, safe_detail)

    # 数据库异常兜底：未被人显式接住的 SQLAlchemyError 落到这里，统一转成
    # 中性 500，绝不把 SQL 栈回前端（未处理异常的兜底处理器只回异常类名，已经安全；
    # 这里再补一层是为了给 DB 错误更精确的日志与文案）。需注册在通用 Exception
    # 处理器之前，FastAPI 按最具体类型匹配。
    from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        from utils.logger import exception as log_exception
        log_exception(f"数据库异常 | path={request.url.path} | method={request.method}")
        return create_error_response(
            code=ErrorCode.UNKNOWN_ERROR,
            message="数据库操作失败，请稍后重试",
            detail={"type": "DatabaseError"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
        # 记类型：只看「未处理异常」这四个字定位不到根因（排查软删除 500 时踩过）。
        # 堆栈只进服务端日志，不回前端。
        log_exception(
            f"未处理异常 | path={request.url.path} | method={request.method} "
            f"| type={type(exc).__name__}: {exc}"
        )
        return create_error_response(
            code=ErrorCode.UNKNOWN_ERROR,
            message="服务器内部错误",
            detail={"type": type(exc).__name__},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
