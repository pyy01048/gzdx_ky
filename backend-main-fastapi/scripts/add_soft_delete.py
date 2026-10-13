# -*- coding: utf-8 -*-
"""软删除字段迁移（quiz_questions / knowledge_chunks）。

## 为什么需要

本周因判重逻辑只看题干不看答案，误删 158 条真题（仅恢复 89 条）。
事后加的 `services/delete_guard.py` 是**代码路径**层面的闸门：它只在
Python 代码里生效，手写 SQL、ORM 之外的连接、未来的新脚本都能绕过。
闸门治标，根因是「删除 = 不可逆」。

本脚本给两张核心表加 `is_deleted INTEGER DEFAULT 0`，把删除语义从
「物理 DELETE」改成「标记 + 查询排除」，让误删变成可回滚的。

## 设计取舍：为什么是 INTEGER DEFAULT 0

1. **不是 BOOLEAN**：SQLite 里 BOOLEAN 只是一个名字约定（`BOOLEAN` 的
   真实存储亲和性是 NUMERIC），值存进去是 0/1。既有列已经这么用了
   （`is_available BOOLEAN`、`is_junk BOOLEAN`）。新列用 INTEGER 是为了
   **与既有代码的 `.is_(True)` / `.is_(False)` 兼容**，并且避免 SQLAlchemy
   把 `NULL` 悄悄转成 `False` 而掩盖「未标记」与「显式正常」的区别。

2. **不是 deleted_at 时间戳（至少现在不是）**：
   `deleted_at` 能告诉我们「什么时候删的」，对**回滚窗口**和**物化清理
   排期**很有价值，这是它唯一强于 `is_deleted` 的地方。但它的问题是：
   - 「删了但没有时间」表达不出来（时间戳 NULL 语义天然歧义：
     是没删，还是删了但没记时间？）；
   - 按时间窗口批量恢复需要 `WHERE deleted_at BETWEEN ...`，
     而没有时窗口时你**列不出「最近删了哪些」** —— 排查事故时这很致命；
   - 每次软删都要维护时间戳，写入路径更容易出 bug。

   **本方案的选择**：先上 `is_deleted`（足够安全、足够简单），把
   「时间维度」交给**独立的删除流水表** `soft_delete_log`（见下方
   `--with-log-table`）。流水表只在真正执行软删时 INSERT 一行，
   既拿到时间戳，又不污染主表，且可审计、可按窗口批量回滚。
   如果将来确认「主表自带时间戳」更方便，再做一次迁移把 log 回填进
   `deleted_at` 即可，兼容性不受影响。

3. **DEFAULT 0 而非 NOT NULL**：SQLite 的 `ALTER TABLE ADD COLUMN`
   不能带 `NOT NULL` 而不给默认值。加上 `DEFAULT 0` 后，历史行在
   SQLite 里读出来就是 0（SQLite 的 ALTER ADD COLUMN 对存量行会应用
   默认值），不需要全表 UPDATE。

## 索引设计

- `quiz_questions(is_deleted)`：单列。绝大多数查询形态是
  「全表 + is_deleted=0 + 若干等值条件」，SQLite 会挑 `is_deleted`
  做索引扫描再回表过滤；行选择性低时（软删占比 <5%）这比复合索引更划算。
- `knowledge_chunks(is_deleted)`：同上。

## 用法

```bash
# 默认 dry-run，只打印计划，不写库
python scripts/add_soft_delete.py

# 真要写库时显式 --apply，并强烈建议先指定 --db 指向副本库试跑
python scripts/add_soft_delete.py --apply --db D:/platform/database/kaoyan_softdelete_test.db
```

脚本**幂等**：列/索引已存在时跳过，重复执行不报错、退出码 0。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 目标库路径下限（1MB）。低于此值视为空壳/诱饵库，拒绝迁移。
#: 历史上 backup_service 硬编码 data/kaoyan.db 备份了空壳库，这个下限
#: 是同一个教训的复用。
MIN_DB_BYTES = 1 * 1024 * 1024

#: 待加字段的表 → 索引名
TARGETS: dict[str, str] = {
    "quiz_questions": "ix_quiz_questions_is_deleted",
    "knowledge_chunks": "ix_knowledge_chunks_is_deleted",
}

COLUMN_NAME = "is_deleted"
COLUMN_DDL = "INTEGER DEFAULT 0"

#: 软删流水表：记录每次软删动作，供「按时间窗口批量回滚」使用。
LOG_TABLE = "soft_delete_log"
LOG_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS soft_delete_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    deleted_by TEXT,
    reason TEXT,
    batch_id TEXT,
    restored_at TEXT,
    restored_by TEXT,
    restore_reason TEXT
)
"""


