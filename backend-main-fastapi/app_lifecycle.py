# -*- coding: utf-8 -*-
"""应用生命周期（docs/完善方案/04-后端架构与代码质量.md §3.5）。

原 main.py 的 `@app.on_event("startup")` 在 FastAPI 0.104 起已弃用（0.115 仍兼容
但告警）。依赖升级窗口正是迁 lifespan 的时机——本模块承接全部启动逻辑：

  - OCR 可用性预热（后台线程，不阻塞启动）
  - 建表 + 默认配置 + 平台配置补建 + 内置管理员
  - 原生表 DDL / chunk 标签列 / 索引与优化幂等补建
  - 后台任务队列 / 定时任务 / 数据库自动备份
  - Ollama 本地模型自动登记

print 全部替换为 logger（utils.logger 统一日志系统），服务器 journalctl 里
格式统一（此前 30 处 print 不进日志文件、无级别、无时间戳）。
"""
import os
from contextlib import asynccontextmanager

from database import Base, SessionLocal, engine
from fastapi import FastAPI
from models import AIProvider, CustomLink, PlatformConfig
from utils.logger import get_logger

logger = get_logger("main.lifecycle")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """创建数据库表并写入默认配置（不写任何学习内容，见 docx/16 §1.5-G）。"""
    # P0-2：OCR 可用性预热提前到启动期。RapidOCR 的 ONNX 引擎冷初始化 ~6.6s，
    # 若等第一个请求才触发，那次请求（乃至事件循环）要白吃 6.6s。
    # start_warmup 是 fire-and-forget 守护线程，不阻塞启动。
    try:
        from services.ocr_router import get_ocr_router

        get_ocr_router()
        logger.info("[启动] OCR 可用性预热已发起（后台线程）")
    except Exception as e:  # noqa: BLE001
        logger.warning("[启动] OCR 预热发起失败（不影响主服务）: %s", e)
    Base.metadata.create_all(bind=engine)
    _init_default_config()
    # 幂等补建缺失的平台配置行（存量库升级用；已有则跳过）
    try:
        db = SessionLocal()
        try:
            _ensure_missing_platform_configs(db)
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[启动] 平台配置补建失败（不影响主服务）: %s", e)
    try:
        from utils.security import ensure_bootstrap_admin
        db = SessionLocal()
        try:
            ensure_bootstrap_admin(db)
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[启动] 内置管理员初始化失败: %s", e)
    # 幂等补建非ORM 映射的原生表（如 phase_daily_reviews）。
    # create_all 只能建 Base.metadata 里声明过的表，而 planner.py 的阶段
    # 复习接口直接用 text() 读写 phase_daily_reviews，该表无 ORM 模型，
    # 因此必须显式执行 DDL，否则空库/新部署时 /api/planner/phase 必 500。
    try:
        from services.module_a_schema import ensure_module_a_schema
        db = SessionLocal()
        result = ensure_module_a_schema(db)
        db.close()
        logger.info("[启动] 原生表DDL 补建完成: %s", result)
    except Exception as e:
        logger.warning("[启动] 原生表 DDL 补建失败（不影响主服务）: %s", e)
    # chunk 三层标签补列（models.KnowledgeChunk 已声明新列，但 create_all 不给
    # 存量表加列 —— 必须在任何 ORM 查询 knowledge_chunks 之前幂等 ALTER 补齐）。
    try:
        from services.chunk_classifier import ensure_chunk_label_columns
        db = SessionLocal()
        added = ensure_chunk_label_columns(db)
        db.close()
        if added:
            logger.info("[启动] knowledge_chunks 新增标签列: %s", added)
    except Exception as e:
        logger.warning("[启动] chunk 标签列补建失败: %s", e)
    # V3.0 数据库性能优化（创建缺失索引+WAL模式+缓存）
    try:
        from services.db_optimizer import init_database_optimization
        db = SessionLocal()
        result = init_database_optimization(db)
        db.close()
        logger.info("[启动] 数据库优化完成: %s", result)
    except Exception as e:
        logger.warning("[启动] 数据库优化失败（不影响主服务）: %s", e)
    # V3.0 启动后台任务队列
    try:
        import asyncio

        from services.server_optimizer import get_task_queue
        task_queue = get_task_queue()
        asyncio.create_task(task_queue.start())
        logger.info("[启动] 后台任务队列已启动")
    except Exception as e:
        logger.warning("[启动] 后台任务队列启动失败（不影响主服务）: %s", e)
    # 自动登记本机已下载的 Ollama 本地模型（仅新增，不覆盖用户配置）
    _register_ollama_providers()
    # 启动定时任务（复习提醒 / 网盘同步）
    try:
        from services.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:  # noqa: BLE001
        logger.warning("[启动] 定时任务启动失败（不影响主服务）: %s", e)
    # V3.0 数据库自动备份（每天一次；多 worker 时只由持调度锁的进程执行）
    try:
        from services.backup_service import daily_backup_if_needed
        from services.scheduler import acquire_singleton_lock
        backup_path = daily_backup_if_needed() if acquire_singleton_lock() else None
        if backup_path:
            logger.info("[启动] 数据库自动备份完成: %s", backup_path)
    except Exception as e:
        logger.warning("[启动] 数据库备份失败（不影响主服务）: %s", e)

    yield


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
            logger.info("[启动] 已登记本地 Ollama 模型：%s", ", ".join(added))
    except Exception as e:
        db.rollback()
        logger.warning("[启动] Ollama 模型登记失败（不影响主服务）: %s", e)
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
        logger.info("[初始化] 补建平台配置: quark_netdisk")


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
                    "ankiConnect_url": "http://localhost:8765",
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
        logger.info("[初始化] 默认配置写入完成")
    except Exception as e:
        db.rollback()
        logger.warning("[初始化] 默认配置写入失败: %s", e)
    finally:
        db.close()
