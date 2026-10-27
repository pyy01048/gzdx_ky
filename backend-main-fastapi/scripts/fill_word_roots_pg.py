# -*- coding: utf-8 -*-
"""词根词缀库构建（PostgreSQL）——批量翻译版。

数据源：ECDICT 附带的 wordroot.txt（权威词根词典，611 条目）
  - root: 423 / prefix: 110 / suffix（各类）: 78

改进点：
- 使用 qwen2.5-coder:1.5b 批量翻译（5 条/批），避免 qwen3:8b 的 thinking 污染
- 每次翻译后立即写库，失败重试 2 次
- 幂等：DROP+CREATE（本脚本是初始化脚本）
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import psycopg

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
WORDROOT_JSON = DATA_DIR / "ECDICT-master" / "wordroot.txt"

DB_CONFIG = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen2.5-coder:1.5b"

BATCH_SIZE = 5

SUFFIX_CLASSES = {
    "noun-forming suffix": "noun",
    "adjective-forming suffix": "adjective",
    "verb-forming suffix": "verb",
    "adverb-forming suffix": "adverb",
    "adjective- and noun-forming suffix": "adj-noun",
}


def split_variants(root_text: str) -> list[str]:
    """拆分变体：'pter, ptero, pteryg, pteryx' -> ['pter','ptero','pteryg','pteryx']"""
    if not root_text:
        return []
    parts = [p.strip() for p in re.split(r"[,/]", root_text) if p.strip()]
    return [p for p in parts if len(p) >= 1]


def normalize_type(cls: str) -> tuple[str, str]:
    """返回 (type, subtype)。"""
    if cls == "root":
        return "root", ""
    if cls == "prefix":
        return "prefix", ""
    if cls in SUFFIX_CLASSES:
        return "suffix", SUFFIX_CLASSES[cls]
    if "suffix" in cls:
        return "suffix", "other"
    return "root", ""


def ollama_batch_translate(texts: list[str]) -> list[str]:
    """批量翻译英语词根含义为中文。每批 5 条，模型输出编号行。

    返回与输入等长的列表；失败项为空串。
    """
    if not texts:
        return []
    lines = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    prompt = (
        "你是英语词根词典翻译助手。把下列英语词根/词缀含义逐条翻译成简洁的中文。\n"
        "要求：\n"
        "1. 每条只输出一行中文翻译，不要解释、不要引号、不要标序号\n"
        "2. 输出必须与输入顺序一致，每行一条\n"
        f"待翻译:\n{lines}\n\n中文翻译:\n"
    )
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 256},
    }).encode("utf-8")

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                out = (data.get("response", "") or "").strip()
            if not out:
                return [""] * len(texts)

            # 解析输出：按行拆分，取每行第一个中文字符以后的内容作为翻译
            out_lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            results: list[str] = []
            for i, t in enumerate(texts):
                if i < len(out_lines):
                    # 去掉可能的前缀编号（如 "1. " 或 "1:"）
                    ln = re.sub(r"^\s*\d+[\.:、)]\s*", "", out_lines[i])
                    ln = ln.strip().strip('"').strip("'").strip()
                    # 过滤掉 still thinking 之类的污染
                    if "thinking" in ln or "好的" in ln or "用户" in ln or len(ln) > 60:
                        ln = ""
                else:
                    ln = ""
                results.append(ln)
            return results
        except Exception as e:
            if attempt == 2:
                print(f"    翻译失败（3次）: {e}")
                return [""] * len(texts)
            time.sleep(2)
    return [""] * len(texts)


def main() -> None:
    if not WORDROOT_JSON.exists():
        print(f"[错误] 词根词典不存在: {WORDROOT_JSON}")
        sys.exit(1)

    with open(WORDROOT_JSON, encoding="utf-8") as f:
        data = json.load(f)

    print(f"加载词根词典: {len(data)} 条目")

    conn = psycopg.connect(**DB_CONFIG, autocommit=True)
    cur = conn.cursor()

    cur.execute("""
        DROP TABLE IF EXISTS word_roots CASCADE;
        CREATE TABLE word_roots (
            id          bigserial PRIMARY KEY,
            morpheme    varchar(200) NOT NULL,
            variants    jsonb,
            type        varchar(20)  NOT NULL,
            subtype     varchar(20)  NOT NULL DEFAULT '',
            origin      varchar(100),
            meaning     text,
            meaning_cn  text,
            explanation text,
            example_words jsonb,
            word_count  integer DEFAULT 0,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX uq_word_roots_morpheme ON word_roots (morpheme, type);
        CREATE INDEX idx_word_roots_type ON word_roots (type);
        CREATE INDEX idx_word_roots_morpheme ON word_roots (morpheme);
    """)
    print("表 word_roots 已创建")

    # 预处理：收集所有需要翻译的条目
    entries = []
    pending = []  # (index, meaning)
    for key, entry in data.items():
        cls = entry.get("class", "")
        morpheme = entry.get("root", "") or key
        meaning = entry.get("meaning", "") or ""
        origin = entry.get("origin", "") or ""
        explanation = entry.get("function", "") or ""
        examples = entry.get("example", []) or []
        variants = split_variants(morpheme)

        type_, subtype = normalize_type(cls)
        if not morpheme.strip():
            continue

        entries.append({
            "morpheme": morpheme,
            "variants": variants,
            "type": type_,
            "subtype": subtype,
            "origin": origin,
            "meaning": meaning,
            "explanation": explanation,
            "examples": examples,
            "meaning_cn": "",
        })

        if meaning and len(meaning) <= 120:
            pending.append((len(entries) - 1, meaning))

    print(f"有效条目: {len(entries)}, 需要翻译: {len(pending)}")

    # 批量翻译
    total_batches = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE
    done = 0
    missing_cn = []
    for b in range(total_batches):
        chunk = pending[b * BATCH_SIZE: (b + 1) * BATCH_SIZE]
        texts = [m for _, m in chunk]
        results = ollama_batch_translate(texts)
        for (idx, _), cn in zip(chunk, results):
            entries[idx]["meaning_cn"] = cn
            if not cn:
                missing_cn.append(entries[idx]["morpheme"])
        done += len(chunk)
        ok = len([r for r in results if r])
        print(f"  批 {b+1}/{total_batches}: 翻译 {len(chunk)} 条, 成功 {ok} 条 ({done}/{len(pending)})")
        time.sleep(0.3)

    print(f"翻译完成，缺中文含义 {len(missing_cn)} 条")

    # 写库
    inserted = 0
    skipped = 0
    for e in entries:
        cur.execute(
            """
            INSERT INTO word_roots
                (morpheme, variants, type, subtype, origin, meaning, meaning_cn,
                 explanation, example_words)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                e["morpheme"],
                json.dumps(e["variants"], ensure_ascii=False),
                e["type"],
                e["subtype"],
                e["origin"] or None,
                e["meaning"] or None,
                e["meaning_cn"] or None,
                e["explanation"] or None,
                json.dumps(e["examples"], ensure_ascii=False) if e["examples"] else None,
            ),
        )
        inserted += 1

    print(f"插入: {inserted}, 跳过: {skipped}")
    print(f"缺中文含义: {len(missing_cn)} 条: {missing_cn[:20]}")

    cur.execute("SELECT type, count(*) FROM word_roots GROUP BY type ORDER BY type")
    print("\n=== type 分布 ===")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")

    cur.execute("SELECT count(*) FROM word_roots")
    print(f"\n总条数: {cur.fetchone()[0]}")

    cur.execute("SELECT count(*) FROM word_roots WHERE meaning_cn IS NOT NULL AND meaning_cn != ''")
    print(f"有中文含义: {cur.fetchone()[0]}")

    try:
        cur.execute("""
            UPDATE word_roots wr SET word_count = sub.cnt
            FROM (
                SELECT trim(both ' -' FROM unnest(string_to_array(regexp_replace(root, '\\d+$', ''), ','))) AS mor,
                       count(*) AS cnt
                FROM words
                WHERE root IS NOT NULL AND root != ''
                GROUP BY 1
            ) sub
            WHERE wr.morpheme = sub.mor
               OR EXISTS (
                   SELECT 1 FROM jsonb_array_elements_text(wr.variants) v
                   WHERE v = sub.mor
               )
        """)
        print("已关联 words 表 word_count")
    except Exception as e:
        print(f"[提示] 关联 word_count 失败（不影响主数据）: {e}")

    cur.close()
    conn.close()
    print("\n完成 ✅")


if __name__ == "__main__":
    main()