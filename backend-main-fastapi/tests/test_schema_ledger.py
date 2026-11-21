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

import uuid

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
