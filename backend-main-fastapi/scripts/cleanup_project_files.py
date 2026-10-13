# -*- coding: utf-8 -*-
"""项目文件清理：删除冗余备份 / 测试产物 / 临时诊断文件，回收磁盘空间。

保留（安全网）
------------
* D:\平台\database\kaoyan.db                         —— 线上库（权威）
* D:\平台\database\kaoyan.db.safe_20261012.db        —— 本次新建的「最终干净态」备份
* D:\平台\database\kaoyan.db.bak_m0-20261012_002221.db —— 历史基线（readmark 前）

删除（均为可重建 / 已过期的冗余副本）
--------------------------------------
* database\ 下其余所有 *.bak* / 遗留 *.db（-shm/-wal 一并删）
* backend\data\backups\ 全部（脚本生成的备份堆，3.4GB，可重建）
* backend\data\backup_v11_20261010\ 全部
* backend\data\kaoyan_before_readmark.db            （已被历史基线覆盖）
* backend\data\kaoyan.db.bak_20261007               （过期）
* backend\scripts\_*.log/_*.json/_*.jsonl/_*.txt/_*.out 临时诊断产物
* backend\ 下所有 __pycache__                        （可重建）

纪律：先造安全网备份，再删；打印回收空间与删除清单（落 manifest）。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
DBDIR = os.path.dirname(DB)
BACKEND = r"D:\平台\backend-main-fastapi"
DATA = os.path.join(BACKEND, "data")
SAFE = os.path.join(DBDIR, "kaoyan.db.safe_20261012.db")
BASELINE = os.path.join(DBDIR, "kaoyan.db.bak_m0-20261012_002221.db")
KEEP_DB = {"kaoyan.db", os.path.basename(SAFE), os.path.basename(BASELINE)}


def gb(b: float) -> str:
    return f"{b/1e9:.2f} GB"


def make_safe_backup() -> None:
    if os.path.exists(SAFE):
        print(f"[skip] 安全网已存在: {SAFE}")
        return
    src = sqlite3.connect(DB)
    out = sqlite3.connect(SAFE)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    print(f"[ok] 已建安全网: {SAFE} ({gb(os.path.getsize(SAFE))})")


def collect_deletions() -> list[str]:
    dels: list[str] = []
    # database/ 冗余
    for f in os.listdir(DBDIR):
        p = os.path.join(DBDIR, f)
        if not os.path.isfile(p):
            continue
        if f in KEEP_DB:
            continue
        if f == "kaoyan.db":
            continue
        dels.append(p)
        # 配对 sidecar
        for suf in (".db-shm", ".db-wal"):
            if os.path.exists(p + suf):
                dels.append(p + suf)
    # data/backups 整堆
    for d in (os.path.join(DATA, "backups"), os.path.join(DATA, "backup_v11_20261010")):
        if os.path.isdir(d):
            for f in os.listdir(d):
                p = os.path.join(d, f)
                if os.path.isfile(p):
                    dels.append(p)
    # data 遗留
    for f in ("kaoyan_before_readmark.db", "kaoyan.db.bak_20261007"):
        p = os.path.join(DATA, f)
        if os.path.exists(p):
            dels.append(p)
    # scripts 临时诊断
    sdir = os.path.join(BACKEND, "scripts")
    for f in os.listdir(sdir):
        if f.startswith("_") and f.endswith((".log", ".json", ".jsonl", ".txt", ".out")):
            dels.append(os.path.join(sdir, f))
    # __pycache__
    for dp, dn, fn in os.walk(BACKEND):
        if os.path.basename(dp) == "__pycache__":
            for f in fn:
                dels.append(os.path.join(dp, f))
    return dels


def main() -> int:
    make_safe_backup()
    dels = collect_deletions()
    total = sum((os.path.getsize(p) for p in dels if os.path.exists(p)), 0)
    print(f"\n将删除 {len(dels)} 个文件，预计回收 {gb(total)}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = os.path.join(BACKEND, f"cleanup_manifest_{stamp}.txt")
    removed = 0
    with open(manifest, "w", encoding="utf-8") as mf:
        for p in dels:
            mf.write(p + "\n")
            try:
                if os.path.exists(p):
                    os.remove(p)
                    removed += 1
            except Exception as e:
                print(f"  [WARN] 删失败 {p}: {e}")
    # 清理空目录（data/backups, backup_v11）
    for d in (os.path.join(DATA, "backups"), os.path.join(DATA, "backup_v11_20261010")):
        try:
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except Exception:
            pass
    print(f"[ok] 已删除 {removed} 个文件。manifest → {manifest}")
    # 验证保留
    print("\n保留核对:")
    for p in (DB, SAFE, BASELINE):
        print(f"   {'EXISTS' if os.path.exists(p) else 'MISSING!!'}  {os.path.relpath(p, r'D:\平台')} ({gb(os.path.getsize(p)) if os.path.exists(p) else 0})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
