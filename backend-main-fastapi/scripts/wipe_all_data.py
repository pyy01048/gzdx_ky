# -*- coding: utf-8 -*-
"""清空 kaoyan 生产库全部数据（保留 schema / 视图 / 触发器 / ENUM = 应用框架）。

用途：用户计划重新填充知识库并重训模型时，把数据库重置到"只有框架"的状态。

用法：
    python scripts/wipe_all_data.py            #  dry-run：列出所有表与行数，不执行
    python scripts/wipe_all_data.py --yes      #  执行 TRUNCATE ... RESTART IDENTITY CASCADE

安全设计：
- 只认 core/db_session.py 的引擎（连接串单一来源），不读散落的 .env 覆盖
- 拒绝在指向 kaoyan_test 时执行（防误伤测试沙箱）
- TRUNCATE 保留表结构、视图、触发器、函数、ENUM、序列定义；仅清数据并重置序列
- 执行前打印完整表清单与总行数，需 --yes 才真正动手
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from core.db_session import build_database_url, engine  # noqa: E402


def _engine():
    return engine


def _guard(engine) -> None:
    """拒绝误伤测试库。"""
    url = str(engine.url)
    if "kaoyan_test" in url:
        raise SystemExit(
            "拒绝执行：当前连接指向 kaoyan_test（测试沙箱）。\n"
            "本脚本只允许对生产库 kaoyan 执行。请检查 .env 的 PG_DATABASE。"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="清空 kaoyan 生产库全部数据（保留 schema）")
    ap.add_argument("--yes", action="store_true", help="确认执行；缺省为 dry-run")
    args = ap.parse_args()

    engine = _engine()
    _guard(engine)

    with engine.connect() as conn:
        db = conn.execute(text("SELECT current_database()")).scalar()
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' "
                "ORDER BY table_name"
            )
        ).scalars().all()

        if not rows:
            print("public schema 下没有表，无需处理。")
            return 0

        # 逐表统计行数（TRUNCATE 前留档）
        counts: list[tuple[str, int]] = []
        total = 0
        for t in rows:
            n = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
            counts.append((t, n))
            total += n

        print(f"数据库: {db}")
        print(f"待清空表数: {len(rows)}，总行数: {total}")
        for t, n in counts:
            print(f"  {t:<48} {n:>10}")

        if not args.yes:
            print("\n[dry-run] 未做任何修改。确认无误后加 --yes 执行。")
            return 0

        # 单条 TRUNCATE 一口气清完（CASCADE 处理外键依赖）
        table_list = ", ".join(f'"{t}"' for t in rows)
        conn.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))
        conn.commit()

        # 复核
        left = 0
        for t in rows:
            left += conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
        print(f"\n完成：{len(rows)} 张表已清空，剩余总行数 = {left}")
        if left:
            print("警告：仍有残留行，请检查上面的表清单。")
            return 2
        print("schema / 视图 / 触发器 / ENUM 均保留，应用框架完好。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
