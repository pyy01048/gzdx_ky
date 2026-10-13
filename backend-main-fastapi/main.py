"""考研备考平台 FastAPI 后端主入口。"""

import os
import datetime
import time

from dotenv import load_dotenv

# 加载 .env（含网盘凭证、监听地址等）
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import engine, Base, SessionLocal
from models import (
    AIProvider, CustomLink, PlatformConfig,
)
from routers import (
    kaoyan,
    kaoyan_ext,
    insight,
    qa_tools,
    conflicts,
    ai_tutoring,
    codebank,
    dashboard,
    tasks,
    quiz,
    errors,
    ai,
    netdisk,
    goals,
    documents,
    flashcards,
    customization,
    imports,
    analytics,
    planner,
    words,
    taxonomy,
    review,
    kb,
    quality,
    backup,
    storage,
    analysis,
    papers,
    formula,
    exam,
    answers,
    gate,
    blind_spot,
    plan,
    growth,
    kb_import,
    notices,
    notice_alert,
)

# --------------------------------------------------------------------------- #
# 定时任务
# --------------------------------------------------------------------------- #
from services.scheduler import start_scheduler

# --------------------------------------------------------------------------- #
# 应用实例
# --------------------------------------------------------------------------- #
app = FastAPI(
    title="考研备考平台 API",
    description="一站式考研备考管理后端服务",
    version="3.0.0",
)

# --------------------------------------------------------------------------- #
# 统一日志系统初始化
# --------------------------------------------------------------------------- #
from utils.logger import setup_logging, get_logger, info as log_info
from utils.timeutil import utcnow, utcnow_aware  # 统一时间规范（P0-4）
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

# --------------------------------------------------------------------------- #
# 字段命名自动转换中间件（请求头 X-Response-Camel-Case: true 时启用）
# --------------------------------------------------------------------------- #
from utils.middleware import CamelCaseResponseMiddleware
app.add_middleware(CamelCaseResponseMiddleware)

# --------------------------------------------------------------------------- #
# 简单认证中间件（可选启用，.env 配置 APP_PASSWORD 后生效）
# --------------------------------------------------------------------------- #
from utils.auth import SimpleAuthMiddleware, get_auth_status, AUTH_ENABLED
app.add_middleware(SimpleAuthMiddleware)

# 认证状态查询接口
@app.get("/api/auth/status")
async def auth_status():
    return get_auth_status()

# 登录接口（验证密码）
@app.post("/api/auth/login")
async def auth_login(request: dict):
    from utils.auth import verify_password
    password = request.get("password", "")
    if verify_password(password):
        return {"success": True, "message": "登录成功"}
    from fastapi import HTTPException
    raise HTTPException(status_code=401, detail="密码错误")

# V3.0 性能优化中间件
from services.server_optimizer import request_timer, get_task_queue, perf_monitor

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
_cors_regex = os.getenv("CORS_ORIGIN_REGEX", "").strip() or (
    r"^http://("
    r"localhost|127\.0\.0\.1|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Token", "X-Requested-With",
                   "X-App-Password"],
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

    from fastapi.responses import JSONResponse

    # 放行 CORS 预检请求
    if request.method == "OPTIONS":
        return await call_next(request)

    token = request.headers.get("X-API-Token") or request.query_params.get("token")
    if token != _APP_API_TOKEN:
        return JSONResponse(
            status_code=401,
            content={"detail": "未授权：缺少或错误的 API Token"},
        )
    return await call_next(request)

