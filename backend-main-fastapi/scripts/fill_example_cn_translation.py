#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补全 Tatoeba 例句的中文翻译（针对完全无中文翻译的考研词）

策略：
1. 找出所有「没有任何中文例句」的考研词（约 1682 个）
2. 对每个词选取 1 条最短的英文例句
3. 用 Ollama qwen2.5-coder:1.5b 批量翻译（每批 5 条）
4. 更新 word_examples.sentence_cn

运行: python scripts/fill_example_cn_translation.py
"""
import os
import re
import sys
import time
import json
import logging
import urllib.request

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DSN = "host=127.0.0.1 port=5432 user=kaoyan password=kaoyan_dev_2026 dbname=kaoyan"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:1.5b"
BATCH_SIZE = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fill_example_cn")

SYSTEM_PROMPT = (
    "你是一个专业的英语翻译。请将用户给出的英文句子翻译成简洁自然的中文。"
    "只输出中文翻译结果，不要输出任何解释、引号或额外内容。"
)


def ollama_translate(texts):
    """调用 Ollama 批量翻译，返回 [cn1, cn2, ...]"""
    prompt_lines = []
    for i, t in enumerate(texts, 1):
        prompt_lines.append(f"{i}. {t}")
    prompt = "\n".join(prompt_lines)
    payload = {
        "model": MODEL,
        "prompt": f"{SYSTEM_PROMPT}\n\n待翻译句子：\n{prompt}\n\n请逐句输出中文翻译，每行一句：",
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 512},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw = data.get("response", "")
                return parse_translations(raw, len(texts))
        except Exception as e:
            log.warning("Ollama 调用失败(第%d次): %s", attempt + 1, e)
            time.sleep(3)
    return [None] * len(texts)


def parse_translations(raw, n):
    """从模型输出中解析 n 句翻译（兼容多种格式）"""
    if not raw:
        return [None] * n
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    results = [None] * n

    # 策略1: 匹配 "1. xxx" / "1、xxx" / "1：xxx"
    numbered = {}
    for l in lines:
        m = re.match(r"^(\d+)[.、．:：]\s*(.*)", l)
        if m:
            numbered[int(m.group(1))] = m.group(2).strip()
    if numbered:
        for i in range(1, n + 1):
            if i in numbered:
                results[i - 1] = numbered[i]
        if all(r for r in results):
            return results

    # 策略2: 匹配 "第一句：xxx" / "第1句：xxx"
    cn_sents = []
    for l in lines:
        m = re.match(r"^第[一二三四五六七八九十\d]+句[：:]\s*(.*)", l)
        if m:
            cn_sents.append(m.group(1).strip())
            if len(cn_sents) >= n:
                break
    if len(cn_sents) >= n:
        return cn_sents[:n]

    # 策略3: 按行对应（去掉编号前缀）
    clean_lines = [re.sub(r"^\d+[.、．:：]\s*", "", l) for l in lines]
    for i in range(n):
        if i < len(clean_lines):
            results[i] = clean_lines[i]
    return results


def main():
    conn = psycopg.connect(DB_DSN)
    try:
        # 1. 找出完全无中文翻译的词，各选 1 条最短例句
        cur = conn.cursor()
        cur.execute("""
            WITH no_cn_words AS (
                SELECT DISTINCT word FROM word_examples we
                WHERE NOT EXISTS (
                    SELECT 1 FROM word_examples we2
                    WHERE we2.word = we.word
                      AND we2.sentence_cn IS NOT NULL AND we2.sentence_cn != ''
                )
            ),
            ranked AS (
                SELECT we.id, we.word, we.sentence_en,
                       ROW_NUMBER() OVER (PARTITION BY we.word ORDER BY length(we.sentence_en)) rn
                FROM word_examples we
                JOIN no_cn_words n ON n.word = we.word
                WHERE we.sentence_cn IS NULL OR we.sentence_cn = ''
            )
            SELECT id, word, sentence_en FROM ranked WHERE rn = 1
            ORDER BY word
        """)
        rows = cur.fetchall()
        log.info("需要翻译的例句数: %d", len(rows))
        if not rows:
            print("没有需要翻译的例句")
            return

        # 2. 分批翻译
        updated = 0
        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start:start + BATCH_SIZE]
            texts = [r[2] for r in batch]
            translations = ollama_translate(texts)
            for (rid, word, _en), cn in zip(batch, translations):
                if cn and cn.strip():
                    try:
                        cur.execute(
                            "UPDATE word_examples SET sentence_cn = %s WHERE id = %s",
                            (cn.strip(), rid),
                        )
                        updated += cur.rowcount
                    except Exception as e:
                        conn.rollback()
                        log.warning("更新失败 id=%s: %s", rid, e)
                        continue
            conn.commit()
            if (start // BATCH_SIZE) % 20 == 0:
                log.info("已翻译 %d/%d (成功更新 %d)", start + len(batch), len(rows), updated)

        log.info("完成！成功更新 %d 条例句的中文翻译", updated)
    finally:
        conn.close()


if __name__ == "__main__":
    main()