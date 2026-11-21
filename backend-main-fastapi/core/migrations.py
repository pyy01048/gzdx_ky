# -*- coding: utf-8 -*-
"""schema_migrations 迁移账本（完善方案 05-数据库与迁移管理 §3.1）。

设计要点（尊重项目"不用 Alembic"的既有决策，只补最小账本）：

* ``core/sql/*.sql`` 仍是唯一的结构变更载体；本模块只负责"该不该执行、执行过没有"。
* 每个脚本执行成功后写入一行 ``schema_migrations``（版本号 + SHA256 + 耗时 + 执行者）。
* 已登记脚本的 checksum 一旦与磁盘文件不符 → 立即中止：结构变更只能新增脚本，
  禁止改历史脚本（否则存量库与新库会悄悄分叉）。
* 存量库收编：账本为空但库里已有业务表时，默认走 **baseline**（只登记不执行），
  避免在生产库上重放 48 个历史脚本（其中含 DELETE/backfill）。
  全新空库则直接执行全部脚本。

对外入口（脚本 scripts/execute_core_sql.py 与启动生命周期共用）::

    from core.migrations import run_pending
    result = run_pending(engine, applied_by="startup")

    result.applied    # 本次真正执行的版本号列表
    result.baselined  # 本次仅登记（未执行）的版本号列表
    result.skipped    # 已登记且 checksum 一致的版本号列表
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text

SQL_DIR = Path(__file__).resolve().parent / "sql"

LEDGER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms INTEGER,
    applied_by  TEXT
)
"""

_VERSION_RE = re.compile(r"^(\d{3}[a-z]?_[A-Za-z0-9_\-]+)\.sql$")


@dataclass
class MigrationResult:
    applied: list[str] = field(default_factory=list)
    baselined: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    mode: str = "pending"  # pending | baseline | empty


class ChecksumMismatch(RuntimeError):
    """已登记脚本被修改——必须中止（结构变更请新增编号脚本）。"""


# --------------------------------------------------------------------------- #
# SQL 切分：正确处理单引号 / 双引号 / 行注释 / 块注释 / $$ dollar-quote
# --------------------------------------------------------------------------- #
def split_statements(sql: str) -> list[str]:
    """把多语句 SQL 文本切成单条语句，跳过纯注释与空白。

    旧实现直接按 ';' 切分，遇到 ``DO $$ ... $$`` / 函数体里的分号会切碎。
    这里做一次轻量词法扫描，只跟踪"是否会误切"的状态。
    """
    stmts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_single = in_double = in_line_comment = in_block_comment = False
    dollar_tag: str | None = None

    while i < n:
        ch = sql[i]
        two = sql[i : i + 2]

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                buf.append(ch)
            i += 1
            continue
        if in_block_comment:
            if two == "*/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue
        if in_single:
            buf.append(ch)
            if ch == "'" and sql[i + 1 : i + 2] == "'":  # 转义 ''
                buf.append("'")
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            buf.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue

        if two == "--":
            in_line_comment = True
            i += 2
            continue
        if two == "/*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
            continue
        if ch == "$":
            m = re.match(r"\$[A-Za-z_]*\$", sql[i:])
            if m:
                dollar_tag = m.group(0)
                buf.append(dollar_tag)
                i += len(dollar_tag)
                continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if _has_code(stmt):
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if _has_code(tail):
        stmts.append(tail)
    return stmts


def _has_code(stmt: str) -> bool:
    """去掉注释后是否还有实质内容。"""
    cleaned = re.sub(r"/\*.*?\*/", " ", stmt, flags=re.S)
    cleaned = re.sub(r"--[^\n]*", " ", cleaned)
    return bool(cleaned.strip())


# --------------------------------------------------------------------------- #
# 脚本发现 / checksum
# --------------------------------------------------------------------------- #
#: 历史编号与真实依赖顺序不一致的脚本 → 排序键（不改文件名，账本仍按原名记账）
#:
#: 094a 是后期从 093 拆出的"加列"脚本：必须排在 080/081 视图之前；
#: 093 建触发器/回填：必须排在 080/081 之后。纯数字排序会把 093 排在 094a 前，
#: 导致空库重建时 093 引用尚未建立的 mastery 列（2026-11-20 空库演练实测）。
#: 108 两个脚本：先补 user_id 列（scope_columns），再加约束/索引（data_isolation）。
ORDER_OVERRIDES: dict[str, str] = {
    "094a_kp_mastery_columns": "079a_kp_mastery_columns",
    "093_kp_mastery_compat": "081z_kp_mastery_compat",
    "108_user_scope_columns": "108a_user_scope_columns",
    "108_user_data_isolation": "108b_user_data_isolation",
}


def list_scripts(sql_dir: Path = SQL_DIR) -> list[Path]:
    """按真实依赖顺序返回脚本（只认 ``NNN_name.sql``，排除 000 账本自身）。"""
    files = []
    for p in sql_dir.glob("*.sql"):
        if p.stem == "000_schema_migrations":
            continue
        if _VERSION_RE.match(p.name):
            files.append(p)
    return sorted(files, key=lambda p: ORDER_OVERRIDES.get(p.stem, p.stem))


def file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_ledger(conn) -> None:
    conn.execute(text(LEDGER_TABLE_SQL))


def _load_ledger(conn) -> dict[str, str]:
    rows = conn.execute(text("SELECT version, checksum FROM schema_migrations"))
    return {r[0]: r[1] for r in rows}


