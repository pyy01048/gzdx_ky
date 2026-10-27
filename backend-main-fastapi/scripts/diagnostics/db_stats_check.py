# -*- coding: utf-8 -*-
"""P1-4 数据库统计信息体检（只读 + ANALYZE）。

背景：审计发现 `kaoyan` 库 110 张表里 **103 张从未 ANALYZE**，`n_live_tup=0`
——查询规划器只能靠默认页数估算，走错顺序扫描/嵌套循环。本脚本：

1. 打印统计现状（未分析表数、回滚率、GUC、最大表的 seq/idx 扫描）；
2. 带 ``--analyze`` 时对全库执行 ``ANALYZE``（只更新 pg_stat，不碰数据行）。

用法::

    python scripts/diagnostics/db_stats_check.py            # 只读体检
    python scripts/diagnostics/db_stats_check.py --analyze  # 体检 + ANALYZE
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402


def _rows(conn, sql: str):
    return list(conn.execute(text(sql)))


def report(conn) -> None:
    print("== 全库统计现状 ==")
    for row in _rows(
        conn,
        "select count(*) filter (where last_analyze is null and last_autoanalyze is null) as never_analyzed,"
        "       count(*) as total_tables,"
        "       coalesce(sum(n_live_tup),0)::bigint as live_rows"
        "  from pg_stat_user_tables",
    ):
        never, total, live = tuple(row)
        print(f"   从未分析表: {never}/{total}   行数统计合计: {live}")

    print("== 事务提交/回滚 ==")
    for row in _rows(
        conn,
        "select xact_commit, xact_rollback,"
        "       round(100.0 * xact_rollback / nullif(xact_commit + xact_rollback, 0), 2)"
        "  from pg_stat_database where datname = current_database()",
    ):
        commit, rollback, pct = tuple(row)
        print(f"   commit={commit}  rollback={rollback}  回滚占比={pct}%")

    print("== 关键 GUC ==")
    for key in ("shared_buffers", "work_mem", "maintenance_work_mem", "effective_cache_size"):
        try:
            print(f"   {key} = {_rows(conn, 'show ' + key)[0][0]}")
        except Exception as exc:  # pragma: no cover - 诊断输出
            print(f"   {key} = ? ({type(exc).__name__})")

    print("== 最大的 10 张表（含最后分析时间）==")
    for row in _rows(
        conn,
        "select relname, n_live_tup, coalesce(seq_scan,0), coalesce(idx_scan,0),"
        "       last_analyze, last_autoanalyze"
        "  from pg_stat_user_tables order by n_live_tup desc nulls last limit 10",
    ):
        relname, live, seqs, idxs, la, laa = tuple(row)
        stamp = la or laa or "NEVER"
        print(f"   {relname:32s} live={live:>8} seq={seqs:>8} idx={idxs:>8} last={stamp}")

    print("== 缺失索引线索：全表顺序扫描且行数 > 1000 ==")
    rows = _rows(
        conn,
        "select relname, n_live_tup, coalesce(seq_scan,0) as seqs, coalesce(idx_scan,0) as idxs"
        "  from pg_stat_user_tables"
        "  where coalesce(idx_scan,0) = 0 and coalesce(seq_scan,0) > 20 and n_live_tup > 1000"
        "  order by n_live_tup desc limit 15",
    )
    if not rows:
        print("   （无）")
    for relname, live, seqs, idxs in rows:
        print(f"   {relname:32s} live={live:>8} seq={seqs} idx={idxs}   <- 0 次索引命中")


def run_analyze(conn) -> None:
    t0 = time.time()
    conn.execute(text("ANALYZE"))
    conn.commit()
    print(f"ANALYZE 全库完成，耗时 {time.time() - t0:.1f}s（仅刷新统计，不动数据行）")
    print("== 分析后复查 ==")
    for row in _rows(
        conn,
        "select count(*) filter (where last_analyze is null and last_autoanalyze is null), count(*)"
        "  from pg_stat_user_tables",
    ):
        never, total = tuple(row)
        print(f"   仍未分析表: {never}/{total}")


def _db_snapshot() -> tuple:
    """(commit, rollback, activity_count) 快照，独立连接，避免干扰被测窗口。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        return tuple(
            db.execute(
                text(
                    "select xact_commit, xact_rollback,"
                    "       (select count(*) from pg_stat_activity)"
                    "  from pg_stat_database where datname = current_database()"
                )
            ).first()
        )
    finally:
        db.close()


