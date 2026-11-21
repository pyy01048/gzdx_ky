# -*- coding: utf-8 -*-
"""C 批次1 全量执行 CLI（文档 KP 挂载 / 失败重索引 / 科目字典+队列）。

用法（backend venv，服务器 /opt/kaoyan/backend-main-fastapi）：
    python scripts/b1_document_governance.py --dry-run     # 只出前后统计快照
    python scripts/b1_document_governance.py               # 全量执行
    python scripts/b1_document_governance.py --kp-doc-limit 50   # 限流试跑

验收口径：输出 before/after 全量统计（非抽样）；重跑幂等（batch KP 只删本来源）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def main() -> int:
    ap = argparse.ArgumentParser(description="C 批次1 文档治理")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--kp-doc-limit", type=int, default=None)
    args = ap.parse_args()

    from database import SessionLocal
    from services.document_governance import run_batch1

    db = SessionLocal()
    try:
        report = run_batch1(db, dry_run=args.dry_run, kp_doc_limit=args.kp_doc_limit)
    finally:
        db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
