# -*- coding: utf-8 -*-
"""迁移账本守卫测试（完善方案 05 §3.1 / 验收清单）。

覆盖：
1. SQL 切分器：dollar-quote / 引号 / 注释内的分号不会被切碎
2. 脚本发现：只看 NNN_name.sql，排除 000 账本自身
3. checksum 守卫：已登记脚本被修改必须中止
4. 幂等：同一目录跑两遍，第二遍 0 执行
5. 空库全量执行 + ledger_status 待执行清零

测试库隔离由 conftest 保证（kaoyan_test）；本文件额外使用独立 schema
``t_schema_ledger``，避免污染测试库的 public schema（那里是其余用例的舞台）。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
from core.migrations import (
    ChecksumMismatch,
    ledger_status,
    list_scripts,
    run_pending,
    split_statements,
)
from sqlalchemy import create_engine, text


# --------------------------------------------------------------------------- #
# 纯函数：不需要数据库
# --------------------------------------------------------------------------- #
def test_split_statements_handles_dollar_quote():
    sql = """
    CREATE FUNCTION f() RETURNS void AS $$
    BEGIN
        PERFORM 1;  -- 函数体内的分号不能切
        PERFORM 2;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TABLE demo (id int);
    """
    stmts = split_statements(sql)
    assert len(stmts) == 2
    assert stmts[0].lstrip().startswith("CREATE FUNCTION")
    assert stmts[1].lstrip().startswith("CREATE TABLE demo")


def test_split_statements_ignores_quoted_and_comment_semicolons():
    sql = """
    -- 注释里的分号; 不切
    /* 块注释; 也不切 */
    INSERT INTO t (v) VALUES ('a;b');
    SELECT "col;name" FROM t;
    """
    stmts = split_statements(sql)
    assert len(stmts) == 2
    assert "a;b" in stmts[0]
    assert '"col;name"' in stmts[1]


def test_split_statements_skips_comment_only():
    assert split_statements("-- 只有注释\n/* 还是注释 */\n") == []


def test_list_scripts_excludes_ledger_and_sorts():
    scripts = list_scripts()
    stems = [p.stem for p in scripts]
    assert "000_schema_migrations" not in stems
    assert all(s[0].isdigit() for s in stems)
    # 编号脚本全部收录（无重复/无遗漏）
    assert len(stems) == len(set(stems))
    # 已知依赖顺序覆盖：094a 加列在 080 视图之前，093 触发器回填在 081 之后
    idx = {s: i for i, s in enumerate(stems)}
    assert idx["094a_kp_mastery_columns"] < idx["080_views_and_gates"]
    assert idx["093_kp_mastery_compat"] > idx["081_gates"]
    assert idx["108_user_scope_columns"] < idx["108_user_data_isolation"]


# --------------------------------------------------------------------------- #
# 数据库集成：独立 schema
# --------------------------------------------------------------------------- #
@pytest.fixture()
def scratch_engine():
    """在测试库里开一个独立 schema，用完即删。"""
    from core.db_session import build_database_url

    schema = f"t_ledger_{uuid.uuid4().hex[:8]}"
    engine = create_engine(
        build_database_url(),
        connect_args={"options": f"-csearch_path={schema}"},
    )
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as exc:  # noqa: BLE001 —— 无 PG 环境直接跳过
        pytest.skip(f"PostgreSQL 不可用：{exc}")
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


@pytest.fixture()
def sql_dir(tmp_path):
    d = tmp_path / "sql"
    d.mkdir()
    (d / "001_users.sql").write_text("CREATE TABLE users (id serial PRIMARY KEY, name text);", encoding="utf-8")
    (d / "002_posts.sql").write_text(
        "CREATE TABLE posts (id serial PRIMARY KEY, user_id int REFERENCES users(id));",
        encoding="utf-8",
    )
    return d


def test_schema_and_initializer_exclude_manual_data_scripts():
    from scripts.init_db import extra_shards

    backend = Path(__file__).resolve().parents[1]
    assert "212_admission_details_anonymize.sql" not in (backend / "core" / "pg_schema.sql").read_text(encoding="utf-8")
    shards = extra_shards()
    assert not any(name.startswith(("212_", "213_", "160_", "203_")) for name in shards)


def test_manual_data_scripts_never_execute_automatically(scratch_engine, tmp_path):
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "212_admission_details_anonymize.sql").write_text(
        "CREATE TABLE must_not_exist (id int);", encoding="utf-8"
    )
    result = run_pending(scratch_engine, sql_dir, applied_by="pytest")
    assert result.applied == []
    assert result.manual_required == ["212_admission_details_anonymize"]
    with scratch_engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('must_not_exist')")).scalar_one() is None
    assert ledger_status(scratch_engine, sql_dir)["pending"] == []


def test_script_failure_rolls_back_all_its_statements(scratch_engine, tmp_path):
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "001_atomic.sql").write_text(
        "CREATE TABLE atomic_first (id int); INSERT INTO missing_table VALUES (1);", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="事务已回滚|第 2/2 条"):
        run_pending(scratch_engine, sql_dir, applied_by="pytest")
    with scratch_engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('atomic_first')")).scalar_one() is None


def test_run_pending_is_idempotent(scratch_engine, sql_dir):
    first = run_pending(scratch_engine, sql_dir, applied_by="pytest")
    assert first.mode == "pending"
    assert first.applied == ["001_users", "002_posts"]

    second = run_pending(scratch_engine, sql_dir, applied_by="pytest")
    assert second.applied == []
    assert sorted(second.skipped) == ["001_users", "002_posts"]

    status = ledger_status(scratch_engine, sql_dir)
    assert status["pending"] == []
    assert status["checksum_drift"] == []


def test_checksum_mismatch_blocks(scratch_engine, sql_dir):
    run_pending(scratch_engine, sql_dir, applied_by="pytest")
    (sql_dir / "001_users.sql").write_text(
        "CREATE TABLE users (id serial PRIMARY KEY, name text, email text);", encoding="utf-8"
    )
    with pytest.raises(ChecksumMismatch):
        run_pending(scratch_engine, sql_dir, applied_by="pytest")


def test_audited_drift_reconciliation_requires_postcondition(scratch_engine, sql_dir, monkeypatch):
    import core.migrations as migrations

    run_pending(scratch_engine, sql_dir, applied_by="pytest")
    old_checksum = migrations.file_checksum(sql_dir / "001_users.sql")
    (sql_dir / "001_users.sql").write_text(
        "CREATE TABLE users (id serial PRIMARY KEY, name text, email text);", encoding="utf-8"
    )
    new_checksum = migrations.file_checksum(sql_dir / "001_users.sql")
    monkeypatch.setitem(
        migrations.AUDITED_CHECKSUM_DRIFT,
        "001_users",
        {
            "ledger_checksum": old_checksum,
            "file_checksum": new_checksum,
            "verify_sql": "SELECT EXISTS (SELECT 1 FROM users WHERE name = 'ready')",
        },
    )

    with scratch_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (name) VALUES ('ready')"))
    with pytest.raises(ChecksumMismatch):
        run_pending(scratch_engine, sql_dir, applied_by="pytest")

    result = run_pending(
        scratch_engine,
        sql_dir,
        applied_by="pytest",
        reconcile_audited_drift=True,
    )
    assert result.reconciled == ["001_users"]
    assert ledger_status(scratch_engine, sql_dir)["checksum_drift"] == []


def test_audited_drift_reconciliation_fails_closed_when_postcondition_is_false(scratch_engine, sql_dir, monkeypatch):
    import core.migrations as migrations

    run_pending(scratch_engine, sql_dir, applied_by="pytest")
    old_checksum = migrations.file_checksum(sql_dir / "001_users.sql")
    (sql_dir / "001_users.sql").write_text(
        "CREATE TABLE users (id serial PRIMARY KEY, name text, email text);", encoding="utf-8"
    )
    new_checksum = migrations.file_checksum(sql_dir / "001_users.sql")
    monkeypatch.setitem(
        migrations.AUDITED_CHECKSUM_DRIFT,
        "001_users",
        {
            "ledger_checksum": old_checksum,
            "file_checksum": new_checksum,
            "verify_sql": "SELECT EXISTS (SELECT 1 FROM users WHERE name = 'missing')",
        },
    )

    with pytest.raises(RuntimeError, match="账本校正后校验失败"):
        run_pending(
            scratch_engine,
            sql_dir,
            applied_by="pytest",
            reconcile_audited_drift=True,
        )
    with scratch_engine.connect() as conn:
        assert (
            conn.execute(text("SELECT checksum FROM schema_migrations WHERE version = '001_users'")).scalar_one()
            == old_checksum
        )


def test_baseline_mode_records_without_executing(scratch_engine, sql_dir):
    # 先建一张"业务表"，模拟存量库 → run_pending 应自动 baseline 而非执行
    with scratch_engine.begin() as conn:
        conn.execute(text("CREATE TABLE legacy_table (id int)"))
    result = run_pending(scratch_engine, sql_dir, applied_by="pytest")
    assert result.mode == "baseline"
    assert sorted(result.baselined) == ["001_users", "002_posts"]

    # baseline 只登记：目标表不应被创建
    with scratch_engine.connect() as conn:
        rows = (
            conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"))
            .scalars()
            .all()
        )
    assert "users" not in rows and "posts" not in rows
    assert "legacy_table" in rows


def test_new_script_runs_on_baselined_db(scratch_engine, sql_dir):
    with scratch_engine.begin() as conn:
        conn.execute(text("CREATE TABLE legacy_table (id int)"))
    run_pending(scratch_engine, sql_dir, applied_by="pytest")  # baseline

    (sql_dir / "003_new.sql").write_text("CREATE TABLE brand_new (id int);", encoding="utf-8")
    result = run_pending(scratch_engine, sql_dir, applied_by="pytest")
    assert result.mode == "pending"
    assert result.applied == ["003_new"]


def test_empty_ledger_baseline_executes_personal_bank_migrations(scratch_engine, tmp_path):
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    for name in ("204_personal_question_bank.sql", "205_exam_question_source_text.sql"):
        shutil.copyfile(Path(__file__).resolve().parents[1] / "core" / "sql" / name, sql_dir / name)

    with scratch_engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id BIGSERIAL PRIMARY KEY)"))
        conn.execute(
            text("""
            CREATE TABLE quiz_questions (
                id BIGSERIAL PRIMARY KEY,
                is_available BOOLEAN,
                is_junk BOOLEAN
            )
        """)
        )
        conn.execute(text("CREATE TYPE source_kind AS ENUM ('bank', 'exam')"))
        conn.execute(
            text("""
            CREATE TABLE exam_sessions (
                id BIGSERIAL PRIMARY KEY,
                question_source source_kind NOT NULL DEFAULT 'bank'::source_kind
            )
        """)
        )
        conn.execute(
            text("""
            CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
            BEGIN NEW.updated_at = now(); RETURN NEW; END;
            $$ LANGUAGE plpgsql
        """)
        )

    preview = run_pending(scratch_engine, sql_dir, applied_by="pytest", dry_run=True)
    assert preview.mode == "baseline"
    assert preview.applied == ["204_personal_question_bank", "205_exam_question_source_text"]

    result = run_pending(scratch_engine, sql_dir, applied_by="pytest")
    assert result.mode == "baseline"
    assert result.applied == ["204_personal_question_bank", "205_exam_question_source_text"]
    assert result.baselined == []

    with scratch_engine.connect() as conn:
        tables = set(
            conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
            ).scalars()
        )
        assert {"quiz_question_sets", "quiz_question_set_items", "quiz_question_states"} <= tables
        assert conn.execute(text("SELECT owner_user_id FROM quiz_questions LIMIT 0")).fetchall() == []
        data_type = conn.execute(
            text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'exam_sessions' AND column_name = 'question_source'
        """)
        ).scalar_one()
        assert data_type == "character varying"

    second = run_pending(scratch_engine, sql_dir, applied_by="pytest")
    assert second.applied == []
    assert second.skipped == ["204_personal_question_bank", "205_exam_question_source_text"]