def rollback_window(seconds: float) -> None:
    """空闲窗口内观察 commit/rollback 增量 —— 判断回滚是常态流量还是测试产物。

    审计看到 36% 回滚率，默认怀疑业务路径异常；但 pytest 的 fixture 每个用例
    都 ``session.rollback()``（``tests/conftest.py``），一次全量跑就产生上千回滚。
    空闲窗口 + 前后差分能把两者区分开。
    """
    from database import SessionLocal

    a = _db_snapshot()
    print(f"[t0 ] commit={a[0]} rollback={a[1]} conns={a[2]}")
    time.sleep(seconds)
    b = _db_snapshot()
    print(f"[t+{int(seconds)}s] commit={b[0]} rollback={b[1]} conns={b[2]}")
    print(f"   空闲增量: commit={b[0] - a[0]:+d}  rollback={b[1] - a[1]:+d}")

    db = SessionLocal()
    try:
        print("== 会话状态分布 ==")
        for row in db.execute(
            text(
                "select coalesce(state,'<none>'), count(*) from pg_stat_activity"
                "  where datname = current_database() group by 1 order by 2 desc"
            )
        ):
            print("   ", tuple(row))
        print("== 非空闲会话 ==")
        rows = db.execute(
            text(
                "select pid, state, left(coalesce(query, ''), 60), now() - state_change"
                "  from pg_stat_activity"
                "  where datname = current_database() and state <> 'idle' limit 10"
            )
        )
        found = False
        for row in rows:
            print("   ", tuple(row))
            found = True
        if not found:
            print("    （无）")
    finally:
        db.close()


def sample_queries(seconds: float = 8.0, interval: float = 0.15) -> None:
    """高频采样 ``pg_stat_activity``，找出空闲窗口里仍在跑的语句与连接来源。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        print("== 连接来源（application_name × state）==")
        for row in db.execute(
            text(
                "select coalesce(nullif(application_name, ''), '<none>') as app, coalesce(state, '<none>') as st, count(*)"
                "  from pg_stat_activity where datname = current_database()"
                " group by 1, 2 order by 3 desc"
            )
        ):
            print("   ", tuple(row))

        print(f"== 活跃语句采样（{seconds:.0f}s，间隔 {interval * 1000:.0f}ms）==")
        seen: dict = {}
        deadline = time.time() + seconds
        while time.time() < deadline:
            for row in db.execute(
                text(
                    "select coalesce(nullif(application_name, ''), '<none>') as app,"
                    "       backend_type,"
                    "       left(regexp_replace(coalesce(query, ''), '\\s+', ' ', 'g'), 90) as q"
                    "  from pg_stat_activity"
                    " where datname = current_database() and state = 'active'"
                    "   and pid <> pg_backend_pid()"
                )
            ):
                key = tuple(row)
                seen[key] = seen.get(key, 0) + 1
            time.sleep(interval)
        if not seen:
            print("    （窗口内无其他活跃语句）")
        for key, count in sorted(seen.items(), key=lambda kv: -kv[1])[:20]:
            print(f"    x{count:<5} app={key[0]:<16} type={key[1]:<22} {key[2]}")
    finally:
        db.close()


def activity_dump() -> None:
    """打印每条连接的来源与最近语句（找匿名连接归属）。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "select pid, coalesce(nullif(application_name, ''), '<none>') as app, state,"
                "       client_addr, client_port, backend_start, state_change,"
                "       left(regexp_replace(coalesce(query, ''), '\\s+', ' ', 'g'), 70) as last_query"
                "  from pg_stat_activity"
                " where datname = current_database()"
                " order by backend_start"
            )
        )
        for row in rows:
            print("   ", tuple(row))
    finally:
        db.close()


