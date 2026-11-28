# -*- coding: utf-8 -*-
"""schema_migrations 迁移账本（完善方案 05-数据库与迁移管理 §3.1）。

设计要点（尊重项目"不用 Alembic"的既有决策，只补最小账本）：

* ``core/sql/*.sql`` 仍是唯一的结构变更载体；本模块只负责"该不该执行、执行过没有"。
* 每个脚本执行成功后写入一行 ``schema_migrations``（版本号 + SHA256 + 耗时 + 执行者）。
* 已登记脚本的 checksum 一旦与磁盘文件不符 → 立即中止：结构变更只能新增脚本，
  禁止改历史脚本（否则存量库与新库会悄悄分叉）。
* 存量库收编：账本为空但库里已有业务表时，默认走 **baseline**（只登记不执行），
  避免在生产库上重放 48 个历史脚本（其中含 DELETE/backfill）。
  204 及以后的增量结构迁移仍必须执行，否则个人题库与组卷修复会被空账本跳过。
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

from core.migration_policy import is_automatic_schema_script

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

# 空账本存量库不得把上线后新增的结构迁移标成已执行。
BASELINE_FORWARD_FROM = 204

MIGRATION_PREFLIGHT = {
    "206_quiz_persistent_sessions": """
        SELECT count(*) FROM (
            SELECT session_id, question_id FROM quiz_attempts
            WHERE session_id IS NOT NULL AND question_id IS NOT NULL
            GROUP BY session_id, question_id HAVING count(*) > 1
        ) duplicates
    """,
    "208_quiz_practice_modes": """
        SELECT count(*) FROM quiz_sessions
        WHERE mode IS NOT NULL
          AND mode NOT IN ('chapter_practice', 'smart_paper', 'free_practice', 'practice', 'memorize')
    """,
}

CLIENT_ATTEMPT_PREFLIGHT = """
    SELECT count(*) FROM (
        SELECT user_id, client_attempt_id FROM quiz_attempts
        WHERE user_id IS NOT NULL AND client_attempt_id IS NOT NULL
        GROUP BY user_id, client_attempt_id HAVING count(*) > 1
    ) duplicates
