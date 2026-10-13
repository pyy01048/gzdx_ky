# -*- coding: utf-8 -*-
"""给 `kaoyan_notices` 增加 `content` 列（导入时用户粘贴的正文快照）。

**默认 dry-run（只读），必须显式加 `--apply` 才写库。**

用法：
    python scripts/notice_content_migration.py              # dry-run，只报告
    python scripts/notice_content_migration.py --apply      # 备份后执行

设计约束（来自 team-lead 任务书）：
  - 幂等：重复执行不报错，已有列时 dry-run 报告"无需迁移"
  - 备份：`sqlite3` `Connection.backup()` API（**禁止 cp / shutil.copy2**，
    WAL 模式下拷贝 .db 文件会丢未 checkpoint 的数据）
  - 只加列，0 DELETE / 0 UPDATE / 0 DROP
  - 不动 `is_read` / `is_starred` / `read_at` / `starred_at`
  - 不改 `importance_level` / `importance_score` 已有口径

为什么单独写脚本而不塞进 `ensure_alert_schema()`：
  `ensure_alert_schema()` 在**每次 API 请求**都会跑，把带备份的迁移放进请求
  路径会让用户请求触发一次全库备份。迁移是低频运维动作，应该显式执行。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DB_PATH = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\_backup_notice_alert"
NEW_COLUMN = ("content", "TEXT")

# 通知中心前端 + 7 个已读 API 明确消费的列；加列后必须逐列确认仍在
PROTECTED_COLUMNS = [
    "id", "school_id", "school_name", "title", "notice_type", "publish_date",
    "url", "source", "fetched_at",
    "importance_level", "importance_score", "importance_reason",
    "deadline_date", "events_json", "classified_at",
    "is_read", "is_starred", "read_at", "starred_at",
]


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def backup_db(tag: str) -> str:
    """用 sqlite3 的 `backup()` API 备份真库（WAL 安全），返回备份路径。"""
    Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = str(Path(BACKUP_DIR) / f"kaoyan_{ts}_{tag}.db")
    src = _connect(DB_PATH)
    try:
        dst_conn = sqlite3.connect(dst)
        src.backup(dst_conn)
        dst_conn.close()
    finally:
        src.close()
    return dst


def verify_backup(path: str) -> tuple:
    """备份自检：integrity_check + 列数 + 行数。返回 (ok, detail)。"""
    conn = _connect(path)
    try:
        integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
        cols = [r[1] for r in conn.execute("PRAGMA table_info(kaoyan_notices)")]
        rows = conn.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
        has_new = NEW_COLUMN[0] in cols
        return (integ == "ok" and rows > 0,
                f"integrity={integ} columns={len(cols)} rows={rows} "
                f"{NEW_COLUMN[0]}={'present' if has_new else 'absent'}")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="真正执行 ALTER TABLE（默认只 dry-run）")
    args = ap.parse_args()

    print("=" * 78)
    print("  kaoyan_notices 增加 content 列 —— 迁移"
          + ("（APPLY 模式）" if args.apply else "（DRY-RUN，只读）"))
    print("=" * 78)

    conn = _connect(DB_PATH)
    try:
        cols_before = [r[1] for r in conn.execute("PRAGMA table_info(kaoyan_notices)")]
        rows_before = conn.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
        name, typ = NEW_COLUMN
        already = name in cols_before

        print(f"  数据库: {DB_PATH}")
        print(f"  当前列数: {len(cols_before)}   行数: {rows_before}")
        print(f"  目标: 新增 `{name} {typ}`")
        print(f"  幂等检查: {'列已存在，无需迁移' if already else '列缺失，需要迁移'}")

        # ---- 受保护列必须全部在位（加列不能顺手弄丢别人的字段） ----
        missing = [c for c in PROTECTED_COLUMNS if c not in cols_before]
        if missing:
            print(f"  [FAIL] 受保护列缺失: {missing} —— 先解决再迁移，中止")
            return 2
        print(f"  受保护列检查: {len(PROTECTED_COLUMNS)}/{len(PROTECTED_COLUMNS)} 在位 ✅")

        # ---- 影响面：显式 SELECT 列表会不会变形 ----
        print()
        print("  影响面分析（不是推断，逐项核对）：")
        print("    - routers/notices.py 已读 API：SELECT 使用**显式列清单**，")
        print("      无 `SELECT *`，加列不改变返回形状")
        print("    - 通知中心前端：按字段名取值，不认识的字段被忽略")
        print("    - 我的 routers/notice_alert.py：INSERT 使用显式列清单")
        print("      → 我将改为「列探测后再决定是否写 content」，迁移前后都可用")

        if already:
            print()
            print("  [DONE] 列已存在，dry-run 与 apply 结果相同，无需操作。")
            return 0

        if not args.apply:
            print()
            print("  [DRY-RUN] 未写库。加 --apply 才会：备份 → ALTER TABLE ADD COLUMN")
            print(f"  [DRY-RUN] 备份将写入: {BACKUP_DIR}\\kaoyan_<时间戳>_before_content.db")
            return 0

        # ---- APPLY：先备份 ----
        print()
        print("  [1/3] 备份真库（sqlite3 backup() API，WAL 安全）…")
        bpath = backup_db("before_content")
        ok, detail = verify_backup(bpath)
        print(f"        备份: {bpath}")
        print(f"        自检: {detail} {'✅' if ok else '❌'}")
        if not ok:
            print("  [FAIL] 备份自检未通过，中止迁移（不动真库）")
            return 3

        # ---- APPLY：ALTER TABLE ----
        print("  [2/3] 执行 ALTER TABLE ADD COLUMN…")
        conn.execute(f"ALTER TABLE kaoyan_notices ADD COLUMN {name} {typ}")
        conn.commit()

        # ---- APPLY：验证 ----
        print("  [3/3] 验证迁移结果…")
        cols_after = [r[1] for r in conn.execute("PRAGMA table_info(kaoyan_notices)")]
        rows_after = conn.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
        null_cnt = conn.execute(
            f"SELECT COUNT(*) FROM kaoyan_notices WHERE {name} IS NULL").fetchone()[0]
        integ = conn.execute("PRAGMA integrity_check").fetchone()[0]

        print(f"        列数: {len(cols_before)} → {len(cols_after)}")
        print(f"        行数: {rows_before} → {rows_after}"
              f" {'✅' if rows_after == rows_before else '❌ 行数变了！'}")
        print(f"        新增列 `{name}` 在位: {name in cols_after}")
        print(f"        {name} 为 NULL 的行: {null_cnt}（预期 = 全部行，纯新增列无数据）")
        print(f"        integrity_check: {integ}")

        lost = [c for c in cols_before if c not in cols_after]
        print(f"        丢失列: {lost if lost else '无 ✅'}")

        ok2 = (name in cols_after and rows_after == rows_before
               and not lost and integ == "ok")
        print()
        print(f"  [{'DONE ✅' if ok2 else 'FAIL ❌'}] 迁移"
              f"{'成功' if ok2 else '未通过验证，请从备份恢复'}")
        print(f"  备份路径（如需回滚）: {bpath}")
        return 0 if ok2 else 4
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
