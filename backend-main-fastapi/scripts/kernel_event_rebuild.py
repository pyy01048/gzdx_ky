# -*- coding: utf-8 -*-
"""S1：kernel 事件流 → SQLite 投影重建（幂等，可 cron 定时跑）。

用法（backend venv）：
    python scripts/kernel_event_rebuild.py
    python scripts/kernel_event_rebuild.py --jsonl data/kernel_events.jsonl --sqlite data/kernel_events.db

消费 kernel.event_store.rebuild 的 Projection/RebuildReport：
全量删旧插新于单事务内 → 重跑 diff=0（幂等验收口径）。
坏行/重复 event_id 进 rejected/duplicates 计数，不中断重建（红线 6）。
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
    ap = argparse.ArgumentParser(description="kernel 事件投影重建")
    ap.add_argument("--jsonl", default=str(_BACKEND / "data" / "kernel_events.jsonl"))
    ap.add_argument("--sqlite", default=str(_BACKEND / "data" / "kernel_events.db"))
    args = ap.parse_args()

    from services.kernel_bridge import project_events_to_sqlite

    jsonl = Path(args.jsonl)
    if not jsonl.exists():
        print(json.dumps({"ok": True, "note": "jsonl 不存在，空投影", "jsonl": str(jsonl)}, ensure_ascii=False))
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        jsonl.touch()
    report = project_events_to_sqlite(jsonl, Path(args.sqlite))
    print(json.dumps({"ok": True, "sqlite": args.sqlite, **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
