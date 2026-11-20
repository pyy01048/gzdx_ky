"""考研备考平台 FastAPI 后端主入口。"""

import logging
import os
import time

from dotenv import load_dotenv

# 加载 .env（含网盘凭证、监听地址等）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from app_lifecycle import lifespan
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routers.registry import iter_routers
from utils.response import UtcZJSONResponse

# --------------------------------------------------------------------------- #
# ORM 旧属性名兼容别名
#
# 必须在 `from models import ...` 之后安装：ADR-002/003 的 canonical schema 改了
# 若干列名（source→source_label / file_type→source_format / interval→interval_days
# 等），业务路由仍按旧属性名读写，此处补 synonym 别名，零改业务代码。
# 放在此处而非 database.py，是为避免与 models.py 形成循环导入。
# --------------------------------------------------------------------------- #
try:
    import orm_aliases
    # 注意：此处位于 `from models import ...` **之后**，全部 ORM 映射类已注册完毕，
    # 枚举类型适配才能覆盖全表。（database.get_db() 里另有一次懒初始化兜住非 FastAPI 场景。）
    _alias_done = orm_aliases.install()
    logging.getLogger(__name__).info(
        "ORM 兼容适配：%d 个模型，%d 处变更",
        len(_alias_done), sum(len(v) for v in _alias_done.values()),
    )
except Exception as _exc:  # noqa: BLE001
    logging.getLogger(__name__).warning("ORM 兼容适配安装失败：%s", _exc)

# --------------------------------------------------------------------------- #
# 定时任务
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# 应用实例
# --------------------------------------------------------------------------- #
from fastapi import Depends as _Depends
from utils.access_policy import enforce_access, is_production

_PROD = is_production()

app = FastAPI(
    title="考研备考平台 API",
    description="一站式考研备考管理后端服务",
    version="3.0.0",
    lifespan=lifespan,
    # 时间格式的唯一闸门：库里是 naive UTC，默认编码出的 "…T16:00:00" 没有偏移，
    # 前端 new Date() 会当本地时间解析 → 北京用户看什么都早 8 小时。
    # 见 utils/response.py:UtcZJSONResponse。
    default_response_class=UtcZJSONResponse,
    # 必须在构造时给：include_router 会在挂载那一刻合并 app 级依赖，事后再加不生效
    dependencies=[_Depends(enforce_access)],
    docs_url=None if _PROD else "/docs",
    redoc_url=None if _PROD else "/redoc",
    openapi_url=None if _PROD else "/openapi.json",
)

# --------------------------------------------------------------------------- #
# 统一日志系统初始化
# --------------------------------------------------------------------------- #
from utils.logger import get_logger, setup_logging
from utils.logger import info as log_info
from utils.timeutil import utcnow_aware  # 统一时间规范（P0-4）

setup_logging()
logger = get_logger("main")
log_info("=" * 60)
log_info("考研备考平台 V3.0 启动中...")
log_info("=" * 60)

# --------------------------------------------------------------------------- #
# 全局异常处理器注册
# --------------------------------------------------------------------------- #
from utils.exceptions import register_exception_handlers

register_exception_handlers(app)

# V3.0 性能优化中间件
from services.server_optimizer import perf_monitor, request_timer

# --------------------------------------------------------------------------- #
# 请求超时守卫（P1-1，通用保险）
# 任意单个慢接口超时后主动返回 504，而不是无限拖住调用方。
# 采用裸 ASGI 实现，只观察「响应头何时发出」，绝不触碰响应体 ——
# 因此 SSE 长连接（/api/ai/chat/stream）天然免疫，不会被破坏。
# 阈值：API_TIMEOUT_GET_SECONDS=30 / API_TIMEOUT_WRITE_SECONDS=60
from utils.timeout_guard import TimeoutGuardMiddleware

app.add_middleware(TimeoutGuardMiddleware)

@app.middleware("http")
async def performance_middleware(request, call_next):
    """V3.0 请求计时与性能监控中间件。"""
    start_time = time.time()
    try:
        response = await request_timer(request, call_next)
        elapsed = (time.time() - start_time) * 1000
        perf_monitor.record_request(elapsed, success=True)
        return response
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        perf_monitor.record_request(elapsed, success=False)
        raise e

# CORS - 默认允许本机与局域网访问（手机/平板同 WiFi 打开需要）
# 安全提示：不要配置为 "*"，尤其是 allow_credentials=True 时
_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000"
    ).split(",")
    if o.strip()
]
# 局域网来源自动放行：手机通过 http://192.168.x.x:8000 访问时，
# Origin 会是那个 IP，写死白名单会导致跨域被拦。
_cors_regex = os.getenv("CORS_ORIGIN_REGEX", "").strip() or (None if _PROD else (
    r"^http://("
    r"localhost|127\.0\.0\.1|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$"
))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Token", "X-Requested-With"],
    max_age=3600,
)

