"""APScheduler 定时任务管理（网盘同步 / 复习提醒）。"""

import asyncio
import datetime
import logging
import os
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import SessionLocal
from models import NetdiskFile, PlatformConfig
from services.review_scheduler import ReviewScheduler
from utils.timeutil import utcnow  # 统一 naive UTC 时间规范（P0-4）

logger = logging.getLogger("kaoyan.scheduler")

# --------------------------------------------------------------------------- #
#时区（Windows 关键修复）
# --------------------------------------------------------------------------- #
#历史坑：Windows 上若缺少 tzdata 包，APScheduler 用字符串 "Asia/Shanghai" 构造
# 调度器会抛/静默失败：
#     No time zone found with key Asia/Shanghai
# 结果是 **定时任务根本没注册**，日志却什么都看不到（静默失败）。
# 这里改用 **固定 +08:00 偏移** 的 tzinfo，不依赖 zoneinfo/tzdata 数据库，
# 因此在任何平台都稳定可用（北京时间无夏令时，固定偏移是精确的）。
try:
    from zoneinfo import ZoneInfo

    _SHANGHAI_TZ: Any = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001  —— 缺 tzdata 时退回固定偏移
    _SHANGHAI_TZ = datetime.timezone(datetime.timedelta(hours=8), "CST")


scheduler = BackgroundScheduler(timezone=_SHANGHAI_TZ)

# uvicorn --workers N 时每个 worker 都会跑 startup：只有拿到 PG 会话级咨询锁的那个
# worker 跑定时任务，否则提醒/采集/备份会重复 N 次。锁随持有连接存活，进程退出即释放。
_SINGLETON_LOCK_KEY = 0x6B79_5343  # "kySC"
_singleton_conn = None


def acquire_singleton_lock() -> bool:
    """本进程是否为定时任务的唯一执行者（幂等；非 PG 后端视为单进程直接返回 True）。"""
    global _singleton_conn
    if _singleton_conn is not None:
        return True
    from sqlalchemy import text
    from core.db_session import engine

    if engine.dialect.name != "postgresql":
        return True
    conn = engine.connect()
    try:
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _SINGLETON_LOCK_KEY}).scalar())
        conn.commit()  # 会话级锁不随事务结束释放；提交避免 idle-in-transaction 超时杀连接
    except Exception:
        conn.close()
        raise
    if not got:
        conn.close()
        return False
    _singleton_conn = conn
    return True


# --------------------------------------------------------------------------- #
# 定时任务 1：复习提醒（每日统计到期卡片/错题/任务）
# --------------------------------------------------------------------------- #
def _review_reminder_job() -> None:
    db = SessionLocal()
    try:
        due_cards = len(ReviewScheduler.get_due_flashcards(db))
        due_errors = len(ReviewScheduler.get_due_errors(db))
        due_tasks = len(ReviewScheduler.get_due_tasks(db))
        total = due_cards + due_errors + due_tasks
        msg = (
            f"[定时提醒] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} "
            f"今日待复习：卡片 {due_cards}、错题 {due_errors}、任务 {due_tasks}（合计 {total}）"
        )
        logger.info(msg)
        print(msg)
    except Exception as e:  # noqa: BLE001
        logger.error("复习提醒任务失败: %s", e)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 定时任务 2：网盘同步（拉取根目录文件列表入库）
