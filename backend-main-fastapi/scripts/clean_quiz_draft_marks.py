"""清洗 quiz_questions 答案/解析字段的「草稿」标记污染。

背景（2026-10-12 体检）：1576 道题的 answer 字段形如
    '【草稿】B查看答案' / '【草稿】A' / '【草稿】F＝∑m（1,2,4）'
用户点「看答案」看到的是这类噪声前缀，而不是干净的答案。

清洗规则（保守、可逆前缀剥离，不臆造内容）：
  * 去掉 answer 开头的「【草稿】」「【草稿解析】」「【解析】」等标记
  * 去掉尾部的「查看答案」按钮文字
  * 剥完后若为空 → 该题答案视为缺失（置 NULL，交给质量门禁降级）

用法：
    python scripts/clean_quiz_draft_marks.py            # dry-run
    python scripts/clean_quiz_draft_marks.py --apply
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

# 前缀标记（可叠加）
_PREFIX = re.compile(r"^\s*(?:【[^】]{0,8}】|\[[^\]]{0,8}\]|＜[^＞]{0,8}＞)\s*")
# 尾部按钮文字
_SUFFIX = re.compile(r"(?:查看答案|点击查看答案|展开答案|显示答案)\s*$")
# 纯答案标记（剥离后无内容则视为空）
_ANSWER_MARK = re.compile(r"^\s*【?(?:草稿)?解析?】?\s*$")


def clean_answer(a: str) -> str:
    if a is None:
        return None
    s = a
    # 反复剥离前缀标记（可能叠加多层）
    for _ in range(4):
        n = _PREFIX.sub("", s)
        if n == s:
            break
        s = n
    s = _SUFFIX.sub("", s).strip()
    if _ANSWER_MARK.match(s):
        return None
    return s or None


def backup(con: sqlite3.Connection) -> str:
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_draftclean_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    return bak


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")

    rows = con.execute(
        "SELECT id, answer FROM quiz_questions "
        "WHERE answer LIKE '%【%' OR answer LIKE '%查看答案%'"
    ).fetchall()

    changes = []
    emptied = 0
    for i, a in rows:
        new = clean_answer(a)
        if new != a:
            changes.append((i, a, new))
            if new is None:
                emptied += 1

    print(f"命中 {len(rows)} 条，需修改 {len(changes)} 条（其中剥空 {emptied} 条）")
    for i, old, new in changes[:12]:
        print(f"  #{i}: {old[:60]!r} → {str(new)[:60]!r}")

    if args.apply and changes:
        bak = backup(con)
        print(f"\n备份 → {bak}")
        con.execute("BEGIN")
        for i, _, new in changes:
            con.execute("UPDATE quiz_questions SET answer=? WHERE id=?", (new, i))
        con.commit()
        print(f"已清洗 {len(changes)} 条")

    left = con.execute(
        "SELECT count(*) FROM quiz_questions WHERE answer LIKE '%【草稿%'"
    ).fetchone()[0]
    print(f"\n残留【草稿】: {left}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
