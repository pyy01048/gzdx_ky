"""物理删除硬防护（quiz_questions / knowledge_chunks）。

背景
----
本周因判重逻辑缺陷，误删过 158 条真题（后仅恢复 89 条）。根因分析发现：
凡是能用 DELETE 物理删除 ``quiz_questions`` / ``knowledge_chunks`` 的代码路径，
都缺少物理删除防护。这道门就是为此而立——把「不可逆的数据损失」从一个
靠人记住的约定，变成一个由代码强制执行的前置条件。

设计红线
--------
1. **默认关闭**。只有环境变量 ``KAOYAN_ALLOW_PHYSICAL_DELETE`` 严格等于字符串
   ``"1"`` 才放行。``"true"`` / ``"yes"`` / ``"0"`` / 空串 一律视为未开启。
   正常运行时这个变量不设置，所以默认行为是「拦住」。
2. **只允许 SQLite backup API**。备份一律走 ``src.backup(dst)``。
   **绝对禁止 ``shutil.copy2`` / 文件级拷贝**：本库是 WAL 模式，
   ``-wal`` / ``-shm`` 里尚未合并进主库的数据在文件级拷贝时会被丢掉，
   产出一个「看着成功、实则缺数据」的备份，比没有备份更危险。
3. **绝不备份错库**。真库由 ``.env`` 的 ``DATABASE_PATH`` 指向
   ``D:\\平台\\database\\kaoyan.db``；仓库里的 ``data/kaoyan.db`` 是一个
   几百KB 的空壳诱饵库。历史上 backup_service 就因为硬编码它，
   导致定时备份一直在备份空壳、恢复时用空壳覆盖真库。
   因此本模块的 :func:`_resolve_db_path` 复用 backup_service 的解析顺序，
   并强制加**1MB 体积下限校验**拦住空壳库。
"""

import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

#: 环境变量名。严格等于 "1" 才允许物理删除。
ENV_FLAG = "KAOYAN_ALLOW_PHYSICAL_DELETE"

#: 允许物理删除时环境变量必须取的值。
ENV_ENABLED_VALUE = "1"

#: 备份/恢复目标最小合理体积（1MB）。低于此值一律拒绝——
#: 拦住 data/kaoyan.db 这类空壳诱饵库，以及 0 字节 / 截断的废备份。
MIN_DB_BYTES = 1 * 1024 * 1024

#: 项目根目录（本文件位于 <root>/services/）。
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 备份根目录。
BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")

#: 自动备份命名规范：`kaoyan_YYYYmmdd_HHMMSS[_ffffff][_<tag>].db`
#: 其中 ``_<tag>`` 是可选标签（通常是被备份的数据库文件名）。
#: rollback_window 与 _is_auto_backup 共用此正则，禁止各自另写一套。
#: 注意：人工备份形如 ``kaoyan_pre_restore_YYYYmmdd_HHMMSS.db``，
#: 其日期段前有 "pre_restore" 之类的前缀，**不会**匹配本正则，
#: 因此不会被误当成自动回滚候选。
BACKUP_NAME_PATTERN = re.compile(
    r"^kaoyan_(\d{8})_(\d{6})(?:_(\d{6}))?(?:_[0-9A-Za-z]+)?\.db$"
)


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class PhysicalDeleteBlocked(RuntimeError):
    """物理删除被拦截。

    继承 ``RuntimeError``，这样即使调用方只按 ``RuntimeError`` 兜底也不会漏接。
    """


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #
def _read_env_flag() -> str:
    """读取环境变量开关的原始值。"""
    return os.environ.get(ENV_FLAG, "").strip()


def _describe_env_flag() -> str:
    """生成人类可读的环境变量状态描述（未设置时不写 None）。"""
    raw = os.environ.get(ENV_FLAG)
    if raw is None:
        return f"{ENV_FLAG}=未设置（当前视为关闭）"
    if raw.strip() == "":
        return f"{ENV_FLAG}=\"\"（空值，当前视为关闭）"
    return f"{ENV_FLAG}={raw!r}"


