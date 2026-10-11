# -*- coding: utf-8 -*-
"""
答案置信度体系 Schema（P0-方向一，2026-10）
============================================
为每条答案/解析标注「来源 + 置信度分数」，并把交叉校验冲突改为人工确认队列。

新增表（全部 CREATE TABLE IF NOT EXISTS，幂等可重跑）：
  1. answer_confidence_meta   —— 每题「当前生效答案」的聚合元信息
     （最终来源 / 置信度分数 / 是否参与自动判分），供判分链路快速查询。
  2. answer_conflict_queue    —— 人工确认队列：交叉校验冲突不再自动消解，
     冲突双方答案、来源、置信度全部入队，等待人工确认/驳回。
  3. answer_confidence_log    —— 置信度审计日志：候选写入、入队、确认、驳回
     全程留痕，便于追溯与自检。

设计约定：
  - 本模块只做 DDL，不依赖 SQLAlchemy models，接收原生 sqlite3.Connection，
    方便在测试中以内存库独立验证。
  - 所有 DDL 均幂等；不 ALTER 现有业务表（answer_candidates /
    quiz_questions 结构保持不变），避免对 280MB 生产库产生风险。
  - 置信度分数：bank=0.90 / extracted=0.85 / llm=0.50 /
    user_confirmed=0.95；阈值：used_for_grading >= 0.7，
    参与自动判分需 >= 0.7 且来源非纯 LLM 生成（详见 service 层）。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import List

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# DDL（全部幂等）
# --------------------------------------------------------------------------- #
SCHEMA_SQL: List[str] = [
    # 1) 每题的聚合置信度元信息（1:1 quiz_questions）
    """
    CREATE TABLE IF NOT EXISTS answer_confidence_meta (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL UNIQUE,
        final_source TEXT,
        final_confidence REAL NOT NULL DEFAULT 0.0,
        grade_eligible INTEGER NOT NULL DEFAULT 0,
        conflict_pending INTEGER NOT NULL DEFAULT 0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # 2) 人工确认队列（交叉校验冲突的落点）
    """
    CREATE TABLE IF NOT EXISTS answer_conflict_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL,
        bank_answer TEXT,
        bank_source TEXT,
        bank_confidence REAL,
        alt_answer TEXT,
        alt_source TEXT,
        alt_confidence REAL,
        conflict_detail TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        resolved_by TEXT,
        resolved_at DATETIME,
        note TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_confq_qid ON answer_conflict_queue(question_id)
    """,
    # 同一题目最多一条未处理(pending)的冲突记录（部分唯一索引）
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_confq_pending
        ON answer_conflict_queue(question_id) WHERE status = 'pending'
    """,
    # 3) 置信度审计日志
    """
    CREATE TABLE IF NOT EXISTS answer_confidence_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL,
        event TEXT NOT NULL,
        source TEXT,
        answer TEXT,
        confidence REAL,
        used_for_grading INTEGER,
        note TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_acl_qid ON answer_confidence_log(question_id)
    """,
]


def ensure_answer_confidence_schema(conn: sqlite3.Connection) -> dict:
    """幂等创建答案置信度体系相关表。

    Args:
        conn: 原生 sqlite3 连接（可传内存库用于测试）。

    Returns:
        {"created_tables": [str, ...]} 本次实际创建的表名列表。

    Raises:
        sqlite3.Error: DDL 执行失败（不做数据变更，安全）。
    """
    created: List[str] = []
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        for stmt in SCHEMA_SQL:
            conn.execute(stmt)
            if stmt.strip().upper().startswith("CREATE TABLE"):
                # 幂等：无论是否已存在都无副作用，仅收集表名供报告
                name = stmt.split("(", 1)[0].replace("CREATE TABLE IF NOT EXISTS", "").strip()
                created.append(name)
        conn.commit()
    except sqlite3.Error as e:  # pragma: no cover - 依赖 SQLite 行为
        conn.rollback()
        logger.exception("答案置信度 Schema 创建失败")
        raise
    return {"created_tables": sorted(set(created))}


if __name__ == "__main__":  # pragma: no cover
    conn = sqlite3.connect(":memory:")
    print(ensure_answer_confidence_schema(conn))
