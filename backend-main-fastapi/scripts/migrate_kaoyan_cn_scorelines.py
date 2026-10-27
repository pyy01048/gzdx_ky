# -*- coding: utf-8 -*-
"""给 kaoyan_scorelines 补齐「按专业展示分数线」所需的列。

掌上考研（kaoyan.cn）的分数线是逐专业一行（名称/代码/院系/学位类别/
单科线/差值），现有表只有 numeric 列，无法还原展示口径。

用法：
    python scripts/migrate_kaoyan_cn_scorelines.py          # dry-run
    python scripts/migrate_kaoyan_cn_scorelines.py --apply  # 写库
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from database import engine  # noqa: E402

COLUMNS = [
    ("major_code", "VARCHAR(20)"),
    ("major_name", "VARCHAR(120)"),
    ("depart_name", "VARCHAR(120)"),
    ("degree_type", "VARCHAR(20)"),
    ("note", "TEXT"),
    ("special_remark", "TEXT"),
    ("diff_total", "INTEGER"),
    ("source_id", "VARCHAR(64)"),
]
INDEXES = [
    ("ix_scorelines_source_id", "kaoyan_scorelines (source_id)"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际执行 DDL（默认 dry-run）")
    args = ap.parse_args()

    insp = inspect(engine)
    existing = {c["name"] for c in insp.get_columns("kaoyan_scorelines")}
    todo = [(n, t) for n, t in COLUMNS if n not in existing]
    idx_names = {i["name"] for i in insp.get_indexes("kaoyan_scorelines")}
    todo_idx = [(n, d) for n, d in INDEXES if n not in idx_names]

    print(f"数据库：{engine.url.render_as_string(hide_password=True)}")
    print(f"待加列：{[n for n, _ in todo] or '无'}")
    print(f"待加索引：{[n for n, _ in todo_idx] or '无'}")
    if not args.apply:
        print("dry-run，不执行。加 --apply 写库。")
        return 0

    with engine.begin() as conn:
        for name, ddl in todo:
            conn.execute(text(f"ALTER TABLE kaoyan_scorelines ADD COLUMN {name} {ddl}"))
            print(f"  + {name} {ddl}")
        for name, target in todo_idx:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {target}"))
            print(f"  + index {name}")
    print("完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