# --------------------------------------------------------------------------- #
# 可选 API Token 认证（.env 配置 APP_API_TOKEN 后启用）
# --------------------------------------------------------------------------- #
_APP_API_TOKEN = os.getenv("APP_API_TOKEN", "").strip()


@app.middleware("http")
async def api_token_auth(request, call_next):
    """轻量 API Token 认证。

    仅当 .env 中配置了 APP_API_TOKEN 时生效：请求需携带
    `X-API-Token` 头或 `?token=` 查询参数。未配置则完全放行
    （本地离线直连场景，保持零侵入）。
    """
    if not _APP_API_TOKEN:
        return await call_next(request)

    from utils.exceptions import http_error_response

    # 放行 CORS 预检请求
    if request.method == "OPTIONS":
        return await call_next(request)

    token = request.headers.get("X-API-Token") or request.query_params.get("token")
    if token != _APP_API_TOKEN:
        # 中间件里 raise HTTPException 不会被异常处理器接住（它在路由外层），
        # 所以直接返回错误壳对象，别自己拼 {"detail": ...}。
        return http_error_response(401, "未授权：缺少或错误的 API Token")
    return await call_next(request)

# --------------------------------------------------------------------------- #
# 传输层优化中间件（V3.0 性能优化）
#
# 顺序说明：Starlette 的 add_middleware 是「后添加者在外层」。这两个放在全部
# 现有中间件之后，即位于整个中间件链最外层：
#   GZip（最外）→ StaticCache → api_token_auth → CORS → performance →
#   TimeoutGuard → CamelCase → 路由
# GZip 因此压缩的是「最终响应体」（含静态资源）；StaticCache 在压缩之前改写
# 缓存头，两者互不干扰。GZip 为选择性压缩：SSE / 206 分段 / 二进制流透传
# （见 utils/middleware.py 的实测说明），不会破坏 AI 流式对话与视频 seek。
# --------------------------------------------------------------------------- #
from utils.middleware import GZipApiMiddleware, StaticCacheControlMiddleware

app.add_middleware(StaticCacheControlMiddleware)
app.add_middleware(GZipApiMiddleware, minimum_size=1000, compresslevel=6)

# --------------------------------------------------------------------------- #
# 挂载路由
#
# V3.1 重构后路由统一收口到 routers/registry.py，这里只做一件事：
#   for r in iter_routers(): app.include_router(r)
# 唯一例外：code_oj（/api/code/*，代码上机 OJ）保持**不挂载**——判题要起子进程
# 跑用户代码，2C2G 节点扛不住；97 号表与代码全部保留，恢复时删掉下面一行即可。
# --------------------------------------------------------------------------- #
for _r in iter_routers():
    if getattr(_r, "prefix", "") == "/api/code":
        continue  # 代码上机 OJ 暂不挂载（见上方注释）
    app.include_router(_r)


# --------------------------------------------------------------------------- #
# 健康检查
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health_check():
    from services.health_service import kb_health_snapshot

    # KB 健康检查面板数据源：数据库连接 / 向量库 / FTS5 / 关键表行数。
    # kb_health_snapshot 内部对每个探测项独立降级，不会让本接口自己 500。
    kb = kb_health_snapshot()
    return {
        # 进程在线即 ok；数据库/KB 层缺口只在 kb.status 体现为 degraded
        "status": "ok" if kb.get("database", {}).get("status") == "healthy" else "degraded",
        "service": "kaoyan-backend",
        "version": "3.0.0",
        # 纯展示字段：带 +00:00 的 ISO8601 对前端 new Date() 更友好
        "timestamp": utcnow_aware().isoformat(),
        "kb": kb,
    }


@app.get("/api/access-info")
async def access_info():
    """返回本机与局域网访问地址（含手机扫码二维码）。

    手机接入流程：电脑双击 start-lan.bat → 页面/控制台显示二维码 →
    手机扫码即用。这个接口让前端也能直接展示"怎么用手机打开"。
    """
    from utils.network import get_access_info

    return get_access_info(auth_enabled=True)


# V3.0 性能监控端点
@app.get("/api/performance")
async def performance_stats():
    """获取系统性能统计信息。"""
    from services.ai_optimizer import get_ai_cache
    from services.ai_optimizer import get_perf_monitor as get_ai_perf
    from services.search_optimizer import get_search_cache, get_search_monitor
    from services.server_optimizer import perf_monitor

    return {
        "server": perf_monitor.get_stats(),
        "ai_cache": get_ai_cache().stats(),
        "ai_performance": get_ai_perf().stats(),
        "search_cache": get_search_cache().stats(),
        "search_performance": get_search_monitor().stats(),
    }