# --------------------------------------------------------------------------- #
# 挂载路由
# --------------------------------------------------------------------------- #
app.include_router(kaoyan.router)
app.include_router(kaoyan_ext.router)
app.include_router(insight.router)
app.include_router(qa_tools.router)
app.include_router(conflicts.router)
app.include_router(ai_tutoring.router)
app.include_router(codebank.router)
app.include_router(dashboard.router)
app.include_router(tasks.router)
app.include_router(quiz.router)
app.include_router(errors.router)
app.include_router(ai.router)
app.include_router(netdisk.router)
app.include_router(goals.router)
app.include_router(documents.router)
app.include_router(flashcards.router)
app.include_router(customization.router)
app.include_router(imports.router)
app.include_router(analytics.router)
app.include_router(planner.router)
app.include_router(words.router)
app.include_router(taxonomy.router)
app.include_router(review.router)
app.include_router(kb.router)
app.include_router(backup.router)
app.include_router(storage.router)
app.include_router(analysis.router)
app.include_router(papers.router)
app.include_router(formula.router)
app.include_router(exam.router)
app.include_router(answers.router)
app.include_router(gate.router)
app.include_router(blind_spot.router)
app.include_router(plan.router)
app.include_router(growth.router)
app.include_router(kb_import.router)
app.include_router(notice_alert.router)
# 通知已读标记（/api/notices/*）：单用户设计，状态落在 kaoyan_notices 列上
app.include_router(notices.router)
# 评测与数据质量只读接口（/api/quality/*）：eval_runs 趋势 + 语料体检口径
app.include_router(quality.router)


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
    from utils.auth import AUTH_ENABLED

    return get_access_info(auth_enabled=bool(AUTH_ENABLED))


# V3.0 性能监控端点
@app.get("/api/performance")
async def performance_stats():
    """获取系统性能统计信息。"""
    from services.server_optimizer import perf_monitor
    from services.ai_optimizer import get_ai_cache, get_perf_monitor as get_ai_perf
    from services.search_optimizer import get_search_monitor, get_search_cache

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
# P0 修复：Windows 下 FastAPI StaticFiles 将 .js 返回为 text/plain 导致前端白屏，
# 挂载前显式注册 MIME 类型（strict=True 覆盖内置映射）
import mimetypes
mimetypes.add_type("application/javascript", ".js", strict=True)
mimetypes.add_type("application/javascript", ".mjs", strict=True)
mimetypes.add_type("text/css", ".css", strict=True)
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
        from fastapi.responses import JSONResponse
        # 路由给的 detail 是人话（如 "文档不存在: [99999999]"），此前被一律压成
        # "Not Found"：前端分不清"这条记录不存在"和"接口没注册"，用户只能看到 404。
        return JSONResponse(status_code=404,
                            content={"detail": getattr(exc, "detail", None) or "Not Found",
                                     "path": path})
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={"detail": "index.html not found"})


# --------------------------------------------------------------------------- #
# 启动事件：创建表 + 插入示例数据
# --------------------------------------------------------------------------- #
@app.on_event("startup")
def on_startup():
    """创建数据库表并写入默认配置（不写任何学习内容，见 docx/16 §1.5-G）。"""
    Base.metadata.create_all(bind=engine)
    _init_default_config()
    # 幂等补建非ORM 映射的原生表（如 phase_daily_reviews）。
    # create_all 只能建 Base.metadata 里声明过的表，而 planner.py 的阶段
    # 复习接口直接用 text() 读写 phase_daily_reviews，该表无 ORM 模型，
    # 因此必须显式执行 DDL，否则空库/新部署时 /api/planner/phase 必 500。
    try:
        from services.module_a_schema import ensure_module_a_schema
        db = SessionLocal()
        result = ensure_module_a_schema(db)
        db.close()
        print(f"[启动] 原生表DDL 补建完成: {result}")
    except Exception as e:
        print(f"[启动] 原生表 DDL 补建失败（不影响主服务）: {e}")
    # chunk 三层标签补列（models.KnowledgeChunk 已声明新列，但 create_all 不给
    # 存量表加列 —— 必须在任何 ORM 查询 knowledge_chunks 之前幂等 ALTER 补齐）。
    try:
        from services.chunk_classifier import ensure_chunk_label_columns
        db = SessionLocal()
        added = ensure_chunk_label_columns(db)
        db.close()
        if added:
            print(f"[启动] knowledge_chunks 新增标签列: {added}")
    except Exception as e:
        print(f"[启动] chunk 标签列补建失败: {e}")
    # V3.0 数据库性能优化（创建缺失索引+WAL模式+缓存）
    try:
        from services.db_optimizer import init_database_optimization
        db = SessionLocal()
        result = init_database_optimization(db)
        db.close()
        print(f"[启动] 数据库优化完成: {result}")
    except Exception as e:
        print(f"[启动] 数据库优化失败（不影响主服务）: {e}")
    # V3.0 启动后台任务队列
    try:
        import asyncio
        task_queue = get_task_queue()
        asyncio.create_task(task_queue.start())
        print("[启动] 后台任务队列已启动")
    except Exception as e:
        print(f"[启动] 后台任务队列启动失败（不影响主服务）: {e}")
    # 自动登记本机已下载的 Ollama 本地模型（仅新增，不覆盖用户配置）
    _register_ollama_providers()
    # 启动定时任务（复习提醒 / 网盘同步）
    try:
        start_scheduler()
    except Exception as e:  # noqa: BLE001
        print(f"[启动] 定时任务启动失败（不影响主服务）: {e}")
    # V3.0 数据库自动备份（每天一次）
    try:
        from services.backup_service import daily_backup_if_needed
        backup_path = daily_backup_if_needed()
        if backup_path:
            print(f"[启动] 数据库自动备份完成: {backup_path}")
    except Exception as e:
        print(f"[启动] 数据库备份失败（不影响主服务）: {e}")


