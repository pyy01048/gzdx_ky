# -*- coding: utf-8 -*-
"""kaoyan_admissions 脏数据清洗脚本（幂等）。

背景（docx/11 §5.2.3）：
    kaoyan_admissions 出现 1 行 year=2099 的脏数据（csv 导入异常），
    应被清除；同批导入的 6 行 year=2025 数据是正常的，**不得触碰**。

处理策略：**物理删除** year=2099 的行。
    理由：2099 明显是导入占位/错误年份，不指向任何真实招生年度；
    物理删除最干净，且不影响 2025/2026 的真实数据。相比「标记」，
    删除可避免后续聚合端点（如 enrollment-plan 取 max(year)）被
    2099 误导而返回空数据。脚本本身幂等：重复运行不会产生副作用。

安全设计：
    - 默认 dry-run（只报告将要删除的行，不写库）；
    - ``--apply`` 才真正执行；
    - 写库前先备份整个 db 文件到 ``<db>.backup-<timestamp>``；
    - 删除前后各打印一次按年份分布，便于核对。

用法：
    python scripts/clean_admissions_dirty.py            # dry-run（默认）
    python scripts/clean_admissions_dirty.py --apply    # 真正删除 + 备份

禁止 ``git add -A``；本脚本仅操作 kaoyan_admissions 表。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time

# 脏数据年份阈值：>= 该值视为异常（真实招生年度不可能到 2099）
_DIRTY_YEAR = 2099
# 相对项目根定位默认 db（允许被 --db 覆盖）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = os.path.join(_PROJECT_ROOT, "data", "kaoyan.db")


def _resolve_db_path(db_arg: str | None) -> str:
    """解析待清洗的数据库路径。

    优先级：命令行 --db > 环境变量 DATABASE_PATH > 项目 data/kaoyan.db。
    这里刻意不导入 database 模块，避免 .env 副作用干扰脚本的独立运行。
    """
    if db_arg:
        return os.path.abspath(db_arg)
    env_path = os.environ.get("DATABASE_PATH", "").strip()
    if env_path:
        return os.path.abspath(env_path)
    # 兜底：尝试读取项目 .env 的 DATABASE_PATH（不引入 dotenv 依赖）
    env_file = os.path.join(_PROJECT_ROOT, ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("DATABASE_PATH=") and not line.startswith("#"):
                        return os.path.abspath(line.split("=", 1)[1].strip())
        except OSError:
            pass
    return _DEFAULT_DB


def _year_distribution(cur: sqlite3.Cursor) -> list[tuple[int, int]]:
    """返回 [(year, count), ...]，按年份升序。"""
    return list(
        cur.execute(
            "SELECT year, COUNT(*) FROM kaoyan_admissions GROUP BY year ORDER BY year"
        ).fetchall()
    )


def _find_dirty_rows(cur: sqlite3.Cursor, dirty_year: int) -> list[tuple]:
    """找出所有 year >= dirty_year 的脏行（含主键与关键字段，便于核对）。"""
    dirty = list(
        cur.execute(
            "SELECT id, school_id, major_id, year, enroll_count, data_source "
            "FROM kaoyan_admissions WHERE year >= ? ORDER BY year, id",
            (dirty_year,),
        ).fetchall()
    )
    return dirty


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="清洗 kaoyan_admissions 中的 year=2099 脏数据（幂等，默认 dry-run）"
    )
    parser.add_argument("--apply", action="store_true", help="真正执行删除（默认仅演练）")
    parser.add_argument("--db", default=None, help="数据库路径（默认取 DATABASE_PATH / data/kaoyan.db）")
    parser.add_argument("--dirty-year", type=int, default=_DIRTY_YEAR, help="脏数据年份阈值（默认 2099）")
    args = parser.parse_args(argv)

    dirty_year = args.dirty_year

    db_path = _resolve_db_path(args.db)
    if not os.path.exists(db_path):
        print(f"[ERROR] 数据库不存在: {db_path}", file=sys.stderr)
        return 2

    print("=" * 68)
    print(f"目标数据库: {db_path}")
    print(f"模式: {'APPLY（写库）' if args.apply else 'DRY-RUN（仅演练）'}")
    print(f"脏数据判定: year >= {dirty_year}")
    print("=" * 68)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        print("\n[清洗前] 年份分布：")
        before = _year_distribution(cur)
        for y, n in before:
            print(f"    year={y}: {n} 行")

        dirty = _find_dirty_rows(cur, dirty_year)
        if not dirty:
            print("\n[OK] 未发现脏数据，无需处理（脚本幂等，重复运行安全）。")
            return 0

        print(f"\n[发现] 待删除脏数据 {len(dirty)} 行：")
        for row in dirty:
            print(
                f"    id={row['id']} school_id={row['school_id']} "
                f"major_id={row['major_id']} year={row['year']} "
                f"enroll_count={row['enroll_count']} source={row['data_source']}"
            )

        if not args.apply:
            print("\n[DRY-RUN] 未写库。确认无误后加 --apply 执行。")
            return 0

        # ---- 备份（写库前必须） ----
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_path = f"{db_path}.backup-{ts}"
        shutil.copy2(db_path, backup_path)
        print(f"\n[备份] 已写入: {backup_path}")

        # ---- 执行删除（仅 year >= 阈值，绝不触碰 2025/2026） ----
        cur.execute("DELETE FROM kaoyan_admissions WHERE year >= ?", (dirty_year,))
        affected = cur.rowcount
        conn.commit()
        print(f"[写入] 已删除 {affected} 行（year >= {dirty_year}）。")

        print("\n[清洗后] 年份分布：")
        after = _year_distribution(cur)
        for y, n in after:
            print(f"    year={y}: {n} 行")

        # 校验：2025 行数必须保持不变
        before_2025 = dict(before).get(2025, 0)
        after_2025 = dict(after).get(2025, 0)
        if before_2025 == after_2025:
            print(f"\n[校验] year=2025 行数保持 {after_2025} 行，未受影响 ✓")
        else:
            print(
                f"\n[警告] year=2025 行数发生变化：{before_2025} -> {after_2025}",
                file=sys.stderr,
            )
            return 1

        print("\n[DONE] 清洗完成。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
