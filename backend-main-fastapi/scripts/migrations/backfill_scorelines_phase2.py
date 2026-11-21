# -*- coding: utf-8 -*-
"""分数线 major_id 二次回填（完善方案 05 §3.3 / 11 文档联动）。

背景：``kaoyan_scorelines`` 中 15 万行 major_id 为 NULL（多来源重复 + 专业名包装不一），
导致"按专业查分数线"失真。本脚本只做**安全回填**，规则：

  1. 精确优先：同校 major_code 完全一致 → 唯一命中才填
  2. 名称归一：去空白/全半角/括号后缀（(专业学位)/(全日制)/(非全日制)）/方向截断 →
     与同校 kaoyan_majors.name 归一后完全一致 → 唯一命中才填
  3. 兜底：专业名包含于 major.name 或反之，且该校唯一命中 → 填（置信度 0.7）
  4. 同一 (school_id, major_id, year, line_type) 已有行（uq_scoreline 冲突）→ 跳过，不覆盖
  5. 其余保持 NULL（不做猜测），进报告给人看

默认 dry-run；``--apply`` 前自动建备份表 ``bak_scorelines_majorid_<ts>``。

用法：
    python scripts/migrations/backfill_scorelines_phase2.py --dry-run
    python scripts/migrations/backfill_scorelines_phase2.py --apply
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from sqlalchemy import text  # noqa: E402

SUFFIX_RE = re.compile(r"[（(](?:专业学位|专业硕士|学术学位|学术型|全日制|非全日制|专硕|学硕)[)）]")


def norm_name(name: str | None) -> str:
    s = str(name or "").strip()
    s = s.replace("（", "(").replace("）", ")").replace("　", " ")
    s = re.sub(r"\s+", "", s)
    s = SUFFIX_RE.sub("", s)
    # 「085400 电子信息(01 方向)」类：括号内是方向，截断
    s = re.sub(r"\([^)]*方向[^)]*\)$", "", s)
    return s.lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default=str(BASE.parent / "docs" / "reports"))
    ap.add_argument("--sample", type=int, default=30, help="报告里展示的样例数")
    args = ap.parse_args()

    from core.db_session import IS_POSTGRES, build_database_url  # noqa: PLC0415
    from sqlalchemy import create_engine  # noqa: PLC0415

    if not IS_POSTGRES:
        print("[x] 仅支持 PostgreSQL")
        return 2
    engine = create_engine(build_database_url())

    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT id, school_id, year, line_type, major_code, major_name "
                    "FROM kaoyan_scorelines WHERE major_id IS NULL AND enabled IS TRUE"
                )
            )
            .mappings()
            .all()
        )
        majors = (
            conn.execute(text("SELECT id, school_id, code, name FROM kaoyan_majors WHERE enabled IS TRUE"))
            .mappings()
            .all()
        )
        occupied = {
            (r[0], r[1], r[2], r[3])
            for r in conn.execute(
                text("SELECT school_id, major_id, year, line_type FROM kaoyan_scorelines WHERE major_id IS NOT NULL")
            ).all()
        }

    by_school_code: dict[tuple, list[int]] = defaultdict(list)
    by_school_name: dict[tuple, list[int]] = defaultdict(list)
    for m in majors:
        if m["code"]:
            by_school_code[(m["school_id"], str(m["code"]).strip())].append(m["id"])
        by_school_name[(m["school_id"], norm_name(m["name"]))].append(m["id"])

    plans: list[dict] = []
    skipped_conflict = 0
    unmatched: list[str] = []

    for r in rows:
        sid = r["school_id"]
        candidates: list[int] = []
        confidence = 0.0

        code = (r["major_code"] or "").strip()
        if code:
            hit = by_school_code.get((sid, code), [])
            if len(hit) == 1:
                candidates, confidence = hit, 1.0

        if not candidates:
            key = norm_name(r["major_name"])
            if key:
                hit = by_school_name.get((sid, key), [])
                if len(hit) == 1:
                    candidates, confidence = hit, 0.95

        if not candidates:
            key = norm_name(r["major_name"])
            if key:
                loose = [
                    mid
                    for (school, name), ids in by_school_name.items()
                    if school == sid and name and (key in name or name in key)
                    for mid in ids
                ]
                if len(set(loose)) == 1:
                    candidates, confidence = list(set(loose)), 0.7

        if not candidates:
            if r["major_name"]:
                unmatched.append(str(r["major_name"]))
            continue

        mid = candidates[0]
        sig = (sid, mid, r["year"], r["line_type"])
        if sig in occupied:
            skipped_conflict += 1
            continue
        occupied.add(sig)
        plans.append(
            {"id": int(r["id"]), "major_id": mid, "confidence": confidence, "major_name": r["major_name"], "code": code}
        )

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {
        "generated_at": ts,
        "mode": "apply" if args.apply else "dry-run",
        "null_rows_scanned": len(rows),
        "planned": len(plans),
        "by_confidence": {
            "1.0": sum(1 for p in plans if p["confidence"] == 1.0),
            "0.95": sum(1 for p in plans if p["confidence"] == 0.95),
            "0.7": sum(1 for p in plans if p["confidence"] == 0.7),
        },
        "skipped_unique_conflict": skipped_conflict,
        "unmatched_distinct_names": len(set(unmatched)),
        "unmatched_top": sorted({n for n in unmatched})[: args.sample],
        "sample": plans[: args.sample],
    }
    (out_dir / f"scorelines-backfill-{ts}.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md = [
        f"# 分数线 major_id 二次回填报告（{ts}）",
        "",
        f"- 模式：{'APPLY' if args.apply else 'DRY-RUN'}",
        f"- 扫描 NULL 行：{len(rows)}｜可回填：{len(plans)}｜唯一键冲突跳过：{skipped_conflict}",
        f"- 置信度分布：code 精确 {stats['by_confidence']['1.0']}｜名称精确 {stats['by_confidence']['0.95']}｜"
        f"包含匹配 {stats['by_confidence']['0.7']}",
        f"- 未匹配专业名（去重）：{len(set(unmatched))} 个，Top{args.sample}：",
        "",
        "```",
        "\n".join(stats["unmatched_top"]),
        "```",
        "",
        "| 分数线行 | 专业ID | 置信度 | 专业名 |",
        "|---|---|---|---|",
    ]
    md += [f"| {p['id']} | {p['major_id']} | {p['confidence']} | {p['major_name']} |" for p in plans[:200]]
    (out_dir / f"scorelines-backfill-{ts}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"报告：{out_dir / f'scorelines-backfill-{ts}.md'}")
    print(f"扫描 {len(rows)}｜可回填 {len(plans)}｜冲突跳过 {skipped_conflict}")

    if not args.apply:
        print("[dry-run] 未写库。核对报告后加 --apply。")
        return 0
    if not plans:
        return 0

    bak = f"bak_scorelines_majorid_{ts.replace('-', '')}"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {bak} AS SELECT id, major_id FROM kaoyan_scorelines WHERE major_id IS NULL"
            )
        )
        for p in plans:
            conn.execute(
                text("UPDATE kaoyan_scorelines SET major_id = :m WHERE id = :i AND major_id IS NULL"),
                {"m": p["major_id"], "i": p["id"]},
            )
    print(f"[✓] 已回填 {len(plans)} 行（备份表 {bak}）")
    print(f"回滚：UPDATE kaoyan_scorelines s SET major_id=NULL FROM {bak} b WHERE s.id=b.id;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
