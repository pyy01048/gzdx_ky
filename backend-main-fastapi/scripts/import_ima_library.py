# -*- coding: utf-8 -*-
"""
IMA 知识库 → 本地 documents 表 导入器
=====================================
职责：读 staging 库(ima_inventory.db)的条目 → 用 ima_classify 分类 → 写入真库 documents 表。

设计约束（与项目既有脚本同规格）：
- **幂等**：以 ima_media_id 为去重键，重跑不会产生重复行。
- **dry-run 默认**：不加 --apply 只打印计划，不写库。
- **写库前自动备份**：sqlite backup API（真库是 WAL 模式，禁止 shutil.copy）。
- **可审计**：输出分类分布 + 存疑清单 + 审计 JSON。

字段映射（IMA → documents）：
    title        → file_name
    media_id     → file_path / ima_media_id   （IMA 指针，正文按需 fetch，不落库）
    media_type   → file_type                  （pdf/word/image）
    file_size    → size
    分类结果      → subject / doc_type / stage
    folder_path  → folder_path
    introduction → content                     （IMA 已解析文本，作为初始正文）
    固定          → subject_source='ima', index_status='pending'

用法：
    python import_ima_library.py                 # dry-run，只看计划
    python import_ima_library.py --apply         # 真正写库（自动备份）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# 让脚本能 import 同目录的 ima_classify
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ima_classify import classify_item  # noqa: E402

# 真库（由 .env 的 DATABASE_PATH 指定；backend-main-fastapi/data/kaoyan.db 是诱饵库，禁止使用）
REAL_DB = os.environ.get("DATABASE_PATH") or r"D:\平台\database\kaoyan.db"
STAGING_DB = r"D:\平台\tools\datasource\ima_inventory.db"
BACKUP_DIR = r"D:\平台\backend-main-fastapi\data\backups"
AUDIT_PATH = r"D:\平台\docx\_analysis\ima-import-audit.json"

# IMA media_type → 本地 file_type
MEDIA_TYPE_MAP = {
    1: "pdf",
    3: "word",
    9: "image",
    99: "folder",  # 文件夹：不导入
}


def load_staging_items(staging_db: str) -> list[dict]:
    """读取 staging 库中的**文件类**条目（排除文件夹节点）。"""
    if not os.path.exists(staging_db):
        raise FileNotFoundError(f"staging 库不存在：{staging_db}")
    con = sqlite3.connect(staging_db)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT media_id, title, media_type, file_size, folder_path, intro, can_fetch_content "
            "FROM ima_items WHERE media_type != 99 ORDER BY folder_path, title"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def build_plan(items: list[dict]) -> list[dict]:
    """对每条 staging 条目做分类，生成入库计划。"""
    plan = []
    for it in items:
        title = it.get("title") or ""
        path = it.get("folder_path") or ""
        intro = it.get("intro") or ""
        cls = classify_item(title, path, intro)
        plan.append({
            "media_id": it["media_id"],
            "file_name": title,
            "file_type": MEDIA_TYPE_MAP.get(it.get("media_type"), "unknown"),
            "size": int(it.get("file_size") or 0),
            "folder_path": path,
            "can_fetch_content": int(it.get("can_fetch_content") or 0),
            "content_preview_len": len(intro),
            # IMA 已解析的正文（introduction）。注意：采集时为省上下文，
            # 部分条目 intro 留空 —— 空的不覆盖已有 content。
            "intro": intro,
            **cls,
        })
    return plan


def backup_real_db(real_db: str) -> str:
    """sqlite backup API 备份（WAL 安全）。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_imaimport_{ts}.db")
    src = sqlite3.connect(real_db)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def apply_plan(plan: list[dict], real_db: str) -> dict:
    """把计划写入真库 documents 表（幂等：ima_media_id 已存在则跳过）。"""
    con = sqlite3.connect(real_db)
    con.execute("PRAGMA busy_timeout = 30000")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted, skipped, updated = 0, 0, 0
    try:
        # 幂等去重：先看已有 ima_media_id
        have = {r[0] for r in con.execute(
            "SELECT ima_media_id FROM documents WHERE ima_media_id IS NOT NULL"
        )}
        for p in plan:
            mid = p["media_id"]
            if mid in have:
                # 已存在则刷新分类（分类规则可能迭代），但不新增行。
                # 注意：绝不覆盖 doc_type —— 该列是既有语义(raw/note/index 三层结构)，
                # IMA 的"知识/试题/单词"存在新列 content_type，避免两套语义混用。
                # 已有行：刷新分类；正文仅在 IMA 侧有值时补齐（绝不覆盖已有正文）
                if p.get("intro"):
                    con.execute(
                        "UPDATE documents SET subject=?, content_type=?, stage=?, folder_path=?, "
                        "content=?, updated_at=? WHERE ima_media_id=?",
                        (p["subject"], p["doc_type"], p["stage"], p["folder_path"],
                         p["intro"], now, mid),
                    )
                else:
                    con.execute(
                        "UPDATE documents SET subject=?, content_type=?, stage=?, folder_path=?, "
                        "updated_at=? WHERE ima_media_id=?",
                        (p["subject"], p["doc_type"], p["stage"], p["folder_path"], now, mid),
                    )
                updated += 1
                continue
            con.execute(
                "INSERT INTO documents (file_name, file_path, file_type, size, subject, "
                "doc_type, content_type, stage, ima_media_id, folder_path, subject_source, "
                "content, index_status, parse_progress, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    p["file_name"], mid, p["file_type"], p["size"],
                    p["subject"],
                    "raw",          # doc_type 保持既有语义：IMA 资料属"原始层"
                    p["doc_type"],  # 知识/试题/单词 → content_type 新列
                    p["stage"],
                    mid, p["folder_path"], "ima",
                    p.get("intro") or "",   # IMA 已解析正文（可能为空，待后续 fetch 补齐）
                    "pending", 0, now, now,
                ),
            )
            inserted += 1
        con.commit()
        return {"inserted": inserted, "updated": updated, "skipped": skipped}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="IMA 知识库导入本地 documents 表")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--staging", default=STAGING_DB, help="staging 库路径")
    ap.add_argument("--real-db", default=REAL_DB, help="真库路径")
    args = ap.parse_args()

    print(f"[1/4] 读取 staging：{args.staging}")
    items = load_staging_items(args.staging)
    print(f"      文件类条目：{len(items)} 条")

    print("[2/4] 分类中…")
    plan = build_plan(items)

    # 分布统计
    stage_c = Counter(p["stage"] for p in plan)
    subj_c = Counter(p["subject"] for p in plan)
    type_c = Counter(p["doc_type"] for p in plan)
    combo_c = Counter((p["stage"], p["subject"], p["doc_type"]) for p in plan)
    review = [p for p in plan if p["needs_review"]]

    print("\n=== 分类分布 ===")
    print(f"  stage  : {dict(stage_c)}")
    print(f"  doc_type: {dict(type_c)}")
    print("  subject:")
    for s, n in subj_c.most_common():
        print(f"      {s:12s} {n}")
    print("\n  stage × subject × doc_type（TOP15）:")
    for (st, sj, dt), n in combo_c.most_common(15):
        print(f"      {st}/{sj}/{dt}  → {n}")

    print(f"\n  存疑待复核(subject=其他): {len(review)} 条")
    for p in review[:10]:
        print(f"      - {p['file_name'][:50]}")

    # 审计落盘
    os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "staging_db": args.staging,
            "total": len(plan),
            "distribution": {
                "stage": dict(stage_c),
                "subject": dict(subj_c),
                "doc_type": dict(type_c),
            },
            "needs_review": [{"file_name": p["file_name"], "folder": p["folder_path"]} for p in review],
            "items": [{k: v for k, v in p.items() if k != "reason"} for p in plan],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[3/4] 审计已写入：{AUDIT_PATH}")

    if not args.apply:
        print("[4/4] DRY-RUN 结束（未写库）。加 --apply 执行导入。")
        return 0

    print("[4/4] 备份真库并写入…")
    bak = backup_real_db(args.real_db)
    print(f"      备份：{bak}")
    res = apply_plan(plan, args.real_db)
    print(f"      结果：新增 {res['inserted']} / 更新分类 {res['updated']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
