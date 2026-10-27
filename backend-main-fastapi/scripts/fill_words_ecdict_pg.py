# -*- coding: utf-8 -*-
"""
填充考研词汇 5500 到 PostgreSQL kaoyan 数据库。

数据源：
1. 考研大纲词表: scripts/data/Words-List-csv-5500-main/ordered.csv (5493 词)
2. ECDICT 词典: scripts/data/ECDICT-master/ecdict.csv
3. 词根词典: scripts/data/ECDICT-master/wordroot.txt

映射规则：
- word       <- 词表单词（a/an 拆成 a, an；according to 跳过）
- phonetic   <- ECDICT phonetic
- pos        <- 从 translation 开头提取词性（n./v./vt./vi./a./ad./prep./conj./pron./num./art./aux./int.）
- meaning    <- ECDICT translation（中文释义）
- example    <- ECDICT detail（本版本为空，留空）
- example_cn <- 留空
- root       <- wordroot 映射（若匹配）
- tag        <- 'kaoyan'
- status     <- 'not_mastered' (mastery_level 枚举)
- deck_id    <- 关联创建的 word_decks 记录
- user_id    <- 1

幂等：依赖唯一索引 uq_word_in_deck(deck_id, word)，INSERT ... ON CONFLICT DO NOTHING。
"""

import csv
import json
import os
import re
from datetime import date, datetime, timezone

import psycopg

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

WORD_LIST_CSV = os.path.join(DATA_DIR, "Words-List-csv-5500-main", "ordered.csv")
ECDICT_CSV = os.path.join(DATA_DIR, "ECDICT-master", "ecdict.csv")
WORDROOT_JSON = os.path.join(DATA_DIR, "ECDICT-master", "wordroot.txt")

DB_CONFIG = dict(
    host="127.0.0.1",
    port=5432,
    user="kaoyan",
    password="kaoyan_dev_2026",
    dbname="kaoyan",
)

DECK_NAME = "考研核心词汇"
DECK_DESCRIPTION = "考研英语核心词汇 5500"
DECK_SOURCE = "ECDICT"
USER_ID = 1
TAG = "kaoyan"
STATUS = "not_mastered"

# 词性缩写映射（从中文释义开头提取）
# 匹配形如: vt. / n.&v. / ad.&prep. / a. 等开头词性序列
POS_PATTERN = re.compile(
    r"^(?:\s*\[[^\]]*\]\s*)?"
    r"(?P<pos>(?:vt|vi|aux|conj|prep|pron|num|art|int|ad|adj|adv|n|v|a)"
    r"(?:\.\s*&\s*(?:vt|vi|aux|conj|prep|pron|num|art|int|ad|adj|adv|n|v|a))*)"
    r"\.?\s*"
)


def extract_pos(translation: str) -> str:
    """从中文释义开头提取词性缩写，如 'vt. 放弃' -> 'vt.'，'ad.&prep.' -> 'ad. prep.'"""
    if not translation:
        return ""
    m = POS_PATTERN.match(translation.strip())
    if m:
        pos = m.group("pos").strip()
        # 规范化：补上点号
        parts = [p.strip().rstrip(".") + "." for p in re.split(r"\s*&\s*", pos)]
        return " ".join(parts)
    return ""


def normalize_phonetic(phonetic: str) -> str:
    """规范化音标字符：ECDICT 使用非标准字符，替换为常见 IPA 形式。"""
    if not phonetic:
        return ""
    # 常见 ECDICT 非标准字符映射（部分）
    repl = {
        "ә": "ə",
        "ɒ": "ɒ",
        "ɔ": "ɔ",
        "ð": "ð",
        "θ": "θ",
        "ʃ": "ʃ",
        "ʒ": "ʒ",
        "ŋ": "ŋ",
        "ɡ": "ɡ",
        "ʧ": "tʃ",
        "ʤ": "dʒ",
        "е": "e",
        "а": "ə",
        "ı": "ɪ",
        "ɪ": "ɪ",
        "ʊ": "ʊ",
        "ʌ": "ʌ",
        "ɜ": "ɜ",
        "æ": "æ",
        "ɑ": "ɑ",
        "ɒ": "ɒ",
        "ː": "ː",
        "ˈ": "ˈ",
        "'": "'",
        "є": "e",
    }
    out = []
    for ch in phonetic:
        out.append(repl.get(ch, ch))
    return "".join(out)


def load_word_list(path: str):
    """加载考研词表，返回规范化后的单词列表。
    处理：a/an -> ['a', 'an']；according to（含不间断空格）-> 跳过。
    """
    words = []
    skipped = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw_word = line.split(",")[0].strip()
            # 处理不间断空格 (\xa0)
            clean = raw_word.replace("\xa0", " ").strip()
            if "/" in clean and clean.count("/") == 1:
                # 形如 a/an -> 拆分为 a, an
                for part in clean.split("/"):
                    part = part.strip()
                    if part:
                        words.append(part)
                continue
            if " " in clean:
                # 短语（如 according to）跳过
                skipped.append(clean)
                continue
            words.append(clean)
    return words, skipped