def _db_has_business_tables(conn) -> bool:
    row = conn.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
            "AND table_name <> 'schema_migrations'"
        )
    ).scalar()
    return bool(row)


def exec_ddl(conn, stmt: str) -> None:
    """执行一条 DDL/DML 语句（PG）。

    不能直接用 ``text()`` / ``exec_driver_sql()``：

    * ``text()`` 会把 SQL 字面量里的 ``"offset_minutes":1440`` 误认成绑定参数；
    * psycopg 3.2.x 的客户端语句切分对**含中文的 dollar-quote 块**（``DO $$ … RAISE
      NOTICE '中文' … $$``）会抛 UnicodeDecodeError（实测 000_extensions_and_enums.sql）。

    因此把语句按 UTF-8 编码成 bytes 交给底层 driver cursor：psycopg 对 bytes 不再做
    客户端切分/解码，直接在服务端解析。SQLAlchemy 事务仍由外层 conn 管理。
    """
    raw_conn = getattr(getattr(conn, "connection", None), "driver_connection", None)
    if raw_conn is not None and hasattr(raw_conn, "cursor"):
        with raw_conn.cursor() as cur:
            cur.execute(stmt.encode("utf-8"))
        return
    conn.exec_driver_sql(stmt)


def _apply_script(engine, path: Path) -> None:
    """每个语句独立事务：单条失败不影响后续统计，但整体抛出。

    编号脚本必须幂等（IF NOT EXISTS / ON CONFLICT），因此逐条提交可安全重跑。
    """
    stmts = split_statements(path.read_text(encoding="utf-8"))
    for idx, stmt in enumerate(stmts, 1):
        try:
            with engine.begin() as conn:
                exec_ddl(conn, stmt)
        except Exception as exc:  # noqa: BLE001 —— 附文件名/序号后原样抛出
            head = " ".join(stmt.split())[:160]
            raise RuntimeError(f"[迁移失败] {path.name} 第 {idx}/{len(stmts)} 条：{head}\n{exc}") from exc


def run_pending(
    engine,
    sql_dir: Path | str = SQL_DIR,
    applied_by: str = "manual",
    *,
    baseline_if_no_ledger: bool = True,
    force_baseline: bool = False,
    dry_run: bool = False,
) -> MigrationResult:
    """执行/登记未入账的编号脚本。

    baseline_if_no_ledger=True 时：账本为空且库中已有业务表 → 只登记不执行（存量收编）。
    force_baseline=True → 无条件只登记。
    """
    sql_dir = Path(sql_dir)
    result = MigrationResult()
    scripts = list_scripts(sql_dir)

    with engine.begin() as conn:
        _ensure_ledger(conn)
        ledger = _load_ledger(conn)
        has_tables = _db_has_business_tables(conn)

    # 1) checksum 守卫（先全量校验，再动手）
    pending: list[Path] = []
    for path in scripts:
        ver = path.stem
        digest = file_checksum(path)
        if ver in ledger:
            if ledger[ver] != digest:
                raise ChecksumMismatch(
                    f"[中止] {ver} 已登记但文件内容被修改（checksum 不符）。\n"
                    f"  结构变更请新增编号脚本，禁止改历史脚本。\n"
                    f"  如确认只是空白/注释调整，可手工删除该行后重跑 --baseline。"
                )
            result.skipped.append(ver)
        else:
            pending.append(path)

    if not pending:
        return result

    # 2) 存量库 vs 空库
    do_baseline = force_baseline or (baseline_if_no_ledger and not ledger and has_tables)
    if do_baseline:
        result.mode = "baseline"
        if dry_run:
            result.baselined = [p.stem for p in pending]
            return result
        with engine.begin() as conn:
            for path in pending:
                conn.execute(
                    text(
                        "INSERT INTO schema_migrations (version, checksum, duration_ms, applied_by) "
                        "VALUES (:v, :c, 0, :by) ON CONFLICT (version) DO NOTHING"
                    ),
                    {"v": path.stem, "c": file_checksum(path), "by": f"{applied_by}:baseline"},
                )
                result.baselined.append(path.stem)
        return result

    # 3) 正常执行
    result.mode = "pending"
    if dry_run:
        result.applied = [p.stem for p in pending]
        return result
    for path in pending:
        t0 = time.monotonic()
        _apply_script(engine, path)
        duration_ms = int((time.monotonic() - t0) * 1000)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, checksum, duration_ms, applied_by) "
                    "VALUES (:v, :c, :d, :by) "
                    "ON CONFLICT (version) DO UPDATE SET checksum = EXCLUDED.checksum, "
                    "duration_ms = EXCLUDED.duration_ms, applied_at = now(), applied_by = EXCLUDED.applied_by"
                ),
                {"v": path.stem, "c": file_checksum(path), "d": duration_ms, "by": applied_by},
            )
        result.applied.append(path.stem)
    return result


def ledger_status(engine, sql_dir: Path | str = SQL_DIR) -> dict:
    """给 /api/health、diagnostics 用的只读状态。"""
    sql_dir = Path(sql_dir)
    scripts = {p.stem: file_checksum(p) for p in list_scripts(sql_dir)}
    with engine.begin() as conn:
        _ensure_ledger(conn)
        ledger = _load_ledger(conn)
    pending = sorted(v for v in scripts if v not in ledger)
    drifted = sorted(v for v, c in ledger.items() if v in scripts and scripts[v] != c)
    return {
        "total_scripts": len(scripts),
        "applied": len(ledger),
        "pending": pending,
        "checksum_drift": drifted,
    }
