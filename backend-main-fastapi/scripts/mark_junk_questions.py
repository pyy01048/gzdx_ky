# -*- coding: utf-8 -*-
"""OCR 碎片题标记（M1-1f，2026-10）。

消费 M1-1e 诊断产物 `tools/datasource/junk_questions_candidates.json`，
把**确定垃圾（high 档）**的题标记 `is_junk=1`，供刷题列表默认过滤。

范围与安全（严格遵循 M1-1e 结论）：
  * **只标 high 档**（319 条，证据极强）；medium 档噪音高，**不标**；
  * 含控制字符(\x01)的题是"缺图真实题"，**绝不标**（不在 high 档内，天然排除）；
  * **不删除**——仅打标记，可回滚；
  * 幂等新增列 `is_junk`（Boolean 默认 0）；
  * 默认 dry-run；--apply 先用 sqlite backup API 备份；
  * 审计日志 `tools/datasource/junk_mark_audit.json`。

用法：
    python scripts/mark_junk_questions.py            # 预览
    python scripts/mark_junk_questions.py --apply     # 写库（先备份）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)
REPO_ROOT = os.path.dirname(BASE_DIR)
CANDIDATES_JSON = os.path.join(REPO_ROOT, "tools", "datasource",
                               "junk_questions_candidates.json")
AUDIT_JSON = os.path.join(REPO_ROOT, "tools", "datasource", "junk_mark_audit.json")


def _has_column(cur: sqlite3.Cursor) -> bool:
    cols = {r[1] for r in cur.execute("PRAGMA table_info(quiz_questions)")}
    return "is_junk" in cols


def _ensure_column(cur: sqlite3.Cursor) -> None:
    """幂等新增 is_junk 列（仅 --apply 时调用）。"""
    if not _has_column(cur):
        cur.execute("ALTER TABLE quiz_questions ADD COLUMN is_junk INTEGER DEFAULT 0")


def _load_high_ids() -> list[int]:
    if not os.path.exists(CANDIDATES_JSON):
        raise FileNotFoundError(
            f"未找到 {CANDIDATES_JSON}，请先运行 diagnose_junk_questions.py")
    with open(CANDIDATES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return [r["id"] for r in data.get("high", [])]


def main() -> int:
    ap = argparse.ArgumentParser(description="标记 OCR 碎片题（is_junk=1）")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认预览）")
    ap.add_argument("--sample", type=int, default=10, help="预览样例条数")
    args = ap.parse_args()

    high_ids = _load_high_ids()

    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    col_exists = _has_column(cur)
    # 幂等：已标记为 1 的跳过
    already = set()
    if col_exists:
        already = {r[0] for r in cur.execute(
            "SELECT id FROM quiz_questions WHERE is_junk = 1")}
    effective = [i for i in high_ids if i not in already]

    total_q = cur.execute("SELECT COUNT(*) FROM quiz_questions").fetchone()[0]

    print(f"数据库: {DB_PATH}")
    print(f"high 档候选: {len(high_ids)} 条；已标记跳过 {len(high_ids) - len(effective)}；"
          f"本次将标记 {len(effective)} 条")
    print(f"is_junk 列：{'已存在' if col_exists else '待 --apply 时创建'}")
    print(f"题目总数: {total_q}")

    if args.sample > 0 and effective:
        print(f"\n----- 待标记样例（前 {args.sample} 条）-----")
        for qid in effective[: args.sample]:
            r = cur.execute("SELECT subject, content FROM quiz_questions WHERE id=?",
                            (qid,)).fetchone()
            if r:
                print(f"  Q{qid} [{r[0]}] {r[1][:60]!r}")

    if not args.apply:
        print("\n[DRY-RUN] 未写库。确认后加 --apply 执行（会自动备份）。")
        con.close()
        return 0

    # ---- 备份（sqlite backup API，WAL 安全）----
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_junkmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    print(f"\n已备份 → {bak}")

    _ensure_column(cur)
    con.commit()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    marked: list[dict] = []
    for qid in effective:
        row = cur.execute("SELECT subject, content FROM quiz_questions WHERE id=?",
                          (qid,)).fetchone()
        if not row:
            continue
        cur.execute("UPDATE quiz_questions SET is_junk = 1 WHERE id = ?", (qid,))
        marked.append({"id": qid, "subject": row[0], "content": (row[1] or "")[:80]})
    con.commit()

    # 审计落盘（追加批次）
    prev = {}
    if os.path.exists(AUDIT_JSON):
        try:
            with open(AUDIT_JSON, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = {}
    batches = prev.get("batches", []) if isinstance(prev, dict) else []
    batches.append({
        "applied_at": now,
        "db_path": DB_PATH,
        "backup": bak,
        "source": "tools/datasource/junk_questions_candidates.json (high 档)",
        "marked_count": len(marked),
        "medium_not_marked": True,
        "control_char_not_marked": True,
        "entries": marked,
    })
    with open(AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump({"batches": batches}, f, ensure_ascii=False, indent=2)

    # 复核：可刷题量对比（以全库 subject 无过滤为基准）
    junk_now = cur.execute(
        "SELECT COUNT(*) FROM quiz_questions WHERE is_junk = 1").fetchone()[0]
    print("\n===== 标���完成 =====")
    print(f"本批标记 {len(marked)} 条；全库 is_junk=1 共 {junk_now} 条")
    print(f"刷题可选题（默认排除 is_junk）：{total_q} → {total_q - junk_now}")
    print(f"审计日志 → {AUDIT_JSON}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
