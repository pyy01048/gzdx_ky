# -*- coding: utf-8 -*-
"""热门数据路径冷启动预热（2026-11 性能波）。

问题：部署/重启 uvicorn 后，连接池为空、PG 计划缓存冷、操作系统页缓存可能已驱逐，
首个真实用户在 dashboard / schools / quiz 等只读端点会白吃 150~300ms 冷启动
（本机实测：/api/dashboard 首调 290ms、/api/kaoyan/schools 150ms、/api/analytics/overview 306ms，
稳态均 <60ms）。这部分成本与查询本身无关，纯属"第一个人碰开关"。

本模块在启动后台线程跑一组代表性轻量只读查询，把：
  * SQLAlchemy 连接池（QueuePool 预占连接，首请求不再现建连）
  * PG 计划缓存（热点谓词的 generic plan 提前编译）
  * 操作系统页缓存 / PG shared_buffers（热点表与索引页提前读入内存）
预热到稳态，使首个真实用户即享稳态延迟。

关掉方式：``HOT_PATH_WARMUP=0``（测试/低配机器）。与 SEARCH_WARMUP 同一套做法：
fire-and-forget 守护线程，不阻塞启动，失败只告警，绝不影响主流程。
"""

from __future__ import annotations

import os
import threading
import time

from database import SessionLocal
from utils.logger import get_logger

logger = get_logger("services.hot_path_warmup")

_lock = threading.Lock()
_started = False

# (标签, SQL) —— 全部只读、带 LIMIT，确保轻量；谓词对齐线上热点端点的过滤口径。
_PRIME_QUERIES = (
    (
        "quiz_active_pool",
        "SELECT id FROM quiz_questions WHERE is_available IS TRUE AND (is_junk IS FALSE OR is_junk IS NULL) LIMIT 20",
    ),
    (
        "quiz_active_count",
        "SELECT count(*) FROM quiz_questions WHERE is_available IS TRUE AND (is_junk IS FALSE OR is_junk IS NULL)",
    ),
    ("quiz_review_queue", "SELECT id FROM quiz_questions WHERE needs_review IS TRUE LIMIT 20"),
    ("schools_list", "SELECT id FROM kaoyan_schools ORDER BY id LIMIT 20"),
    ("schools_count", "SELECT count(*) FROM kaoyan_schools"),
    ("documents_list", "SELECT id FROM documents ORDER BY id LIMIT 5"),
    ("documents_count", "SELECT count(*) FROM documents"),
    ("goals_count", "SELECT count(*) FROM goals"),
    ("errors_count", "SELECT count(*) FROM error_records"),
    ("users_count", "SELECT count(*) FROM users"),
)


def run_hot_path_warmup() -> dict:
    """同步执行预热查询，返回各步耗时（毫秒）。任一步失败都不抛出。"""
    from sqlalchemy import text

    out: dict[str, float] = {}
    db = SessionLocal()
    try:
        for name, sql in _PRIME_QUERIES:
            t0 = time.perf_counter()
            try:
                db.execute(text(sql)).fetchall()
                out[name] = round((time.perf_counter() - t0) * 1000, 1)
            except Exception as e:  # noqa: BLE001 —— 预热失败只是首请求变慢，不能影响启动
                out[name] = round((time.perf_counter() - t0) * 1000, 1)
                logger.warning("[预热] 热门路径 %s 失败（首请求会重试）: %s", name, e)
        # 仪表盘冷启动主因：study_calendar.day_ledger 首次执行要编译 6 条聚合查询并
        # 冷读 StudySession / ReviewRecord / AnswerRecord 等表页（实测冷 392ms / 热 5ms）。
        # 这里用同一会话跑一次，把 PG 计划缓存 + 操作系统页缓存预热到稳态，
        # 首个真实用户打开 dashboard 即享 <10ms（否则会白吃 ~300ms）。
        try:
            from services import study_calendar

            t0 = time.perf_counter()
            study_calendar.day_ledger(db)
            out["study_calendar.day_ledger"] = round((time.perf_counter() - t0) * 1000, 1)
        except Exception as e:  # noqa: BLE001
            logger.warning("[预热] day_ledger 失败（首请求会重试）: %s", e)
        # 显式把连接留在池里：SessionLocal() 关闭时连接归还 QueuePool 复用
        try:
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
    return out


def start_hot_path_warmup() -> bool:
    """起守护线程做热门路径预热（幂等：重复调用只起一次）。返回是否新起了线程。"""
    global _started
    if os.environ.get("HOT_PATH_WARMUP", "1").lower() in {"0", "false", "no"}:
        logger.info("[预热] HOT_PATH_WARMUP=0，跳过热门数据路径预热")
        return False
    with _lock:
        if _started:
            return False
        _started = True

    def _warm() -> None:
        t0 = time.perf_counter()
        steps = run_hot_path_warmup()
        total_ms = round((time.perf_counter() - t0) * 1000, 1)
        slow = {k: v for k, v in steps.items() if v >= 50}
        logger.info(
            "[预热] 热门数据路径完成，总用时 %.1fms（%d 步；慢查询>=50ms: %s）",
            total_ms,
            len(steps),
            slow or "无",
        )

    threading.Thread(target=_warm, name="hot-path-warmup", daemon=True).start()
    return True