# --------------------------------------------------------------------------- #
def _netdisk_sync_job() -> None:
    db = SessionLocal()
    try:
        cfg = (
            db.query(PlatformConfig)
            .filter(PlatformConfig.platform_name == "baidu_netdisk")
            .first()
        )
        if not cfg or not cfg.sync_enabled or not cfg.token:
            logger.info("网盘同步跳过：未启用或无 token")
            return

        from services.netdisk_service import NetdiskService

        async def _run() -> int:
            svc = NetdiskService(db)
            result = await svc.get_file_list("/")
            files = result.get("list", [])
            synced = 0
            for f in files:
                fs_id = str(f.get("fs_id", ""))
                existing = (
                    db.query(NetdiskFile).filter(NetdiskFile.fs_id == fs_id).first()
                    if fs_id
                    else None
                )
                file_data = {
                    "file_name": f.get("server_filename", f.get("filename", "")),
                    "path": f.get("path", ""),
                    "file_type": _guess_type(f.get("server_filename", "")),
                    "size": f.get("size", 0),
                    "category": svc.auto_classify(f.get("server_filename", "")),
                    "fs_id": fs_id,
                }
                if existing:
                    for key, value in file_data.items():
                        setattr(existing, key, value)
                else:
                    db.add(NetdiskFile(**file_data))
                synced += 1
            cfg.last_sync = utcnow()  # naive UTC，与 DB 列对齐（P0-4）
            db.commit()
            return synced

        synced = asyncio.run(_run())
        msg = f"[网盘同步] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 完成，共 {synced} 个文件"
        logger.info(msg)
        print(msg)
    except Exception as e:  # noqa: BLE001
        logger.error("网盘同步任务失败: %s", e)
    finally:
        db.close()


def _guess_type(filename: str) -> str:
    name = (filename or "").lower()
    if any(name.endswith(ext) for ext in [".mp4", ".avi", ".mkv", ".mov", ".flv"]):
        return "video"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".mp3", ".wav", ".flac")):
        return "audio"
    if name.endswith((".doc", ".docx", ".txt")):
        return "doc"
    return "other"