def _sqlite_url_to_path(url: str) -> Optional[str]:
    """把 SQLite 连接串转成文件路径；非 SQLite 或内存库返回 None。

    同时兼容 ``sqlite:///`` 与异步驱动形式 ``sqlite+aiosqlite:///``，
    以及 Windows 下 ``sqlite:///D:/x.db`` 带前导斜杠的写法。
    """
    if not url:
        return None
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            raw = url[len(prefix):]
            break
    else:
        # 其它方言（postgresql:// 等）—— 本项目是 SQLite，交给调用方回落。
        return None

    if not raw or ":memory:" in raw or raw.startswith(":memory:"):
        # 内存库没有可备份的文件实体。
        return None
    # Windows 绝对路径经 SQLAlchemy 序列化后常带前导斜杠：sqlite:///D:/x.db
    return raw.lstrip("/") if re.match(r"^[A-Za-z]:", raw.lstrip("/")) else raw


def _resolve_db_path() -> str:
    """解析**真库**路径（红线：绝不备份/恢复错库）。

    解析优先级（与 ``services/backup_service.py`` 完全同源，禁止二次推断）：

    1. ``database.py`` 里的 ``SQLALCHEMY_DATABASE_URL`` —— 唯一事实来源；
    2. 环境变量 ``KAOYAN_DB_PATH``；
    3. 仓库同级 ``database/kaoyan.db``；
    4. 最后才回落到 ``data/kaoyan.db``（会被下面的体积校验拦住）。

    历史 bug：backup_service 曾硬编码 ``data/kaoyan.db``，而真库实际由
    ``.env`` 的 ``DATABASE_PATH`` 指向仓库外。那导致定时备份一直在备份一个
    空壳诱饵库，且恢复时用空壳**覆盖真库**，直接摧毁全部数据。

    体积下限校验：无论走哪条优先级，解析结果小于 ``MIN_DB_BYTES``（1MB）
    一律拒绝——空壳库绝不能被当成真库去备份或回滚。

    Raises:
        PhysicalDeleteBlocked: 解析出的文件过小 / 指向内存库 / 全部候选均不可用。
    """
    candidates: list[tuple[str, str]] = []  # (来源说明, 路径)

    # 1) database.py 的 SQLALCHEMY_DATABASE_URL
    try:
        from database import SQLALCHEMY_DATABASE_URL  # type: ignore

        resolved = _sqlite_url_to_path(SQLALCHEMY_DATABASE_URL)
        if resolved:
            candidates.append(("database.SQLALCHEMY_DATABASE_URL", resolved))
    except Exception:  # noqa: BLE001 —— 导入失败不应放弃备份，降级继续
        pass

    # 2) 环境变量 KAOYAN_DB_PATH
    env = (os.environ.get("KAOYAN_DB_PATH") or "").strip()
    if env:
        candidates.append(("env KAOYAN_DB_PATH", env))

    # 3) 仓库同级 database/kaoyan.db
    candidates.append((
        "repo database/kaoyan.db",
        os.path.join(BASE_DIR, os.pardir, "database", "kaoyan.db"),
    ))

    # 4) 最后回落 data/kaoyan.db（保持既有行为，由体积校验兜住）
    candidates.append(("fallback data/kaoyan.db", os.path.join(BASE_DIR, "data", "kaoyan.db")))

    for source, path in candidates:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            continue
        size = os.path.getsize(path)
        if size < MIN_DB_BYTES:
            # 空壳诱饵库 / 0 字节库 —— 绝不能当成真库。记录下来继续找下一个候选。
            _record_rejected(source, path, size)
            continue
        return path

    raise PhysicalDeleteBlocked(
        "无法解析出可用的真库路径（所有候选均不存在或低于 "
        f"{MIN_DB_BYTES} 字节下限）。已尝试：\n"
        + "\n".join(f"  - {src}: {os.path.abspath(p)}" for src, p in candidates)
        + "\n请检查 .env 的 DATABASE_PATH 是否指向真库，"
          "或用 KAOYAN_DB_PATH 显式指定。"
    )


def _record_rejected(source: str, path: str, size: int) -> None:
    """记录一个被体积下限拦下的候选库，便于排查。"""
    print(
        f"[delete_guard] 拒绝候选库({source}): {path} "
        f"大小 {size} B < {MIN_DB_BYTES} B，疑似空壳诱饵库"
    )


# --------------------------------------------------------------------------- #
# 物理删除开关
# --------------------------------------------------------------------------- #
def physical_delete_allowed(table_name: str) -> bool:
    """当前是否允许对 ``table_name`` 执行物理删除。

    只有当环境变量 ``KAOYAN_ALLOW_PHYSICAL_DELETE`` **严格等于字符串 "1"**
    时返回 True。注意是严格等于："true" / "yes" / "on" / "0" / 空串
    一律视为 False。

    Args:
        table_name: 表名（仅用于日志与调试，不影响判定结果）。

    Returns:
        True 表示允许物理删除。
    """
    return _read_env_flag() == ENV_ENABLED_VALUE