"""

# 2026-11-27 逐项核对过的历史漂移。只有账本旧值、磁盘当前值和数据库后置条件
# 三者同时匹配才允许校正；120_auth_sessions 必须先由 209 完成实际列类型修复。
AUDITED_CHECKSUM_DRIFT: dict[str, dict[str, str]] = {
    "103_backfill_review_schedules": {
        "ledger_checksum": "347afbea5fc32b846b3d090b63d85d104943eca193101e85c0baa92f2ee03ce3",
        "file_checksum": "e1be97606a64c7285843a2d010911b0440c8add83e3dfe6fa047975ab2807660",
        "verify_sql": """
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'review_schedules'::regclass
                   AND conname = 'uq_review_schedule'
                   AND pg_get_constraintdef(oid) = 'UNIQUE (user_id, item_type, item_id)'
            ) AND NOT EXISTS (
                SELECT 1 FROM review_schedules WHERE item_type IN ('knowledge', 'error')
            )
        """,
    },
    "104_users": {
        "ledger_checksum": "fb377288bd9c361d1f39a588fe7265b45a49775daa89c3e32f3b862b903702de",
        "file_checksum": "2c16982eac2a3d99fb2f9239c5241169b91fa53917d048c4a842f522ece1539c",
        "verify_sql": """
            SELECT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'users'::regclass
                   AND conname = 'ck_users_role'
                   AND pg_get_constraintdef(oid) LIKE '%admin%'
                   AND pg_get_constraintdef(oid) LIKE '%doc_admin%'
                   AND pg_get_constraintdef(oid) LIKE '%user%'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = current_schema() AND table_name = 'users'
                   AND column_name IN ('last_login_at', 'created_at', 'updated_at')
                   AND data_type = 'timestamp without time zone'
            )
        """,
    },
    "118_users_query_indexes": {
        "ledger_checksum": "43b8b8f28933d17a7de2f4cd14e7ec50ac30ba4a79c9cdf6a3df48141ba20de6",
        "file_checksum": "eda439cff8026b8e13f116b5c26aed974c09f955ff99abffd1a2ee0eb26c610a",
        "verify_sql": """
            SELECT EXISTS (
                SELECT 1 FROM pg_index
                 WHERE indexrelid = to_regclass('ux_users_username_lower')
                   AND indisunique
                   AND pg_get_indexdef(indexrelid) LIKE '%lower(%username%'
            ) AND EXISTS (
                SELECT 1 FROM pg_index
                 WHERE indexrelid = to_regclass('ix_users_created_at')
                   AND pg_get_indexdef(indexrelid) LIKE '%(created_at)%'
            )
        """,
    },
    "119_school_engineering_eval": {
        "ledger_checksum": "01799bd111ecf5b6164e742e1e1ae8139ef37c7bd2e26d1da907f3cc7d5a7b5d",
        "file_checksum": "25575868870951f438b4f24b6a55c4e7f3c3b5ed9ffe44a51565acf2ac481bdf",
        "verify_sql": """
            SELECT to_regclass('ky_discipline') IS NOT NULL
               AND to_regclass('ky_school') IS NOT NULL
               AND to_regclass('ky_school_discipline_eval') IS NOT NULL
               AND to_regclass('ky_school_double_first') IS NOT NULL
               AND to_regclass('v_school_engineering_card') IS NOT NULL
               AND to_regclass('v_discipline_rank') IS NOT NULL
        """,
    },
    "120_auth_sessions": {
        "ledger_checksum": "8b32c5964d38fdf49569755bef75d6b2997fdf1c9d8698fb64ee2011c1ec9bf8",
        "file_checksum": "2974df85375b626ef1755bde2e8c32de2ab98eff0157667a38925bce476a0138",
        "verify_sql": """
            SELECT (
                SELECT count(*) = 4 FROM information_schema.columns
                 WHERE table_schema = current_schema() AND table_name = 'auth_sessions'
                   AND column_name IN ('created_at', 'last_used_at', 'expires_at', 'revoked_at')
                   AND data_type = 'timestamp with time zone'
            ) AND (
                SELECT count(*) = 2 FROM information_schema.columns
                 WHERE table_schema = current_schema() AND table_name = 'auth_sessions'
                   AND column_name IN ('created_at', 'last_used_at')
                   AND is_nullable = 'NO' AND column_default = 'now()'
            ) AND NOT EXISTS (
                SELECT 1 FROM auth_sessions WHERE created_at IS NULL OR last_used_at IS NULL
            )
        """,
    },
    "120_school_branding": {
        "ledger_checksum": "0d7cae86792124da6b01352845099ca53fcded98b5baae17910fdb63b900b0be",
        "file_checksum": "81cc235289dc6f63b62172ed75f60e684d8653e4e13eb318832a27304408a9d8",
        "verify_sql": """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = current_schema() AND table_name = 'kaoyan_schools'
                   AND column_name = 'cover_url' AND data_type = 'character varying'
                   AND character_maximum_length = 500
            )
        """,
    },
    "125_gamification_coins": {
        "ledger_checksum": "2a8863c49f35cba58e507ada062e20765de66ad226f8dc30b3916d09ad2488b1",
        "file_checksum": "38e63408cd27abaedcdbef45b21ecffe7b989e6237638b0cf8e04954fcc0261d",
        "verify_sql": """
            SELECT to_regclass('coin_accounts') IS NOT NULL
               AND to_regclass('coin_ledger') IS NOT NULL
               AND to_regclass('checkin_logs') IS NOT NULL
               AND to_regclass('gamification_rules') IS NOT NULL
               AND to_regclass('gamification_settings') IS NOT NULL
               AND to_regclass('reward_items') IS NOT NULL
               AND to_regclass('redemptions') IS NOT NULL
               AND to_regclass('user_profiles') IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'user_profiles'
                      AND column_name = 'prefs' AND data_type = 'jsonb'
               )
        """,
    },
}


@dataclass
class MigrationResult:
    applied: list[str] = field(default_factory=list)
    baselined: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    reconciled: list[str] = field(default_factory=list)
    manual_required: list[str] = field(default_factory=list)
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


def _is_audited_drift(version: str, ledger_checksum: str, disk_checksum: str) -> bool:
    expected = AUDITED_CHECKSUM_DRIFT.get(version)
    return bool(
        expected and expected["ledger_checksum"] == ledger_checksum and expected["file_checksum"] == disk_checksum
    )


def reconcile_known_drift(engine, applied_by: str = "manual", sql_dir: Path | str = SQL_DIR) -> list[str]:
    """核对数据库后置条件后，校正白名单内已审计的历史 checksum。"""
    sql_dir = Path(sql_dir)
    reconciled: list[str] = []
    with engine.begin() as conn:
        _ensure_ledger(conn)
        ledger = _load_ledger(conn)
        for version, expected in AUDITED_CHECKSUM_DRIFT.items():
            if version not in ledger:
                continue
            path = sql_dir / f"{version}.sql"
            digest = file_checksum(path)
            if digest != expected["file_checksum"]:
                raise ChecksumMismatch(f"[中止] 已审计脚本 {version} 的磁盘内容已再次变化。")
            if ledger[version] == digest:
                continue
            if ledger[version] != expected["ledger_checksum"]:
                raise ChecksumMismatch(f"[中止] {version} 的账本 checksum 不在本次审计范围内。")
            if conn.execute(text(expected["verify_sql"])).scalar() is not True:
                raise RuntimeError(f"[中止] {version} 账本校正后校验失败：数据库后置条件不满足。")
            conn.execute(
                text(
                    "UPDATE schema_migrations SET checksum = :checksum, "
                    "applied_by = COALESCE(applied_by, '') || ';reconciled:' || :by "
                    "WHERE version = :version AND checksum = :old_checksum"
                ),
                {
                    "checksum": digest,
                    "by": applied_by,
                    "version": version,
                    "old_checksum": expected["ledger_checksum"],
                },
            )
            reconciled.append(version)
    return reconciled


def _forward_migration(path: Path) -> bool:
    return is_automatic_schema_script(path) and int(path.stem[:3]) >= BASELINE_FORWARD_FROM


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
    stmts = [
        stmt
        for stmt in split_statements(path.read_text(encoding="utf-8"))
        if stmt.strip().rstrip(";").strip().upper() not in {"BEGIN", "COMMIT", "START TRANSACTION"}
    ]
    try:
        with engine.begin() as conn:
            preflight = MIGRATION_PREFLIGHT.get(path.stem)
            violations = int(conn.execute(text(preflight)).scalar_one() or 0) if preflight else 0
            if path.stem == "206_quiz_persistent_sessions":
                has_client_attempt_id = conn.execute(
                    text("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'quiz_attempts'
                          AND column_name = 'client_attempt_id'
                    )
                """)
                ).scalar_one()
                if has_client_attempt_id:
                    violations += int(conn.execute(text(CLIENT_ATTEMPT_PREFLIGHT)).scalar_one() or 0)
            if violations:
                raise RuntimeError(f"[迁移预检失败] {path.name} 存在重复会话答题或不支持的会话模式。")
            for idx, stmt in enumerate(stmts, 1):
                try:
                    exec_ddl(conn, stmt)
                except Exception as exc:  # noqa: BLE001
                    head = " ".join(stmt.split())[:160]
                    raise RuntimeError(f"[迁移失败] {path.name} 第 {idx}/{len(stmts)} 条：{head}\n{exc}") from exc
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"[迁移失败] {path.name} 事务已回滚。\n{exc}") from exc


