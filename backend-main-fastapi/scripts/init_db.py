"""空库初始化 / 结构升级（幂等，可重复执行）。

用法（在 backend-main-fastapi 目录下，DATABASE_URL 指向目标库）：
    python scripts/init_db.py           # 建表/补列 + 内置科目 + 首个管理员
    python scripts/init_db.py --list    # 只列出将执行的 SQL 分片

顺序与测试夹具 tests/conftest.py::db_schema 一致：
    1. core/pg_schema.sql（\\ir 收编的权威分片）
    2. core/sql 下未被收编的增量分片，按文件名序逐个执行
    3. ORM create_all 兜底 + 原生表补建
    4. 内置科目字典 + 首个管理员（密码取 ADMIN_INITIAL_PASSWORD）
不写任何学习内容（题目/文档/院校数据走后续导入）。
"""
import argparse
import glob
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
CORE = os.path.join(BASE, "core")


def extra_shards() -> list[str]:
    with open(os.path.join(CORE, "pg_schema.sql"), encoding="utf-8") as fh:
        included = set(re.findall(r"^\\ir\s+sql/(\S+)", fh.read(), re.M))
    return sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(CORE, "sql", "*.sql"))
        if os.path.basename(p) not in included
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="只列出分片，不执行")
    args = parser.parse_args()

    shards = extra_shards()
    if args.list:
        print("core/pg_schema.sql")
        for name in shards:
            print(f"core/sql/{name}")
        return 0

    from core.db_session import IS_POSTGRES, apply_schema
    from database import Base, SessionLocal, engine
    import models  # noqa: F401  注册 ORM 表

    print(f"目标库: {engine.url.render_as_string(hide_password=True)}")
    if not IS_POSTGRES:
        print("错误：生产初始化只支持 PostgreSQL（检查 DATABASE_URL）")
        return 2

    failures: list[str] = []
    try:
        apply_schema()
        print("[1/4] pg_schema.sql 已应用")
    except Exception as exc:  # noqa: BLE001
        print(f"[1/4] pg_schema.sql 失败: {type(exc).__name__}: {exc}")
        return 1

    for name in shards:
        try:
            apply_schema(os.path.join(CORE, "sql", name))
            print(f"[2/4] 已执行 {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            print(f"[2/4] 失败 {name}: {type(exc).__name__}: {exc}")

    Base.metadata.create_all(bind=engine)
    from services.module_a_schema import ensure_module_a_schema
    from services.taxonomy import ensure_subject_config_seeds
    from utils.security import ensure_bootstrap_admin

    db = SessionLocal()
    try:
        ensure_module_a_schema(db)
        db.commit()
        print("[3/4] ORM 表与原生表已补齐")
        seeded = ensure_subject_config_seeds(db)
        db.commit()
        admin = ensure_bootstrap_admin(db)
        db.commit()
        print(f"[4/4] 内置科目新增 {seeded} 个；"
              + (f"已创建管理员 {admin}" if admin else "已有用户，跳过管理员创建"))
    finally:
        db.close()

    if failures:
        print(f"\n{len(failures)} 个分片失败: {', '.join(failures)}")
        return 1
    print("\n初始化完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