def require_physical_delete_enabled(table_name: str) -> None:
    """物理删除前置闸门：未显式放行则抛 :class:`PhysicalDeleteBlocked`。

    在每一处对 ``quiz_questions`` / ``knowledge_chunks`` 的物理删除之前调用。
    默认（环境变量未设置）会抛异常，从而把不可逆的数据损失挡在门外。

    Args:
        table_name: 即将被物理删除的表名。

    Raises:
        PhysicalDeleteBlocked: 物理删除未被放行时。
    """
    if physical_delete_allowed(table_name):
        return

    raise PhysicalDeleteBlocked(
        f"物理删除已拦截：表 {table_name}\n"
        f"  当前环境变量状态：{_describe_env_flag()}\n"
        f"  原因：quiz_questions / knowledge_chunks 的物理删除不可逆，"
        f"本周曾因判重缺陷误删 158 条真题（仅恢复 89 条）。\n"
        f"  如确需执行物理删除，请在当前会话临时开启后重试：\n"
        f"    PowerShell: $env:{ENV_FLAG}='1'; <你的命令>\n"
        f"    bash:export {ENV_FLAG}=1 && <你的命令>\n"
        f"  并且必须先用 backup_before_delete() 完成备份（走 SQLite backup API，"
        f"禁止 copy2）。"
    )


# --------------------------------------------------------------------------- #
# 备份 / 回滚
# --------------------------------------------------------------------------- #
def _backup_dir_for(db_path: str) -> str:
    """返回给定数据库应当使用的备份目录。"""
    return BACKUP_DIR


