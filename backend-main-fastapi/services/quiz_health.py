# -*- coding: utf-8 -*-
"""题库健康快照（完善方案 11 §3.5）。

指标（只降不升，进 /api/health 与告警）：
    warn_available         可用但 validation_status=warn 的题数（目标 0）
    dup_groups             归一化题干重复组数（目标 <20，且剩余为合法跨年同题）
    no_analysis_objective  客观题缺解析数
    past_exam_ratio        真题占比（含 is_past_exam=true）
    total_available        可用题总数

实现约定：每个指标独立 try/except，单项失败只影响该项（同 health_service 约定）。
归一化用 SQL 侧的 ``regexp_replace(content, '\\s', '', 'g')`` 近似——
Python 侧的完整归一（全半角/标点）在去重脚本里做，这里只做趋势监控，不追求逐条精确。
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _scalar(conn, sql: str, **params) -> int | float | None:
    try:
        return conn.execute(text(sql), params).scalar()
    except Exception as exc:  # noqa: BLE001
        logger.debug("quiz_health 查询失败：%s", exc)
        # PG 下一条语句失败会把整个事务置为 aborted，导致后续指标全部失败。
        # 健康探测是只读场景：回滚以结束坏事务，下一条查询会自动开启新事务。
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


def _dialect_name(conn) -> str:
    """Connection 自带 .dialect；Session 走 get_bind()；两者都不可用时返回空。"""
    dialect = getattr(conn, "dialect", None)
    if dialect is not None:
        return getattr(dialect, "name", "") or ""
    try:
        bind = conn.get_bind()
        return getattr(getattr(bind, "dialect", None), "name", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def quiz_health_snapshot(conn=None) -> dict:
    """返回题库健康指标；任何一项失败为 None，不抛异常。"""
    own = conn is None
    if own:
        from database import engine

        conn = engine.connect()
    try:
        is_pg = _dialect_name(conn) == "postgresql"
        snap: dict = {}

        snap["total_available"] = _scalar(conn, "SELECT count(*) FROM quiz_questions WHERE is_available IS TRUE")
        snap["warn_available"] = _scalar(
            conn,
            "SELECT count(*) FROM quiz_questions WHERE is_available IS TRUE AND validation_status = 'warn'",
        )
        snap["no_analysis_objective"] = _scalar(
            conn,
            "SELECT count(*) FROM quiz_questions "
            "WHERE is_available IS TRUE AND CAST(question_type AS text) IN ('single','multiple','judge') "
            "AND (analysis IS NULL OR btrim(analysis) = '')",
        )
        snap["past_exam_count"] = _scalar(
            conn,
            "SELECT count(*) FROM quiz_questions WHERE is_past_exam IS TRUE",
        )
        if snap["total_available"] and snap["past_exam_count"] is not None:
            snap["past_exam_ratio"] = round(snap["past_exam_count"] / snap["total_available"], 4)
        else:
            snap["past_exam_ratio"] = None

        if is_pg:
            dup_sql = (
                "SELECT count(*) FROM ("
                "  SELECT regexp_replace(lower(content), '\\s', '', 'g') AS k"
                "  FROM quiz_questions WHERE is_available IS TRUE"
                "  GROUP BY k HAVING count(*) > 1"
                ") t"
            )
        else:
            dup_sql = (
                "SELECT count(*) FROM ("
                "  SELECT lower(replace(replace(content, ' ', ''), char(10), '')) AS k"
                "  FROM quiz_questions WHERE is_available = 1"
                "  GROUP BY k HAVING count(*) > 1"
                ") t"
            )
        snap["dup_groups"] = _scalar(conn, dup_sql)

        # 告警阈值（09 文档心跳通道消费）：warn>0 / dup>=20 视为需要处理
        alerts = []
        if (snap.get("warn_available") or 0) > 0:
            alerts.append(f"warn 题 {snap['warn_available']} 道待处置")
        if (snap.get("dup_groups") or 0) >= 20:
            alerts.append(f"重复题干 {snap['dup_groups']} 组（阈值 20）")
        snap["alerts"] = alerts
        snap["status"] = "warn" if alerts else "ok"
        return snap
    finally:
        if own:
            conn.close()
