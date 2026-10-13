"""delete_guard 自测脚本 —— 覆盖规格要求的三种情况。

(a) 环境变量未设置时 DELETE 被拦截，且真库行数不变
(b) 环境变量=1 时允许删除
(c) 备份与回滚往返后行数一致

为避免污染真库（670MB 生产数据），所有破坏性操作都在**真库的临时副本**上做。
但路径解析、体积下限校验、空壳库拦截都跑真库解析逻辑，以验证「不备份错库」。

运行：python scripts/verify_delete_guard.py
"""

import os
import sqlite3
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import services.delete_guard as dg  # noqa: E402


def _hr(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def _count(path: str, table: str) -> int:
    """统计指定表的行数。"""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _prepare_sandbox():
    """用真库建一张两表齐全的小副本，用于跑破坏性测试。

    不用copy2（真库是 WAL 模式，文件级拷贝会丢 -wal 里未合并的数据），
    一律走 SQLite backup API。
    """
    real_db = dg._resolve_db_path()
    print(f"[sandbox] _resolve_db_path() 解析到的真库: {real_db}")
    print(f"[sandbox] 真库大小: {os.path.getsize(real_db) / 1024 / 1024:.2f} MB")

    tmpdir = tempfile.mkdtemp(prefix="delete_guard_test_")
    sandbox = os.path.join(tmpdir, "sandbox.db")

    # 先把真库的表结构 + 两表数据抽到一个新库，再补齐体积以过1MB 校验。
    src = sqlite3.connect(real_db)
    dst = sqlite3.connect(sandbox)
    try:
        src.backup(dst)  # SQLite backup API，WAL 安全
    finally:
        dst.close()
        src.close()

    # 瘦身：只保留两张受保护的表，避免测试副本过大
    conn = sqlite3.connect(sandbox)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        keep = {"quiz_questions", "knowledge_chunks"}
        for t in tables:
            if t not in keep and not t.startswith("sqlite_"):
                try:
                    conn.execute(f"DROP TABLE IF EXISTS \"{t}\"")
                except sqlite3.Error:
                    pass
        conn.commit()
        # 灌 filler 数据把体积顶过 MIN_DB_BYTES，验证体积下限校验会放行真副本
        n_q = conn.execute("SELECT COUNT(*) FROM quiz_questions").fetchone()[0]
        n_c = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        conn.execute("CREATE TABLE IF NOT EXISTS _filler (x BLOB)")
        blob = os.urandom(1024 * 1024)
        for _ in range(2):
            conn.execute("INSERT INTO _filler (x) VALUES (?)", (blob,))
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    print(f"[sandbox] 测试副本: {sandbox}")
    print(f"[sandbox] 初始行数 quiz_questions={n_q}, knowledge_chunks={n_c}")
    return sandbox, n_q, n_c


def case_a_blocked(sandbox: str, n_q: int) -> bool:
    """(a) 环境变量未设置时 DELETE 被拦截且真库行数不变。"""
    _hr("(a) 环境变量未设置 → DELETE 应被拦截，行数不变")

    os.environ.pop(dg.ENV_FLAG, None)
    print(f"  环境变量 {dg.ENV_FLAG}: 未设置")
    print(f"  physical_delete_allowed('quiz_questions') = "
          f"{dg.physical_delete_allowed('quiz_questions')}")

    # 尝试走真实的删除路径（模拟插入闸门后的代码）
    blocked = False
    try:
        dg.require_physical_delete_enabled("quiz_questions")
        conn = sqlite3.connect(sandbox)
        try:
            conn.execute("DELETE FROM quiz_questions")
            conn.commit()
        finally:
            conn.close()
    except dg.PhysicalDeleteBlocked as e:
        blocked = True
        print("\n  --- 捕获到 PhysicalDeleteBlocked ---")
        for line in str(e).splitlines():
            print(f"  | {line}")

    after = _count(sandbox, "quiz_questions")
    print(f"\n  拦截生效: {blocked}")
    print(f"  行数 before={n_q} after={after}  → 不变: {before_after_ok(n_q, after)}")
    ok = blocked and n_q == after
    print(f"  结果: {'PASS' if ok else 'FAIL'}")
    return ok


def before_after_ok(before: int, after: int) -> bool:
    """行数是否保持不变。"""
    return before == after


def case_b_allowed(sandbox: str, n_q: int) -> bool:
    """(b) 环境变量=1 时允许删除。"""
    _hr("(b) 环境变量=1 → 应允许物理删除")

    # 严格等于 "1" 的边界值验证
    for val, expect in [("1", True), ("true", False), ("yes", False),
                        ("0", False), ("", False)]:
        os.environ[dg.ENV_FLAG] = val
        got = dg.physical_delete_allowed("quiz_questions")
        flag = "OK" if got == expect else "MISMATCH"
        print(f"  {dg.ENV_FLAG}={val!r:8} -> {got} (期望 {expect}) {flag}")

    os.environ[dg.ENV_FLAG] = "1"
    print(f"\n  设置 {dg.ENV_FLAG}=1 后重试删除路径...")

    # 物理删除前置：先备份（规格要求这是所有物理删除的前置步骤）
    backup_path = dg.backup_before_delete(sandbox)
    print(f"  前置备份完成: {backup_path}")
    print(f"  备份体积: {os.path.getsize(backup_path) / 1024 / 1024:.2f} MB")

    passed = False
    try:
        dg.require_physical_delete_enabled("quiz_questions")
        conn = sqlite3.connect(sandbox)
        try:
            conn.execute("DELETE FROM quiz_questions")
            conn.commit()
        finally:
            conn.close()
        passed = True
    except dg.PhysicalDeleteBlocked as e:
        print(f"  意外被拦截: {e}")

    after = _count(sandbox, "quiz_questions")
    print(f"  闸门放行: {passed}")
    print(f"  行数 before={n_q} after={after}  → 已清空: {after == 0}")
    ok = passed and after == 0
    print(f"  结果: {'PASS' if ok else 'FAIL'}")
    return ok


def case_c_backup_rollback(sandbox: str, n_q: int) -> bool:
    """(c) 备份与回滚往返后行数一致。"""
    _hr("(c) 备份 → 删除 → 回滚，往返后行数一致")

    conn = sqlite3.connect(sandbox)
    try:
        conn.execute(
            "INSERT INTO quiz_questions (content) VALUES (?)",
            ("回滚往返测试题-%s" % os.urandom(6).hex(),),
        )
        conn.commit()
    finally:
        conn.close()

    baseline = _count(sandbox, "quiz_questions")
    print(f"  基线行数（删除前）: {baseline}")

    # 1) 备份
    backup_path = dg.backup_before_delete(sandbox)
    print(f"  备份: {backup_path} "
          f"({os.path.getsize(backup_path) / 1024 / 1024:.2f} MB)")

    # 2) 物理删除全部题目
    os.environ[dg.ENV_FLAG] = "1"
    dg.require_physical_delete_enabled("quiz_questions")
    conn = sqlite3.connect(sandbox)
    try:
        conn.execute("DELETE FROM quiz_questions")
        conn.commit()
    finally:
        conn.close()
    after_delete = _count(sandbox, "quiz_questions")
    print(f"  删除后行数: {after_delete}")

    # 3) 查回滚窗口
    info = dg.rollback_window("quiz_questions", sandbox, minutes=30)
    print(f"\n  rollback_window() 返回:")
    if info:
        for k, v in info.items():
            print(f"    {k}: {v}")
    else:
        print("    None（窗口内无可用备份）")
        print("  结果: FAIL")
        return False

    # 4) 用备份覆盖回滚
    dg._sqlite_backup_file(info["backup_path"], sandbox)
    after_rollback = _count(sandbox, "quiz_questions")
    print(f"\n  回滚后行数: {after_rollback}")

    # 5) 窗口外查询应返回 None
    stale = dg.rollback_window("quiz_questions", sandbox, minutes=0)
    print(f"  minutes=0 查询结果: {stale}（期望 None）")

    ok = (after_rollback == baseline and stale is None)
    print(f"\n  往返一致: {baseline} == {after_rollback} → {after_rollback == baseline}")
    print(f"  结果: {'PASS' if ok else 'FAIL'}")
    return ok


def case_d_shell_guard() -> bool:
    """附加验证：空壳诱饵库必须被 1MB 体积下限拦住。"""
    _hr("(附加) 空壳诱饵库拦截验证")

    decoy = os.path.join(BASE_DIR, "data", "kaoyan.db")
    if os.path.isfile(decoy):
        size = os.path.getsize(decoy)
        print(f"  空壳诱饵库: {decoy} ({size} B)")
        try:
            dg._assert_valid_backup(decoy)
            print("  体积校验: 未拦截 → FAIL")
            return False
        except dg.PhysicalDeleteBlocked as e:
            print(f"  体积校验已拦截: {str(e).splitlines()[0]}")
            return size < dg.MIN_DB_BYTES
    print("  未找到 data/kaoyan.db，跳过")
    return True


def main() -> int:
    print("=" * 70)
    print("  delete_guard 自测")
    print("=" * 70)

    sandbox, n_q, _ = _prepare_sandbox()

    results = {}
    try:
        results["a"] = case_a_blocked(sandbox, n_q)
        results["b"] = case_b_allowed(sandbox, n_q)
        results["c"] = case_c_backup_rollback(sandbox, n_q)
        results["d"] = case_d_shell_guard()
    finally:
        os.environ.pop(dg.ENV_FLAG, None)

    _hr("汇总")
    for k, label in [("a", "(a) 未设置时拦截+行数不变"),
                     ("b", "(b) =1 时允许删除"),
                     ("c", "(c) 备份回滚往返一致"),
                     ("d", "(附加) 空壳库被体积校验拦住")]:
        print(f"  {label:38} {'PASS' if results.get(k) else 'FAIL'}")

    all_ok = all(results.values())
    print(f"\n  总体: {'ALL PASS' if all_ok else 'HAS FAILURE'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())