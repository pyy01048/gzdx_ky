#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NETEMVocabulary 大纲词补全 + 例句回填 (PostgreSQL)

数据源: data_sources/NETEMVocabulary/netem_full_list.json
  - 5530 考研大纲词，按词频排序，含 释义/CEFR/例句/例句翻译/词频/真题次数

动作:
  1. 对 deck 内已存在的词（deck_id=1 及其用户副本）: 若 example 为空则回填例句/例句翻译
  2. 对 deck 内缺失的大纲词: INSERT（SM-2 默认状态）
  3. 更新 word_decks.word_count

幂等: 依赖唯一索引 uq_word_in_deck(deck_id, word) + ON CONFLICT DO NOTHING / DO UPDATE
运行: python scripts/import_netem_supplement_pg.py
"""
import io
import json
import os
import sys
from datetime import date, datetime, timezone

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
NETEM_JSON = os.path.join(PROJECT_ROOT, "..", "data_sources", "NETEMVocabulary", "netem_full_list.json")

DB_CONFIG = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)

STATUS = "not_mastered"
TAG = "kaoyan"


def load_netem(path: str):
    """加载 NETEM 全量词表，返回 {lower_word: item}"""
    if not os.path.exists(path):
        print(f"NETEM 文件不存在: {path}")
        sys.exit(1)
    with io.open(path, encoding="utf-8") as f:
        data = json.load(f)
    key = list(data.keys())[0]
    items = data[key]
    result = {}
    for it in items:
        w = (it.get("单词") or "").strip()
        if w:
            result[w.lower()] = it
    return result


def main():
    netem = load_netem(NETEM_JSON)
    print(f"NETEM 词条数: {len(netem)}")

    conn = psycopg.connect(**DB_CONFIG, autocommit=True)
    cur = conn.cursor()

    # 找所有「考研核心词汇」deck（user 副本）
    cur.execute("SELECT id, user_id FROM word_decks WHERE name = %s ORDER BY id", ("考研核心词汇",))
    decks = cur.fetchall()
    print(f"考研核心词汇 deck: {decks}")

    today = date.today()
    now = datetime.now(timezone.utc)

    total_insert = 0
    total_update = 0
    for deck_id, uid in decks:
        cur.execute("SELECT lower(word) FROM words WHERE deck_id = %s", (deck_id,))
        existing = {r[0] for r in cur.fetchall()}

        insert_batch = []
        update_batch = []
        for lower_w, item in netem.items():
            word = item["单词"].strip()
            meaning = (item.get("释义") or "").strip()
            example = (item.get("例句") or "").strip() or None
            example_cn = (item.get("例句翻译") or "").strip() or None
            if lower_w in existing:
                update_batch.append((example, example_cn, deck_id, lower_w))
            else:
                insert_batch.append((
                    deck_id, word, meaning or None, example, example_cn, TAG,
                    STATUS, 2.5, 0, 0, 0, today, None, [], now, now, uid,
                ))

        # 回填例句（仅当 example 为空）
        if update_batch:
            UPDATE_SQL = """
                UPDATE words SET
                    example = COALESCE(words.example, %s),
                    example_cn = COALESCE(words.example_cn, %s),
                    updated_at = NOW()
                WHERE deck_id = %s AND lower(word) = %s
            """
            for b in update_batch:
                cur.execute(UPDATE_SQL, b)
            total_update += cur.rowcount

        # 插入缺失大纲词
        if insert_batch:
            INSERT_SQL = """
                INSERT INTO words (
                    deck_id, word, phonetic, pos, meaning, root, example, example_cn, tag,
                    status, ease_factor, interval_days, reps, lapses, due_date, last_review,
                    review_history, created_at, updated_at, user_id
                ) VALUES (%s,%s,NULL,NULL,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (deck_id, word) DO NOTHING
            """
            BATCH = 500
            for i in range(0, len(insert_batch), BATCH):
                cur.executemany(INSERT_SQL, insert_batch[i:i + BATCH])
            total_insert += cur.rowcount

        # 更新 word_count
        cur.execute(
            "UPDATE word_decks SET word_count = (SELECT count(*) FROM words WHERE deck_id=%s) WHERE id=%s",
            (deck_id, deck_id),
        )
        print(f"deck {deck_id} (user {uid}): 回填 {len(update_batch)} 条, 插入 {len(insert_batch)} 条")

    print(f"\n合计: 例句回填 {total_update}, 缺失插入 {total_insert}")
    cur.close()
    conn.close()
    print("=== 完成 ===")


if __name__ == "__main__":
    main()