"""清理 flashcards 无意义条目。

背景（2026-10-12 体检）：652 张卡片里有 front='1'/back='1' 这类垃圾，
以及 front 为单个数字/标点的无效卡。

判定（保守，只删明确无意义的）：
  * front 清洗后为空
  * front 为纯数字/纯标点
  * front 与 back 相同且都很短（< 4 字）
  * front 与 back 都为空

不删除：front 是真实短术语（如「化简」「稳压」）但 back 只有元数据的卡片——
        这些是低价值「考点卡」，属设计取舍，保留待后续补充释义。

用法：
    python scripts/clean_flashcards.py
    python scripts/clean_flashcards.py --apply
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


def is_garbage(front: str, back: str) -> bool:
    f = (front or "").strip()
    b = (back or "").strip()
    if not f and not b:
        return True
    if not f:
        return True
    # 纯数字 / 纯标点
    if re.fullmatch(r"[\d\s\.\-_/\\]+", f):
        return True
    if not re.search(r"[\w\u4e00-\u9fa5]", f):
        return True
    # front == back 且都短
    if f == b and len(f) < 4:
        return True
    return False


def backup(con: sqlite3.Connection) -> str:
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_cardclean_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
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
    rows = con.execute("SELECT id, front, back FROM flashcards").fetchall()
    bad = [(i, f, b) for i, f, b in rows if is_garbage(f, b)]
    print(f"卡片总数 {len(rows)}，判定无意义 {len(bad)}")
    for i, f, b in bad[:15]:
        print(f"  #{i} front={f!r} back={b!r}")

    if args.apply and bad:
        bak = backup(con)
        print(f"\n备份 → {bak}")
        ids = [i for i, _, _ in bad]
        con.execute("BEGIN")
        con.execute(
            f"DELETE FROM flashcards WHERE id IN ({','.join('?' * len(ids))})", ids)
        con.commit()
        print(f"已删除 {len(ids)} 张")

    left = con.execute("SELECT count(*) FROM flashcards").fetchone()[0]
    print(f"\n当前卡片数: {left}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
