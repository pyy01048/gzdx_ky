"""把 `knowledge_chunks.subject` 全库同步进检索镜像（fts / vec），并体检镜像一致性。

背景（2026-10-13 全库实测）：学科过滤打在镜像列上，而镜像列是入库时的拷贝，
历次回填/弃权只改了 chunk 表 →
  · FTS 学科漂移 9704/61032 = 15.90%
  · 1235 块 chunk 表已判「其他」（junk 弃权）但镜像仍挂具体学科，弃权块照样进学科池
  · FTS 孤儿 243 行 / vec 孤儿 267 行（chunk 已删但镜像还在，检索会召回不存在的内容）
  · vec 镜像只覆盖 18433/61091 = 30.2% 的块（向量召回本身就只跑三分之一语料）

用法：
    python scripts/sync_chunk_mirrors.py --dry-run        # 只体检，不写
    python scripts/sync_chunk_mirrors.py                  # 同步 subject（幂等）
    python scripts/sync_chunk_mirrors.py --prune-orphans  # 额外删除孤儿镜像行（需显式开关）

红线：本脚本**从不删除 chunk**，只在 `--prune-orphans` 下删除"其 chunk 已不存在"的
镜像行；不重算向量（vec 覆盖率只报告，补齐请走 `scripts/` 的向量重建链路）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from sqlalchemy import text  # noqa: E402

from services.chunk_classifier import MIRROR_TABLES, sync_mirror_subjects  # noqa: E402


def _subject_map(db, sql: str) -> dict:
    return {int(i): (s or "") for i, s in db.execute(text(sql)).fetchall()}


def audit(db) -> dict:
    """镜像一致性体检：漂移 / 弃权未同步 / 孤儿 / 覆盖率。"""
    kc = _subject_map(db, "SELECT id, subject FROM knowledge_chunks")
    res = {"chunks": len(kc)}
    for tbl, key in MIRROR_TABLES:
        try:
            mir = _subject_map(db, f"SELECT {key}, subject FROM {tbl}")
        except Exception as e:  # noqa: BLE001
            print(f"  {tbl}: 读取失败（表可能尚未创建）{type(e).__name__}")
            continue
        comparable = [(kc[i], mir[i]) for i in mir if i in kc and kc[i]]
        drift = sum(1 for a, b in comparable if a != b)
        # 镜像里挂具体学科、chunk 表却已判「其他」= 弃权未生效
        abstain_leak = sum(1 for i in mir
                           if kc.get(i) == "其他" and mir[i] not in ("", "其他"))
        orphans = sum(1 for i in mir if i not in kc)
        missing = sum(1 for i in kc if i not in mir)
        n = len(comparable) or 1
        res[tbl] = {"rows": len(mir), "comparable": len(comparable),
                    "drift": drift, "drift_rate": round(drift / n, 4),
                    "abstain_leak": abstain_leak, "orphans": orphans,
                    "missing": missing,
                    "coverage": round(len(mir) / (len(kc) or 1), 4)}
    return res


def print_audit(a: dict) -> None:
    print(f"  knowledge_chunks 块数：{a['chunks']}")
    for k, v in a.items():
        if k == "chunks":
            continue
        print(f"  {k}: 行 {v['rows']}  可比 {v['comparable']}  "
              f"学科漂移 {v['drift']} ({v['drift_rate']:.2%})  "
              f"弃权未同步 {v['abstain_leak']}  孤儿 {v['orphans']}  "
              f"未入镜像 {v['missing']}  覆盖率 {v['coverage']:.2%}")


def prune_orphans(db) -> dict:
    out = {}
    for tbl, key in MIRROR_TABLES:
        stmt = text(f"DELETE FROM {tbl} WHERE NOT EXISTS "
                    f"(SELECT 1 FROM knowledge_chunks kc WHERE kc.id = {tbl}.{key})")
        try:
            r = db.execute(stmt)
            db.commit()
            out[tbl] = int(r.rowcount or 0)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print(f"  {tbl} 孤儿清理失败: {type(e).__name__}: {e}")
            out[tbl] = -1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="检索镜像学科同步与一致性体检")
    ap.add_argument("--dry-run", action="store_true", help="只体检，不写库")
    ap.add_argument("--prune-orphans", action="store_true",
                    help="删除 chunk 已不存在的镜像行（默认不删）")
    args = ap.parse_args()

    from database import SessionLocal
    db = SessionLocal()
    try:
        print("=== 同步前体检 ===")
        before = audit(db)
        print_audit(before)

        if args.dry_run:
            print("\n--dry-run：未写入。去掉该参数即执行 subject 同步（幂等）。")
            return 0

        print("\n=== 执行 subject 全库同步 ===")
        synced = sync_mirror_subjects(db)
        print(f"  影响行数：{synced}")
        if args.prune_orphans:
            removed = prune_orphans(db)
            print(f"  孤儿镜像行已删除：{removed}")
        print("\n=== 同步后体检 ===")
        print_audit(audit(db))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
