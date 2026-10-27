#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 KyleBing 考研词库丰富核心词库的 extra 字段 (PostgreSQL)

对「考研核心词汇」deck 中已存在的词，若 extra 为空，则写入 KyleBing 的
同近义(synonyms)/短语(phrases)/同根(rel_words) 结构化 JSON。

数据源: data_sources/english-vocabulary/.../full/正序/考研.jsonl (5047 唯一词)
幂等: 仅更新 extra IS NULL 的行
运行: python scripts/enrich_words_kylebing_pg.py
"""
import io
import json
import os
import sys

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
JSONL = os.path.join(
    PROJECT_ROOT, "..", "data_sources", "english-vocabulary", "english-vocabulary-master",
    "full_line_jsonl", "full", "正序", "考研.jsonl",
)

DB_CONFIG = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)

CORE_DECK_NAME = "考研核心词汇"


def load_unique_words(path: str):
    """加载 考研.jsonl，按 headWord 去重（保留内容最全的一条），返回 {lower: extra}"""
    if not os.path.exists(path):
        print(f"JSONL 不存在: {path}")
        sys.exit(1)
    result = {}
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            content = (obj.get("content") or {}).get("word") or {}
            wc = content.get("content") or {}
            word = (obj.get("headWord") or content.get("wordHead") or "").strip()
            if not word:
                continue
            synos = []
            for s in (wc.get("syno") or {}).get("synos") or []:
                synos.append({
                    "pos": s.get("pos"),
                    "tran": s.get("tran"),
                    "words": [w.get("w") for w in (s.get("hwds") or []) if w.get("w")],
                })
            phrases = []
            for p in (wc.get("phrase") or {}).get("phrases") or []:
                phrases.append({"phrase": p.get("pContent"), "cn": p.get("pCn")})
            rels = []
            for r in (wc.get("relWord") or {}).get("rels") or []:
                rels.append({
                    "pos": r.get("pos"),
                    "words": [{"w": x.get("hwd"), "tran": x.get("tran")} for x in (r.get("words") or []) if x.get("hwd")],
                })
            extra = {"synonyms": synos, "phrases": phrases, "rel_words": rels, "source": "KyleBing"}
            result[word.lower()] = extra  # 后出现的覆盖（内容更全）
    return result


def main():
    data = load_unique_words(JSONL)
    print(f"KyleBing 唯一词: {len(data)}")

    conn = psycopg.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM word_decks WHERE name = %s ORDER BY id", (CORE_DECK_NAME,))
        deck_ids = [r[0] for r in cur.fetchall()]
        print(f"核心 deck: {deck_ids}")

        total = 0
        for deck_id in deck_ids:
            cur.execute(
                "SELECT id, lower(word) FROM words WHERE deck_id=%s AND (extra IS NULL OR extra = '{}'::jsonb)",
                (deck_id,),
            )
            rows = cur.fetchall()
            print(f"deck {deck_id}: 待丰富 {len(rows)}")
            batch = []
            for wid, lower_w in rows:
                extra = data.get(lower_w)
                if extra:
                    batch.append((json.dumps(extra, ensure_ascii=False), wid))
            BATCH_SIZE = 500
            for i in range(0, len(batch), BATCH_SIZE):
                sub = batch[i:i + BATCH_SIZE]
                cur.executemany(
                    "UPDATE words SET extra = %s::jsonb, updated_at = NOW() WHERE id = %s",
                    sub,
                )
            total += cur.rowcount
            print(f"deck {deck_id}: 实际丰富 {len(batch)}")

    conn.commit()
    conn.close()
    print(f"总计丰富: {total}")
    print("=== 完成 ===")


if __name__ == "__main__":
    main()