def lock_owner() -> None:
    """查调度单例锁 ``pg_try_advisory_lock`` 的持有者（应是当前在服进程）。"""
    from database import SessionLocal
    from services.scheduler import _SINGLETON_LOCK_KEY

    db = SessionLocal()
    try:
        print(f"锁 key = 0x{_SINGLETON_LOCK_KEY:X} ({_SINGLETON_LOCK_KEY})")
        rows = db.execute(
            text(
                "select l.pid, l.classid, l.objid, a.application_name, a.backend_type,"
                "       a.state, a.client_port, now() - a.backend_start as conn_age"
                "  from pg_locks l"
                "  join pg_stat_activity a on a.pid = l.pid"
                " where l.locktype = 'advisory' and l.granted"
                "   and (l.classid = :k or l.objid = :k)"
            ),
            {"k": _SINGLETON_LOCK_KEY},
        ).fetchall()
        if not rows:
            print("   无人持锁 —— 当前没有任何进程在跑定时任务（调度器已停摆）")
        for row in rows:
            print("   holder:", tuple(row))
    finally:
        db.close()


def statements_top(limit: int = 15) -> None:
    """pg_stat_statements 归因：谁在跑、谁在把事务变成回滚。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        print("== 调用次数最多的语句（含失败）==")
        for row in db.execute(
            text(
                "select calls, round(total_exec_time::numeric, 1) as total_ms,"
                "       round(mean_exec_time::numeric, 2) as mean_ms, rows,"
                "       left(regexp_replace(query, '\\s+', ' ', 'g'), 80) as q"
                "  from pg_stat_statements"
                " order by calls desc limit :n"
            ),
            {"n": limit},
        ):
            print("   ", tuple(row))
        print("== 失败语句（sqlerrcode 非空）==")
        # PG17 才有 sqlerrcode 列；16 及以下直接跳过，别让诊断脚本自己崩。
        has_err = db.execute(
            text(
                "select count(*) from information_schema.columns"
                "  where table_name = 'pg_stat_statements' and column_name = 'sqlerrcode'"
            )
        ).scalar()
        if not has_err:
            print("    （本版 PG 的 pg_stat_statements 无 sqlerrcode 列，跳过）")
            return
        rows = db.execute(
            text(
                "select calls, sqlerrcode, left(regexp_replace(query, '\\s+', ' ', 'g'), 80) as q"
                "  from pg_stat_statements where sqlerrcode is not null"
                " order by calls desc limit :n"
            ),
            {"n": limit},
        ).fetchall()
        if not rows:
            print("    （无）")
        for row in rows:
            print("    ", tuple(row))
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="kaoyan 库统计体检 / ANALYZE")
    ap.add_argument("--analyze", action="store_true", help="执行全库 ANALYZE")
    ap.add_argument(
        "--window",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="空闲窗口观察 commit/rollback 增量（不跑体检报告）",
    )
    ap.add_argument(
        "--sample",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="采样 pg_stat_activity，找出空闲期仍在执行的语句与连接来源",
    )
    ap.add_argument("--activity", action="store_true", help="打印每条连接的来源与最近语句")
    ap.add_argument("--lock", action="store_true", help="查调度单例锁 pg_try_advisory_lock 的持有者")
    ap.add_argument(
        "--statements",
        type=int,
        nargs="?",
        const=15,
        default=0,
        metavar="N",
        help="用 pg_stat_statements 归因：调用最多的语句 + 失败语句",
    )
    ap.add_argument(
        "--interval",
        type=float,
        default=0.15,
        metavar="SECONDS",
        help="采样间隔（配合 --sample；抓短事务要 0.02 级别）",
    )
    args = ap.parse_args()

    if args.lock:
        lock_owner()
        return 0

    if args.statements:
        statements_top(args.statements)
        return 0

    if args.activity:
        activity_dump()
        return 0

    if args.sample > 0:
        sample_queries(args.sample, args.interval)
        return 0

    if args.window > 0:
        rollback_window(args.window)
        return 0

    from database import SessionLocal

    db = SessionLocal()
    try:
        report(db)
        if args.analyze:
            run_analyze(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