def _register_ollama_providers():
    """若本机 Ollama 可用，自动登记已下载的本地模型为 AI 服务商。

    9b 用于学术答疑（高数/线代/专业课），4b 用于文档处理（总结/改写）。
    仅新增、不覆盖：已存在同 model_name 的配置则跳过，保留用户设置。
    """
    try:
        import json
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
            models = [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return
    if not models:
        return
    db = SessionLocal()
    try:
        # 模型名 -> (展示名, 降级优先级)
        wanted = {
            "qwen3:8b": ("本地学术答疑 qwen3.5:9b", 5),
            "qwen3:4b": ("本地文档处理 qwen3.5:4b", 6),
        }
        added = []
        for model_name, (name, prio) in wanted.items():
            if model_name not in models:
                continue
            if db.query(AIProvider).filter(AIProvider.model_name == model_name).first():
                continue  # 已存在则跳过，保留用户配置
            db.add(AIProvider(
                name=name,
                provider_type="ollama",
                base_url="http://127.0.0.1:11434/v1",
                api_key="ollama",
                model_name=model_name,
                temperature=0.7,
                is_enabled=True,
                fallback_priority=prio,
            ))
            added.append(model_name)
        db.commit()
        if added:
            print(f"[启动] 已登记本地 Ollama 模型：{', '.join(added)}")
    except Exception as e:
        db.rollback()
        print(f"[启动] Ollama 模型登记失败（不影响主服务）: {e}")
    finally:
        db.close()


def _ensure_missing_platform_configs(db):
    """幂等补建缺失的平台配置行（存量库升级用）。

    只新增不更新：用户改过的 web_view_url / app_key 一律保留。
    目前只需补 quark_netdisk（2026-10 网盘重构新增）。
    """
    existing = {
        c.platform_name
        for c in db.query(PlatformConfig.platform_name).all()
    }
    if "quark_netdisk" not in existing:
        db.add(PlatformConfig(
            platform_name="quark_netdisk",
            sync_enabled=False,
            sync_frequency="daily",
            extra={
                "web_view_url": "https://pan.quark.cn/",
                "embed_mode": "web_view",
            },
        ))
        db.commit()
        print("[初始化] 补建平台配置: quark_netdisk")


def _init_default_config():
    """写入平台默认配置（AI 供应商 / 快捷链接 / 网盘与平台开关）。

    这里**只写配置，不写学习内容**。原先本函数还会在 goals 为空时播种
    一条 Goal（exam_date 硬编码 2027-12-25）、7 条 Task、4 道 QuizQuestion、
    2 条 ErrorRecord —— 那些是演示数据，不是用户数据，且已被实测确认写进了
    生产库（tasks id 1-7 标题逐字相同、goals 行与播种同事务），而 #22 之后
    倒计时以 Goal.exam_date 为唯一时间源，等于让假日期决定全站倒计时。
    口径依据：docx/16 §1.5-G 与已批准的「空库必须渲染空状态，绝不播种内容」。
    """
    db = SessionLocal()
    try:
        # 幂等判据换成配置表本身：内容播种已删除，不能再拿 goals 当判据
        if db.query(PlatformConfig).count() > 0:
            return

        # ---- AI 配置模板 ----
        ai_providers = [
            AIProvider(
                name="豆包（默认）",
                provider_type="doubao",
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                model_name="doubao-pro-32k",
                temperature=0.7,
                is_default=True,
                is_enabled=True,
                fallback_priority=1,
            ),
            AIProvider(
                name="DeepSeek",
                provider_type="deepseek",
                base_url="https://api.deepseek.com/v1",
                model_name="deepseek-chat",
                temperature=0.7,
                is_default=False,
                is_enabled=True,
                fallback_priority=2,
            ),
            AIProvider(
                name="通义千问",
                provider_type="qwen",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model_name="qwen-plus",
                temperature=0.7,
                is_default=False,
                is_enabled=False,
                fallback_priority=3,
            ),
        ]
        db.add_all(ai_providers)

        # ---- 快捷链接 ----
        links = [
            CustomLink(name="中国研究生招生信息网", url="https://yz.chsi.com.cn/",
                       category="官方", sort_order=1),
            CustomLink(name="学信网", url="https://www.chsi.com.cn/",
                       category="官方", sort_order=2),
            CustomLink(name="中国教育在线考研", url="https://kaoyan.eol.cn/",
                       category="资讯", sort_order=3),
            CustomLink(name="B站考研", url="https://search.bilibili.com/all?keyword=考研",
                       category="学习", sort_order=4),
        ]
        db.add_all(links)

        # ---- 平台配置 ----
        platform_configs = [
            PlatformConfig(
                platform_name="baidu_netdisk",
                app_key=os.getenv("BAIDU_NETDISK_APP_KEY", ""),
                secret_key=os.getenv("BAIDU_NETDISK_SECRET_KEY", ""),
                sync_enabled=True,
                sync_frequency="hourly",
                extra={
                    "app_id": os.getenv("BAIDU_NETDISK_APP_ID", ""),
                    "sync_dir": "/考研资料/2026",
                    "auto_sync": True,
                    "connected": True,
                },
            ),
            PlatformConfig(
                platform_name="shengcai",
                sync_enabled=False,
                sync_frequency="daily",
                extra={
                    "username": "",
                    "password": "",
                    "cookie": "",
                    "sync_question_bank": False,
                    "auto_fetch": False,
                },
            ),
            PlatformConfig(
                platform_name="anki",
                sync_enabled=False,
                sync_frequency="daily",
                extra={
                    "anki_connect_url": "http://localhost:8765",
                    "deck_sync": False,
                    "auto_export_errors": False,
                },
            ),
            PlatformConfig(
                platform_name="momo",
                sync_enabled=False,
                sync_frequency="daily",
                extra={
                    "device_id": "",
                    "data_import": False,
                    "daily_word_goal": 100,
                    "ai_mnemonic": False,
                },
            ),
            PlatformConfig(
                platform_name="bilibili",
                sync_enabled=False,
                sync_frequency="daily",
                extra={
                    "sessdata": "",
                    "favorites_sync": False,
                    "watch_progress": False,
                    "auto_notes": False,
                },
            ),
            PlatformConfig(
                platform_name="xmind",
                sync_enabled=False,
                sync_frequency="daily",
                extra={
                    "import_dir": "",
                    "auto_link_knowledge": False,
                    "preview": False,
                },
            ),
        ]
        db.add_all(platform_configs)

        db.commit()
        print("[初始化] 默认配置写入完成")
    except Exception as e:
        db.rollback()
        print(f"[初始化] 默认配置写入失败: {e}")
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import uvicorn

    # 监听地址从 .env 读取。默认 127.0.0.1（仅本机）；
    # 要让手机/其他设备访问，把 .env 的 HOST 改为 0.0.0.0。
    _host = os.getenv("HOST", "127.0.0.1")
    _port = int(os.getenv("PORT", "8000"))

    try:
        from utils.network import get_access_info

        _info = get_access_info(port=_port)
        print("=" * 62)
        print("  考研学习平台 · 服务启动")
        print("=" * 62)
        print(f"  本机访问 : {_info['local_url']}")
        if _info["exposed"] and _info["lan_url"]:
            print(f"  手机访问 : {_info['lan_url']}   ← 同一 WiFi 下可用")
        elif _info["lan_ip"]:
            print(f"  手机访问 : 需先把 .env 的 HOST 改为 0.0.0.0")
            print(f"             （本机局域网 IP 为 {_info['lan_ip']}）")
        for _t in _info["tips"]:
            print(f"  · {_t.replace('**', '')}")
        print("=" * 62)
    except Exception as _e:
        print(f"[warn] 无法生成访问信息: {_e}")

    uvicorn.run("main:app", host=_host, port=_port, reload=False)
