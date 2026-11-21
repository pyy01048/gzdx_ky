# -*- coding: utf-8 -*-
"""C 批次2 全量执行入口（服务器/本地通用）：公告/改考清洗与分类治理。

用法：
    python scripts/b2_notice_governance.py            # 全量执行 + before/after 快照
    python scripts/b2_notice_governance.py --dry-run  # 只快照不写
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal  # noqa: E402
from services.kaoyan.notice_governance import run_batch2  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        rep = run_batch2(db, dry_run=args.dry_run)
        db.commit()
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
