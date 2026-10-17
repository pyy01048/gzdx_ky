# -*- coding: utf-8 -*-
"""知识点**分批**回填：对已入库文档补抽 `knowledge_points`。

## 为什么只能分批

实测（RTX 4060 Laptop 8GB / qwen2.5-coder:7b）：
  * 单 chunk 约 19–20s，`max_chunks=8` 下一篇约 55–75s（并发 2 实测有效）；
  * 单篇产出被 `SMART_INGEST_KP_MAX_PER_DOC=15` 封顶，`max_chunks=5` 就能拿到 13 个，
    8 块只是把丢弃数拉高 —— 赶时间时用 `--max-chunks 5` 可省约 30% 时间。
  * 由此：约 **55–65 篇/小时**。全量 3584 篇 ≈ 55–65 小时连续跑，**不可一次做完**。

## 用法

    # 先看方案（不调模型、不写库）
    python scripts/kp_backfill_batch.py --subject 政治 --limit 50 --dry-run

    # 真跑：政治 50 篇
    python scripts/kp_backfill_batch.py --subject 政治 --limit 50

    # 指定文档
    python scripts/kp_backfill_batch.py --ids 30,24,25

    # 数学教材（质量较差，见下方说明）
    python scripts/kp_backfill_batch.py --subject 数学 --limit 30 --max-chunks 8

## 优先级建议

1. 政治（讲义/思维导图类，实测质量最好：13–15 个/篇，全是真知识点）
2. 专业课教材（`专业课-贵大834` 等，篇数少、价值高）
3. 数学讲义/公式手册 —— **教材类（习题全解指南、含前言版权页的）质量差**，
   实测会抽出「邱伯骆」（作者名）、「习题全解」「精品课程教材」这类前言噪声，
   当前 `_BOILERPLATE_PATTERNS` 没盖住作者名与「精品课程教材」。建议先跑前先补名单，
   否则会污染知识图谱。

## 一个坑：本脚本**无法**靠 rollback 做"假跑"

`extract_kps_for_document` 在落库后自己 `db.commit()`（`services/kp_extract.py`
插入成功分支），调用方事后再 `db.rollback()` 已经无效 —— 实测因此意外落了 81 条。
要"只看不写"就用 `--dry-run`（它在调模型之前就返回）。

## 前置条件

Ollama 必须已启动并监听 127.0.0.1:11434（见 `scripts/start_ollama.ps1`）。
本脚本**不会**自己拉起 Ollama；长时间批量建议另开一个终端跑
`python scripts/_ollama_watchdog.py`。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

PG_URL = os.environ.get(
    "KP_BACKFILL_DB_URL",
    "postgresql+psycopg://kaoyan:kaoyan_dev_2026@127.0.0.1:5432/kaoyan",
)

#: 优先级排序：目标科目靠前，其次按正文长度（长的通常内容更实）
_ORDER_BY = """
ORDER BY
  CASE subject
    WHEN '政治' THEN 0
    WHEN '数学' THEN 1
    WHEN '数字电子技术' THEN 2
    WHEN '模拟电子技术' THEN 2
    ELSE 3
  END,
  length(coalesce(content,'')) DESC
"""


def pick_documents(db, subject: str | None, limit: int, ids: list[int],
                   min_chars: int):
    """选出待回填文档：已有知识点的跳过（幂等，可重复跑）。"""
    where = [
        "coalesce(is_junk,false) = false",
        f"length(coalesce(content,'')) >= {int(min_chars)}",
        # 幂等：已经有知识点的文档不再重复抽
        "NOT EXISTS (SELECT 1 FROM knowledge_points kp WHERE kp.document_id = documents.id)",
    ]
    params: dict = {}
    if ids:
        where.append("id = ANY(:ids)")
        params["ids"] = ids
    elif subject:
        where.append("subject = :subject")
        params["subject"] = subject
    sql = ("SELECT id, file_name, subject, length(coalesce(content,'')) "
           "FROM documents WHERE " + " AND ".join(where) + _ORDER_BY
           + " LIMIT :limit")
    params["limit"] = limit
    return db.execute(text(sql), params).fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default=None, help="按学科过滤，如 政治 / 数学")
    ap.add_argument("--ids", default=None, help="逗号分隔的 doc_id，优先于 --subject")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--max-chunks", type=int, default=8,
                    help="单篇最多抽多少块；赶时间用 5（实测省 30% 且产出只少约 2 个）")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--min-chars", type=int, default=800)
    ap.add_argument("--dry-run", action="store_true", help="只列出将处理的文档，不调模型")
    args = ap.parse_args()

    ids = [int(x) for x in args.ids.split(",") if x.strip()] if args.ids else []
    eng = create_engine(PG_URL)
    Session = sessionmaker(bind=eng)
    db = Session()

    rows = pick_documents(db, args.subject, args.limit, ids, args.min_chars)
    if not rows:
        print("没有符合条件的文档（可能都已抽过，或过滤条件太严）")
        return 0

    est = len(rows) * (49 if args.max_chunks <= 5 else 65)
    print(f"待处理 {len(rows)} 篇，预计 {est/60:.0f}–{est*1.3/60:.0f} 分钟"
          f"（按 {'49' if args.max_chunks <= 5 else '65'}s/篇 估）")
    for r in rows:
        print(f"  #{r[0]:<5} {r[3]:>7}字 [{r[2]}] {str(r[1])[:52]}")
    if args.dry_run:
        print("\n[dry-run] 未调模型、未写库。")
        return 0

    import services.kp_extract as kp

    print(f"\nKP_MODEL={kp.KP_MODEL}  OLLAMA_HOST={kp._OLLAMA_HOST}")
    t_start = time.time()
    total_kept = 0
    for i, r in enumerate(rows, 1):
        doc_id, file_name, subject = r[0], r[1], r[2]
        row = db.execute(
            text("SELECT content, chapter FROM documents WHERE id=:d"),
            {"d": doc_id}).fetchone()
        t0 = time.time()
        try:
            out = kp.extract_kps_for_document(
                db, doc_id=doc_id, text=row[0] or "", file_name=file_name,
                doc_subject=subject or "", chapter=row[1] or "",
                concurrency=args.concurrency, max_chunks=args.max_chunks)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(rows)}] #{doc_id} ✗ {type(e).__name__}: {e}"[:200])
            db.rollback()
            continue
        secs = round(time.time() - t0, 1)
        total_kept += int(out.get("kept") or 0)
        flag = "✓" if out.get("kept") else ("skip" if out.get("skipped") else "✗")
        print(f"[{i}/{len(rows)}] #{doc_id} {flag} {secs:>6.1f}s "
              f"kept={out.get('kept')} dropped={out.get('dropped')} "
              f"failed={out.get('failed')} {out.get('subject_mix')} "
              f"| {str(file_name)[:36]}")
        if out.get("errors"):
            print("      errors:", out["errors"][:2])

    print(f"\n完成 {len(rows)} 篇，新增知识点 {total_kept} 个，"
          f"总耗时 {round(time.time()-t_start)/60:.1f} 分钟")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
