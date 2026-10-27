# -*- coding: utf-8 -*-
"""kaoyan_notices 重复清理 · PostgreSQL 版。

判重键（单一事实来源 = services.kaoyan.notice_dedup）:
    (school_id, normalize_notice_url(url), normalize_notice_title(title))

保留策略（优先级）:
  1. is_read / is_starred 有标记的行优先（用户交互过）
  2. fetched_at 最早
  3. id 最小
被删行的 is_read / is_starred / read_at / starred_at 迁移到保留行，
保证用户交互状态不丢失。

安全:
  - 默认 dry-run；--apply 才执行。
  - --apply 先建备份表 kaoyan_notices_dedup_backup_20261021。

用法::

    python scripts/dedupe_notices_pg.py           # dry-run
    python scripts/dedupe_notices_pg.py --apply   # 备份后执行
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from services.kaoyan.notice_dedup import (  # noqa: E402
    normalize_notice_title,
    normalize_notice_url,
)

BACKUP_SUFFIX = "_dedup_backup_20261021"

TABLE = "kaoyan_notices"


def load_groups(db) -> dict[tuple, list[dict]]:
    rows = db.execute(text(
        f"select id, school_id, title, url, is_read, is_starred, read_at, "
        f"starred_at, fetched_at from {TABLE} order by id"
    )).all()
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        (rid, school, title, url, is_read, is_star, read_at, star_at, fetched) = r
        key = (school or -1, normalize_notice_url(url), normalize_notice_title(title))
        groups.setdefault(key, []).append({
            "id": rid, "school": school, "title": title or "", "url": url or "",
            "read": bool(is_read), "star": bool(is_star),
            "read_at": read_at, "star_at": star_at, "fetched": fetched,
        })
    return {k: v for k, v in groups.items() if len(v) > 1}


def pick_keeper(dups: list[dict]) -> dict:
    # 1) 被读/星标者优先  2) fetched_at 最早（None 视为最旧）  3) id 最小
    pool = sorted(dups, key=lambda d: (
        not (d["read"] or d["star"]),      # False(交互过) 在前
        d["fetched"] is None,              # None 视为最旧
        d["fetched"] or d["id"],           # fetched_at 升序
        d["id"],
    ))
    return pool[0]


def plan(db) -> tuple[list[dict], int, int, int, int]:
    groups = load_groups(db)
    deletes: list[dict] = []
    n_calc = n_star = 0
    pending = sum(len(v) - 1 for v in groups.values())
    for key, dups in groups.items():
        keep = pick_keeper(dups)
        if keep is None:
            continue
        for d in dups:
            if d["id"] == keep["id"]:
                continue
            deletes.append({**d, "keep_id": keep["id"]})
            if d["read"]:
                n_calc += 1
            if d["star"]:
                n_star += 1
    n_delete = len(deletes)
    return groups, pending, n_delete, n_calc, n_star


def inspect(db) -> None:
    groups, pending, n_delete, n_calc, n_star = plan(db)
    print(f"== 公告重复组（校+归一URL+归一标题）: {len(groups)} 组，可删 {n_delete} 行 "
          f"（read 状态迁移 {n_calc}，star 状态迁移 {n_star}）==")
    shown = 0
    for key, dups in groups.items():
        if shown >= 12:
            print(f"  ... 其余 {len(groups) - shown} 组略")
            break
        keep = pick_keeper(dups)
        print(f"  school={key[0]} url={key[1][:56]}")
        print(f"      保留 id={keep['id']} read={keep['read']} title={keep['title'][:34]!r}")
        for d in dups:
            if d["id"] != keep["id"]:
                print(f"      删除 id={d['id']} read={d['read']} star={d['star']} "
                      f"title={d['title'][:34]!r} fetched={str(d['fetched'])[:10]}")
        shown += 1
    print(f"\n[dry-run] 未动库（--apply 执行）")


def apply(db) -> None:
    groups, _pending, n_delete, n_calc, n_star = plan(db)
    if not n_delete:
        print("无重复，无需处理")
        return
    # 1) 备份
    del_ids: list[int] = []
    per_group_keep: dict[int, dict] = {}
    row_map: dict[int, tuple[dict, int]] = {}
    for key, dups in groups.items():
        keep = pick_keeper(dups)
        per_group_keep[keep["id"]] = keep
        for d in dups:
            if d["id"] != keep["id"]:
                del_ids.append(d["id"])
                row_map[d["id"]] = (d, keep["id"])
    db.execute(text(f"drop table if exists {TABLE}{BACKUP_SUFFIX}"))
    db.execute(text(
        f"create table {TABLE}{BACKUP_SUFFIX} as select * from {TABLE} where id = any(:ids)"
    ), {"ids": del_ids})
    print(f"备份 {len(del_ids)} 行 → {TABLE}{BACKUP_SUFFIX}")

    # 2) 状态迁移到保留行（read/starred 取并；时间取最早）
    migrated = 0
    for did in del_ids:
        d, keep_id = row_map[did]
        k = per_group_keep[keep_id]
        db.execute(text(f"""
            update {TABLE} set
              is_read    = is_read or :r,
              is_starred = is_starred or :s,
              read_at = coalesce(read_at, cast(:ra as text)),
              starred_at = coalesce(starred_at, cast(:sa as text))
            where id = :k
        """), {"r": d["read"], "s": d["star"],
               "ra": d["read_at"], "sa": d["star_at"], "k": k["id"]})
        migrated += 1
    # 3) 删除
    db.execute(text(f"delete from {TABLE} where id = any(:ids)"), {"ids": del_ids})
    db.commit()
    total = db.execute(text(f"select count(*) from {TABLE}")).scalar()
    print(f"[APPLIED] 备份 {len(del_ids)} 行，状态迁移 {migrated} 行，删除 {len(del_ids)} 行；"
          f"剩 {int(total):,} 行（read 迁移 {n_calc}，star 迁移 {n_star}）")


def main() -> int:
    from database import SessionLocal

    db = SessionLocal()
    try:
        if "--apply" in sys.argv:
            apply(db)
        else:
            inspect(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