# --------------------------------------------------------------------------- #
# 静态文件服务（前端 build 产物）
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
# 题目配图出口：quiz_questions.images[].path 形如 question_pages/xxx.png，
# 实际文件在 data/storage/images/ 下，前端按 /media/images/<path> 取图。
# 路径相对本文件计算，换机器不失效。
MEDIA_IMAGES_DIR = os.path.join(BASE_DIR, "data", "storage", "images")
# P0 修复：Windows 下 FastAPI StaticFiles 将 .js 返回为 text/plain 导致前端白屏，
# 挂载前显式注册 MIME 类型（strict=True 覆盖内置映射）
import mimetypes

mimetypes.add_type("application/javascript", ".js", strict=True)
mimetypes.add_type("application/javascript", ".mjs", strict=True)
mimetypes.add_type("text/css", ".css", strict=True)
# Windows 注册表里的图片 MIME 不一定可靠，显式钉死，避免浏览器当成下载流
mimetypes.add_type("image/png", ".png", strict=True)
mimetypes.add_type("image/jpeg", ".jpg", strict=True)
mimetypes.add_type("image/jpeg", ".jpeg", strict=True)
mimetypes.add_type("image/webp", ".webp", strict=True)
# 注意：必须先于下面的 "/" 根挂载注册，否则所有路径都会被根挂载先吃掉。
os.makedirs(MEDIA_IMAGES_DIR, exist_ok=True)
app.mount(
    "/media/images",
    StaticFiles(directory=MEDIA_IMAGES_DIR),
    name="media_images",
)
if os.path.exists(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# --------------------------------------------------------------------------- #
# SPA 前端路由 fallback：非 /api 路径的 404 统一返回 index.html
# --------------------------------------------------------------------------- #
from fastapi import Request as FastAPIRequest
from fastapi.responses import FileResponse


@app.exception_handler(404)
async def spa_fallback_handler(request: FastAPIRequest, exc):
    """SPA 前端路由 fallback：非 API 路径的 404 返回 index.html，支持直接访问前端路由。"""
    path = request.url.path
    # API 路径、静态资源路径、文档路径不做 fallback
    if path.startswith("/api") or path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi") or "." in path.split("/")[-1]:
        from utils.exceptions import http_error_response
        # 路由给的 detail 是人话（如 "文档不存在: [99999999]"），此前被一律压成
        # "Not Found"：前端分不清"这条记录不存在"和"接口没注册"，用户只能看到 404。
        # 本函数原先自己拼 {"detail":..., "path":...}，导致 404 是全站唯一不合
        # 错误壳的状态码；现在把文案和 path 一起交给归一函数，path 留在 detail 里。
        detail = getattr(exc, "detail", None)
        extra = dict(detail) if isinstance(detail, dict) else {"message": detail or "Not Found"}
        extra["path"] = path
        return http_error_response(404, extra)
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    from utils.exceptions import http_error_response
    return http_error_response(404, {"message": "index.html not found", "path": path})


# --------------------------------------------------------------------------- #
# 启动逻辑已迁 app_lifecycle.lifespan（docs/完善方案/04 §3.5）
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # 监听地址从 .env 读取。默认 127.0.0.1（仅本机）；
    # 要让手机/其他设备访问，把 .env 的 HOST 改为 0.0.0.0。
    _host = os.getenv("HOST", "127.0.0.1")
    _port = int(os.getenv("PORT", "8000"))

    try:
        from utils.network import get_access_info

        _info = get_access_info(port=_port)
        logger.info("=" * 62)
        logger.info("  考研学习平台 · 服务启动")
        logger.info("=" * 62)
        logger.info(f"  本机访问 : {_info['local_url']}")
        if _info["exposed"] and _info["lan_url"]:
            logger.info(f"  手机访问 : {_info['lan_url']}   ← 同一 WiFi 下可用")
        elif _info["lan_ip"]:
            logger.info("  手机访问 : 需先把 .env 的 HOST 改为 0.0.0.0")
            logger.info(f"             （本机局域网 IP 为 {_info['lan_ip']}）")
        for _t in _info["tips"]:
            logger.info(f"  · {_t.replace('**', '')}")
        logger.info("=" * 62)
    except Exception as _e:
        logger.warning(f"[warn] 无法生成访问信息: {_e}")

    # P0-3：统一走看门狗 —— 进程半死（accept 循环挂掉但进程还在，
    # 实测 WinError 64 那次）时会干净退出并给出非零码，而不是挂着假装正常。
    from utils.server_watchdog import run_with_watchdog

    raise SystemExit(run_with_watchdog(_host, _port))
