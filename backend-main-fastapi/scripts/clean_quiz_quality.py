# -*- coding: utf-8 -*-
"""题库可见题的质量分层收口（docx/22 §3.2 的 ②③④）。

背景（真库实测，9096 题）
------------------------
    无选项 + 有答案 + 未 junk   2855   ← ③ 应标 answer_type='subjective'（简答/记忆模式）
    无选项 + 无答案 + 未 junk   1871   ← ④ 应标 quality='incomplete' + is_available=0（不可作答）
    有选项 + 有答案 + 未 junk    545   ← 真正可自动判分的客观题
    answer_type 现状：9096/9096 全为 'objective'（无区分，后端 exam_builder 会把
    无选项题也当客观题自动判分 → 判分语义错误）

处置（与 docx/22 §3.2 一致，deterministic、幂等）
----------------------------------------------
② 管综错配残留：未 junk 题里命中管综专属特征（逻辑推理/条件充分性/论证有效性）
   → is_junk=1（刷题不可见）。注意「写作」不入选：英语作文是真的，会误伤。
③ 无选项但有答案 → answer_type='subjective'（供 exam_builder 走人工判分/简答模式）。
④ 无选项且无答案 → quality='incomplete' 且 is_available=0（明确不可作答）。

安全
----
* dry-run 默认开，必须显式 `--apply` 才写库。
* `--apply` 前强制用 SQLite `backup()` API 备份（禁 cp/copy2）。
* 只改这三类题的行，不动有选项的正常客观题。

用法
----
    python scripts/clean_quiz_quality.py              # dry-run
    python scripts/clean_quiz_quality.py --apply      # 写库（自动先备份）
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

# 无选项 / 无答案 的判定口径（与 quiz_health_check / quiz_quality_gate 对齐）
_NO_OPT = "(options IS NULL OR TRIM(options)='' OR options='[]' OR options='null')"
_NO_ANS = "(answer IS NULL OR TRIM(answer)='')"

# 管综专属特征（不含「写作」——英语作文会误伤）
_GUANZONG_KW = ("逻辑推理", "条件充分性", "论证有效性分析", "论证有效性")


def _where(*extra: str) -> str:
    return " AND ".join((_NO_OPT,) + extra) if extra else _NO_OPT


def backup_db(src_path: str, dst_path: str) -> str:
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dst_path


def plan(conn: sqlite3.Connection) -> dict:
    c = conn.cursor()

    def one(sql: str) -> int:
        return c.execute(sql).fetchone()[0]

    gz_where = " AND ".join(f"content LIKE '%{k}%'" for k in _GUANZONG_KW)
    gz_where = "(" + gz_where.replace(" AND ", " OR ") + ")"
    return {
        # ② 管综残留（未 junk）
        "gz_junk": one(f"SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0 AND {gz_where}"),
        "gz_ids": [r[0] for r in c.execute(
            f"SELECT id FROM quiz_questions WHERE is_junk=0 AND {gz_where}")],
        # ③ 无选项 + 有答案 + 未 junk + 仍是 objective
        "subjective": one(
            f"SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0 AND {_NO_OPT} "
            f"AND NOT {_NO_ANS} AND (answer_type IS NULL OR answer_type<>'subjective')"),
        # ④ 无选项 + 无答案 + 未 junk
        "incomplete": one(
            f"SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0 AND {_NO_OPT} "
            f"AND {_NO_ANS} AND (quality IS NULL OR quality<>'incomplete')"),
    }


def stats(conn: sqlite3.Connection) -> dict:
    c = conn.cursor()

    def one(sql: str) -> int:
        try:
            return c.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return -1

    return {
        "total": one("SELECT COUNT(*) FROM quiz_questions"),
        "visible_nonjunk": one("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0"),
        "answerable_avail": one(
            "SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0 AND is_available=1 "
            f"AND NOT {_NO_ANS}"),
        "no_opt_answer": one(f"SELECT COUNT(*) FROM quiz_questions WHERE {_NO_OPT} AND NOT {_NO_ANS}"),
        "no_opt_noans": one(f"SELECT COUNT(*) FROM quiz_questions WHERE {_NO_OPT} AND {_NO_ANS}"),
        "subjective_cnt": one("SELECT COUNT(*) FROM quiz_questions WHERE answer_type='subjective'"),
        "incomplete_cnt": one("SELECT COUNT(*) FROM quiz_questions WHERE quality='incomplete'"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="题库可见题质量分层收口（dry-run 默认）")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup", default=None)
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f"数据库不存在: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    try:
        before = stats(conn)
        p = plan(conn)

        print("=" * 72)
        print("题库质量分层收口" + ("（DRY-RUN，不写库）" if not args.apply else "（APPLY）"))
        print("=" * 72)
        print("  清理前：")
        for k, v in before.items():
            print(f"    {k:<20} {v}")
        print()
        print(f"  ② 管综错配残留（未 junk）待标 junk = {p['gz_junk']}")
        if p["gz_ids"][:10]:
            print(f"     id 示例 {p['gz_ids'][:10]}")
        print(f"  ③ 无选项+有答案 → 标 answer_type='subjective' = {p['subjective']}")
        print(f"  ④ 无选项+无答案 → 标 quality='incomplete' + is_available=0 = {p['incomplete']}")
        print()

        if not args.apply:
            print(">>> DRY-RUN 结束，未做任何改动。确认后加 --apply（自动先备份）。")
            return 0

        if not (p["gz_junk"] or p["subjective"] or p["incomplete"]):
            print(">>> 无需清理。")
            return 0

        bk = args.backup or (args.db + ".quizquality.bak")
        print(f">>> 备份中（SQLite backup() API）→ {bk}")
        backup_db(args.db, bk)
        print(f">>> 备份完成（{os.path.getsize(bk) / 1e6:.1f} MB）")

        c = conn.cursor()
        # ②
        gz_where = "(" + " OR ".join(f"content LIKE '%{k}%'" for k in _GUANZONG_KW) + ")"
        n2 = c.execute(
            f"UPDATE quiz_questions SET is_junk=1 WHERE is_junk=0 AND {gz_where}").rowcount
        # ③
        n3 = c.execute(
            f"UPDATE quiz_questions SET answer_type='subjective' WHERE is_junk=0 AND {_NO_OPT} "
            f"AND NOT {_NO_ANS} AND (answer_type IS NULL OR answer_type<>'subjective')").rowcount
        # ④
        n4 = c.execute(
            f"UPDATE quiz_questions SET quality='incomplete', is_available=0 WHERE is_junk=0 "
            f"AND {_NO_OPT} AND {_NO_ANS} AND (quality IS NULL OR quality<>'incomplete')").rowcount
        conn.commit()

        after = stats(conn)
        print(f">>> ② 标 junk {n2} 行")
        print(f">>> ③ 标 subjective {n3} 行")
        print(f">>> ④ 标 incomplete {n4} 行")
        print("\n  清理前后对比：")
        for k in before:
            b, a = before[k], after[k]
            print(f"    {k:<20} {b:>6} → {a:>6}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
