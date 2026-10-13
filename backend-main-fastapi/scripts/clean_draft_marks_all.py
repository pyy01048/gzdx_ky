"""清洗「草稿」标记污染（覆盖 analysis 与 error_records）。

背景（2026-10-12 二次体检）：首次只清了 quiz_questions.answer，
实测仍有三处残留：
  * quiz_questions.analysis  含「【草稿解析】…」 约 1576 行
  * error_records.correct_answer 含「【草稿】B查看答案」 若干行
用户在错题复盘详情里看到的就是带前缀的脏答案。

用法：
    python scripts/clean_draft_marks_all.py
    python scripts/clean_draft_marks_all.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

_PREFIX = re.compile(r"^\s*(?:【[^】]{0,10}】|\[[^\]]{0,10}\]|＜[^＞]{0,10}＞)\s*")
_SUFFIX = re.compile(r"(?:查看答案|点击查看答案|展开答案|显示答案)\s*$")
_ONLY_MARK = re.compile(r"^\s*【?(?:草稿)?解析?】?\s*$")
# 只剥离含「草稿」的标记，避免误伤「【考纲要求】」等有意义的前缀
_DRAFT_PREFIX = re.compile(r"^\s*(?:【[^】]{0,10}草稿[^】]{0,10}】|\[[^\]]{0,10}草稿[^\]]{0,10}\])\s*")


def clean(v: str) -> str:
    if v is None:
        return None
    s = v
    for _ in range(4):
        n = _DRAFT_PREFIX.sub("", s)
        if n == s:
            break
        s = n
    s = _SUFFIX.sub("", s).strip()
    if _ONLY_MARK.match(s):
        return None
    return s or None


def backup(con):
    d = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"kaoyan_pre_draftall_{datetime.now():%Y%m%d_%H%M%S}.db")
    with sqlite3.connect(p) as dest:
        con.backup(dest)
    return p


TARGETS = [
    # 仅清理真正的「草稿」污染。注意：
    #   error_records.analysis 的「【四段式错因分析】」是段落标题、
    #   flashcards.back 的「【考纲要求·了解】」是考纲等级，均为有意义信息，
    #   不在清理范围内。
    ("quiz_questions", "analysis"),
    ("error_records", "correct_answer"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")

    total = 0
    plans = []
    for table, col in TARGETS:
        rows = con.execute(
            f"SELECT id, {col} FROM {table} WHERE {col} LIKE '%【%' OR {col} LIKE '%查看答案%'"
        ).fetchall()
        ch = []
        for i, v in rows:
            nv = clean(v)
            if nv != v:
                ch.append((i, v, nv))
        print(f"{table}.{col}: 命中 {len(rows)}，需改 {len(ch)}")
        for i, o, n in ch[:3]:
            print(f"    #{i}: {o[:55]!r} → {str(n)[:55]!r}")
        total += len(ch)
        plans.append((table, col, ch))

    print(f"\n合计需改 {total} 条")
    if args.apply and total:
        bak = backup(con)
        print(f"备份 → {bak}")
        con.execute("BEGIN")
        for table, col, ch in plans:
            for i, _, n in ch:
                con.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (n, i))
        con.commit()
        print("清洗完成")

    print("\n=== 复核残留 ===")
    for table, col in TARGETS:
        n = con.execute(f"SELECT count(*) FROM {table} WHERE {col} LIKE '%【草稿%'").fetchone()[0]
        print(f"  {table}.{col}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
