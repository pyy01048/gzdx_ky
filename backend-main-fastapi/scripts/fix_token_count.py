# -*- coding: utf-8 -*-
"""修复 knowledge_chunks.token_count=0：按项目 token 估计算法重算并回填。

算法与 scripts/fill_kb_docs_and_kps.py 的 token_count() 保持一致：
    汉字算 1 token，连续字母数字/下划线算 1 token，其余标点不计。
"""
import os
import sys
import psycopg

DB_CONFIG = dict(
    host="127.0.0.1", port=5432, user="kaoyan",
    password="kaoyan_dev_2026", dbname="kaoyan",
)


def token_count(text: str) -> int:
    n = 0
    word = False
    for ch in text or "":
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            n += 1
            word = False
        elif ch.isalnum() or ch in "_-":
            word = True
        else:
            if word:
                n += 1
                word = False
    if word:
        n += 1
    return max(n, 1)


def main() -> int:
    with psycopg.connect(**DB_CONFIG) as pg, pg.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE token_count = 0 OR token_count IS NULL")
        total_zero = cur.fetchone()[0]
        print(f"待修复 token_count=0/null 的块数: {total_zero}")

        # 分批拉取，避免一次载入 2 万+ 行长文本占内存
        BATCH = 2000
        updated = 0
        last_id = 0
        while True:
            cur.execute(
                """
                SELECT id, text FROM knowledge_chunks
                WHERE (token_count = 0 OR token_count IS NULL) AND id > %s
                ORDER BY id
                LIMIT %s
                """,
                (last_id, BATCH),
            )
            rows = cur.fetchall()
            if not rows:
                break
            for cid, text in rows:
                tc = token_count(text)
                cur.execute(
                    "UPDATE knowledge_chunks SET token_count=%s, updated_at=now() WHERE id=%s",
                    (tc, cid),
                )
                updated += 1
                last_id = cid
            pg.commit()
            print(f"  已回填 {updated}/{total_zero} ...", flush=True)

        # 验证
        cur.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE token_count = 0 OR token_count IS NULL")
        remain = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE token_count > 0")
        positive = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM knowledge_chunks")
        total = cur.fetchone()[0]
        print(f"\n=== 结果 ===")
        print(f"总块数: {total}")
        print(f"token_count>0: {positive}")
        print(f"token_count=0/null 剩余: {remain}")
        if remain:
            cur.execute("SELECT id, document_id, LENGTH(text) FROM knowledge_chunks WHERE token_count=0 OR token_count IS NULL LIMIT 10")
            print("剩余 0 值示例(应均为空/极短块):", cur.fetchall())
    return 0


if __name__ == "__main__":
    sys.exit(main())
