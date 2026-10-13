"""
数据库自动备份服务 V3.0
每天自动备份，保留最近7天，支持在线备份（不需要停服务）
"""
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from database import BASE_DIR, DATA_DIR

BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")


def _resolve_db_path() -> str:
    """解析**真库**路径（红线：绝不备份/恢复错库）。

    历史 bug：本文件曾硬编码 ``data/kaoyan.db``，但真库实际在
    ``<repo>/database/kaoyan.db``（由 database.py 的 ``_configured_db`` 解析）。
    那行硬编码导致：
      - 定时备份一直在备份一个 0 字节空壳库（备份看着成功，实则毫无价值）
      - ``restore_backup()`` 会用 0 字节库**覆盖真库**，直接摧毁用户全部数据

    这里改为向 database.py 询问真实连接串，与 ORM 保持同源，禁止二次推断。
    """
    # 1) 优先取 database.py 实际使用的路径（唯一事实来源）
    try:
        from database import SQLALCHEMY_DATABASE_URL  # type: ignore
        prefix = "sqlite:///"
        if SQLALCHEMY_DATABASE_URL.startswith(prefix):
            resolved = SQLALCHEMY_DATABASE_URL[len(prefix):]
            # 兼容 Windows 绝对路径可能带前导斜杠：sqlite:///D:/x.db
            if os.path.isfile(resolved):
                return os.path.abspath(resolved)
            alt = resolved.lstrip("/")
            if os.path.isfile(alt):
                return os.path.abspath(alt)
    except Exception:  # noqa: BLE001 —— 回落继续，不因导入问题放弃备份
        pass

    # 2) 环境变量显式指定
    env = os.environ.get("KAOYAN_DB_PATH")
    if env and os.path.isfile(env):
        return os.path.abspath(env)

    # 3) 仓库同级 database/kaoyan.db
    repo_db = os.path.abspath(os.path.join(BASE_DIR, os.pardir, "database", "kaoyan.db"))
    if os.path.isfile(repo_db):
        return repo_db

    # 4) 最后才回落到 data/kaoyan.db（保持既有行为，但会被下面的体积校验拦住）
    return os.path.join(DATA_DIR, "kaoyan.db")


DB_PATH = _resolve_db_path()
#: 备份/恢复的最小合理体积。低于此值一律拒绝—— 防止 0 字节空壳库被当成"备份"，
#: 也防止损坏备份被恢复到真库。
MIN_DB_BYTES = 1 * 1024 * 1024
MAX_BACKUPS = 7  # 保留最近7天
#: 无论如何都不许低于这个下限 —— 即使清理逻辑出错，也必须留下可回滚的备份
MIN_BACKUPS = 3


