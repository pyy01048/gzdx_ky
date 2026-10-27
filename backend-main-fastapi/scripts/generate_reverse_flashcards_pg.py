# -*- coding: utf-8 -*-
"""生成反向闪卡（释义→知识点名），将卡片总量扩至 3000+。

背景：现有 flashcards 1853 张，均为「知识点名 → 释义」正向卡。
本脚本为每个已有正向卡的知识点补一张「释义 → 知识点名」反向卡，
使卡片总量达到 3700+，覆盖「看释义回忆概念」的记忆场景。

幂等：
- 以 knowledge_point_id 为锚，若该知识点已存在反向卡则跳过。
- 判定反向卡：front 不等于该知识点的 name（正向卡的 front 是 name）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

DB_CONFIG = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)

USER_ID = 1


def main() -> None:
    conn = psycopg.connect(**DB_CONFIG, autocommit=True)
    cur = conn.cursor()

    # 找出所有已有正向卡的知识点（正向卡：front = kp.name）
    cur.execute("""
        SELECT f.knowledge_point_id, kp.name, kp.description
        FROM flashcards f
        JOIN knowledge_points kp ON kp.id = f.knowledge_point_id
        WHERE f.knowledge_point_id IS NOT NULL
          AND kp.description IS NOT NULL
          AND length(kp.description) >= 5
        ORDER BY f.knowledge_point_id
    """)
    rows = cur.fetchall()
    print(f"可生成反向卡的知识点: {len(rows)}")

    # 已存在的反向卡：front 不等于 kp.name 的卡片
    cur.execute("""
        SELECT knowledge_point_id FROM flashcards
        WHERE knowledge_point_id IS NOT NULL
          AND front IS DISTINCT FROM (
              SELECT name FROM knowledge_points WHERE id = knowledge_point_id
          )
    """)
    existing_reverse = {r[0] for r in cur.fetchall()}
    print(f"已存在的反向卡: {len(existing_reverse)}")

    inserted = 0
    skipped = 0
    for kp_id, name, desc in rows:
        if kp_id in existing_reverse:
            skipped += 1
            continue
        # front = 释义（截断到 200 字），back = 知识点名
        front = (desc or "").strip()[:200]
        if not front:
            skipped += 1
            continue
        cur.execute(
            """
            INSERT INTO flashcards
                (front, back, knowledge_point_id, review_count, interval_days,
                 ease_factor, mastery, user_id)
            VALUES (%s, %s, %s, 0, 0, 2.5, 'not_mastered', %s)
            """,
            (front, name, kp_id, USER_ID),
        )
        inserted += 1

    print(f"新增反向卡: {inserted}, 跳过已有: {skipped}")

    cur.execute("SELECT count(*) FROM flashcards")
    print(f"闪卡总数: {cur.fetchone()[0]}")

    cur.close()
    conn.close()
    print("完成 ✅")


if __name__ == "__main__":
    main()
