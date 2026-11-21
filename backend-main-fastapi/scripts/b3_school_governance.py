# -*- coding: utf-8 -*-
"""C 批次3 治理执行入口（院校地区拆分/层级嵌套/空章节统计；补爬链另走服务器脚本）。

用法：
    python scripts/b3_school_governance.py            # 全量执行 + before/after
    python scripts/b3_school_governance.py --dry-run  # 只统计不写
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from services.kaoyan.school_governance import run_batch3_governance  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        rep = run_batch3_governance(db, dry_run=args.dry_run)
        db.commit()
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
