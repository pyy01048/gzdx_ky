# -*- coding: utf-8 -*-
"""V4 结构迁移：新增三级结构 / 联动 / 复习追踪字段与表，并移除课表死表。

设计原则（务必遵守）：
  * **只增不改不丢**：新列全部 nullable 或带默认值，绝不 DROP 有数据的表。
  * **幂等**：重复执行安全，已存在的列/表/索引自动跳过。
  * **先备份**：执行前自动复制一份 kaoyan.db.bak-<时间戳>。

执行：
    cd backend-main-fastapi
    python scripts/migrate_v4_schema.py
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "kaoyan.db")

# --------------------------------------------------------------------------- #
# 1. 新增列
# --------------------------------------------------------------------------- #
NEW_COLUMNS: list[tuple[str, str, str]] = [
    # knowledge_points：三级结构的"题型"层 + 复习进度追踪字段
    ("knowledge_points", "question_types", "ALTER TABLE knowledge_points ADD COLUMN question_types JSON"),
    ("knowledge_points", "difficulty", "ALTER TABLE knowledge_points ADD COLUMN difficulty INTEGER DEFAULT 3"),
    ("knowledge_points", "review_count", "ALTER TABLE knowledge_points ADD COLUMN review_count INTEGER DEFAULT 0"),
    ("knowledge_points", "last_review", "ALTER TABLE knowledge_points ADD COLUMN last_review DATETIME"),
    ("knowledge_points", "next_review", "ALTER TABLE knowledge_points ADD COLUMN next_review DATETIME"),
    ("knowledge_points", "ease_factor", "ALTER TABLE knowledge_points ADD COLUMN ease_factor FLOAT DEFAULT 2.5"),
    ("knowledge_points", "interval", "ALTER TABLE knowledge_points ADD COLUMN interval INTEGER DEFAULT 0"),
    ("knowledge_points", "lapses", "ALTER TABLE knowledge_points ADD COLUMN lapses INTEGER DEFAULT 0"),
    ("knowledge_points", "question_count", "ALTER TABLE knowledge_points ADD COLUMN question_count INTEGER DEFAULT 0"),

    # documents：文档组织三层结构 + OCR 标记
    ("documents", "doc_type", "ALTER TABLE documents ADD COLUMN doc_type VARCHAR(20)"),
    ("documents", "structure_level", "ALTER TABLE documents ADD COLUMN structure_level VARCHAR(20)"),
    ("documents", "ocr_used", "ALTER TABLE documents ADD COLUMN ocr_used BOOLEAN DEFAULT 0"),
]

# --------------------------------------------------------------------------- #
# 2. 新增表
# --------------------------------------------------------------------------- #
NEW_TABLES: list[tuple[str, str]] = [
    ("error_knowledge_links", """
        CREATE TABLE IF NOT EXISTS error_knowledge_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_id INTEGER NOT NULL REFERENCES error_records(id),
            knowledge_point_id INTEGER REFERENCES knowledge_points(id),
            chunk_id INTEGER REFERENCES knowledge_chunks(id),
            document_id INTEGER REFERENCES documents(id),
            relevance FLOAT DEFAULT 0,
            source VARCHAR(20) DEFAULT 'auto',
            created_at DATETIME
        )
    """),
    ("review_records", """
        CREATE TABLE IF NOT EXISTS review_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type VARCHAR(20) NOT NULL,
            item_id INTEGER NOT NULL,
            subject VARCHAR(50),
            chapter VARCHAR(200),
            result VARCHAR(20),
            grade INTEGER DEFAULT 0,
            mastery_before INTEGER DEFAULT 0,
            mastery_after INTEGER DEFAULT 0,
            duration INTEGER DEFAULT 0,
            interval_after INTEGER DEFAULT 0,
            next_review DATETIME,
            note TEXT,
            created_at DATETIME
        )
    """),
]

NEW_INDEXES: list[tuple[str, str, str]] = [
    ("error_knowledge_links", "ix_ekl_error", "error_id"),
    ("error_knowledge_links", "ix_ekl_kp", "knowledge_point_id"),
    ("error_knowledge_links", "ix_ekl_error_kp", "error_id, knowledge_point_id"),
    ("review_records", "ix_review_item", "item_type, item_id"),
    ("review_records", "ix_review_created", "created_at"),
    ("review_records", "ix_review_subject", "subject"),
    ("knowledge_points", "ix_kp_subject_chapter", "subject, chapter"),
    ("knowledge_points", "ix_kp_next_review", "next_review"),
    ("documents", "ix_documents_doc_type", "doc_type"),
]

# --------------------------------------------------------------------------- #
# 3. 待移除的课表死表（仅当确认 0 行时才删，否则只改名保留）
# --------------------------------------------------------------------------- #
DEAD_SCHEDULE_TABLES = ["course_adjustments", "courses", "semesters"]


def table_exists(cur: sqlite3.Connection, name: str) -> bool:
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def row_count(cur: sqlite3.Connection, name: str) -> int:
    try:
        return cur.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    except sqlite3.Error:
        return -1


def main() -> int:
    if not os.path.exists(DB):
        print(f"[x] 数据库不存在：{DB}")
        return 1

    # —— 备份 —— #
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{DB}.bak-{stamp}"
    shutil.copy2(DB, backup)
    print(f"[✓] 已备份 → {os.path.basename(backup)}")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # —— 1. 加列 —— #
    added = 0
    for table, col, ddl in NEW_COLUMNS:
        if not table_exists(cur, table):
            print(f"[!] 跳过 {table}.{col}：表不存在")
            continue
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")')]
        if col in cols:
            print(f"[=] {table}.{col} 已存在")
            continue
        try:
            cur.execute(ddl)
            conn.commit()
            added += 1
            print(f"[+] {table}.{col} 已新增")
        except sqlite3.Error as e:
            conn.rollback()
            print(f"[x] {table}.{col} 失败：{e}")

    # —— 2. 建表 —— #
    for name, ddl in NEW_TABLES:
        if table_exists(cur, name):
            print(f"[=] 表 {name} 已存在")
            continue
        cur.execute(ddl)
        conn.commit()
        print(f"[+] 表 {name} 已创建")

    # —— 3. 建索引 —— #
    for table, index, cols in NEW_INDEXES:
        if not table_exists(cur, table):
            continue
        try:
            cur.execute(f'CREATE INDEX IF NOT EXISTS "{index}" ON "{table}" ({cols})')
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            print(f"[x] 索引 {index} 失败：{e}")
    print(f"[✓] 索引检查完成（{len(NEW_INDEXES)} 个）")

    # —— 4. 清理课表死表 —— #
    for t in DEAD_SCHEDULE_TABLES:
        if not table_exists(cur, t):
            continue
        n = row_count(cur, t)
        if n == 0:
            cur.execute(f'DROP TABLE "{t}"')
            conn.commit()
            print(f"[-] 已删除空表 {t}")
        else:
            cur.execute(f'ALTER TABLE "{t}" RENAME TO "{t}_removed_schedule"')
            conn.commit()
            print(f"[!] {t} 有 {n} 行数据，已改名保留为 {t}_removed_schedule（未删除）")

    # —— 5. 校验 —— #
    print("\n=== 迁移后校验 ===")
    for table in ("knowledge_points", "documents", "error_knowledge_links", "review_records"):
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")')]
        print(f"{table}: {len(cols)} 列 | {cols}")
    remaining = [
        r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if any(k in r[0] for k in ("semester", "course"))
    ]
    print(f"残留课表相关表：{remaining or '无'}")

    conn.close()
    print(f"\n[✓] 迁移完成。新增列 {added} 个。备份：{backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
