"""数据库备份服务 V3.1：后端无关（PostgreSQL / SQLite）。

V3.0 只支持 SQLite；本项目已迁 PostgreSQL，导致 ``create_backup()`` 抛
``FileNotFoundError``，被 ``ensure_write_backup()`` 静默吞掉后**批量导入在无备份
状态下裸写**。本版本按 ``DATABASE_BACKEND`` 分派，并保留 V3.0 全部血泪红线：

  1. 备份失败**必须抛出**，绝不降级为文件拷贝（WAL 下 copy2 会丢未合并数据）。
  2. **先备份成功、后清理旧备份**，避免"新的没做成、旧的也被删光"。
  3. 清理只认自动备份命名，**绝不碰** ``kaoyan_pre_*`` 人工备份。
  4. 恢复源必须通过完整性校验，否则拒绝覆盖真库。
  5. **写点必须先有备份**。``services/kb_service.ensure_write_backup()`` 不再吞异常：
     备份失败即抛 ``WriteBackupBlocked``，由路由层拒绝这次写入（HTTP 503）。
     测试沙箱库由 :func:`is_test_database` 识别并跳过，不参与真实备份与清理。

PG 分支的完整性校验用**表数量对齐**而非文件体积：空库（仅 schema）的合法 dump
实测 502,735 字节，低于 ``MIN_DB_BYTES``，体积红线会误杀它；而「dump 内 TABLE 条目
数 >= 当前库基表数」在 0 行和 9000 行下同样成立，与数据量无关。
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from core.db_session import BACKEND_DIR, DATA_DIR, IS_POSTGRES, SQLALCHEMY_DATABASE_URL

logger = logging.getLogger(__name__)

# 注意：core.db_session 的 BASE_DIR 指向 core/ 子目录，不是后端根目录。
# 备份目录必须落在后端根下的 data/backups（迁移前 database.py 的 BASE_DIR 语义），
# 所以这里用 BACKEND_DIR。
BACKUP_DIR = os.path.join(BACKEND_DIR, "data", "backups")

#: 当前备份后端：postgresql | sqlite
BACKEND = "postgresql" if IS_POSTGRES else "sqlite"
#: 自动备份产物扩展名：PG 用自定义二进制 dump，SQLite 用库文件
DUMP_EXT = ".dump" if IS_POSTGRES else ".db"
#: 历史备份可能两种扩展名并存（迁移前后），清理/列举都要认
AUTO_EXTS = (".db", ".dump")

#: **仅 SQLite 分支**使用的最小合理体积。PG 分支改走表数量校验，
#: 因为空库合法 dump 体积本就小于此值（见模块 docstring 第 4 条）。
MIN_DB_BYTES = 1 * 1024 * 1024
MAX_BACKUPS = 7  # 保留最近7天
#: 无论如何都不许低于这个下限 —— 即使清理逻辑出错，也必须留下可回滚的备份
MIN_BACKUPS = 3
#: pg_dump / pg_restore 子进程超时（秒）。备份卡死比失败更危险，必须可中断。
PG_SUBPROCESS_TIMEOUT = int(os.environ.get("PG_BACKUP_TIMEOUT", "600"))

#: 测试沙箱库名。与 ``tests/conftest.py`` 的 ``TEST_PG_DATABASE`` 同一约定，
#: 不另立第二套命名，否则两处各改各的会让"测试写真实备份"重新漏出来。
TEST_DB_MARKER = os.environ.get("TEST_PG_DATABASE", "kaoyan_test")


def _resolve_db_path() -> str:
    """解析 **SQLite 真库**路径（红线：绝不备份/恢复错库）。

    历史 bug：本文件曾硬编码 ``data/kaoyan.db``，但真库实际在
    ``<repo>/database/kaoyan.db``。那行硬编码导致定时备份一直在备份 0 字节空壳，
    而 ``restore_backup()`` 会用空壳**覆盖真库**，直接摧毁用户全部数据。

    现在唯一事实来源是 ``core.db_session.SQLALCHEMY_DATABASE_URL``，禁止二次推断。
    PostgreSQL 后端下本函数仍返回一个路径字符串（供 ``migrate.py`` 等 SQLite 时代
    脚本做存在性判断后自行退出），**不参与 PG 备份**。
    """
    prefix = "sqlite:///"
    url = SQLALCHEMY_DATABASE_URL or ""
    if url.startswith(prefix):
        resolved = url[len(prefix):]
        # 兼容 Windows 绝对路径可能带前导斜杠：sqlite:///D:/x.db
        if os.path.isfile(resolved):
            return os.path.abspath(resolved)
        alt = resolved.lstrip("/")
        if os.path.isfile(alt):
            return os.path.abspath(alt)

    env = os.environ.get("KAOYAN_DB_PATH")
    if env and os.path.isfile(env):
        return os.path.abspath(env)

    repo_db = os.path.abspath(os.path.join(BACKEND_DIR, os.pardir, "database", "kaoyan.db"))
    if os.path.isfile(repo_db):
        return repo_db

    return os.path.join(DATA_DIR, "kaoyan.db")


DB_PATH = _resolve_db_path()


# --------------------------------------------------------------------------- #
# PostgreSQL：连接参数与工具发现
# --------------------------------------------------------------------------- #
def _pg_parts() -> dict[str, str]:
    """从连接串解析 pg_dump/pg_restore 所需参数（与 ORM 同源，不读散落配置）。"""
    url = (SQLALCHEMY_DATABASE_URL or "").replace("postgresql+psycopg", "postgresql", 1)
    u = urlparse(url)
    return {
        "host": u.hostname or "127.0.0.1",
        "port": str(u.port or 5432),
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "dbname": (u.path or "").lstrip("/") or "kaoyan",
    }


def is_test_database() -> bool:
    """当前连接是否指向测试沙箱库——测试库一律不做真实备份。

    不做隔离的后果实测过：每个写接口用例都会在 ``data/backups`` 里堆一份 dump，
    并且 ``cleanup_old_backups()`` 会据此清理**生产**备份。

    SQLite 走临时目录判定；PG 走库名判定（``kaoyan_test`` / ``*_test`` / ``test_*``）。
    """
    if IS_POSTGRES:
        name = _pg_parts()["dbname"]
        return name == TEST_DB_MARKER or name.endswith("_test") or name.startswith("test_")
    import tempfile

    tmp = os.path.abspath(tempfile.gettempdir())
    candidate = os.path.abspath(DB_PATH)
    try:
        return os.path.commonpath([tmp, candidate]) == tmp
    except ValueError:  # 不同盘符无公共路径
        return False


def _pg_tool(name: str) -> str | None:
    """定位 PG 客户端工具，**不在代码里写死任何机器专属绝对路径**。

    解析顺序：
      1. ``<NAME>_PATH`` 显式覆盖（如 ``PG_DUMP_PATH``）——单工具精确定位；
      2. ``PG_BIN_DIR`` 目录——与 ``scripts/startup_manager.py`` 用同一个环境变量，
         避免两处各配一份；
      3. 系统 ``PATH`` 查找。

    找不到返回 None，由调用方决定如何报错（不要在这里抛，便于降级诊断）。
    """
    exe_suffix = ".exe" if os.name == "nt" else ""
    override = os.environ.get(f"{name.upper()}_PATH", "").strip()
    if override and os.path.isfile(override):
        return override
    bindir = os.environ.get("PG_BIN_DIR", "").strip()
    if bindir:
        candidate = os.path.join(bindir, name + exe_suffix)
        if os.path.isfile(candidate):
            return candidate
    return shutil.which(name)


def _run(cmd: list[str], password: str | None = None) -> subprocess.CompletedProcess:
    """执行子进程。密码只经环境变量传递，绝不进 argv（会泄漏到进程表与日志）。

    ``--no-password`` + ``stdin=DEVNULL`` 是关键：否则认证失败时 pg_dump 会在
    stdin 上等待交互输入，把备份请求挂死到超时。
    """
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True,
        timeout=PG_SUBPROCESS_TIMEOUT, stdin=subprocess.DEVNULL, check=False,
    )


def _live_table_count() -> int | None:
    """当前 PG 库 public schema 的基表数——备份完整性的对照锚点。"""
    from sqlalchemy import text

    from core.db_session import engine

    try:
        with engine.connect() as conn:
            return int(conn.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )).scalar() or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("读取当前库基表数失败：%s", str(e)[:200])
        return None


def _dump_table_count(dump_path: str) -> int:
    """解析 dump 的 TOC，返回其中 TABLE 条目数。

    TOC 行形如 ``235; 1259 27685 TABLE public ai_providers kaoyan``，
    即 ``<dumpId>; <catalogId> <objectId> TAG <schema> <name> <owner>``。

    注意 ``TABLE DATA`` 条目（有数据后才会出现）切分后第 3 个字段同样是 ``TABLE``，
    必须按第 4 个字段排除，否则计数会虚高一倍、把不完整 dump 误判为有效。
    """
    exe = _pg_tool("pg_restore")
    if not exe:
        return -1
    try:
        r = _run([exe, "--list", dump_path])
    except subprocess.TimeoutExpired:
        return -1
    if r.returncode != 0:
        return -1
    n = 0
    for line in (r.stdout or "").splitlines():
        parts = line.split(";", 1)
        if len(parts) < 2:
            continue
        fields = parts[1].strip().split()
        # fields = [catalogId, objectId, TAG, schema, name, owner]
        if len(fields) >= 4 and fields[2] == "TABLE" and fields[3] not in ("DATA", "-"):
            n += 1
    return n


def _verify_pg_dump(dump_path: str) -> int:
    """校验 PG dump 是否可用：表条目数不得少于当前库基表数。

    Returns:
        dump 内的 TABLE 条目数

    Raises:
        RuntimeError: 产物缺失、无法解析、或表数量不足
    """
    if not os.path.isfile(dump_path) or os.path.getsize(dump_path) == 0:
        raise RuntimeError(f"备份产物缺失或为 0 字节: {dump_path}")
    got = _dump_table_count(dump_path)
    if got < 0:
        raise RuntimeError(f"备份产物无法被 pg_restore 解析（非有效自定义格式 dump）: {dump_path}")
    expected = _live_table_count()
    if expected is None:
        raise RuntimeError("无法读取当前库基表数，拒绝把未经对照的 dump 认定为有效备份")
    if got < expected:
        raise RuntimeError(f"备份内 TABLE 条目 {got} < 当前库基表 {expected}，判定为不完整备份: {dump_path}")
    return got


def _create_pg_backup(backup_path: str) -> int:
    """pg_dump 自定义格式备份。Returns 产物字节数。"""
    exe = _pg_tool("pg_dump")
    if not exe:
        raise RuntimeError(
            "找不到 pg_dump：请设置 PG_BIN_DIR（指向含 pg_dump/pg_restore 的目录，"
            "与 scripts/startup_manager.py 同一个变量）或把它加入 PATH。"
            "PG 后端下没有 pg_dump 就无法产生可回滚备份，绝不允许静默跳过。"
        )
    p = _pg_parts()
    cmd = [
        exe, "-h", p["host"], "-p", p["port"], "-U", p["user"], "-d", p["dbname"],
        "--format=custom", "--compress=6", "--no-password", "-f", backup_path,
    ]
    r = _run(cmd, password=p["password"])
    if r.returncode != 0:
        raise RuntimeError(f"pg_dump 退出码 {r.returncode}: {(r.stderr or '').strip()[:300]}")
    _verify_pg_dump(backup_path)
    return os.path.getsize(backup_path)


# --------------------------------------------------------------------------- #
# SQLite：在线备份 API
# --------------------------------------------------------------------------- #
def _create_sqlite_backup(backup_path: str) -> int:
    """用 SQLite 在线备份 API 备份（支持 WAL，不需停服务）。

    前置校验：``sqlite3.connect()`` 对不存在的路径会**创建一个空库**，于是备份一个
    根本不存在的源库时 ``src.backup(dst)`` 会安静地成功、产出 0 行废备份骗过调用方。
    源库不存在必须直接失败。
    """
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(f"源数据库不存在，拒绝备份: {DB_PATH}")
    if os.path.getsize(DB_PATH) == 0:
        raise RuntimeError(f"源数据库为空文件，拒绝备份: {DB_PATH}")

    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
        raise RuntimeError(f"备份产物无效: {backup_path}")
    chk = sqlite3.connect(backup_path)
    try:
        chk.execute("PRAGMA quick_check").fetchone()
    finally:
        chk.close()
    return os.path.getsize(backup_path)


# --------------------------------------------------------------------------- #
# 对外统一入口
# --------------------------------------------------------------------------- #
def ensure_backup_dir():
    """确保备份目录存在"""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _unique_backup_path() -> str:
    """自动备份命名：``kaoyan_<YYYYmmdd_HHMMSS><ext>``，同秒撞名时改用微秒。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"kaoyan_{timestamp}{DUMP_EXT}")
    if os.path.exists(path):
        stamp_micro = datetime.now().strftime("%H%M%S_%f")
        path = os.path.join(BACKUP_DIR, f"kaoyan_{stamp_micro}{DUMP_EXT}")
    return path