def load_ecdict(path: str):
    """加载 ECDICT csv，返回 {word: row_dict} 和 {lower_word: row_dict}。"""
    exact = {}
    lower = {}
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            w = row["word"]
            exact[w] = row
            lower.setdefault(w.lower(), row)
    return exact, lower


def load_wordroot(path: str):
    """加载词根词典，返回 {example_word_lower: root} 映射。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    mapping = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        root = entry.get("root") or key
        examples = entry.get("example") or []
        for ex in examples:
            if isinstance(ex, str):
                mapping.setdefault(ex.lower(), root)
    return mapping


def main():
    print("=== 步骤 1: 加载考研词表 ===")
    word_list, skipped = load_word_list(WORD_LIST_CSV)
    print(f"词表单词数: {len(word_list)} (跳过短语: {skipped})")

    print("=== 步骤 2: 加载 ECDICT ===")
    ecdict_exact, ecdict_lower = load_ecdict(ECDICT_CSV)
    print(f"ECDICT 词条数: {len(ecdict_exact)}")

    print("=== 步骤 3: 加载词根映射 ===")
    root_map = load_wordroot(WORDROOT_JSON)
    print(f"词根映射数: {len(root_map)}")

    print("=== 步骤 4: 匹配数据 ===")
    records = []
    missing = []
    for w in word_list:
        row = ecdict_exact.get(w) or ecdict_lower.get(w.lower())
        if row is None:
            missing.append(w)
            continue
        records.append((w, row))

    print(f"匹配成功: {len(records)}, 未匹配: {len(missing)} -> {missing[:30]}")

    print("=== 步骤 5: 连接数据库 ===")
    conn = psycopg.connect(**DB_CONFIG, autocommit=True)
    cur = conn.cursor()

    # 检查/创建 deck
    print(f"--- 创建/查找 deck: {DECK_NAME}")
    cur.execute(
        "SELECT id FROM word_decks WHERE user_id = %s AND name = %s",
        (USER_ID, DECK_NAME),
    )
    deck_row = cur.fetchone()
    if deck_row:
        deck_id = deck_row[0]
        print(f"deck 已存在 id={deck_id}, 复用")
    else:
        cur.execute(
            """
            INSERT INTO word_decks (name, description, source, word_count, created_at, user_id)
            VALUES (%s, %s, %s, 0, %s, %s)
            RETURNING id
            """,
            (DECK_NAME, DECK_DESCRIPTION, DECK_SOURCE, datetime.now(timezone.utc), USER_ID),
        )
        deck_id = cur.fetchone()[0]
        print(f"deck 已创建 id={deck_id}")

    print("--- 写入 words（幂等，已存在则更新） ---")
    inserted = 0
    today = date.today()
    now = datetime.now(timezone.utc)

    batch = []
    for word, row in records:
        phonetic = normalize_phonetic(row.get("phonetic") or "")
        translation = (row.get("translation") or "").strip()
        definition = (row.get("definition") or "").strip()
        meaning = translation if translation else definition
        pos = extract_pos(translation)
        root = root_map.get(word.lower(), "")
        tag = TAG

        batch.append(
            (
                deck_id,
                word,
                phonetic or None,
                pos or None,
                meaning or None,
                root or None,
                None,  # example
                None,  # example_cn
                tag,
                STATUS,
                2.5,
                0,
                0,
                0,
                today,
                None,
                [],
                now,
                now,
                USER_ID,
            )
        )

    # 分批插入
    # 幂等策略：依赖唯一索引 uq_word_in_deck(deck_id, word)。
    # 已存在的词则更新数据字段（不产生重复，且可修复历史数据）。
    INSERT_SQL = """
        INSERT INTO words (
            deck_id, word, phonetic, pos, meaning, root, example, example_cn, tag,
            status, ease_factor, interval_days, reps, lapses, due_date, last_review,
            review_history, created_at, updated_at, user_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (deck_id, word) DO UPDATE SET
            phonetic = EXCLUDED.phonetic,
            pos = EXCLUDED.pos,
            meaning = EXCLUDED.meaning,
            root = EXCLUDED.root,
            example = EXCLUDED.example,
            example_cn = EXCLUDED.example_cn,
            tag = EXCLUDED.tag,
            updated_at = EXCLUDED.updated_at
    """
    BATCH_SIZE = 500
    for i in range(0, len(batch), BATCH_SIZE):
        sub = batch[i : i + BATCH_SIZE]
        cur.executemany(INSERT_SQL, sub)
        inserted += cur.rowcount

    print(f"本次插入/更新: {inserted}, 词表总数: {len(records)}")

    # 更新 deck word_count
    cur.execute(
        "UPDATE word_decks SET word_count = "
        "(SELECT count(*) FROM words WHERE deck_id = %s) WHERE id = %s",
        (deck_id, deck_id),
    )
    print("已更新 deck word_count")

    cur.close()
    conn.close()
    print("=== 完成 ===")


if __name__ == "__main__":
    main()