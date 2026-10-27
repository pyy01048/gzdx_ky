# -*- coding: utf-8 -*-
"""断链文档路径修复：按文件名在知识库内重新定位，回写 file_path。

背景（2026-10 体检实测）
------------------------
``documents.file_path`` 有值但文件已不存在的记录共 **378** 条，成因是
入库后文件被移动到别的目录（如 ``inbox/数电/`` → ``documents/2026/数电/``），
而 ``file_path`` 没有同步更新 —— 是**路径失联**，不是数据丢失。

实测可修复比例：
    唯一命中（同名文件在树内只有一处）  75 条  ← 本脚本处理
    多处命中（无法确定指向哪个）         0 条
    完全找不到（源文件确已删除）       303 条  ← 只报告，绝不编造路径

安全红线：
  1. **只在唯一命中时改写**：同名多处一律跳过，绝不猜测。
  2. **只改 file_path 一列**，不碰 content / canonical_content 等正文列。
  3. 默认 dry-run，加 ``--apply`` 才落库；落库前用 SQLite backup() 备份。
  4. 找不到源文件的记录保持原样，写入报告供人工处置。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

DB_DEFAULT = r"D:\平台\database\kaoyan.db"
KB_ROOT_DEFAULT = r"D:\平台\knowledge_base"


def build_tree(kb_root: str) -> dict[str, list[str]]:
    """扫描知识库，建立 文件名 → [绝对路径, ...] 索引。"""
    tree: dict[str, list[str]] = {}
    for root, _dirs, files in os.walk(kb_root):
        for name in files:
            tree.setdefault(name, []).append(os.path.join(root, name))
    return tree


def plan_repairs(conn: sqlite3.Connection, tree: dict[str, list[str]]) -> dict:
    """产出修复计划，不写库。"""
    rows = conn.execute(
        "SELECT id, file_name, file_path FROM documents "
        "WHERE file_path IS NOT NULL AND file_path <> ''"
    ).fetchall()

    fixable, missing, already_ok = [], [], 0
    for doc_id, name, path in rows:
        if os.path.exists(path):
            already_ok += 1
            continue
        hits = tree.get(name) or tree.get(os.path.basename(path))
        if not hits:
            missing.append({"id": doc_id, "file_name": name, "old_path": path})
        elif len(hits) == 1:
            fixable.append({"id": doc_id, "file_name": name,
                            "old_path": path, "new_path": hits[0]})
        else:
            # 多处命中：不猜，交人工
            missing.append({"id": doc_id, "file_name": name, "old_path": path,
                            "reason": "同名多处", "candidates": hits[:5]})

    return {
        "total_with_path": len(rows),
        "already_ok": already_ok,
        "fixable": fixable,
        "unresolved": missing,
    }


def backup_db(db_path: str) -> str:
    """SQLite 官方 backup() API 备份。禁止 cp/copy2：WAL 模式下会丢数据。"""
    target = db_path + ".bak-brokenlink-" + __import__("time").strftime("%Y%m%d-%H%M%S")
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return target


def main() -> int:
    ap = argparse.ArgumentParser(description="修复文档 file_path 断链")
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--kb-root", default=KB_ROOT_DEFAULT)
    ap.add_argument("--apply", action="store_true", help="真正落库（默认只预览）")
    ap.add_argument("--report", default="", help="报告输出路径（JSON）")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"[x] 数据库不存在：{args.db}")
        return 2

    tree = build_tree(args.kb_root)
    conn = sqlite3.connect(args.db)
    try:
        plan = plan_repairs(conn, tree)

        print("=" * 60)
        print("文档断链修复计划")
        print("=" * 60)
        print(f"  file_path 有值      {plan['total_with_path']}")
        print(f"  文件正常            {plan['already_ok']}")
        print(f"  可自动修复(唯一命中) {len(plan['fixable'])}")
        print(f"  无法定位(需人工)     {len(plan['unresolved'])}")

        if plan["fixable"]:
            print("\n  前 8 条修复明细：")
            for it in plan["fixable"][:8]:
                print(f"    #{it['id']} {it['file_name']}")
                print(f"       旧 {it['old_path']}")
                print(f"       新 {it['new_path']}")

        if args.report:
            Path(args.report).write_text(
                json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n  报告已写入：{args.report}")

        if not args.apply:
            print("\n[预览模式] 未改动数据库。确认无误后加 --apply 执行。")
            return 0

        if not plan["fixable"]:
            print("\n没有可自动修复的记录。")
            return 0

        backup = backup_db(args.db)
        print(f"\n已备份：{backup}")

        # 只改 file_path 一列；逐条独立提交，单条失败不影响整体
        fixed = failed = 0
        for it in plan["fixable"]:
            try:
                conn.execute("UPDATE documents SET file_path = ? WHERE id = ?",
                             (it["new_path"], it["id"]))
                conn.commit()
                fixed += 1
            except sqlite3.Error as exc:
                conn.rollback()
                failed += 1
                print(f"    [x] #{it['id']} 失败：{exc}")

        print(f"\n已修复 {fixed} 条，失败 {failed} 条")

        # 复核：修复后仍断链的数量
        left = 0
        for _id, _n, p in conn.execute(
            "SELECT id, file_name, file_path FROM documents "
            "WHERE file_path IS NOT NULL AND file_path <> ''"
        ):
            if not os.path.exists(p):
                left += 1
        print(f"复核：仍断链 {left} 条（原 378）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
