# -*- coding: utf-8 -*-
"""章节习题跨库同步（08 工学 810 题批次，source_kind='chapter_exercise'）。

背景：2026-11-20 的 810 题批次只入了本地库（见 docs/reports/08工学题库导入报告-20261120.md），
服务器库 chapter_exercise=0。本脚本把该批次按「科目名映射 + 内容指纹去重」 additive 同步到目标库。

纪律：
- 只增不改：目标库已有同指纹（content+options）题目一律跳过，绝不覆盖。
- subject_id 按科目名在**目标库** subjects 表重新解析；目标库缺科目 → 跳过并报告
  （科目创建走 ADR-002 单源治理，不在本脚本里私建）。
- chapter_id / origin_document_id / origin_chunk_id 是本库引用，跨库无意义 → 置 NULL。
- 保留来源诚实标注：source_kind/source_label/answer_source/ai_generated/verified/
  question_category/year=NULL（不伪装真题）。

用法：
    python scripts/sync_quiz_chapter_exercise.py --export out.json   # 源库导出
    python scripts/sync_quiz_chapter_exercise.py --apply out.json [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._conn import pg_connect  # noqa: E402

PORTABLE_COLS = [
    "content",
    "options",
    "option_count",
    "answer",
    "analysis",
    "rubric",
    "max_score",
    "question_type",
    "answer_type",
    "difficulty",
    "source_kind",
    "is_past_exam",
    "source_label",
    "year",
    "paper",
    "source_paper",
    "source_page",
    "question_no",
    "external_id",
    "subject",
    "chapter",
    "knowledge_point",
    "confidence",
    "quality",
    "ai_generated",
    "verified",
    "variant_group",
    "answer_source",
    "answer_confidence",
    "is_available",
    "is_junk",
    "is_retest",
    "figure_missing",
    "validation_status",
    "validation_errors",
    "validated_at",
    "classify_confidence",
    "classify_source",
    "needs_review",
    "images",
    "question_category",
    "exam_type",
    "source_platform",
    "source_url",
]


def _fp(content: str, options) -> str:
    return hashlib.md5((content + json.dumps(options, ensure_ascii=False, sort_keys=True)).encode("utf-8")).hexdigest()


def export(out_path: str) -> None:
    conn = pg_connect()
    cols = ", ".join(PORTABLE_COLS)
    rows = conn.execute(
        f"SELECT {cols} FROM quiz_questions WHERE source_kind = 'chapter_exercise' ORDER BY id"
    ).fetchall()
    items = []
    for r in rows:
        d = dict(zip(PORTABLE_COLS, r, strict=False))
        for k in ("options", "images", "validation_errors"):
            if d[k] is not None and not isinstance(d[k], list | dict):
                d[k] = json.loads(d[k])
        if d.get("validated_at") is not None:
            d["validated_at"] = str(d["validated_at"])
        items.append(d)
    Path(out_path).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"导出 {len(items)} 题 → {out_path}")
    conn.close()


def apply(in_path: str, dry_run: bool) -> None:
    items = json.loads(Path(in_path).read_text(encoding="utf-8"))
    conn = pg_connect()
    subj = {r[0]: r[1] for r in conn.execute("SELECT name, id FROM subjects").fetchall()}
    existing = {_fp(r[0], r[1]) for r in conn.execute("SELECT content, options FROM quiz_questions").fetchall()}
    # option_count / is_past_exam 是生成列（GENERATED ALWAYS），不可显式插入
    ins_cols = [c for c in PORTABLE_COLS if c not in ("option_count", "is_past_exam")] + ["subject_id"]
    cols = ", ".join(ins_cols)
    placeholders = ", ".join(f"%({c})s" for c in ins_cols)
    sql = f"INSERT INTO quiz_questions ({cols}) VALUES ({placeholders})"
    inserted = skipped_dup = 0
    missing_subjects: dict[str, int] = {}
    try:
        for d in items:
            name = d.get("subject")
            if name not in subj:
                missing_subjects[name] = missing_subjects.get(name, 0) + 1
                continue
            if _fp(d["content"], d.get("options")) in existing:
                skipped_dup += 1
                continue
            params = {
                c: (
                    json.dumps(d[c], ensure_ascii=False)
                    if c in ("options", "images", "validation_errors") and d[c] is not None
                    else d[c]
                )
                for c in PORTABLE_COLS
            }
            params["subject_id"] = subj[name]
            if not dry_run:
                conn.execute(sql, params)
            existing.add(_fp(d["content"], d.get("options")))
            inserted += 1
        if dry_run:
            conn.rollback()
            print(f"[dry-run] 将新增 {inserted}，指纹跳过 {skipped_dup}")
        else:
            conn.commit()
            print(f"APPLY_OK：新增 {inserted}，指纹跳过 {skipped_dup}")
        if missing_subjects:
            print("目标库缺科目（跳过，需走科目单源治理补建）：")
            for k, v in sorted(missing_subjects.items()):
                print(f"  {k}: {v} 题")
        total = conn.execute("SELECT count(*) FROM quiz_questions WHERE source_kind='chapter_exercise'").fetchone()[0]
        print(f"目标库 chapter_exercise 现有 {total} 题")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", metavar="OUT_JSON")
    ap.add_argument("--apply", metavar="IN_JSON")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.export:
        export(args.export)
    elif args.apply:
        apply(args.apply, args.dry_run)
    else:
        ap.print_help()