# --------------------------------------------------------------------------- #
# 定时任务 3：完成度自检（每日数据质量巡检）
# 检查：文档索引率 / 向量覆盖率 / 错题关联率 / 题库解析率，结果写日志
# --------------------------------------------------------------------------- #
def _completion_selfcheck_job() -> None:
    db = SessionLocal()
    try:
        import json

        from models import Document, KnowledgeChunk, QuizQuestion

        # 1. 文档索引率（documents.index_status = 'indexed'）
        doc_total = db.query(Document).count()
        doc_indexed = (
            db.query(Document)
            .filter(Document.index_status == "indexed")
            .count()
            if hasattr(Document, "index_status")
            else doc_total
        )

        # 2. 向量覆盖率（chunk_vectors / knowledge_chunks_vec 行数 ÷ knowledge_chunks）
        #    PG 迁移后权威向量表是 chunk_vectors；SQLite 时代是 knowledge_chunks_vec。
        #    这里先探测真实表名，避免在 PG 上执行 SQLite 方言导致事务 aborted。
        from sqlalchemy import text

        chunk_total = db.query(KnowledgeChunk).count()
        vec_total = 0
        try:
            vec_table = db.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename IN "
                    "('chunk_vectors','knowledge_chunks_vec') "
                    "ORDER BY (tablename = 'chunk_vectors') DESC, tablename LIMIT 1"
                )
            ).scalar()
            if vec_table is None:
                # 非 PG 环境（SQLite）：直接尝试旧表名
                vec_table = "knowledge_chunks_vec"
            vec_total = (
                db.execute(
                    text(f'SELECT COUNT(*) FROM "{vec_table}"')
                ).scalar()
                or 0
            )
        except Exception:
            db.rollback()  # 事务可能已 aborted，先恢复再继续
            vec_total = 0

        # 3. 错题关联率（error_records 中被 error_knowledge_links 关联的去重数量）
        from models import ErrorRecord

        error_total = db.query(ErrorRecord).count()
        linked_total = 0
        try:
            linked_total = (
                db.execute(
                    text(
                        "SELECT COUNT(DISTINCT error_id) FROM error_knowledge_links"
                    )
                ).scalar()
                or 0
            )
        except Exception:
            db.rollback()  # 事务可能已 aborted，先恢复再继续
            linked_total = 0

        # 4. 题库解析率（quiz_questions.analysis 非空）
        quiz_total = db.query(QuizQuestion).count()
        quiz_analysis = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.analysis.isnot(None))
            .filter(QuizQuestion.analysis != "")
            .count()
        )

        def _pct(n: int, d: int) -> float:
            return round(n * 100.0 / d, 2) if d else 0.0

        stats = {
            "doc_index_rate": _pct(doc_indexed, doc_total),
            "vec_coverage_rate": _pct(vec_total, chunk_total),
            "error_link_rate": _pct(linked_total, error_total),
            "quiz_analysis_rate": _pct(quiz_analysis, quiz_total),
            "raw": {
                "documents": {"indexed": doc_indexed, "total": doc_total},
                "chunks": {"vec": vec_total, "total": chunk_total},
                "errors": {"linked": linked_total, "total": error_total},
                "quiz": {"analysis": quiz_analysis, "total": quiz_total},
            },
        }
        msg = (
            f"[完成度自检] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"文档索引率 {stats['doc_index_rate']}%（{doc_indexed}/{doc_total}）| "
            f"向量覆盖率 {stats['vec_coverage_rate']}%（{vec_total}/{chunk_total}）| "
            f"错题关联率 {stats['error_link_rate']}%（{linked_total}/{error_total}）| "
            f"题库解析率 {stats['quiz_analysis_rate']}%（{quiz_analysis}/{quiz_total}）"
        )
        logger.info(msg)
        print(msg)
        logger.info("COMPLETION_SELFCHECK %s", json.dumps(stats, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        logger.error("完成度自检任务失败: %s", e)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 启动 / 停止
# --------------------------------------------------------------------------- #
def _kaoyan_collect_job():
    """T5 择校数据周期采集 —— 已按合规决策停用（默认 no-op）。

    背景：原实现每周一 06:00 自动回填国家线 + 抓取 10 所院校公告列表。
    但平台已明确「**不做爬虫**」：高校属事业单位站点，自动抓取 + 对外服务
    会放大法律与反爬风险，且用户提供的合规分析明确建议走官方公开渠道。

    保留函数与调度注册是为了不破坏既有配置，但受 KAOYAN_AUTO_COLLECT 开关
    （默认 0/关闭）保护。院校/公告数据改为**手动导入 + 本地维护**：
      - POST /api/kaoyan/import  手动导入官方公布数据
      - 「数据管理」页的人工维护入口
    若用户未来明确需要自动更新，置环境变量 KAOYAN_AUTO_COLLECT=1 并自行承担合规责任。
    """
    if os.environ.get("KAOYAN_AUTO_COLLECT", "0") != "1":
        logger.info("[择校采集] 已按合规策略停用（KAOYAN_AUTO_COLLECT=0）；院校数据请手动导入")
        return

    from services.kaoyan.collector import backfill_national_lines_task, collect_notices_task

    try:
        nl = backfill_national_lines_task()
        logger.info("[择校采集] 国家线回填: %s", nl)
    except Exception as e:  # noqa: BLE001
        logger.error("[择校采集] 国家线回填失败: %s", e)
    try:
        nt = collect_notices_task(max_schools=10)
        logger.info("[择校采集] 公告: %s", nt)
    except Exception as e:  # noqa: BLE001
        logger.error("[择校采集] 公告采集失败: %s", e)


def _kaoyan_daily_autofill_job():
    """院校数据每日增量自动入库（各校公示次晨 6:30 后进库）。

    调 pipeline/notice_data_autofill.main：A 公告增量爬取 + B 名单提取 + C 入库。
    受 KAOYAN_AUTO_COLLECT 开关保护（默认 0 关闭；置 1 开启并承担合规责任，
    与原 _kaoyan_collect_job 同一决策口径）。
    """
    if os.environ.get("KAOYAN_AUTO_COLLECT", "0") != "1":
        logger.info("[每日采集] KAOYAN_AUTO_COLLECT=0，跳过自动入库（手动: python pipeline/notice_data_autofill.py）")
        return
    from pipeline.notice_data_autofill import main as autofill_main

    try:
        autofill_main()
        logger.info("[每日采集] 自动入库完成")
    except Exception as e:  # noqa: BLE001
        logger.error("[每日采集] 自动入库失败: %s", e)


def _notice_alert_job() -> None:
    """通知提醒扫描（每日 07:40）。

    产出「今日待办提醒」到 ``kaoyan_alert_records``：
    临期截止 / 新发布紧急通知 / 订阅范围内更新。
    同一notice_id + alert_kind 唯一，不会重复打扰；用户可 ack 掉单条。

    时区：job 用显式 tzinfo 的 CronTrigger（不用字符串），见模块头部说明，
    规避 Windows 缺 tzdata 导致的静默不注册。
    """
    from services.kaoyan.notice_alert import scan_alerts, cn_now

    db = SessionLocal()
    try:
        result = scan_alerts(db, trigger="schedule")
        msg = (
            f"[通知提醒] {cn_now().strftime('%Y-%m-%d %H:%M')} "
            f"扫描 {result['scanned']} 条 / 新增提醒 {result['created']} 条 / "
            f"去重跳过 {result['skipped_dup']} 条（{result['elapsed_ms']}ms）"
        )
        logger.info(msg)
        print(msg)
    except Exception as e:  # noqa: BLE001
        logger.error("通知提醒扫描任务失败: %s", e)
    finally:
        db.close()


def start_scheduler():
    """启动后台调度器（幂等）。多 worker 下只有持锁进程真正启动，其余返回 None。"""
    if scheduler.running:
        return scheduler
    if os.getenv("SCHEDULER_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
        logger.info("SCHEDULER_ENABLED=0，跳过定时任务")
        return None
    if not acquire_singleton_lock():
        logger.info("定时任务已由其他 worker 持有，本进程不启动调度器")
        return None
    # 复习提醒：每天 08:30
    scheduler.add_job(
        _review_reminder_job,
        CronTrigger(hour=8, minute=30, timezone=_SHANGHAI_TZ),
        id="review_reminder",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # 网盘同步：每小时第 30 分钟
    scheduler.add_job(
        _netdisk_sync_job,
        CronTrigger(minute=30, timezone=_SHANGHAI_TZ),
        id="netdisk_sync",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # 完成度自检：每天 07:30
    scheduler.add_job(
        _completion_selfcheck_job,
        CronTrigger(hour=7, minute=30, timezone=_SHANGHAI_TZ),
        id="completion_selfcheck",
        replace_existing=True,
        misfire_grace_time=3600,
    )
# T5 择校数据采集：每周一 06:00（轻量增量：国家线+公告）
    scheduler.add_job(
        _kaoyan_collect_job,
        CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=_SHANGHAI_TZ),
        id="kaoyan_collect",
        replace_existing=True,
        misfire_grace_time=86400,
    )
    # 院校数据每日增量：各校公示次晨 6:30 后自动入库（KAOYAN_AUTO_COLLECT=1 时生效）
    scheduler.add_job(
        _kaoyan_daily_autofill_job,
        CronTrigger(hour=6, minute=30, timezone=_SHANGHAI_TZ),
        id="kaoyan_daily_autofill",
        replace_existing=True,
        misfire_grace_time=86400,
    )
    # 通知提醒扫描：每天 07:40（时区显式，避免 Windows tzdata 静默失败）
    scheduler.add_job(
        _notice_alert_job,
        CronTrigger(hour=7, minute=40, timezone=_SHANGHAI_TZ),
        id="notice_alert_scan",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("APScheduler 已启动（复习提醒 08:30 / 网盘同步每小时 / 完成度自检 07:30 / 择校采集每周一 06:00）")
    print("[调度] APScheduler 已启动：复习提醒 08:30、网盘同步每小时、完成度自检 07:30、择校采集每周一06:00")
    return scheduler


def stop_scheduler():
    """停止调度器（幂等）。"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler 已停止")