# --------------------------------------------------------------------------- #
# 结果模型
# --------------------------------------------------------------------------- #
@dataclass
class ColumnPlan:
    """单表列的迁移计划。"""

    table: str
    exists: bool
    ddl: str
    nullable_rows: int = 0


@dataclass
class IndexPlan:
    """单表索引的迁移计划。"""

    table: str
    index_name: str
    exists: bool
    ddl: str


@dataclass
class Report:
    """整体迁移报告。"""

    db_path: str = ""
    dry_run: bool = True
    columns: list[ColumnPlan] = field(default_factory=list)
    indexes: list[IndexPlan] = field(default_factory=list)
    log_table_created: bool = False

    @property
    def has_pending(self) -> bool:
        """是否还有未执行的变更。"""
        pending_cols = [c for c in self.columns if not c.exists]
        pending_idx = [i for i in self.indexes if not i.exists]
        return bool(pending_cols or pending_idx or self.log_table_created)


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _sqlite_url_to_path(url: str) -> Optional[str]:
    """把 SQLite 连接串转成本地文件路径；非 SQLite / 内存库返回 None。"""
    if not url:
        return None
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            raw = url[len(prefix):]
            break
    else:
        return None
    if not raw or ":memory:" in raw:
        return None
    return raw.lstrip("/") if len(raw) > 2 and raw[1] == ":" else raw


