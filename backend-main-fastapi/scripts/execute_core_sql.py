# -*- coding: utf-8 -*-
"""core/sql 编号脚本执行器（PG 线）+ 迁移账本入口（完善方案 05 §3.1）。

历史用法（仍兼容，单文件立即执行）::

    python scripts/execute_core_sql.py core/sql/108_user_data_isolation.sql

新增用法（推荐）::

    python scripts/execute_core_sql.py --status        # 查看账本状态（会补齐账本表）
    python scripts/execute_core_sql.py --all-pending   # 执行所有未入账脚本
    python scripts/execute_core_sql.py --all-pending --dry-run
    python scripts/execute_core_sql.py --baseline      # 存量库收编：只登记不执行
    python scripts/execute_core_sql.py --all-pending --reconcile-audited-drift

行为约定：
    * 账本为空且库中已有业务表 → ``--all-pending`` 自动降级为 baseline 并明确提示
      （存量库收编，避免在生产库重放历史脚本）。
    * 已登记脚本 checksum 变了 → 直接中止，禁止改历史脚本。
    * 任何数据写操作前请先备份（项目铁律，见 00 文档 §四）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.db_session import IS_POSTGRES, build_database_url  # noqa: E402
from core.migrations import (  # noqa: E402
    SQL_DIR,
    ChecksumMismatch,
    file_checksum,
    ledger_status,
    run_pending,
    split_statements,
)
from sqlalchemy import create_engine, text  # noqa: E402


def _engine():
    return create_engine(build_database_url())


def _print_result(result, dry_run: bool) -> None:
    tag = "（dry-run）" if dry_run else ""
    if result.mode == "baseline":
        print(f"[i] 存量库收编{tag}：只登记不执行 {len(result.baselined)} 个脚本")
        for v in result.baselined:
            print(f"    + {v}")
        print("[!] 提示：baseline 假设这些脚本在目标库已执行过；如有疑问请核对后手工补跑。")
    if result.applied:
        print(f"[✓] 执行完成{tag}：{len(result.applied)} 个脚本")
        for v in result.applied:
            print(f"    + {v}")
    if result.reconciled:
        print(f"[✓] 已审计账本校正{tag}：{len(result.reconciled)} 个脚本")
        for v in result.reconciled:
            print(f"    ~ {v}")
    if result.skipped:
        print(f"[=] 已入账跳过：{len(result.skipped)} 个")
    if result.manual_required:
        print(f"[!] 手工数据脚本未自动执行：{len(result.manual_required)} 个")
        for v in result.manual_required:
            print(f"    - {v}")
    if not result.applied and not result.skipped and not result.reconciled and not result.manual_required:
        print("[✓] 无待执行脚本")


def _run_single_file(engine, path: Path) -> int:
    """单文件直执行（兼容老用法）；文件名符合编号规则时同步记账。"""
    stmts = split_statements(path.read_text(encoding="utf-8"))
    if not stmts:
        print("[!] 无可执行语句")
        return 0
    failed = 0
    for i, stmt in enumerate(stmts, 1):
        head = " ".join(stmt.split())[:72]
        try:
            with engine.begin() as conn:
                from core.migrations import exec_ddl  # noqa: PLC0415

                exec_ddl(conn, stmt)
            print(f"[{i:>2}/{len(stmts)}] OK   {head}")
        except Exception as exc:  # noqa: BLE001 —— 逐条报错并继续统计
            failed += 1
            print(f"[{i:>2}/{len(stmts)}] FAIL {head}\n      {exc}")
    print(f"[{'✓' if failed == 0 else 'x'}] 完成：{len(stmts) - failed}/{len(stmts)} 成功")

    # 记账（仅编号脚本）：单条失败则不登记，脚本本身幂等可重跑
    if failed == 0 and path.parent.resolve() == SQL_DIR.resolve():
        from core.migrations import _ensure_ledger  # noqa: PLC0415 —— 仅此处需要

        with engine.begin() as conn:
            _ensure_ledger(conn)
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, checksum, duration_ms, applied_by) "
                    "VALUES (:v, :c, 0, 'manual:single') "
                    "ON CONFLICT (version) DO UPDATE SET checksum = EXCLUDED.checksum, "
                    "applied_at = now(), applied_by = EXCLUDED.applied_by"
                ),
                {"v": path.stem, "c": file_checksum(path)},
            )
        print(f"[i] 已登记账本：{path.stem}")
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    if not IS_POSTGRES:
        print("[x] 当前 DATABASE_BACKEND 不是 postgresql；SQLite 线请用 migrate.py")
        return 2

    engine = _engine()
    dry_run = "--dry-run" in argv

    if "--status" in argv:
        status = ledger_status(engine)
        print(f"脚本总数 {status['total_scripts']}｜已登记 {status['applied']}")
        if status["pending"]:
            print("待执行：")
            for v in status["pending"]:
                print(f"    - {v}")
        else:
            print("待执行：无")
        if status["checksum_drift"]:
            print("[!] checksum 漂移（已登记但文件被改，结构变更请新增脚本）：")
            for v in status["checksum_drift"]:
                print(f"    ! {v}")
            return 1
        return 0

    if "--all-pending" in argv or "--baseline" in argv:
        try:
            result = run_pending(
                engine,
                applied_by="push_update" if os.environ.get("DEPLOY_TS") else "manual",
                force_baseline="--baseline" in argv,
                dry_run=dry_run,
                reconcile_audited_drift="--reconcile-audited-drift" in argv,
            )
        except ChecksumMismatch as exc:
            print(str(exc))
            return 3
        _print_result(result, dry_run)
        return 0

    files = [a for a in argv if not a.startswith("--")]
    if not files:
        print("用法：python scripts/execute_core_sql.py <sql 文件> | --all-pending | --baseline | --status")
        return 2
    rc = 0
    for f in files:
        path = Path(f) if Path(f).is_absolute() else (BASE / f)
        if not path.is_file():
            print(f"[x] SQL 文件不存在：{path}")
            return 2
        rc = max(rc, _run_single_file(engine, path))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
