#!/usr/bin/env python
"""文档库治理（S1-4）：科目口径归一 + 违禁标记 + 正文水印清洗。

用法：
    python scripts/normalize_documents.py            # dry-run（只报告）
    python scripts/normalize_documents.py --apply    # 执行

三件事：
  P1 科目口径归一：业务表里出现但不在权威字典的科目名 → 归一到权威名
     （公共课-数学→数学 / 公共课-英语→英语 / 公共课-政治→政治 / 408→计算机学科专业基础408）
     同时同步 documents / quiz_questions / knowledge_chunks / error_records，
     避免"同一份资料在不同页面归属不同科目"（docx/25 ①公用线）。
  P2 违禁文档标记：红线 3 规定内容仅限 0854 相关学科。命中非相关科目
     （法硕/西医/管综/经济联考/教育/心理…）的文档标 documents.is_junk=TRUE，
     非破坏性（不删数据），查询侧过滤 is_junk IS NOT TRUE。
  P3 正文清洗：documents.content / canonical_content 走
     services.content_sanitizer 统一去水印（与题库同一套规则，单一来源）。

幂等可重跑；P1/P2 只动标记与归属，不改正文；P3 只做剥离不做改写。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from services.content_sanitizer import document_has_page_markers, sanitize_text  # noqa: E402


def _clean_doc(text):
    """文档正文清洗：纯数字行是否按页码剔除，取决于该文是否带页标记。"""
    if not text:
        return text
    return sanitize_text(text, drop_standalone_numbers=document_has_page_markers(text))

#: 非标科目名 → 权威名（口径归一）。只放**语义等价**的映射；
#: 语义模糊的（如"数模电"= 数电+模电 合卷）不猜，留报备。
SUBJECT_ALIASES: dict[str, str] = {
    "公共课-数学": "数学",
    "公共课-英语": "英语",
    "公共课-政治": "政治",
    "408": "计算机学科专业基础408",
    "计算机408": "计算机学科专业基础408",
    "数电": "数字电子技术",
    "模电": "模拟电子技术",
}

#: 违禁科目（红线 3：非 0854 相关）
OFFTOPIC_SUBJECTS: set[str] = {
    "法律硕士专业基础", "法律硕士综合", "西医综合", "中医综合", "管理类联考综合",
    "经济类联考综合", "教育学专业基础", "心理学专业基础", "历史学基础",
    "农学门类联考", "计算机基础",
}

#: 参与科目归一的业务表 (表名, 科目列)
SUBJECT_TABLES = [
    ("documents", "subject"),
    ("quiz_questions", "subject"),
    ("knowledge_chunks", "subject"),
    ("error_records", "subject"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行（默认 dry-run）")
    ap.add_argument("--no-content", action="store_true", help="跳过 P3 正文清洗（只做科目治理）")
    ap.add_argument("--batch", type=int, default=200)
    args = ap.parse_args()
    stats = Counter()

    db = SessionLocal()
    try:
        # ---------------- P1 科目口径归一 ----------------
        print("=== P1 科目口径归一 ===")
        for table, col in SUBJECT_TABLES:
            for old, new in SUBJECT_ALIASES.items():
                try:
                    n = db.execute(text(
                        f"SELECT count(*) FROM {table} WHERE {col} = :o"), {"o": old}).scalar()
                except Exception as e:
                    print(f"  {table}.{col}: 跳过（{str(e)[:60]}）")
                    continue
                if not n:
                    continue
                stats[f"P1:{table}:{old}->{new}"] = n
                print(f"  {table}.{col}: {old!r} -> {new!r}  {n} 行")
                if args.apply:
                    db.execute(text(
                        f"UPDATE {table} SET {col} = :n WHERE {col} = :o"),
                        {"n": new, "o": old})
        if args.apply:
            db.commit()

        # ---------------- P2 违禁文档标记 ----------------
        print("\n=== P2 违禁文档标记（红线3）===")
        rows = db.execute(text("""
            SELECT subject, count(*) FROM documents
            WHERE subject = ANY(:subs) AND is_junk IS NOT TRUE
            GROUP BY 1 ORDER BY 2 DESC
        """), {"subs": list(OFFTOPIC_SUBJECTS)}).fetchall()
        for subj, n in rows:
            stats[f"P2:junk:{subj}"] = n
            print(f"  标 junk：{subj}  {n} 篇")
        if args.apply and rows:
            db.execute(text("""
                UPDATE documents SET is_junk = TRUE, updated_at = now()
                WHERE subject = ANY(:subs) AND is_junk IS NOT TRUE
            """), {"subs": list(OFFTOPIC_SUBJECTS)})
            db.commit()
        if not rows:
            print("  （无未标记的违禁文档）")

        # ---------------- P3 正文水印清洗 ----------------
        if not args.no_content:
            print("\n=== P3 正文水印清洗（documents.content / canonical_content）===")
            last_id, cleaned, hits_total = 0, 0, 0
            while True:
                batch = db.execute(text("""
                    SELECT id, content, canonical_content FROM documents
                    WHERE id > :lid AND is_junk IS NOT TRUE
                      AND (content IS NOT NULL OR canonical_content IS NOT NULL)
                    ORDER BY id LIMIT :lim
                """), {"lid": last_id, "lim": args.batch}).fetchall()
                if not batch:
                    break
                for did, content, canonical in batch:
                    last_id = did
                    new_c = _clean_doc(content)
                    new_cc = _clean_doc(canonical)
                    if (new_c or "") != (content or "") or (new_cc or "") != (canonical or ""):
                        cleaned += 1
                        if args.apply:
                            db.execute(text("""
                                UPDATE documents
                                SET content = :c, canonical_content = :cc, updated_at = now()
                                WHERE id = :i
                            """), {"c": new_c, "cc": new_cc, "i": did})
                if args.apply:
                    db.commit()
                if cleaned:
                    print(f"  ... id={last_id} 已清洗 {cleaned}", flush=True)
            stats["P3:docs_cleaned"] = cleaned

        # ---------------- 汇总 ----------------
        print("\n=== 汇总（%s）===" % ("APPLIED" if args.apply else "DRY-RUN"))
        for k, v in sorted(stats.items()):
            print(f"  {k:<44} {v}")
        print()
        print("=== 治理后基线 ===")
        q = lambda sql, **kw: db.execute(text(sql), kw).scalar()  # noqa: E731
        print("  documents 总数      ", q("SELECT count(*) FROM documents"))
        print("  documents is_junk   ", q("SELECT count(*) FROM documents WHERE is_junk IS TRUE"))
        print("  非标科目残留        ", q(
            "SELECT count(*) FROM documents WHERE subject = ANY(:s) AND is_junk IS NOT TRUE",
            s=list(SUBJECT_ALIASES.keys())))
        amb = db.execute(text("""
            SELECT subject, count(*) FROM documents
            WHERE subject IN ('数模电','真题综合','电路','其他','')
            GROUP BY 1 ORDER BY 2 DESC
        """)).fetchall()
        print("  语义模糊科目（留报备，未自动归一）：", dict(amb) if amb else "无")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
