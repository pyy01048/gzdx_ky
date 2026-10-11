"""轻量数据库迁移入口（SQLite 单文件，无需 Alembic）。

用法：
    cd backend-main-fastapi
    python migrate.py            # 执行全部迁移（幂等，可重复运行）
    python migrate.py --list     # 只列出将执行什么

迁移顺序（必须按此顺序，后者依赖前者的列/表）：
    1. migrate_v4_schema.py          加列 / 建表 / 清理死表（含自动备份）
    2. rebuild_knowledge_base.py     重建「章节→知识点→题型」三级结构 + 真题入库
    3. backfill_doc_meta.py          回填资料三层结构 / 扫描件标记

注意：第 2 步在检测到知识点已被错题/复习记录引用时会**主动中止**，
防止把 error_knowledge_links 变成悬空引用。此时改用增量补齐，
或确认后加 --force。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(BASE, "scripts")
DB = os.path.join(BASE, "data", "kaoyan.db")

# (脚本, 说明, 是否必跑)
MIGRATIONS = [
    ("migrate_v4_schema.py", "V4 结构迁移：三级结构 / 错题联动 / 复习追踪字段与表", True),
    ("rebuild_knowledge_base.py", "知识库重建：真题入库 + 考点三级结构化", True),
    ("backfill_doc_meta.py", "回填资料三层结构（原始/加工/索引）与扫描件标记", False),
]


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