def run_pending(
    engine,
    sql_dir: Path | str = SQL_DIR,
    applied_by: str = "manual",
    *,
    baseline_if_no_ledger: bool = True,
    force_baseline: bool = False,
    dry_run: bool = False,
    reconcile_audited_drift: bool = False,
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
    drifted: list[str] = []
    for path in scripts:
        ver = path.stem
        digest = file_checksum(path)
        if ver in ledger:
            if ledger[ver] != digest:
                if reconcile_audited_drift and _is_audited_drift(ver, ledger[ver], digest):
                    drifted.append(ver)
                    continue
                raise ChecksumMismatch(
                    f"[中止] {ver} 已登记但文件内容被修改（checksum 不符）。\n"
                    f"  结构变更请新增编号脚本，禁止改历史脚本。\n"
                    f"  已审计漂移必须显式启用 reconcile_audited_drift，并核对数据库后置条件。"
                )
            result.skipped.append(ver)
        else:
            pending.append(path)

    result.manual_required = [path.stem for path in pending if not is_automatic_schema_script(path)]
    pending = [path for path in pending if is_automatic_schema_script(path)]
    if not pending and not drifted:
        return result

    # 2) 存量库 vs 空库
    do_baseline = force_baseline or (baseline_if_no_ledger and not ledger and has_tables)
    if do_baseline:
        result.mode = "baseline"
        forward = [path for path in pending if _forward_migration(path)]
        pending = [path for path in pending if not _forward_migration(path)]
        if dry_run:
            result.baselined = [p.stem for p in pending]
            result.applied = [p.stem for p in forward]
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
        if not forward:
            if drifted:
                result.reconciled = reconcile_known_drift(engine, applied_by, sql_dir)
            return result
        pending = forward

    # 3) 正常执行（baseline 路径只执行 204 及以后的增量结构）
    if dry_run:
        result.applied = [p.stem for p in pending]
        result.reconciled = drifted
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
    if drifted:
        result.reconciled = reconcile_known_drift(engine, applied_by, sql_dir)
    return result


def ledger_status(engine, sql_dir: Path | str = SQL_DIR) -> dict:
    """给 /api/health、diagnostics 用的只读状态。"""
    sql_dir = Path(sql_dir)
    scripts = {p.stem: file_checksum(p) for p in list_scripts(sql_dir) if is_automatic_schema_script(p)}
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
