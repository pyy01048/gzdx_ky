# -*- coding: utf-8 -*-
"""P1-4：补齐 14 个缺失的 subject_configs 科目配置行。

背景
----
``subject_config`` 是视图（subjects LEFT JOIN subject_configs），而
``subject_configs`` 才是真实配置表。当前 subjects 表有 47 个科目，
但 ``subject_configs`` 只有 33 行配置，缺少 14 个科目：

    id  1,2,3,4,5,68,69,70,71,72,73,74,75,76
    （通信原理/电路/DSP/电磁场/计网 + 半导体物理/传感器/单片机/测控电路/
      激光原理/Python/C-C++/电子技术基础/生物医学工程）

本脚本幂等补种：只插入 ``subject_id`` 尚不存在的行，已存在的不覆盖。
question_types 默认取 ``services.taxonomy.QUESTION_TYPES`` 对应值；
无配置的科目用 ``DEFAULT_QUESTION_TYPES`` 兜底。

安全
----
* 默认 dry-run，只打印计划，不写库；
* ``--apply`` 先备份 ``subject_configs``（pg_dump 到 database/backups/），再插入；
* 只写 ``subject_configs`` 表，不触碰 subjects / subject_chapters / 业务表。

用法
----
    python scripts/backfill_subject_configs.py            # dry-run
    python scripts/backfill_subject_configs.py --apply    # 备份并写库
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.db_session import SessionLocal  # noqa: E402
from core.models import Subject as CoreSubject, SubjectConfig as CoreSubjectConfig  # noqa: E402
from services import taxonomy  # noqa: E402

#: 待补种的目标 subject_id 列表（经诊断确认的 14 个缺失科目）
MISSING_SUBJECT_IDS = [
    1, 2, 3, 4, 5, 68, 69, 70, 71, 72, 73, 74, 75, 76,
]

BACKUP_DIR = r"D:\平台\database\backups"


def _backup_subject_configs() -> str:
    """用 pg_dump 备份 subject_configs 表到 database/backups/。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(BACKUP_DIR, f"subject_configs_backup_before_p14_{stamp}.sql")
    env = dict(os.environ)
    env["PGPASSWORD"] = env.get("PGPASSWORD", "kaoyan_dev_2026")
    cmd = [
        "D:/pgsql/pgenv/Library/bin/pg_dump",
        "-h", "127.0.0.1", "-U", "kaoyan", "-d", "kaoyan",
        "-t", "public.subject_configs", "-f", out,
    ]
    subprocess.run(cmd, check=True, env=env)
    return out


def plan(db) -> list[tuple[int, str, list[str]]]:
    """返回待补种的 (subject_id, subject_name, question_types) 列表。"""
    existing_ids = {r[0] for r in db.query(CoreSubjectConfig.subject_id).all()}
    rows = db.query(CoreSubject).filter(CoreSubject.id.in_(MISSING_SUBJECT_IDS)).all()
    rows_by_id = {r.id: r for r in rows}
    out: list[tuple[int, str, list[str]]] = []
    for sid in MISSING_SUBJECT_IDS:
        if sid in existing_ids:
            continue
        subj = rows_by_id.get(sid)
        if subj is None:
            continue
        types = taxonomy.QUESTION_TYPES.get(subj.name, taxonomy.DEFAULT_QUESTION_TYPES)
        out.append((sid, subj.name, list(types)))
    return out


def apply(db) -> int:
    """执行补种，返回插入行数。"""
    inserts = plan(db)
    for sid, name, types in inserts:
        db.add(CoreSubjectConfig(
            subject_id=sid,
            question_types=list(types),
            is_custom=False,
            extra={},
        ))
    if inserts:
        db.commit()
    return len(inserts)


def verify(db) -> None:
    """打印验收统计。"""
    total_subjects = db.query(CoreSubject).count()
    configured = db.query(CoreSubjectConfig).count()
    missing = (
        db.query(CoreSubject)
        .outerjoin(CoreSubjectConfig, CoreSubjectConfig.subject_id == CoreSubject.id)
        .filter(CoreSubjectConfig.id.is_(None))
        .order_by(CoreSubject.id)
        .all()
    )
    print("\n" + "=" * 70)
    print("验收")
    print("=" * 70)
    print(f"subjects 总数: {total_subjects}")
    print(f"subject_configs 配置行数: {configured}  （目标 ≥ 47）")
    print(f"仍缺配置的科目: {len(missing)}")
    for m in missing:
        print(f"  id={m.id} {m.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="补齐 subject_configs 缺失科目配置")
    parser.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        missing_plan = plan(db)
        if not args.apply:
            print("=" * 70)
            print("DRY-RUN（未写库）")
            print("=" * 70)
            print(f"待补种 {len(missing_plan)} 行：")
            for sid, name, types in missing_plan:
                print(f"  subject_id={sid:>3}  {name:<14} question_types={types}")
            print("\n确认后执行：python scripts/backfill_subject_configs.py --apply")
            return 0

        backup_path = _backup_subject_configs()
        print(f"[backup] {backup_path}")
        inserted = apply(db)
        print(f"[apply] 已补种 {inserted} 行 subject_configs")
        verify(db)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())