def _build_backup_name(tag: str) -> str:
    """按统一规范生成备份文件名：``kaoyan_YYYYmmdd_HHMMSS_<tag>.db``。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_tag = re.sub(r"[^0-9A-Za-z_]+", "_", tag).strip("_") or "db"
    return f"kaoyan_{ts}_{safe_tag}.db"


def _is_auto_backup(name: str) -> bool:
    """判断文件名是否符合自动备份命名规范。"""
    return bool(BACKUP_NAME_PATTERN.match(name))


def backup_before_delete(db_path: str) -> str:
    """所有物理删除的**前置步骤**：用 SQLite backup API 备份真库。

    红线：这里只用 ``sqlite3.Connection.backup()``。
    **绝对禁止 shutil.copy2 / shutil.copy / cp**——WAL 模式下
    ``-wal`` / ``-shm`` 中尚未合并进主库的数据会在文件级拷贝时丢失，
    产出一个「看着成功、实则缺数据」的备份，比没有备份更危险。

    Args:
        db_path: 源数据库路径。

    Returns:
        备份文件的绝对路径。

    Raises:
        PhysicalDeleteBlocked: 源库不存在、为空，或备份产物无效。
    """
    # 前置校验：sqlite3.connect() 对不存在的路径会「创建一个空库」，
    # 于是备份一个根本不存在的源库时会安静地成功、产出 0 字节废备份。
    if not os.path.isfile(db_path):
        raise PhysicalDeleteBlocked(f"源数据库不存在，拒绝备份: {db_path}")
    if os.path.getsize(db_path) == 0:
        raise PhysicalDeleteBlocked(f"源数据库为空文件，拒绝备份: {db_path}")

    backup_dir = _backup_dir_for(db_path)
    os.makedirs(backup_dir, exist_ok=True)

    tag = os.path.splitext(os.path.basename(db_path))[0] or "db"
    backup_path = os.path.join(backup_dir, _build_backup_name(tag))
    # 同秒内重复调用会撞同一个文件名。加微秒后缀保证唯一。
    if os.path.exists(backup_path):
        micro = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = os.path.join(
            backup_dir, f"kaoyan_{micro}_{re.sub(r'[^0-9A-Za-z_]+', '_', tag)}.db"
        )

    src = None
    dst = None
    try:
        # SQLite 在线备份 API —— WAL 安全，不需要停服务。
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(backup_path)
        src.backup(dst)
        dst.close()
        dst = None
        src.close()
        src = None

        # 校验产物确实是可用的 SQLite 库，避免留下 0 字节/半截文件骗过调用方。
        if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
            raise PhysicalDeleteBlocked(f"备份产物无效: {backup_path}")
        _assert_valid_backup(backup_path)

        size = os.path.getsize(backup_path)
        print(f"[delete_guard] 物理删除前备份成功: {backup_path} ({size / 1024 / 1024:.2f} MB)")
        return backup_path
    except Exception:
        # 清理半成品，避免下次被当成有效备份。
        # 刻意不降级到 shutil.copy2：文件级拷贝在 WAL 下会丢数据，
        # 必须让调用方知道这次备份失败了。
        for conn in (dst, src):
            try:
                if conn is not None:
                    conn.close()
            except Exception as _exc:  # noqa: BLE001
                # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
                # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
                logging.getLogger(__name__).warning(
                    '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
                )
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
        except OSError:
            pass
        raise


def _assert_valid_backup(path: str) -> None:
    """校验备份文件可作为恢复源：体积 + SQLite 完整性 + 能读到表。

    这是防止「损坏备份摧毁真库」的最后一道闸。

    Raises:
        PhysicalDeleteBlocked: 任一校验不通过。
    """
    size = os.path.getsize(path)
    if size < MIN_DB_BYTES:
        raise PhysicalDeleteBlocked(
            f"拒绝：备份文件过小（{size} B < {MIN_DB_BYTES} B）: {path}"
        )
    conn = None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = conn.execute("PRAGMA quick_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            raise PhysicalDeleteBlocked(f"拒绝：备份文件完整性校验失败({row}): {path}")
        n = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        if n < 1:
            raise PhysicalDeleteBlocked(f"拒绝：备份文件无任何表: {path}")
    finally:
        if conn is not None:
            conn.close()


def _sqlite_backup_file(src_path: str, dst_path: str) -> None:
    """用 SQLite 在线备份 API 把 src 复制到 dst（WAL 安全，原子可靠）。

    **不使用 shutil.copy2**：文件级覆盖 WAL 库会与残留的 -wal/-shm 产生
    不一致，且不是原子操作。
    """
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def rollback_window(
    table_name: str,
    db_path: str,
    minutes: int = 30,
) -> Optional[dict[str, Any]]:
    """在时间窗口内查找最近一份可用备份，给出回滚方案。

    只认自动备份命名规范（``kaoyan_YYYYmmdd_HHMMSS[_ffffff]_*.db``），
    人工备份（``kaoyan_pre_*``）不参与自动回滚候选，以免误用。

    Args:
        table_name: 待回滚的表名，仅用于日志与返回值标注。
        db_path: 目标数据库路径，仅用于标注与校验。
        minutes: 回滚窗口（分钟）。

    Returns:
        命中窗口内备份时返回描述性 dict（含 ``rollback_hint``），
        窗口内无可用备份时返回 None。
    """
    backup_dir = _backup_dir_for(db_path)
    if not os.path.isdir(backup_dir):
        return None

    cutoff = datetime.now().timestamp() - minutes * 60
    candidates: list[tuple[float, str, os.stat_result]] = []
    for name in os.listdir(backup_dir):
        if not name.endswith(".db") or not _is_auto_backup(name):
            continue
        full = os.path.join(backup_dir, name)
        if not os.path.isfile(full):
            continue
        st = os.stat(full)
        # 按 mtime 倒序（最新在前）
        if st.st_mtime >= cutoff:
            candidates.append((st.st_mtime, full, st))

    if not candidates:
        return None

    candidates.sort(reverse=True, key=lambda item: item[0])

    # 从最新一份开始校验；跳过体积/完整性不合格的（空壳、残缺）备份。
    for mtime, full, st in candidates:
        try:
            _assert_valid_backup(full)
        except PhysicalDeleteBlocked as e:
            print(f"[delete_guard] 跳过无效备份: {e}")
            continue
        age_minutes = max(0.0, (datetime.now().timestamp() - mtime) / 60.0)
        return {
            "table_name": table_name,
            "db_path": os.path.abspath(db_path),
            "backup_path": full,
            "backup_name": os.path.basename(full),
            "size": st.st_size,
            "size_mb": round(st.st_size / 1024 / 1024, 2),
            "age_minutes": round(age_minutes, 2),
            "window_minutes": minutes,
            "rollback_hint": (
                f"用该备份覆盖回滚 {table_name}："
                f"python -c \"import services.backup_service as b; "
                f"b.restore_backup(r'{full}')\""
            ),
        }

    return None


__all__ = [
    "ENV_FLAG",
    "ENV_ENABLED_VALUE",
    "MIN_DB_BYTES",
    "BACKUP_DIR",
    "PhysicalDeleteBlocked",
    "physical_delete_allowed",
    "require_physical_delete_enabled",
    "backup_before_delete",
    "rollback_window",
]
