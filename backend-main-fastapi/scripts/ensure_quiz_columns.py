# -*- coding: utf-8 -*-
"""补齐 quiz_questions 缺列（M0 刷题中心前置修复）。

### 背景（实测）

真库 `DATABASE_PATH`（D:\\平台\\database\\kaoyan.db）的 `quiz_questions` 表**缺少
``answer_source`` / ``answer_confidence`` 两列**，而 `models.QuizQuestion` 已声明
这两列。SQLAlchemy ORM 查询默认 `SELECT` 全部映射列，于是**任何** quiz 查询
（列表 / 详情 / 提交判分）都会抛
``sqlite3.OperationalError: no such column: quiz_questions.answer_source``
—— 刷题中心整体不可用。全库仅此一张表存在该列漂移（已用 metadata 全量比对确认）。

### 做法

只增不改不丢：两列均可空，``ALTER TABLE ... ADD COLUMN`` 幂等（已存在则跳过）。
执行前**必须**先经 `services/backup_service.create_backup()`（sqlite3 ``src.backup()``
在线备份）留底，绝不使用 cp/copy2 复制 .db。

执行：
    cd backend-main-fastapi
    D:/Anaconda/python.exe scripts/ensure_quiz_columns.py
"""
from __future__ import annotations

import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from services.backup_service import create_backup, _resolve_db_path  # noqa: E402

# (列名, 列定义) —— 与 models.QuizQuestion 对齐
NEW_COLUMNS: list[tuple[str, str]] = [
    ("answer_source", "VARCHAR(20)"),        # 答案来源：bank/source_extract/llm_generated/user_confirmed
    ("answer_confidence", "FLOAT"),          # 答案置信度 0-1（<0.8 不参与自动判分）
]


def existing_columns(cur: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}


def main() -> int:
    db_path = _resolve_db_path()
    print(f"[ensure_quiz_columns] 目标库: {db_path}")
    if not os.path.exists(db_path):
        print("[ensure_quiz_columns] 数据库不存在，终止")
        return 2

    # 铁律：任何写库前先做在线备份
    backup_path = create_backup()
    print(f"[ensure_quiz_columns] 已备份 → {backup_path}")

    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        have = existing_columns(cur, "quiz_questions")
        if not have:
            print("[ensure_quiz_columns] quiz_questions 表不存在，终止")
            return 3
        added = []
        for col, ddl in NEW_COLUMNS:
            if col in have:
                print(f"[ensure_quiz_columns] 已存在，跳过: {col}")
                continue
            cur.execute(f"ALTER TABLE quiz_questions ADD COLUMN {col} {ddl}")
            added.append(col)
            print(f"[ensure_quiz_columns] 已新增列: {col} {ddl}")
        con.commit()
        # 复核
        now = existing_columns(cur, "quiz_questions")
        missing = [c for c, _ in NEW_COLUMNS if c not in now]
        if missing:
            print(f"[ensure_quiz_columns] 复核失败，仍缺: {missing}")
            return 4
        print(f"[ensure_quiz_columns] 完成，本次新增 {len(added)} 列: {added}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
