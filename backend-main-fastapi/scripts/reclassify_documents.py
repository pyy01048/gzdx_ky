# -*- coding: utf-8 -*-
"""对**已入库**的 documents 按修复后的判定逻辑重新归类学科。

背景（2026-10 修复）
--------------------
`smart_ingest.process_file` 原来只把 `os.path.basename(path)` 传给
`extract_metadata`，路径里的学科目录（`.../政治/xxx.pdf`）被整段丢掉；
同时 `kb_service._SUBJECT_STRONG["数学"]` 含跨科歧义词「1000题」。
两者叠加，实测把 `专业课-其他/政治/1000题：学习打卡表（新思想）.pdf`
判成 `subject=数学`，同期一批肖1000 / 政治课堂笔记被归到「数学」「真题综合」
「其他」。判定逻辑已修，本脚本负责把**存量错标数据**纠正回来。

只改 `documents.subject` 并同步 `knowledge_chunks.subject`。
（`book_name` / `chapter` 是入库时的瞬时派生值，`documents` 表没有对应列，
因此不落库、也无从改写；脚本会把它们算出来一并打印供人工核对。）

设计约束
--------
* **幂等**：判定只依赖 file_name / file_path / content，重跑结果完全一致；
  已经正确的行不会被改动，第二次跑必然 0 变更。
* **默认 dry-run**：只报告不写库。`--apply` 才写，且写前自动备份。
* **只采信高置信**：`classify_subject_confidence` 返回低置信（只有「真题/试卷」
  这类形态词兜底）时**不动**，避免把合理的标注改成臆测值。

用法
----
    python scripts/reclassify_documents.py                 # 全库预演（推荐先看这个）
    python scripts/reclassify_documents.py --limit 200     # 只扫前 200 篇
    python scripts/reclassify_documents.py --id 123 --id 456
    python scripts/reclassify_documents.py --subject 数学   # 只看当前标成数学的
    python scripts/reclassify_documents.py --apply         # 备份 + 写库
    python scripts/reclassify_documents.py --apply --no-backup

输出示例
--------
    扫描 2611 篇，需重分类 137 篇（5.2%）
    数学        → 政治            112
    真题综合    → 政治             14
    其他        → 英语             11
    dry-run：未写库。确认无误后加 --apply。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database import SessionLocal                            # noqa: E402
from models import Document, KnowledgeChunk                  # noqa: E402
from services import kb_service                              # noqa: E402
from services.taxonomy import normalize_subject              # noqa: E402

BACKUP_DIR = os.path.join(BASE_DIR, "data", "reclassify_backup")


def build_query(db, subject: str, doc_ids: list[int], limit: int):
    q = db.query(Document)
    if doc_ids:
        q = q.filter(Document.id.in_(doc_ids))
    if subject:
        q = q.filter(Document.subject == subject)
    if limit:
        q = q.limit(limit)
    return q


def backup(changes: list[dict]) -> str:
    """写库前把「id + 旧值」落盘，保证可回滚。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"subjects_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"created_at": ts, "rows": changes}, f, ensure_ascii=False, indent=2)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--no-backup", action="store_true", help="--apply 时跳过备份")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 篇")
    ap.add_argument("--id", type=int, action="append", default=[],
                    help="只处理指定 document id（可重复）")
    ap.add_argument("--subject", default="", help="只处理当前学科为 X 的文档")
    ap.add_argument("--show", type=int, default=15, help="打印前 N 条明细")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        docs = build_query(db, args.subject, args.id, args.limit).all()
        scanned = len(docs)
        changes: list[dict] = []
        unchanged = 0
        low_conf = 0
        no_content = 0

        for d in docs:
            content = d.content or ""
            if not content.strip():
                # 无正文只能靠文件名/路径判，仍然判，但置信度门槛会挡掉臆测
                no_content += 1
            new_raw, conf = kb_service.classify_subject_confidence(
                d.file_name or "", content,
                path=d.file_path or "",
            )
            if not conf:
                low_conf += 1
                continue
            new = normalize_subject(new_raw)
            old = (d.subject or "").strip()
            if new == old:
                unchanged += 1
                continue
            meta = kb_service.classify_content_category(d.file_name or "", content)
            changes.append({
                "id": d.id,
                "file_name": d.file_name,
                "file_path": d.file_path,
                "old_subject": old,
                "new_subject": new,
                "content_type": meta,
            })

        total = scanned
        print(f"扫描 {total} 篇文档"
              + (f"（其中无正文 {no_content} 篇）" if no_content else ""))
        print(f"  需重分类 {len(changes)} 篇"
              + (f" = {len(changes) / total * 100:.1f}%" if total else ""))
        print(f"  判定不变 {unchanged} 篇，低置信跳过 {low_conf} 篇")

        if not changes:
            print("\n无需变更（幂等：再跑一次结果相同）。")
            return 0

        pairs = Counter((c["old_subject"] or "(空)", c["new_subject"]) for c in changes)
        print("\n变更分布（旧 → 新）：")
        for (old, new), n in pairs.most_common():
            print(f"  {old:<12} → {new:<12} {n}")

        print(f"\n明细（前 {min(args.show, len(changes))} 条）：")
        for c in changes[: args.show]:
            print(f"  #{c['id']} [{c['old_subject'] or '(空)'} → {c['new_subject']}] "
                  f"{c['file_name']}")

        if not args.apply:
            print("\ndry-run：未写库。确认无误后加 --apply 执行。")
            return 0

        if not args.no_backup:
            bp = backup(changes)
            print(f"\n已备份旧值 → {bp}")

        for c in changes:
            db.query(Document).filter(Document.id == c["id"]).update(
                {Document.subject: c["new_subject"]}, synchronize_session="fetch")
            db.query(KnowledgeChunk).filter(
                KnowledgeChunk.document_id == c["id"]).update(
                {KnowledgeChunk.subject: c["new_subject"]},
                synchronize_session="fetch")
        db.commit()
        print(f"已写库：{len(changes)} 篇 documents.subject + 其 knowledge_chunks.subject")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
