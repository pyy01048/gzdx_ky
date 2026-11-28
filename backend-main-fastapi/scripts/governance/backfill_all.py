#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缺失数据回填统一入口（C-BACKFILL@1）。

依次调用 ``scripts/backfill_content_quality.py`` 的三个子命令，汇总每步回填计数：

    answers          回填 quiz_questions 缺失答案
    options          回填 quiz_questions 缺失选项
    knowledge-links  题→知识点关联

用法：
    python scripts/governance/backfill_all.py --dry-run
    python scripts/governance/backfill_all.py --apply --batch 500
    python scripts/governance/backfill_all.py --apply --batch 500 --skip-failed

契约：C-BACKFILL@1
    - 默认 dry-run，``--apply`` 才写库
    - 幂等：底层脚本只更新 IS NULL 行，重复执行 no-op
    - 可中断恢复：底层脚本自带游标+审计
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# backend-main-fastapi 根目录
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BACKFILL_SCRIPT = _BACKEND_ROOT / "scripts" / "backfill_content_quality.py"

# 依次执行的子命令（C-BACKFILL@1 规定的顺序）
SUBCOMMANDS: tuple[str, ...] = ("answers", "options", "knowledge-links")


def run_one(subcommand: str, apply: bool, batch: int) -> dict[str, Any]:
    """调用底层回填脚本的一个子命令，返回解析后的 summary。

    返回 dict 始终包含 ``command``、``ok``、``returncode`` 字段；
    成功时合并底层脚本输出的 JSON summary，失败时包含 ``stdout``/``stderr``。
    """
    cmd = [
        sys.executable,
        str(_BACKFILL_SCRIPT),
        subcommand,
        "--apply" if apply else "--dry-run",
        "--batch",
        str(batch),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(_BACKEND_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    result: dict = {
        "command": subcommand,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
    }

    # 底层脚本成功时 stdout 为 JSON summary（indent=2）；失败时可能无 JSON
    stdout_text = proc.stdout.strip()
    if stdout_text:
        try:
            summary = json.loads(stdout_text)
            result.update(summary)
        except json.JSONDecodeError:
            result["stdout"] = stdout_text
    if proc.returncode != 0:
        result["stderr"] = proc.stderr.strip()

    # 实时透传底层 stderr（logging 诊断信息），便于排查
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if stdout_text:
        sys.stdout.write(stdout_text + "\n")

    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="缺失数据回填统一入口（C-BACKFILL@1）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dry-run", action="store_true", help="只预览不写库（默认）")
    ap.add_argument("--apply", action="store_true", help="真正写库（与 --dry-run 互斥）")
    ap.add_argument("--batch", type=int, default=500, help="每批处理行数（默认 500）")
    ap.add_argument(
        "--skip-failed",
        action="store_true",
        help="某步失败时跳过继续下一步（默认遇错即停）",
    )
    args = ap.parse_args(argv)

    if args.apply and args.dry_run:
        ap.error("--apply 与 --dry-run 互斥")
    apply = args.apply

    print(f"=== backfill_all 开始 (mode={'apply' if apply else 'dry-run'}, batch={args.batch}) ===")

    results: list[dict[str, Any]] = []
    for sub in SUBCOMMANDS:
        print(f"\n--- 步骤: {sub} ---")
        res = run_one(sub, apply, args.batch)
        results.append(res)
        if not res["ok"]:
            print(f"[失败] {sub} returncode={res['returncode']}")
            if not args.skip_failed:
                print("\n=== 汇总（中断）===")
                _print_summary(results)
                return 1
        else:
            print(
                f"[成功] {sub}: "
                f"processed={res.get('processed', '?')} "
                f"updated={res.get('updated', '?')} "
                f"skipped={res.get('skipped', '?')}"
            )

    print("\n=== 汇总 ===")
    _print_summary(results)

    # 全部成功返回 0，否则返回 1
    return 0 if all(r["ok"] for r in results) else 1


def _print_summary(results: list[dict[str, Any]]) -> None:
    """打印每步回填计数汇总表。"""
    print(f"{'子命令':<18}{'状态':<8}{'processed':>12}{'updated':>12}{'skipped':>12}")
    print("-" * 62)
    total_processed = total_updated = total_skipped = 0
    for r in results:
        status = "成功" if r["ok"] else "失败"
        processed = r.get("processed", 0) or 0
        updated = r.get("updated", 0) or 0
        skipped = r.get("skipped", 0) or 0
        print(f"{r['command']:<18}{status:<8}{processed:>12}{updated:>12}{skipped:>12}")
        total_processed += processed
        total_updated += updated
        total_skipped += skipped
    print("-" * 62)
    print(f"{'合计':<18}{'':<8}{total_processed:>12}{total_updated:>12}{total_skipped:>12}")


if __name__ == "__main__":
    raise SystemExit(main())
