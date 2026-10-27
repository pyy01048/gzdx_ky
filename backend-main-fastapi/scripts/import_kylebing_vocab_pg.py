#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入 KyleBing/english-vocabulary 考研词库 (PostgreSQL)

数据源: data_sources/english-vocabulary/.../full/正序/考研.jsonl (9602 词)
格式: 有道词典 JSONL
  - headWord / content.word.content:
      trans[]  : {pos, tranCn, descCn}  释义
      usphone/ukphone                  音标
      sentence.sentences[] : {sContent, sCn}  例句
      syno.synos[]           : {pos, tran, hwds:[{w}]}  同近义
      phrase.phrases[]       : {pContent, pCn}  短语
      relWord.rels[]         : {pos, words:[{hwd, tran}]}  同根

策略:
  1. 新建 deck「考研扩展词汇」(source=KyleBing)
  2. 只导入核心 deck（考研核心词汇，deck_id=1）中不存在的词，避免重复
  3. words 表新增 extra JSONB 列，存放 同近义/短语/同根 结构化数据
  4. example/example_cn 用首条例句

幂等: uq_word_in_deck(deck_id, word) ON CONFLICT DO NOTHING
运行: python scripts/import_kylebing_vocab_pg.py
"""
import io
import json
import os
import sys
from datetime import date, datetime, timezone

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

DECK_NAME = "考研扩展词汇"
DECK_DESCRIPTION = "考研词汇扩展 9602（KyleBing english-vocabulary，含同近义/短语/例句）"
DECK_SOURCE = "KyleBing"
CORE_DECK_NAME = "考研核心词汇"
USER_ID = 1
TAG = "kaoyan_ext"
STATUS = "not_mastered"


def load_jsonl(path: str):
    """加载考研全量 JSONL，返回 {headWord: obj}"""
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
            hw = (obj.get("headWord") or "").strip()
            if hw:
                result[hw.lower()] = obj
    return result


def extract_word_info(obj: dict):
    """从 full 格式提取 words 表字段与 extra JSON"""
    content = (obj.get("content") or {}).get("word") or {}
    wc = content.get("content") or {}
    word = (obj.get("headWord") or content.get("wordHead") or "").strip()

    trans = wc.get("trans") or []
    meaning_parts = []
    pos_parts = []
    for t in trans:
        pos = (t.get("pos") or "").strip()
        tran_cn = (t.get("tranCn") or "").strip()
        if tran_cn:
            meaning_parts.append(f"{pos}. {tran_cn}" if pos else tran_cn)
        if pos and pos not in pos_parts:
            pos_parts.append(pos)
    meaning = "；".join(meaning_parts) if meaning_parts else ""
    pos = "/".join(pos_parts) if pos_parts else None

    phonetic = (wc.get("ukphone") or wc.get("usphone") or "").strip() or None

    sentences = (wc.get("sentence") or {}).get("sentences") or []
    example = sentences[0].get("sContent") if sentences else None
    example_cn = sentences[0].get("sCn") if sentences else None

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

    extra = {
        "synonyms": synos,
        "phrases": phrases,
        "rel_words": rels,
        "source": "KyleBing",
    }
    return word, phonetic, pos, meaning, example, example_cn, extra


def ensure_extra_column(conn):
    """words 表增加 extra JSONB 列（幂等）"""
    with conn.cursor() as cur:
        cur.execute("""
            ALTER TABLE words ADD COLUMN IF NOT EXISTS extra jsonb
        """)
        conn.commit()


def main():
    data = load_jsonl(JSONL)
    print(f"KyleBing 考研词条数: {len(data)}")

    conn = psycopg.connect(**DB_CONFIG)
    ensure_extra_column(conn)

    today = date.today()
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # 找核心 deck 现有词（避免重复）
        cur.execute("SELECT id FROM word_decks WHERE name = %s ORDER BY id LIMIT 1", (CORE_DECK_NAME,))
        core = cur.fetchone()
        core_id = core[0] if core else None
        cur.execute("SELECT lower(word) FROM words WHERE deck_id = %s", (core_id,))
        core_words = {r[0] for r in cur.fetchall()}
        print(f"核心 deck {core_id} 词数: {len(core_words)}")

        # 创建/复用扩展 deck
        cur.execute("SELECT id FROM word_decks WHERE name = %s AND user_id = %s ORDER BY id LIMIT 1", (DECK_NAME, USER_ID))
        deck = cur.fetchone()
        if deck:
            deck_id = deck[0]
            print(f"deck 已存在 id={deck_id}")
        else:
            cur.execute(
                "INSERT INTO word_decks (name, description, source, word_count, created_at, user_id) "
                "VALUES (%s, %s, %s, 0, %s, %s) RETURNING id",
                (DECK_NAME, DECK_DESCRIPTION, DECK_SOURCE, now, USER_ID),
            )
            deck_id = cur.fetchone()[0]
            print(f"deck 已创建 id={deck_id}")

        # 构造插入批次（只导入核心 deck 没有的词）
        insert_batch = []
        skipped_existing = 0
        for lower_w, obj in data.items():
            word, phonetic, pos, meaning, example, example_cn, extra = extract_word_info(obj)
            if not meaning and not example:
                continue
            if lower_w in core_words:
                skipped_existing += 1
                continue
            insert_batch.append((
                deck_id, word, phonetic, pos, meaning, example, example_cn, TAG,
                STATUS, 2.5, 0, 0, 0, today, None, [], json.dumps(extra, ensure_ascii=False),
                now, now, USER_ID,
            ))

        print(f"需插入（核心 deck 之外）: {len(insert_batch)}，跳过已存在核心词: {skipped_existing}")

        INSERT_SQL = """
            INSERT INTO words (
                deck_id, word, phonetic, pos, meaning, root, example, example_cn, tag,
                status, ease_factor, interval_days, reps, lapses, due_date, last_review,
                review_history, extra, created_at, updated_at, user_id
            ) VALUES (%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (deck_id, word) DO NOTHING
        """
        BATCH = 500
        inserted = 0
        for i in range(0, len(insert_batch), BATCH):
            cur.executemany(INSERT_SQL, insert_batch[i:i + BATCH])
            inserted += cur.rowcount

        cur.execute(
            "UPDATE word_decks SET word_count = (SELECT count(*) FROM words WHERE deck_id=%s) WHERE id=%s",
            (deck_id, deck_id),
        )
        print(f"实际插入: {inserted}, deck word_count 已更新")

    conn.commit()
    conn.close()
    print("=== 完成 ===")


if __name__ == "__main__":
    main()