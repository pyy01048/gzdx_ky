# -*- coding: utf-8 -*-
"""隔离同题干答案冲突题 + 入库闸门第 6 层的执行脚本。

裁决（team-lead，第八轮）：6 组冲突题共 12 条，两侧答案都无法证实为正确，
按【原则 2：两侧都错】全部 is_junk=1 隔离，不重写答案、不做物理 DELETE。

红线：
- 禁止 cp / shutil.copy2（真库为 SQLite WAL 模式，文件级复制会丢未合并的
  -wal 事务），必须使用 sqlite3.Connection.backup() API。
- 禁止 DELETE，只 UPDATE is_junk。

用法：
    python scripts/isolate_conflict_quiz.py backup    # 备份 + integrity_check
    python scripts/isolate_conflict_quiz.py diff      # ATTACH dry-run diff
    python scripts/isolate_conflict_quiz.py apply     # 写库（UPDATE is_junk）
    python scripts/isolate_conflict_quiz.py stats     # 三项数字回报
"""
from __future__ import annotations

from pathlib import Path
import datetime
import os
import sqlite3
import sys

# 路径按本文件位置推导（P0-B2：拆除机器专属绝对路径绑定）
_REPO = Path(__file__).resolve().parents[2]
DB_PATH = str(_REPO / "database" / "kaoyan.db")
BACKUP_DIR = str(_REPO / "database" / "_backup")
PREFIX = "kaoyan_pre_isolate_"

# team-lead 裁决需隔离的 6 组冲突题，格式: (组号, (id1, id2))
CONFLICT_GROUPS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("G07", (288, 8063)),
    ("G15", (400, 8152)),
    ("O02", (64, 1532)),
    ("O15", (140, 1562)),
    ("O16", (142, 1564)),
    ("O19", (315, 8083)),
)

TARGET_IDS: list[int] = [qid for _, pair in CONFLICT_GROUPS for qid in pair]


def latest_backup() -> str | None:
    """返回 BACKUP_DIR 下最新的隔离前备份路径。"""
    if not os.path.isdir(BACKUP_DIR):
        return None
    names = [n for n in os.listdir(BACKUP_DIR) if n.startswith(PREFIX) and n.endswith(".db")]
    if not names:
        return None
    names.sort()
    return os.path.join(BACKUP_DIR, names[-1])