def create_backup() -> str:
    """创建一次数据库备份（后端无关）。

    Returns:
        备份文件路径

    Raises:
        Exception: 备份失败时直接抛出（**不降级、不静默跳过**）——调用方必须知道
            这次没做成可回滚备份。
    """
    ensure_backup_dir()
    backup_path = _unique_backup_path()
    try:
        size = _create_pg_backup(backup_path) if IS_POSTGRES else _create_sqlite_backup(backup_path)
    except Exception as e:  # noqa: BLE001
        print(f"[backup] 数据库备份失败: {e}")
        _remove_quietly(backup_path)  # 清理半成品，避免下次被当成有效备份
        raise

    print(f"[backup] 数据库备份成功({BACKEND}): {backup_path} ({size / 1024 / 1024:.2f} MB)")
    # 清理旧备份：**放在备份成功之后**，且永不早于 MIN_BACKUPS
    cleanup_old_backups()
    return backup_path


def _remove_quietly(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as e:
        logger.warning("删除半成品备份失败 %s: %s", path, str(e)[:120])


def _iter_auto_backups() -> list[Path]:
    """按时间序返回自动备份（不含人工 ``kaoyan_pre_*``）。"""
    if not os.path.isdir(BACKUP_DIR):
        return []
    found: list[Path] = []
    for ext in AUTO_EXTS:
        found.extend(Path(BACKUP_DIR).glob(f"kaoyan_*{ext}"))
    return sorted({p for p in found if _is_auto_backup(p.name)})


def cleanup_old_backups():
    """清理超过 MAX_BACKUPS 个的旧备份。

    两道安全锁（均为修复项）：
      1. 只清理**自动备份**，**绝不碰** ``kaoyan_pre_*``（同事在数据修复前留的人工
         血泪备份）——旧实现用 ``kaoyan_*.db`` 通配，把这些人工备份也算进了清理名单。
      2. 保留数取 ``max(MAX_BACKUPS, MIN_BACKUPS)``，且再留 1 份余量，
         保证**永远至少剩 MIN_BACKUPS 份**，不会把最后一个备份删掉。
    """
    backups = _iter_auto_backups()
    keep = max(MAX_BACKUPS, MIN_BACKUPS)
    excess = len(backups) - keep - 1
    if excess <= 0:
        return
    for old in backups[:excess]:
        try:
            old.unlink()
            print(f"[backup] 清理旧备份: {old}")
        except Exception as e:  # noqa: BLE001
            print(f"[backup] 清理旧备份失败: {old}, {e}")


def _is_auto_backup(name: str) -> bool:
    """判断是否为自动备份文件。

    自动备份命名：``kaoyan_YYYYmmdd_HHMMSS.<db|dump>``，同秒重名时追加微秒：
    ``kaoyan_HHMMSS_ffffff.<db|dump>``。人工备份一律带额外前缀（``kaoyan_pre_``、
    ``kaoyan_pre_restore_``），必须与自动备份区分开，否则清理逻辑会误删人工血泪备份。
    """
    stem = name.rsplit(".", 1)[0] if name.endswith(AUTO_EXTS) else name
    if not stem.startswith("kaoyan_"):
        return False
    ts = stem[len("kaoyan_"):]
    if ts.startswith("pre_"):
        return False
    parts = ts.split("_")
    # 标准形： [YYYYmmdd, HHMMSS]；微秒形： [HHMMSS, ffffff]
    if len(parts) == 2 and all(len(x) in (6, 8) and x.isdigit() for x in parts):
        return (len(parts[0]), len(parts[1])) in ((8, 6), (6, 6))
    return False


def list_backups() -> list:
    """列出所有备份（含人工备份，两种扩展名）。"""
    ensure_backup_dir()
    backups = []
    for ext in AUTO_EXTS:
        for f in Path(BACKUP_DIR).glob(f"kaoyan_*{ext}"):
            stat = f.stat()
            backups.append({
                "name": f.name,
                "path": str(f),
                "size": stat.st_size,
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "backend": "postgresql" if f.name.endswith(".dump") else "sqlite",
                "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
    return sorted(backups, key=lambda b: b["created_at"], reverse=True)


def _is_valid_sqlite_backup(path: str) -> bool:
    """校验 SQLite 备份可用作恢复源（体积 + 完整性 + 能否读到表）。"""
    if not os.path.isfile(path):
        return False
    size = os.path.getsize(path)
    if size < MIN_DB_BYTES:
        print(f"[backup] 拒绝：备份文件过小({size} B < {MIN_DB_BYTES} B): {path}")
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                print(f"[backup] 拒绝：备份文件完整性校验失败({row}): {path}")
                return False
            n = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            if n < 1:
                print(f"[backup] 拒绝：备份文件无任何表: {path}")
                return False
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        print(f"[backup] 拒绝：备份文件无法作为 SQLite 读取: {e}")
        return False
    return True


def _is_valid_backup(path: str) -> bool:
    """校验备份文件是否可用作恢复源——这是防止「损坏备份摧毁真库」的最后一道闸。

    按产物扩展名分派：``.dump`` 走 PG 表数量对齐，``.db`` 走 SQLite 体积+完整性。
    体积红线只对 SQLite 生效：空库的合法 PG dump 本就小于 1MB。
    """
    if path.endswith(".dump"):
        try:
            _verify_pg_dump(path)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[backup] 拒绝：PG 备份未通过校验: {e}")
            return False
    return _is_valid_sqlite_backup(path)


def restore_backup(backup_path: str) -> bool:
    """从备份恢复数据库（后端无关）。

    红线（修复记录）：
      1. **恢复源必须先过校验**，损坏或空壳备份一律拒绝，绝不覆盖真库。
      2. **恢复前先对当前库做保护备份**，且保护备份同样要过校验，否则不动真库。
      3. SQLite 走 ``backup()`` API 而非文件覆盖：copy2 覆盖 WAL 库会与残留
         -wal/-shm 产生不一致，且不是原子操作。
    """
    if not os.path.exists(backup_path):
        print(f"[backup] 备份文件不存在: {backup_path}")
        return False
    if not _is_valid_backup(backup_path):
        print(f"[backup] 恢复中止：备份文件未通过校验，拒绝覆盖真库")
        return False

    ensure_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        if IS_POSTGRES:
            return _restore_pg(backup_path, timestamp)
        return _restore_sqlite(backup_path, timestamp)
    except Exception as e:  # noqa: BLE001
        print(f"[backup] 数据库恢复失败: {e}")
        return False


def _restore_pg(backup_path: str, timestamp: str) -> bool:
    """PG 恢复：先保护性 dump，再 pg_restore --clean --if-exists。"""
    exe = _pg_tool("pg_restore")
    if not exe:
        raise RuntimeError("找不到 pg_restore：请设置 PG_BIN_DIR 或把它加入 PATH")
    p = _pg_parts()

    pre_restore_path = os.path.join(BACKUP_DIR, f"kaoyan_pre_restore_{timestamp}.dump")
    _create_pg_backup(pre_restore_path)
    print(f"[backup] 恢复前已安全备份当前数据库: {pre_restore_path}")
    if not _is_valid_backup(pre_restore_path):
        print("[backup] 恢复中止：保护备份校验失败，不敢动真库")
        return False

    cmd = [
        exe, "--dbname", p["dbname"], "-h", p["host"], "-p", p["port"],
        "-U", p["user"], "--no-password", "--clean", "--if-exists",
        "--no-owner", "--no-privileges", backup_path,
    ]
    r = _run(cmd, password=p["password"])
    if r.returncode != 0:
        raise RuntimeError(f"pg_restore 退出码 {r.returncode}: {(r.stderr or '').strip()[:300]}")
    print(f"[backup] 数据库恢复成功: {backup_path}")
    return True


def _restore_sqlite(backup_path: str, timestamp: str) -> bool:
    pre_restore_path = os.path.join(BACKUP_DIR, f"kaoyan_pre_restore_{timestamp}.db")
    _sqlite_backup(DB_PATH, pre_restore_path)
    print(f"[backup] 恢复前已安全备份当前数据库: {pre_restore_path}")
    if not _is_valid_backup(pre_restore_path):
        print("[backup] 恢复中止：保护备份校验失败，不敢动真库")
        return False

    _sqlite_backup(backup_path, DB_PATH)
    print(f"[backup] 数据库恢复成功: {backup_path}")
    return True


def _sqlite_backup(src_path: str, dst_path: str):
    """用 SQLite 在线备份 API 把 src 复制到 dst（WAL 安全，原子可靠）。"""
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def should_backup_today() -> bool:
    """判断今天是否已经备份过"""
    ensure_backup_dir()
    today = datetime.now().strftime("%Y%m%d")
    return not any(today in p.name for p in _iter_auto_backups())


def daily_backup_if_needed():
    """如果今天还没备份，则创建备份。测试沙箱库直接跳过（不产生真实备份）。"""
    if is_test_database():
        return None
    if should_backup_today():
        return create_backup()
    return None
