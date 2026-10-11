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
    Goal, Task, QuizQuestion, ErrorRecord,
    AIProvider, CustomLink, PlatformConfig,
)
from routers import (
    kaoyan,
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


# --------------------------------------------------------------------------- #
# 健康检查
# --------------------------------------------------------------------------- #
@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "service": "kaoyan-backend",
        "version": "3.0.0",
        # 纯展示字段：带 +00:00 的 ISO8601 对前端 new Date() 更友好
        "timestamp": utcnow_aware().isoformat(),
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
        return JSONResponse(status_code=404, content={"detail": "Not Found", "path": path})
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
    """创建数据库表并初始化示例数据。"""
    Base.metadata.create_all(bind=engine)
    _init_sample_data()
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


def _init_sample_data():
    """插入示例数据（仅在数据库为空时）。"""
    db = SessionLocal()
    try:
        # 判断是否已有数据
        if db.query(Goal).count() > 0:
            return

        # ---- 考研目标 ----
        goal = Goal(
            exam_date=datetime.date(2027, 12, 25),
            total_score_target=360,
            politics_target=65,
            english_target=65,
            math_target=115,
            major_target=115,
            university="贵州大学",
            major="电子信息（0854）",
            remark="目标贵大电子信息专硕，专业课 834 电子技术基础，全力以赴！",
        )
        db.add(goal)

        # ---- 任务 ----
        today = datetime.date.today()
        tasks_data = [
            Task(title="数学高等数学第一章复习", subject="数学", task_type="学习",
                 stage="基础", status="pending", due_date=today, priority=5),
            Task(title="英语阅读理解精读 2 篇", subject="英语", task_type="刷题",
                 stage="基础", status="pending", due_date=today, priority=4),
            Task(title="政治马原原理梳理", subject="政治", task_type="学习",
                 stage="基础", status="doing", due_date=today, priority=3),
            Task(title="数据结构链表练习", subject="专业课", task_type="刷题",
                 stage="基础", status="pending", due_date=today + datetime.timedelta(days=1), priority=4),
            Task(title="数学线性代数复习", subject="数学", task_type="复习",
                 stage="基础", status="pending", due_date=today + datetime.timedelta(days=1), priority=3),
            Task(title="英语单词背诵 200 个", subject="英语", task_type="背诵",
                 stage="基础", status="done", due_date=today - datetime.timedelta(days=1),
                 priority=2, completed_at=utcnow()),  # naive UTC（P0-4）
            Task(title="政治毛中特框架整理", subject="政治", task_type="学习",
                 stage="强化", status="pending", due_date=today + datetime.timedelta(days=2), priority=3),
        ]
        db.add_all(tasks_data)

        # ---- 题目 ----
        questions = [
            QuizQuestion(
                content="设函数 f(x) 在 x=0 处连续，且 lim(x->0) f(x)/x = 2，则 f'(0) = ?",
                options=["0", "1", "2", "不存在"],
                answer="C",
                analysis="由 lim(x->0) f(x)/x = 2 且 f(x) 在 x=0 连续，可知 f(0)=0。"
                         "因此 f'(0) = lim(x->0) [f(x)-f(0)]/x = lim(x->0) f(x)/x = 2。",
                subject="数学",
                chapter="高等数学-导数",
                knowledge_point="导数定义",
                difficulty=3,
                source="真题",
                question_type="single",
            ),
            QuizQuestion(
                content="The word 'ubiquitous' in the passage most likely means ____.",
                options=["rare", "everywhere", "invisible", "dangerous"],
                answer="B",
                analysis="ubiquitous 意为'无处不在的'，同义词为 everywhere present。",
                subject="英语",
                chapter="阅读理解",
                knowledge_point="词汇理解",
                difficulty=2,
                source="模拟",
                question_type="single",
            ),
            QuizQuestion(
                content="马克思主义哲学区别于旧哲学的最显著特征是____。",
                options=["阶级性", "实践性", "革命性", "科学性"],
                answer="B",
                analysis="实践性是马克思主义哲学区别于其他一切哲学的最显著特征。",
                subject="政治",
                chapter="马原",
                knowledge_point="马克思主义哲学特征",
                difficulty=2,
                source="真题",
                question_type="single",
            ),
            QuizQuestion(
                content="下列关于线性表的说法正确的是____。",
                options=[
                    "顺序表适合随机访问",
                    "链表适合随机访问",
                    "顺序表插入删除效率高",
                    "链表不支持随机访问",
                ],
                answer="A",
                analysis="顺序表通过下标可以直接访问元素，时间复杂度 O(1)，适合随机访问。",
                subject="专业课",
                chapter="数据结构-线性表",
                knowledge_point="顺序表特性",
                difficulty=1,
                source="自建",
                question_type="single",
            ),
        ]
        db.add_all(questions)

        # ---- 错题记录 ----
        errors_data = [
            ErrorRecord(
                question_id=1,
                content="设函数 f(x) 在 x=0 处连续，且 lim(x->0) f(x)/x = 2，则 f'(0) = ?",
                my_answer="A",
                correct_answer="C",
                error_reason="概念混淆",
                subject="数学",
                accuracy=0,
                status="active",
                tags=["导数", "极限"],
                next_review=utcnow() + datetime.timedelta(hours=1),  # naive UTC（P0-4）
            ),
            ErrorRecord(
                question_id=2,
                content="The word 'ubiquitous' in the passage most likely means ____.",
                my_answer="C",
                correct_answer="B",
                error_reason="词汇量不足",
                subject="英语",
                accuracy=0,
                status="active",
                tags=["词汇", "阅读"],
                next_review=utcnow() + datetime.timedelta(hours=2),  # naive UTC（P0-4）
            ),
        ]
        db.add_all(errors_data)

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
        print("[初始化] 示例数据插入完成")
    except Exception as e:
        db.rollback()
        print(f"[初始化] 示例数据插入失败: {e}")
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
