"""清理 AI 伪造 seed 题及其派生的假数据。

背景：quiz_questions 里 id 1-7 是 AI 凭空生成的伪题（source 却写着「真题」/「模拟」/
「自建」），它们又派生了 error_records(id 1-14) 与 answer_records 中的假记录。
这些是演示种子数据污染真实库，必须级联清除，否则错题复盘页展示的是假错题。

安全措施：
- 处理前用 SQLite backup API 备份（非 cp）
- 只删除明确由 id<=7 派生、且 question_id 落在 seed 集合内的记录
- 先 dry-run 打印将要删除的内容

用法：
    python scripts/clean_seed_fakes.py
    python scripts/clean_seed_fakes.py --apply
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
SEED_IDS = (1, 2, 3, 4, 5, 6, 7)

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from services.delete_guard import require_physical_delete_enabled  # noqa: E402


def backup(con: sqlite3.Connection) -> str:
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_seedclean_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
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
    ph = ",".join("?" * len(SEED_IDS))

    print("=== 将要清理的假数据 ===")
    qs = con.execute(
        f"SELECT id, subject, substr(content,1,50) FROM quiz_questions WHERE id IN ({ph})",
        SEED_IDS).fetchall()
    print(f"[quiz_questions] {len(qs)} 条")
    for q in qs:
        print(f"   #{q[0]} [{q[1]}] {q[2]}")

    er = con.execute(
        f"SELECT id, question_id, subject FROM error_records WHERE question_id IN ({ph})",
        SEED_IDS).fetchall()
    print(f"[error_records] {len(er)} 条（错题复盘页的假错题）")
    for e in er:
        print(f"   #{e[0]} ← question#{e[1]} [{e[2]}]")

    ar = con.execute(
        f"SELECT id, question_id FROM answer_records WHERE question_id IN ({ph})",
        SEED_IDS).fetchall()
    print(f"[answer_records] {len(ar)} 条")

    qkl = con.execute(
        f"SELECT id, question_id FROM question_knowledge_links WHERE question_id IN ({ph})",
        SEED_IDS).fetchall()
    print(f"[question_knowledge_links] {len(qkl)} 条")

    ekl_ids = [e[0] for e in er]
    ekl = []
    if ekl_ids:
        ekl = con.execute(
            f"SELECT id, error_id FROM error_knowledge_links WHERE error_id IN "
            f"({','.join('?' * len(ekl_ids))})", ekl_ids).fetchall()
    print(f"[error_knowledge_links] {len(ekl)} 条（挂在这些假错题上的关联）")

    if not args.apply:
        print("\n（dry-run，未写库。加 --apply 执行）")
        return 0

    bak = backup(con)
    print(f"\n备份 → {bak}")

    con.execute("BEGIN")
    if ekl_ids:
        con.execute(
            f"DELETE FROM error_knowledge_links WHERE error_id IN "
            f"({','.join('?' * len(ekl_ids))})", ekl_ids)
    con.execute(f"DELETE FROM error_records WHERE question_id IN ({ph})", SEED_IDS)
    con.execute(f"DELETE FROM answer_records WHERE question_id IN ({ph})", SEED_IDS)
    con.execute(f"DELETE FROM question_knowledge_links WHERE question_id IN ({ph})", SEED_IDS)
    # 物理删除闸门：quiz_questions 物理删除不可逆。seed 伪题 ID 判定若出错
    # 会误删真实题目，必须显式放行。
    require_physical_delete_enabled("quiz_questions")
    con.execute(f"DELETE FROM quiz_questions WHERE id IN ({ph})", SEED_IDS)
    con.commit()
    print("清理完成")

    print("\n=== 复核 ===")
    for t in ("quiz_questions", "error_records", "answer_records"):
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