def ensure_backup_dir():
    """确保备份目录存在"""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def create_backup() -> str:
    """
    创建数据库备份（使用 SQLite .backup 在线备份，不需要停服务）

    红线（修复记录）：
      1. **只允许 `src.backup(dst)`**。旧实现捕获异常后降级 `shutil.copy2`，
         那是**文件级拷贝**—— WAL 模式下 -wal/-shm 里尚未合并进主库的数据
         会丢失，产出一个「看着成功、实则缺数据」的备份，比没有备份更危险。
         现在失败即抛异常，让调用方明确知道备份没做成。
      2. **先备份成功、后清理旧备份**。旧实现顺序相反，备份失败时
         已经先把旧备份删掉了 —— 等于「新的没做成、旧的也被删光」。

    Returns:
        备份文件路径

    Raises:
        Exception: 备份失败时直接抛出（不再静默降级）
    """
    ensure_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"kaoyan_{timestamp}.db")
    # 同秒内重复调用会撞同一个文件名，导致后一次把前一次的产物覆盖/错认。
    # 加随机后缀保证唯一。
    if os.path.exists(backup_path):
        stamp_micro = datetime.now().strftime("%H%M%S_%f")
        backup_path = os.path.join(BACKUP_DIR, f"kaoyan_{stamp_micro}.db")

    # **前置校验**：sqlite3.connect() 对不存在的路径会「创建一个空库」，
    # 于是备份一个根本不存在的源库时，src.backup(dst) 会安静地成功、
    # 产出一个 0 行/0 字节的废备份骗过调用方（旧实现就踩过这个坑：
    # 走降级 copy2 路径后打印「备份成功」）。源库不存在必须直接失败。
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(f"源数据库不存在，拒绝备份: {DB_PATH}")
    if os.path.getsize(DB_PATH) == 0:
        raise RuntimeError(f"源数据库为空文件，拒绝备份: {DB_PATH}")

    src = None
    dst = None
    try:
        # 使用 SQLite 在线备份（支持 WAL 模式，不需要停服务）
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(backup_path)
        src.backup(dst)
        dst.close()
        dst = None
        src.close()
        src = None

        # 校验产物确实是可用的 SQLite 库（避免留下0 字节/半截文件骗过调用方）
        if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
            raise RuntimeError(f"备份产物无效: {backup_path}")
        chk = sqlite3.connect(backup_path)
        try:
            chk.execute("PRAGMA quick_check").fetchone()
        finally:
            chk.close()

        size = os.path.getsize(backup_path)
        print(f"[backup] 数据库备份成功: {backup_path} ({size / 1024 / 1024:.2f} MB)")

        # 清理旧备份：**放在备份成功之后**，且永不早于 MIN_BACKUPS
        cleanup_old_backups()
        return backup_path
    except Exception as e:
        print(f"[backup] 数据库备份失败: {e}")
        # 清理半成品，避免下次被当成有效备份
        try:
            if dst is not None:
                dst.close()
            if src is not None:
                src.close()
        except Exception:
            pass
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
        except OSError:
            pass
        # 刻意**不降级**到 shutil.copy2：文件级拷贝在 WAL 下会丢数据，
        # 必须让调用方知道这次备份失败了。
        raise


def cleanup_old_backups():
    """清理超过 MAX_BACKUPS 个的旧备份。

    两道安全锁（均为修复项）：
      1. 只清理**自动备份** `kaoyan_<YYYYmmdd_HHMMSS>.db`，
         **绝不碰** `kaoyan_pre_*`（同事在数据修复前留的人工血泪备份）——
         旧实现用 `kaoyan_*.db` 通配，把这些人工备份也算进了清理名单。
      2. 保留数取 `max(MAX_BACKUPS, MIN_BACKUPS)`，且再留 1 份余量，
         保证**永远至少剩 MIN_BACKUPS 份**，不会把最后一个备份删掉。
    """
    #严格锚定自动备份命名：kaoyan_ + 14 位时间戳 + .db
    backups = sorted(p for p in Path(BACKUP_DIR).glob("kaoyan_*.db")
                     if _is_auto_backup(p.name))
    keep = max(MAX_BACKUPS, MIN_BACKUPS)
    # 多留 1 份余量：清理后仍>= MIN_BACKUPS
    excess = len(backups) - keep - 1
    if excess <= 0:
        return
    for old in backups[:excess]:
        try:
            old.unlink()
            print(f"[backup] 清理旧备份: {old}")
        except Exception as e:
            print(f"[backup] 清理旧备份失败: {old}, {e}")