def resolve_db_path(explicit: Optional[str]) -> str:
    """解析目标库路径。

    解析顺序：--db 参数 > 环境变量 KAOYAN_DB_PATH > database.py 的
    SQLALCHEMY_DATABASE_URL > 仓库同级 database/kaoyan.db。
    无论走哪条，结果小于 MIN_DB_BYTES 一律拒绝。
    """
    if explicit:
        path = os.path.abspath(explicit)
        if not os.path.isfile(path):
            raise SystemExit(f"[add_soft_delete] 指定的库不存在: {path}")
        return path

    env = (os.environ.get("KAOYAN_DB_PATH") or "").strip()
    if env and os.path.isfile(env):
        return os.path.abspath(env)

    try:
        sys.path.insert(0, BASE_DIR)
        from database import SQLALCHEMY_DATABASE_URL  # type: ignore

        path = _sqlite_url_to_path(SQLALCHEMY_DATABASE_URL)
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    except Exception:  # noqa: BLE001 —— 导入失败降级继续
        pass

    path = os.path.abspath(os.path.join(BASE_DIR, os.pardir, "database", "kaoyan.db"))
    if os.path.isfile(path):
        return path
    raise SystemExit(
        "[add_soft_delete] 无法定位目标库。请用 --db 显式指定，"
        "或设置 KAOYAN_DB_PATH。"
    )


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """表是否存在。"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """列是否存在（用 PRAGMA table_info，避免解析 CREATE TABLE 文本）。"""
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return any(r[1] == column for r in rows)


def index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    """索引是否存在。"""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (index_name,)
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------- #
# 计划生成
# --------------------------------------------------------------------------- #
def build_plan(conn: sqlite3.Connection, db_path: str, dry_run: bool,
               with_log_table: bool) -> Report:
    """扫描目标库，生成迁移计划（不写库）。"""
    report = Report(db_path=db_path, dry_run=dry_run)

    for table, index_name in TARGETS.items():
        if not table_exists(conn, table):
            print(f"[add_soft_delete] 跳过 {table}: 表不存在")
            continue

        col_ddl = f'ALTER TABLE "{table}" ADD COLUMN {COLUMN_NAME} {COLUMN_DDL}'
        exists = column_exists(conn, table, COLUMN_NAME)

        # 仅在列还不存在时统计「多少行会是 NULL」——已存在则无需关心。
        nullable_rows = 0
        if not exists:
            nullable_rows = conn.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]

        report.columns.append(ColumnPlan(
            table=table, exists=exists, ddl=col_ddl, nullable_rows=nullable_rows,
        ))

        idx_ddl = (
            f'CREATE INDEX IF NOT EXISTS "{index_name}" '
            f'ON "{table}" ({COLUMN_NAME})'
        )
        report.indexes.append(IndexPlan(
            table=table, index_name=index_name,
            exists=index_exists(conn, index_name), ddl=idx_ddl,
        ))

    report.log_table_created = with_log_table and not table_exists(conn, LOG_TABLE)
    return report


# --------------------------------------------------------------------------- #
# 应用
# --------------------------------------------------------------------------- #
def apply_plan(conn: sqlite3.Connection, report: Report) -> None:
    """按计划执行迁移。全部语句幂等，可重复执行。"""
    for plan in report.columns:
        if plan.exists:
            print(f"[add_soft_delete] 列已存在，跳过: {plan.table}.{COLUMN_NAME}")
            continue
        conn.execute(plan.ddl)
        print(f"[add_soft_delete] 已加列: {plan.table}.{COLUMN_NAME} ({COLUMN_DDL})")

    if report.log_table_created:
        conn.execute(LOG_TABLE_DDL)
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS ix_soft_delete_log_lookup "
            f"ON {LOG_TABLE} (table_name, deleted_at)"
        )
        print(f"[add_soft_delete] 已建软删流水表: {LOG_TABLE}")

    for plan in report.indexes:
        if plan.exists:
            print(f"[add_soft_delete] 索引已存在，跳过: {plan.index_name}")
            continue
        conn.execute(plan.ddl)
        print(f"[add_soft_delete] 已建索引: {plan.index_name}")


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def print_report(report: Report) -> None:
    """打印迁移计划 / 执行结果。"""
    mode = "DRY-RUN（不写库）" if report.dry_run else "APPLY（写库）"
    size_mb = os.path.getsize(report.db_path) / 1048576
    print("=" * 70)
    print(f"[add_soft_delete] 目标库: {report.db_path} ({size_mb:.1f} MB)")
    print(f"[add_soft_delete] 模式  : {mode}")
    print("=" * 70)

    print("\n[1] 新增列")
    for c in report.columns:
        if c.exists:
            print(f"    - {c.table}.{COLUMN_NAME}: 已存在，跳过")
        else:
            print(f"    + {c.table}.{COLUMN_NAME} {COLUMN_DDL}")
            print(f"      影响行数: {c.nullable_rows}（SQLite 会自动填 0）")

    print("\n[2] 新增索引")
    for i in report.indexes:
        if i.exists:
            print(f"    - {i.index_name}: 已存在，跳过")
        else:
            print(f"    + {i.index_name} ON {i.table}({COLUMN_NAME})")

    print("\n[3] 软删流水表")
    if report.log_table_created:
        print(f"    + {LOG_TABLE}（记录每次软删的时间/原因，供批量回滚）")
    else:
        print(f"    - {LOG_TABLE}: 已存在或未启用，跳过")

    if report.dry_run and report.has_pending:
        print("\n以上变更尚未写入。确认无误后追加 --apply 执行。")
    elif not report.has_pending:
        print("\n库结构已就绪，无需变更（幂等：重复执行安全）。")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    """脚本入口。

    Returns:
        0 成功（含「无需变更」）。非 0 表示被拒绝或执行失败。
    """
    parser = argparse.ArgumentParser(
        description="给 quiz_questions / knowledge_chunks 加软删字段（幂等迁移）",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="真正写库。缺省为 dry-run，只打印计划。",
    )
    parser.add_argument(
        "--db", default=None,
        help="目标库路径。缺省按 KAOYAN_DB_PATH → database.py → ../database 解析。",
    )
    parser.add_argument(
        "--no-log-table", action="store_true",
        help="不创建 soft_delete_log 流水表（不推荐：会失去按时间窗口回滚的能力）。",
    )
    args = parser.parse_args(argv)

    db_path = resolve_db_path(args.db)

    # 体积下限校验：拦住 data/kaoyan.db 这类空壳诱饵库。
    size = os.path.getsize(db_path)
    if size < MIN_DB_BYTES:
        print(
            f"[add_soft_delete] 拒绝：目标库过小（{size} B < {MIN_DB_BYTES} B），"
            f"疑似空壳库: {db_path}"
        )
        return 2

    conn = sqlite3.connect(db_path)
    try:
        report = build_plan(
            conn, db_path, dry_run=not args.apply,
            with_log_table=not args.no_log_table,
        )

        if args.apply:
            apply_plan(conn, report)
            conn.commit()
            # 提交后重建一次报告，让输出反映最终状态。
            report = build_plan(conn, db_path, dry_run=False,
                                with_log_table=not args.no_log_table)
        print_report(report)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())