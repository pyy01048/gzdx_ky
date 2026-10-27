# -*- coding: utf-8 -*-
"""Tatoeba 例句入库脚本（PostgreSQL）。

数据源：
- scripts/data/tatoeba/eng_sentences.tsv      （英文句子，110MB，203万行）
- scripts/data/tatoeba/cmn_sentences.tsv       （中文句子，8.9万行）
- scripts/data/tatoeba/cmn-eng_links.tsv.bz2    （中文↔英文翻译对，7.8万对）

流程：
1. 加载 cmn-eng 链接，构建 eng_id -> cmn_id 映射
2. 加载 cmn 中文句子 dict
3. 加载考研词表（words 表，5512词）
4. 流式扫描英文句子，对每个命中考研词的句子记录 (eng_id, text, [words])
5. 对每个考研词最多保留 5 条例句（优先有中文翻译的）
6. 繁体中文转简体，写入 word_examples 表
"""
from __future__ import annotations

import bz2
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import psycopg
from zhconv import convert  # convert(text, 'zh-cn')

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "tatoeba"

ENG_SENTENCES = DATA_DIR / "eng_sentences.tsv"
CMN_SENTENCES = DATA_DIR / "cmn_sentences.tsv"
CMN_ENG_LINKS = DATA_DIR / "cmn-eng_links.tsv.bz2"

DB_CONFIG = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)

# 每个词最多保留的例句数
MAX_EXAMPLES_PER_WORD = 5
# 每个词收集候选时最多保留的句子数（超出截断）
MAX_CANDIDATES = 12

# 停用词（太短/无实义，不收集例句）
STOP_WORDS = {
    "a", "an", "the", "be", "to", "of", "in", "on", "at", "for", "with",
    "and", "or", "but", "by", "from", "up", "down", "out", "off", "over",
    "under", "again", "then", "now", "as", "if", "it", "is", "are", "was",
    "were", "am", "do", "does", "did", "have", "has", "had", "not", "no",
    "so", "than", "that", "this", "these", "those", "there", "here", "we",
    "you", "he", "she", "they", "i", "my", "your", "his", "her", "its",
    "our", "their", "me", "him", "us", "them", "who", "what", "which",
    "when", "where", "why", "how", "all", "any", "some", "each", "every",
    "both", "few", "more", "most", "other", "such", "only", "own", "same",
    "too", "very", "just", "can", "will", "shall", "may", "must", "would",
    "could", "should", "into", "onto", "upon", "about", "like", "than",
    "because", "while", "before", "after", "between", "through", "during",
    "against", "without", "with", "within", "among", "beyond", "etc",
}


def load_word_list(conn) -> list[dict]:
    """从 words 表加载考研词。"""
    cur = conn.cursor()
    cur.execute("SELECT id, word FROM words ORDER BY id")
    rows = cur.fetchall()
    return [{"id": r[0], "word": r[1]} for r in rows]


