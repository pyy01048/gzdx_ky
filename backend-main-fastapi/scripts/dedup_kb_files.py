# -*- coding: utf-8 -*-
"""knowledge_base 真·重复文件清理（按内容哈希，reference-aware）。

判定
----
* 只在 ``knowledge_base`` 目录树内找「内容完全相同（sha256 一致）」的文件；
* 对每个重复组：
  - 若组内某成员被 ``documents.file_path`` 引用（指向 knowledge_base 下），
    则**保留所有被引用的成员**（不动 DB 依赖）；
  - 若组内无成员被引用，则**保留 1 个**（路径字典序最小，确定性），其余删除；
  - 其余非引用成员一律删除（永久删除，但写 manifest 以便追溯）。
* 只删「确定冗余」的副本；绝不删唯一文件、绝不删被引用的文件。

安全
----
* 默认 dry-run，``--apply`` 才删；
* 删除前生成 manifest CSV（路径/大小/sha256/保留副本）；
* 跳过 ``_trash`` 目录（已隔离区不再参与）。

用法
----
    python scripts/dedup_kb_files.py            # dry-run 报数
    python scripts/dedup_kb_files.py --apply    # 删冗余 + 写 manifest
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

KB = r"D:\平台\knowledge_base"
DB = r"D:\平台\database\kaoyan.db"


def norm_rel(path: str) -> str:
    """把绝对/相对路径归一为 knowledge_base 之下的相对键（小写，正斜杠）。"""
    p = path.replace("\\", "/").lower()
    idx = p.find("knowledge_base/")
    if idx >= 0:
        return p[idx + len("knowledge_base/"):]
    return p


def referenced_rel_paths() -> set:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT file_path FROM documents WHERE file_path IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    refs = set()
    for (fp,) in rows:
        if "knowledge_base" in fp.replace("\\", "/").lower():
            refs.add(norm_rel(fp))
    return refs


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正删除冗余副本（默认 dry-run）")
    args = ap.parse_args()

    refs = referenced_rel_paths()
    print(f"documents 引用且位于 knowledge_base 下的文件数: {len(refs)}")

    # 1) 按大小预分组
    size_map: dict[int, list[str]] = {}
    for dp, dn, fn in os.walk(KB):
        if "_trash" in dp:
            continue
        for f in fn:
            p = os.path.join(dp, f)
            try:
                sz = os.path.getsize(p)
            except Exception:
                continue
            size_map.setdefault(sz, []).append(p)

    dup_sizes = {s: ps for s, ps in size_map.items() if len(ps) > 1}

    # 2) 对同大小文件做内容哈希，找精确重复组
    groups: list[list[str]] = []
    for s, ps in dup_sizes.items():
        hm: dict[str, list[str]] = {}
        for p in ps:
            try:
                hm.setdefault(sha256_of(p), []).append(p)
            except Exception:
                continue
        for h, members in hm.items():
            if len(members) > 1:
                groups.append(members)

    # 3) reference-aware 决策
    keep: list[str] = []
    delete: list[str] = []
    referenced_in_groups = 0
    for members in groups:
        rels = [norm_rel(m) for m in members]
        ref_members = [m for m, r in zip(members, rels) if r in refs]
        if ref_members:
            referenced_in_groups += 1
            keep.extend(ref_members)
            # 其余非引用成员删除
            for m in members:
                if m not in ref_members:
                    delete.append(m)
        else:
            # 无引用：保留字典序最小 1 个
            members_sorted = sorted(members)
            keep.append(members_sorted[0])
            delete.extend(members_sorted[1:])

    total_reclaim = sum(os.path.getsize(p) for p in delete)
    print(f"精确重复组        : {len(groups)}")
    print(f"其中含被引用成员  : {referenced_in_groups} 组")
    print(f"将保留副本        : {len(keep)} 个文件")
    print(f"将删除冗余        : {len(delete)} 个文件")
    print(f"预计回收空间      : {total_reclaim/1e9:.2f} GB")

    if not args.apply:
        print("\n[dry-run] 未删除。加 --apply 执行（并写 manifest）。")
        # 抽样展示
        shown = 0
        for members in groups:
            rels = [norm_rel(m) for m in members]
            ref_members = [m for m, r in zip(members, rels) if r in refs]
            kept = ref_members if ref_members else [sorted(members)[0]]
            removed = [m for m in members if m not in kept]
            if removed:
                shown += 1
                if shown <= 15:
                    print(f"  组: 保留={[os.path.relpath(k, KB) for k in kept]}")
                    print(f"      删除={[os.path.relpath(d, KB) for d in removed]}")
        return 0

    # 4) 执行删除 + manifest
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = os.path.join(KB, f"_trash", f"dedup_manifest_{stamp}.csv")
    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    with open(manifest, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["deleted_path", "size_bytes", "sha256", "kept_twin"])
        for m in delete:
            h = sha256_of(m)
            twins = [x for grp in groups for x in grp if x != m and sha256_of(x) == h] if False else []
            # 计算同组保留副本
            kept_twin = ""
            for grp in groups:
                if m in grp:
                    rels = [norm_rel(x) for x in grp]
                    ref_members = [x for x, r in zip(grp, rels) if r in refs]
                    twins = ref_members if ref_members else [sorted(grp)[0]]
                    kept_twin = "; ".join(os.path.relpath(t, KB) for t in twins if t != m)
                    break
            w.writerow([m, os.path.getsize(m), h, kept_twin])
            try:
                os.remove(m)
            except Exception as e:
                print(f"  [WARN] 删除失败 {m}: {e}")
    print(f"\n已删除 {len(delete)} 个冗余副本。manifest → {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
