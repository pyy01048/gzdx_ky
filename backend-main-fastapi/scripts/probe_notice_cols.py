# -*- coding: utf-8 -*-
"""临时：查 kaoyan_notices 状态列的真实类型。"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402


def main() -> int:
    from database import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(text("""
            select column_name, data_type from information_schema.columns
            where table_name='kaoyan_notices'
              and column_name in ('is_read','is_starred','read_at','starred_at',
                                  'publish_date','fetched_at')
            order by ordinal_position
        """)).all()
        for name, dtype in rows:
            print(f"{name:14} {dtype}")
        sample = db.execute(text(
            "select read_at, starred_at, is_read, is_starred, fetched_at "
            "from kaoyan_notices where read_at is not null limit 3"
        )).all()
        print("read_at 样本:", sample)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