def _is_auto_backup(name: str) -> bool:
    """判断是否为自动备份文件。

    自动备份命名：`kaoyan_YYYYmmdd_HHMMSS.db`，同秒重名时追加微秒：
    `kaoyan_HHMMSS_ffffff.db`（微秒后缀分支的日期部分已并入时间戳）。
    人工备份一律带额外前缀（`kaoyan_pre_`、`kaoyan_pre_restore_`），
    必须与自动备份区分开，否则清理逻辑会误删人工血泪备份。
    """
    stem = name[:-3] if name.endswith(".db") else name
    if not stem.startswith("kaoyan_"):
        return False
    ts = stem[len("kaoyan_"):]
    parts = ts.split("_")
    # 标准形： [YYYYmmdd, HHMMSS]
    if len(parts) == 2 and len(parts[0]) == 8 and len(parts[1]) == 6:
        return parts[0].isdigit() and parts[1].isdigit()
    # 微秒形： [HHMMSS, ffffff]
    if len(parts) == 2 and len(parts[0]) == 6 and len(parts[1]) == 6:
        return parts[0].isdigit() and parts[1].isdigit()
    return False


def list_backups() -> list:
    """列出所有备份"""
    ensure_backup_dir()
    backups = []
    for f in sorted(Path(BACKUP_DIR).glob("kaoyan_*.db"), reverse=True):
        stat = f.stat()
        backups.append({
            "name": f.name,
            "path": str(f),
            "size": stat.st_size,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return backups


def _is_valid_backup(path: str) -> bool:
    """校验备份文件是否可用作恢复源（体积 + SQLite 完整性 + 能否读到表）。

    这是防止「损坏备份摧毁真库」的最后一道闸：真库 500+MB，
    一个 0 字节/截断/空壳的备份绝不能被允许覆盖上去。
    """
    if not os.path.isfile(path):
        return False
    size = os.path.getsize(path)
    if size < MIN_DB_BYTES:
        print(f"[backup] 拒绝：备份文件过小({size} B< {MIN_DB_BYTES} B): {path}")
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
    except Exception as e:
        print(f"[backup] 拒绝：备份文件无法作为 SQLite 读取: {e}")
        return False
    return True


def restore_backup(backup_path: str) -> bool:
    """
    从备份恢复数据库。

    红线（修复记录）：
      1. **体积/完整性前置校验**：损坏或空壳备份一律拒绝，绝不覆盖真库。
      2. **恢复前保护备份改用 SQLite backup()**：原实现用 `shutil.copy2`，
         WAL 模式下会把「-wal 里未合并的数据」全部丢掉 —— 实测真库有表、
         主文件仅 4096B 时，copy2 出的「保护备份」里**连表都不存在**，
         意味着真正需要它的时候，它救不了任何东西。
      3. **恢复走 SQLite backup() API**，而非文件覆盖：直接 copy2 覆盖
         WAL 库会与残留的 -wal/-shm 产生不一致，且不是原子操作。
    """
    if not os.path.exists(backup_path):
        print(f"[backup] 备份文件不存在: {backup_path}")
        return False
    if not _is_valid_backup(backup_path):
        print(f"[backup] 恢复中止：备份文件未通过校验，拒绝覆盖真库 {DB_PATH}")
        return False

    ensure_backup_dir()
    try:
        # 1) 恢复前保护备份：必须用 SQLite backup()，copy2 在 WAL 下不可靠
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pre_restore_path = os.path.join(BACKUP_DIR, f"kaoyan_pre_restore_{timestamp}.db")
        _sqlite_backup(DB_PATH, pre_restore_path)
        print(f"[backup] 恢复前已安全备份当前数据库: {pre_restore_path}")
        if not _is_valid_backup(pre_restore_path):
            print(f"[backup] 恢复中止：保护备份校验失败，不敢动真库")
            return False

        # 2) 恢复：同样走 SQLite backup()，避免 copy2 覆盖 WAL 库造成不一致
        _sqlite_backup(backup_path, DB_PATH)
        print(f"[backup] 数据库恢复成功: {backup_path}")
        return True
    except Exception as e:
        print(f"[backup] 数据库恢复失败: {e}")
        return False


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
    for f in Path(BACKUP_DIR).glob("kaoyan_*.db"):
        if today in f.name:
            return False
    return True


def daily_backup_if_needed():
    """如果今天还没备份，则创建备份"""
    if should_backup_today():
        return create_backup()
    return None