def make_backup() -> str:
    """用 SQLite backup() API 生成一致性快照，并做 integrity_check。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_path = os.path.join(BACKUP_DIR, f"{PREFIX}{ts}.db")

    src = sqlite3.connect(DB_PATH, timeout=60)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
            row = dst.execute("PRAGMA integrity_check").fetchone()
            check = row[0] if row else "unknown"
        finally:
            dst.close()
    finally:
        src.close()

    size_mb = round(os.path.getsize(dst_path) / 1024 / 1024, 1)
    print(f"[backup] path={dst_path}")
    print(f"[backup] size={size_mb} MB")
    print(f"[backup] integrity_check={check}")
    return dst_path


def _ph(conn: sqlite3.Connection, n: int) -> tuple[int, ...]:
    """构造 n 个占位符。"""
    return tuple("?" for _ in range(n))


def dryrun_diff() -> int:
    """ATTACH 挂载备份，对比当前库与备份的 is_junk 值差异（只读）。

    返回越界 id 数量（TARGET_IDS 之外的意外差异）。
    """
    backup = latest_backup()
    if not backup:
        print("[diff] 找不到备份文件，请先执行 backup")
        return 1

    conn = sqlite3.connect(DB_PATH, timeout=60)
    try:
        conn.execute("ATTACH DATABASE ? AS bak", (backup,))
        marks = ",".join("?" * len(TARGET_IDS))

        print(f"[diff] backup={backup}")
        print(f"[diff] {'grp':<5}{'id':<8}{'bak.is_junk':<12}{'cur.is_junk':<12}delta")
        changed: list[tuple[int, int, int]] = []
        for grp, (id1, id2) in CONFLICT_GROUPS:
            for qid in (id1, id2):
                row = conn.execute(
                    f"SELECT b.is_junk, c.is_junk "
                    f"FROM bak.quiz_questions b JOIN main.quiz_questions c "
                    f"ON c.id = b.id WHERE b.id = ?",
                    (qid,),
                ).fetchone()
                if row is None:
                    print(f"[diff] {grp:<5}{qid:<8}缺失于某库")
                    continue
                b_junk, c_junk = int(row[0]), int(row[1])
                delta = c_junk - b_junk
                print(f"[diff] {grp:<5}{qid:<8}{b_junk:<12}{c_junk:<12}{delta:+d}")
                if delta != 0:
                    changed.append((qid, b_junk, c_junk))

        # 越界检查：确认只有 TARGET_IDS 会变
        q = f"""
            SELECT b.id FROM bak.quiz_questions b
            JOIN main.quiz_questions c ON c.id = b.id
            WHERE IFNULL(b.is_junk,-1) <> IFNULL(c.is_junk,-2)
              AND b.id NOT IN ({marks})
        """
        outside = [r[0] for r in conn.execute(q, TARGET_IDS)]
        only_target = [r[0] for r in conn.execute(
            f"SELECT c.id FROM main.quiz_questions c "
            f"WHERE c.id IN ({marks}) AND c.is_junk <> 1", TARGET_IDS)]
        total = conn.execute("SELECT COUNT(*) FROM main.quiz_questions").fetchone()[0]
        bak_total = conn.execute("SELECT COUNT(*) FROM bak.quiz_questions").fetchone()[0]
        conn.execute("DETACH DATABASE bak")
    finally:
        conn.close()

    print(f"[diff] 待改动 {len(changed)} 条 / 目标 {len(TARGET_IDS)} 条")
    print(f"[diff] 越界 id = {len(outside)} {outside if outside else ''}")
    print(f"[diff] 目标中尚未 is_junk=1 的 = {len(only_target)} {only_target if only_target else ''}")
    print(f"[diff] 行数 main={total} / bak={bak_total} {'OK' if total == bak_total else '不一致!'}")
    return len(outside) + len(only_target)


def apply_isolate() -> None:
    """执行隔离：只 UPDATE is_junk=1，禁止 DELETE。"""
    conn = sqlite3.connect(DB_PATH, timeout=60)
    try:
        conn.execute("BEGIN IMMEDIATE")
        before = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0").fetchone()[0]
        marks = ",".join("?" * len(TARGET_IDS))
        rows = conn.execute(
            f"SELECT id, is_junk FROM quiz_questions WHERE id IN ({marks})", TARGET_IDS
        ).fetchall()
        missing = sorted(set(TARGET_IDS) - {r[0] for r in rows})
        if missing:
            raise SystemExit(f"[apply] 目标 id 不存在，中止：{missing}")

        cur = conn.execute(
            f"UPDATE quiz_questions SET is_junk=1 WHERE id IN ({marks}) AND is_junk<>1",
            TARGET_IDS,
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0").fetchone()[0]
        junk1 = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=1").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM quiz_questions").fetchone()[0]
        chk = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()

    print(f"[apply] UPDATE 影响行数={cur.rowcount}")
    print(f"[apply] is_junk=0 {before} -> {after}")
    print(f"[apply] is_junk=1 现为 {junk1} / 总行数 {total}")
    print(f"[apply] integrity_check={chk}")


def report_stats() -> None:
    """输出三项数字。"""
    conn = sqlite3.connect(DB_PATH, timeout=60)
    try:
        total = conn.execute("SELECT COUNT(*) FROM quiz_questions").fetchone()[0]
        j0 = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0").fetchone()[0]
        j1 = conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=1").fetchone()[0]
        ans = conn.execute(
            "SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0 AND answer IS NOT NULL "
            "AND TRIM(answer)<>''").fetchone()[0]
        chk = conn.execute("PRAGMA integrity_check").fetchone()[0]
        left = conn.execute(
            "SELECT COUNT(*) FROM quiz_questions WHERE is_junk=0 AND id IN (%s)"
            % ",".join("?" * len(TARGET_IDS)), TARGET_IDS).fetchone()[0]
    finally:
        conn.close()
    print(f"[stats] 总行数={total}  is_junk=0={j0}  is_junk=1={j1}")
    print(f"[stats] 可刷题且有答案={ans}")
    print(f"[stats] 目标中残留 is_junk=0 = {left}")
    print(f"[stats] integrity_check={chk}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "backup":
        make_backup()
    elif cmd == "diff":
        sys.exit(0 if dryrun_diff() == 0 else 2)
    elif cmd == "apply":
        apply_isolate()
    elif cmd == "stats":
        report_stats()
    else:
        print(__doc__)
