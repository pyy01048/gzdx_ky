"""轻量数据库迁移入口（SQLite 单文件，无需 Alembic）。

用法：
    cd backend-main-fastapi
    python migrate.py            # 执行全部迁移（幂等，可重复运行）
    python migrate.py --list     # 只列出将执行什么

迁移顺序（必须按此顺序，后者依赖前者的列/表）：
    0. ensure_schema_columns          内置幂等补列（直连**真库**，缺列才加，加前 SQLite backup 备份）
    1. migrate_v4_schema.py          加列 / 建表 / 清理死表（含自动备份）
    2. rebuild_knowledge_base.py     重建「章节→知识点→题型」三级结构 + 真题入库
    3. backfill_doc_meta.py          回填资料三层结构 / 扫描件标记

注意：第 2 步在检测到知识点已被错题/复习记录引用时会**主动中止**，
防止把 error_knowledge_links 变成悬空引用。此时改用增量补齐，
或确认后加 --force。

为什么第 0 步单独放这里（而不写进 migrate_v4_schema.py 的 NEW_COLUMNS）：
    migrate_v4_schema.py 解析出的库是 ``backend-main-fastapi/data/kaoyan.db``
    （651KB 的空壳诱饵库），而真库在 ``<repo>/database/kaoyan.db``（数百 MB）；
    且它用 ``shutil.copy2`` 备份（WAL 下会丢数据，违反本项目铁律）。
    故本步骤复用 ``services.backup_service`` 的**真库解析**与 **SQLite backup API**，
    只作用于真库。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(BASE, "scripts")
# 真库路径：与 services.backup_service 同源解析（历史陷阱：本目录 data/kaoyan.db
# 是数百 KB 的空壳诱饵库，真库在 <repo>/database/kaoyan.db）。解析失败才回落旧值。
try:
    from services.backup_service import DB_PATH as DB  # type: ignore
except Exception:  # noqa: BLE001 —— 导入失败不阻断迁移，回落旧行为
    DB = os.path.join(BASE, "data", "kaoyan.db")

# (脚本, 说明, 是否必跑)
MIGRATIONS = [
    ("migrate_v4_schema.py", "V4 结构迁移：三级结构 / 错题联动 / 复习追踪字段与表", True),
    ("rebuild_knowledge_base.py", "知识库重建：真题入库 + 考点三级结构化", True),
    ("backfill_doc_meta.py", "回填资料三层结构（原始/加工/索引）与扫描件标记", False),
]

# --------------------------------------------------------------------------- #
# 第 0 步：内置幂等补列（与 models.py 声明一一对应，避免"孤儿列"）
# 缺列才加；加列前用 SQLite backup API 备份**真库**（禁 cp/copy2）。
# --------------------------------------------------------------------------- #
REQUIRED_COLUMNS: list[tuple[str, str, str]] = [
    # (表, 列, ADD COLUMN 语句) —— 类型/默认值照抄 models.QuizQuestion.figure_missing
    ("quiz_questions", "figure_missing",
     "ALTER TABLE quiz_questions ADD COLUMN figure_missing INTEGER NOT NULL DEFAULT 0"),
]


def ensure_schema_columns() -> int:
    """幂等补列，直接作用于**真库**（backup_service.DB_PATH）。0 正常 / 非 0 出错。"""
    import sqlite3

    from services.backup_service import DB_PATH, create_backup

    if not os.path.isfile(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        print(f"[x] 真库不存在或为空：{DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        todo: list[tuple[str, str, str]] = []
        for table, col, ddl in REQUIRED_COLUMNS:
            if not cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                print(f"[!] 跳过 {table}.{col}：表不存在")
                continue
            cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")')]
            if col in cols:
                print(f"[=] {table}.{col} 已存在")
                continue
            todo.append((table, col, ddl))

        if not todo:
            print("[✓] 无缺列，无需迁移")
            return 0

        backup = create_backup()  # 缺列才备份，避免每次运行都产生备份
        print(f"[✓] 备份（SQLite backup API）→ {os.path.basename(backup)}")
        for table, col, ddl in todo:
            try:
                cur.execute(ddl)
                conn.commit()
                print(f"[+] {table}.{col} 已新增")
            except sqlite3.Error as e:
                conn.rollback()
                print(f"[x] {table}.{col} 失败：{e}")
                return 1
        return 0
    finally:
        conn.close()


def main() -> int:
    list_only = "--list" in sys.argv

    if not os.path.exists(DB):
        print(f"[x] 数据库不存在：{DB}")
        print("    请先启动一次后端（main.py 会自动建库），再运行迁移。")
        return 1

    print("=" * 70)
    print("考研平台 · 数据库迁移")
    print("=" * 70)
    print(f"数据库：{DB}")
    print()

    # —— 第 0 步：内置幂等补列（直连真库）—— #
    if not list_only:
        print("[0] 内置幂等补列（ensure_schema_columns）")
        rc = ensure_schema_columns()
        if rc != 0:
            print("      [x] 补列失败，迁移中止")
            return rc
        print()

    for i, (script, desc, required) in enumerate(MIGRATIONS, 1):
        path = os.path.join(SCRIPTS, script)
        print(f"[{i}/{len(MIGRATIONS)}] {script}")
        print(f"      {desc}")

        if list_only:
            continue

        if not os.path.exists(path):
            print(f"      [!] 脚本缺失，跳过")
            if required:
                return 1
            continue

        # 透传用户附加参数（如 --dry-run / --force）
        extra = [a for a in sys.argv[1:] if a != "--list"]
        result = subprocess.run(
            [sys.executable, path, *extra],
            cwd=BASE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(f"      [x] 退出码 {result.returncode}，迁移中止")
            return result.returncode
        print(f"      [✓] 完成\n")

    if list_only:
        print("（--list 模式，未执行）")
    else:
        print("=" * 70)
        print("[✓] 全部迁移完成")
        print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
