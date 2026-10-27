# -*- coding: utf-8 -*-
"""把「配套题库」文档抽取出的选择题入库。

仅处理 exam_bank_extractor 能高置信解析的文档（实测：TXT 文本层规整版），
PDF 版文本层换行错乱、抽取率极低，一律跳过并在报告中列出。

安全红线：
  1. 默认 dry-run；``--apply`` 前用 SQLite backup() 备份（WAL 禁 cp）。
  2. **按内容去重**：题干 + 选项文本全同的题不重复入库（可重复执行）。
  3. 只插入，不修改、不删除任何已有题目。
  4. 入库前逐题完整性自检（题干/选项/答案均须合规）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.exam_bank_extractor import extract_from_text  # noqa: E402

DB_DEFAULT = r"D:\平台\database\kaoyan.db"

#: 候选文档筛选：题库类且文本量足够
DOC_FILTER = """
    SELECT id, file_name, content FROM documents
    WHERE (file_name LIKE '%配套题库%' OR file_name LIKE '%真题精选%')
      AND length(coalesce(content,'')) > 20000
    ORDER BY length(coalesce(content,'')) DESC
"""

#: 抽取率下限：低于此值说明文本层结构不可用，一律跳过
MIN_EXTRACT_RATE = 0.05
#: 最少抽取题数
MIN_EXTRACTED = 5
#: 答案与选项键的错配率上限（准确率红线：99%）
MAX_ANSWER_MISMATCH = 0.01

#: 每道题至少要有这么多行才能独立成题（PDF 版题干与题号粘连时块会异常膨胀）
MAX_BLOCK_LINES = 120


def backup_db(db_path: str) -> str:
    target = f"{db_path}.bak-examimport-{time.strftime('%Y%m%d-%H%M%S')}"
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


def content_fingerprint(stem: str, options: list[dict]) -> str:
    """题干 + 选项文本指纹，用于跨文档去重。"""
    raw = stem.strip() + "|" + "|".join(o["text"].strip() for o in options)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def load_existing_fingerprints(conn: sqlite3.Connection) -> set[str]:
    """已入库题目的指纹集合（题干+选项）。"""
    got: set[str] = set()
    for content, options in conn.execute(
        "SELECT content, options FROM quiz_questions"
    ):
        try:
            opts = json.loads(options) if options else []
        except (TypeError, ValueError):
            opts = []
        texts = []
        if isinstance(opts, list):
            for o in opts:
                if isinstance(o, dict):
                    texts.append(str(o.get("text", "")).strip())
                elif isinstance(o, str):
                    texts.append(o.strip())
        got.add(content_fingerprint(content or "", [{"text": t} for t in texts]))
    return got


def main() -> int:
    ap = argparse.ArgumentParser(description="真题选择题入库")
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        docs = conn.execute(DOC_FILTER).fetchall()
        print("=" * 66)
        print("真题选择题入库计划")
        print("=" * 66)

        existing = load_existing_fingerprints(conn)
        print(f"  库内已有题目指纹：{len(existing)}\n")

        to_insert: list[dict] = []
        skipped_docs: list[dict] = []

        for d in docs:
            # PDF 文本层（碎片换行）需先重建；TXT 文本层走轻量合并。
            # 判据是文件名后缀而非内容，因为两类文本层形态完全不同（实测）。
            is_pdf = (d["file_name"] or "").lower().endswith(".pdf")
            stats = extract_from_text(
                d["content"] or "", chapter_hint="", is_pdf_layer=is_pdf
            )
            d = dict(d)

            # ---- 门禁 1：抽取率过低 → 文本层结构不可用 ----
            rate = stats.extracted / max(stats.blocks_seen, 1)
            if stats.extracted < MIN_EXTRACTED or rate < MIN_EXTRACT_RATE:
                skipped_docs.append({
                    "file_name": d["file_name"],
                    "extracted": stats.extracted,
                    "blocks_seen": stats.blocks_seen,
                    "rate": round(rate, 4),
                    "reason": "抽取率过低（文本层换行不可靠）",
                })
                continue

            # ---- 门禁 2：准确率自检（用户红线 99%）----
            # 题干与选项错配、答案不在选项内 → 说明块切分错误，直接拒绝整篇
            bad = [q for q in stats.questions
                   if not q.answer
                   or not set(q.answer) <= {o["key"] for o in q.options}
                   or len(q.stem) > 400]
            mismatch_rate = len(bad) / max(len(stats.questions), 1)
            if mismatch_rate > MAX_ANSWER_MISMATCH:
                skipped_docs.append({
                    "file_name": d["file_name"],
                    "extracted": stats.extracted,
                    "blocks_seen": stats.blocks_seen,
                    "rate": round(rate, 4),
                    "mismatch_rate": round(mismatch_rate, 4),
                    "reason": f"准确率不达标（错配 {mismatch_rate:.1%} > {MAX_ANSWER_MISMATCH:.0%}）",
                })
                continue

            new_cnt = 0
            for q in stats.questions:
                fp = content_fingerprint(q.stem, q.options)
                if fp in existing:
                    continue
                existing.add(fp)
                new_cnt += 1
                to_insert.append({
                    "stem": q.stem,
                    "options": q.options,
                    "answer": q.answer,
                    "analysis": q.analysis,
                    "question_type": q.question_type,
                    "source": f"真题:{d['file_name']}",
                    "source_paper": q.source_paper or "",
                    "year": q.year,
                    "chapter": q.chapter or "",
                })
            print(f"  {stats.extracted:>4} 题 / 新增 {new_cnt:>4}（错配 {mismatch_rate:.1%}）  {d['file_name'][:40]}")

        print()
        print(f"  待入库（去重后）：{len(to_insert)} 题")
        print(f"  跳过文档：{len(skipped_docs)} 篇")
        for s in skipped_docs[:6]:
            print(f"    × {s['file_name'][:44]}（抽 {s['extracted']}/{s['blocks_seen']}，{s['reason']}）")

        if args.report:
            Path(args.report).write_text(json.dumps({
                "to_insert": to_insert, "skipped_docs": skipped_docs,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n  报告：{args.report}")

        if not args.apply:
            print("\n[预览模式] 未写库。")
            return 0

        if not to_insert:
            print("\n没有需要新增的题目。")
            return 0

        backup = backup_db(args.db)
        print(f"\n已备份：{backup}")

        inserted = 0
        for r in to_insert:
            conn.execute(
                "INSERT INTO quiz_questions "
                "(content, options, answer, analysis, question_type, source, "
                " source_paper, year, chapter, difficulty, is_available, quality, "
                " is_junk, is_retest, figure_missing) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r["stem"],
                    json.dumps(r["options"], ensure_ascii=False),
                    r["answer"],
                    r["analysis"],
                    r["question_type"],
                    r["source"],
                    r["source_paper"],
                    r["year"],
                    r["chapter"],
                    3,
                    1,
                    "A",
                    0,
                    0,
                    0,
                ),
            )
            inserted += 1
        conn.commit()
        print(f"已入库 {inserted} 题")

        # 复核可刷题量
        n = conn.execute(
            "SELECT COUNT(*) FROM quiz_questions "
            "WHERE question_type IN ('single','multiple','judge') "
            "  AND options IS NOT NULL AND json_valid(options) "
            "  AND json_array_length(options) >= 2 "
            "  AND coalesce(trim(answer),'') <> '' "
            "  AND is_available = 1"
        ).fetchone()[0]
        print(f"复核：当前可刷题量 {n} 题")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