def load_cmn_eng_links() -> dict[int, list[int]]:
    """加载 cmn_id -> [eng_id, ...] 映射（一个中文句可能对应多个英文句）。"""
    result = defaultdict(list)
    with bz2.open(CMN_ENG_LINKS, "rt", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                cmn_id, eng_id = int(parts[0]), int(parts[1])
                result[cmn_id].append(eng_id)
    return dict(result)


def load_cmn_sentences() -> dict[int, str]:
    """加载 cmn_id -> 中文句子。"""
    result = {}
    with open(CMN_SENTENCES, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 3 and parts[1] == "cmn":
                result[int(parts[0])] = parts[2]
    return result


def main() -> None:
    # 1. 加载数据
    print("加载 cmn-eng 链接...")
    cmn_eng_links = load_cmn_eng_links()
    print(f"  中文句链接数: {len(cmn_eng_links)}")

    print("加载中文句子...")
    cmn_sentences = load_cmn_sentences()
    print(f"  中文句子数: {len(cmn_sentences)}")

    conn = psycopg.connect(**DB_CONFIG, autocommit=True)
    words = load_word_list(conn)
    print(f"考研词数: {len(words)}")

    # 2. 构建词表 set（小写）
    word_lower_set = set()
    word_by_lower = {}
    for w in words:
        wl = w["word"].lower().strip()
        if wl and wl not in STOP_WORDS and len(wl) >= 2:
            word_lower_set.add(wl)
            word_by_lower[wl] = w["id"]
    print(f"有效考研词（用于匹配）: {len(word_lower_set)}")

    # 3. 构建 eng_id -> cmn_id 的反向映射（一个英文句可能被多个中文句翻译）
    eng_to_cmn = defaultdict(list)
    for cmn_id, eng_ids in cmn_eng_links.items():
        cmn_text = cmn_sentences.get(cmn_id)
        if not cmn_text:
            continue
        for eng_id in eng_ids:
            eng_to_cmn[eng_id].append(cmn_text)
    print(f"有中文翻译的英文句数: {len(eng_to_cmn)}")

    # 4. 流式扫描英文句子，收集每个词候选
    # candidates: word_lower -> list of dict(eng_id, eng_text, cmn_text)
    candidates: dict[str, list[dict]] = defaultdict(list)
    token_re = re.compile(r"[a-zA-Z']+")

    print("扫描英文句子...")
    total_lines = 0
    matched_lines = 0
    with open(ENG_SENTENCES, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3 or parts[1] != "eng":
                continue
            total_lines += 1
            eng_id = int(parts[0])
            text = parts[2]
            tokens = set(t.lower() for t in token_re.findall(text))
            hit_words = tokens & word_lower_set
            if not hit_words:
                continue
            matched_lines += 1
            cmn_texts = eng_to_cmn.get(eng_id, [])
            cmn_text = convert(cmn_texts[0], "zh-cn") if cmn_texts else ""
            for wl in hit_words:
                lst = candidates[wl]
                if len(lst) >= MAX_CANDIDATES:
                    continue
                lst.append({
                    "eng_id": eng_id,
                    "eng_text": text,
                    "cmn_text": cmn_text,
                })

    print(f"扫描完成: 总英文句 {total_lines}, 命中句 {matched_lines}, 有候选的词 {len(candidates)}")

    # 5. 建表
    cur = conn.cursor()
    cur.execute("""
        DROP TABLE IF EXISTS word_examples CASCADE;
        CREATE TABLE word_examples (
            id          bigserial PRIMARY KEY,
            word_id     bigint NOT NULL REFERENCES words(id) ON DELETE CASCADE,
            word        varchar(100) NOT NULL,
            sentence_en text NOT NULL,
            sentence_cn text,
            source      varchar(20) NOT NULL DEFAULT 'tatoeba',
            sentence_id bigint,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_word_examples_word_id ON word_examples (word_id);
        CREATE INDEX idx_word_examples_word ON word_examples (word);
    """)
    print("表 word_examples 已创建")

    # 6. 写入
    inserted = 0
    skipped_no_cn = 0
    per_word_stats = {}
    for w in words:
        wl = w["word"].lower().strip()
        if wl not in candidates:
            continue
        # 优先有中文翻译的
        lst = sorted(candidates[wl], key=lambda x: (not x["cmn_text"], x["eng_id"]))
        chosen = lst[:MAX_EXAMPLES_PER_WORD]
        per_word_stats[w["word"]] = len(chosen)
        for item in chosen:
            cur.execute(
                """
                INSERT INTO word_examples (word_id, word, sentence_en, sentence_cn, source, sentence_id)
                VALUES (%s, %s, %s, %s, 'tatoeba', %s)
                """,
                (w["id"], w["word"], item["eng_text"], item["cmn_text"] or None, item["eng_id"]),
            )
            inserted += 1
            if not item["cmn_text"]:
                skipped_no_cn += 1

    print(f"\n写入例句: {inserted}")
    print(f"其中无中文翻译: {skipped_no_cn}")
    print(f"有例句的词数: {len(per_word_stats)}")
    with_cn = sum(1 for v in per_word_stats.values() if v >= 1)
    print(f"覆盖词数: {with_cn}")

    # 7. 验证
    cur.execute("SELECT count(*) FROM word_examples")
    print(f"word_examples 总数: {cur.fetchone()[0]}")
    cur.execute("SELECT count(DISTINCT word_id) FROM word_examples")
    print(f"覆盖不同词: {cur.fetchone()[0]}")
    cur.execute("SELECT count(*) FROM word_examples WHERE sentence_cn IS NOT NULL AND sentence_cn != ''")
    print(f"有中文翻译: {cur.fetchone()[0]}")

    cur.close()
    conn.close()
    print("\n完成 ✅")


if __name__ == "__main__":
    main()