def test_preflight_206_handles_schema_before_client_attempt_column(scratch_engine, tmp_path):
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "206_quiz_persistent_sessions.sql").write_text(
        "CREATE TABLE preflight_marker (id int);", encoding="utf-8"
    )
    with scratch_engine.begin() as conn:
        conn.execute(text("CREATE TABLE quiz_attempts (session_id bigint, question_id int)"))

    result = run_pending(scratch_engine, sql_dir, applied_by="pytest")
    assert result.applied == ["206_quiz_persistent_sessions"]
    with scratch_engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('preflight_marker')")).scalar_one() is not None


def test_preflight_206_blocks_existing_duplicate_client_attempts(scratch_engine, tmp_path):
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "206_quiz_persistent_sessions.sql").write_text("CREATE TABLE must_not_exist (id int);", encoding="utf-8")
    with scratch_engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE quiz_attempts (
                session_id bigint, question_id int,
                user_id bigint, client_attempt_id varchar(100)
            )
        """)
        )
        conn.execute(
            text("""
            INSERT INTO quiz_attempts VALUES
            (1, 10, 1, 'same-attempt'), (2, 20, 1, 'same-attempt')
        """)
        )

    with pytest.raises(RuntimeError, match="迁移预检失败"):
        run_pending(scratch_engine, sql_dir, applied_by="pytest")
    with scratch_engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('must_not_exist')")).scalar_one() is None


def test_preflight_208_blocks_unsupported_modes(scratch_engine, tmp_path):
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "208_quiz_practice_modes.sql").write_text("CREATE TABLE must_not_exist (id int);", encoding="utf-8")
    with scratch_engine.begin() as conn:
        conn.execute(text("CREATE TABLE quiz_sessions (mode varchar(50))"))
        conn.execute(text("INSERT INTO quiz_sessions VALUES ('unsupported')"))

    with pytest.raises(RuntimeError, match="迁移预检失败"):
        run_pending(scratch_engine, sql_dir, applied_by="pytest")
    with scratch_engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('must_not_exist')")).scalar_one() is None


def test_school_official_url_guard_cleans_only_audited_values(scratch_engine):
    from core.migrations import _apply_script

    script = Path(__file__).resolve().parents[1] / "core" / "sql" / "213_school_official_url_guard.sql"
    with scratch_engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE kaoyan_schools (
                id bigint PRIMARY KEY,
                official_url varchar(500),
                deleted_at timestamptz,
                updated_at timestamptz
            )
        """)
        )
        conn.execute(
            text("""
            INSERT INTO kaoyan_schools (id, official_url) VALUES
            (1, 'http://www.***'),
            (2, 'https://yz.chsi.com.cn/sch/schoolInfo--schId-367887.dhtml'),
            (705, 'https://www.gznc.edu.cn/'),
            (897, 'https://www.hljut.edu.cn/'),
            (999, 'https://www.example.edu.cn/')
        """)
        )

    _apply_script(scratch_engine, script)
    _apply_script(scratch_engine, script)
    with scratch_engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, official_url FROM kaoyan_schools")).all())
        assert rows[1] is None and rows[2] is None
        assert rows[705] is None and rows[897] is None
        assert rows[999] == "https://www.example.edu.cn/"
    with pytest.raises(Exception, match="ck_kaoyan_schools_official_url"):
        with scratch_engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO kaoyan_schools (id, official_url)
                VALUES (1000, 'https://yz.chsi.com.cn/sch/schoolInfo--schId-1.dhtml')
            """)
            )


def test_apply_script_owns_transaction_despite_legacy_begin_commit(scratch_engine, tmp_path):
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "001_legacy_tx.sql").write_text(
        "BEGIN; CREATE TABLE first_table (id int); COMMIT; "
        "CREATE TABLE second_table (id int); INSERT INTO missing_table VALUES (1);",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="第 3/3 条"):
        run_pending(scratch_engine, sql_dir, applied_by="pytest")
    with scratch_engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('first_table')")).scalar_one() is None
        assert conn.execute(text("SELECT to_regclass('second_table')")).scalar_one() is None
