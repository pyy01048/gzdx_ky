#!/usr/bin/env python
"""题库存量全量清洗（S1-2 数据地基）。

用法：
    python scripts/clean_quiz_questions.py            # dry-run，只报告不改库
    python scripts/clean_quiz_questions.py --apply    # 执行清洗

清洗动作（全部走 services.content_sanitizer 单一来源）：
  P1 字段清洗：题干/选项/答案/解析 去水印、空白规整、内联选项抽取、选项规整
  P2 source 纠偏：source_label 明显是真题（真题/年份卷/贵大/统考）但
     source_kind='textbook' → 改 'past_exam'，同步 is_past_exam=True
  P3 坏题下线：选择题无选项且无法从题干抽取 → needs_review=True +
     is_available=False（保留待修，不删除、不进刷题池）
  P4 违禁科目：source_label 命中非 0854 学科（管综/法硕/西医/植物等）
     → is_junk=True 标记待清（不物理删除，报告交用户确认）

每轮输出前后对比指标；幂等可重跑。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402
from services.content_sanitizer import (  # noqa: E402
    sanitize_question_fields,
    validate_question,
)

#: 真题文件特征（文件名级判据，非 vendor 名单）
import re  # noqa: E402
_PAST_EXAM_LABEL_RE = re.compile(
    r"真题|历年|(\d{2,4}\s*[-~至]\s*\d{2,4}\s*年)|(\d{4}\s*年.*(真题|试卷))|统考真题|回忆版")

_YEAR_RE = re.compile(r"(20\d{2}|[0-9]{2})\s*年")


def _extract_year(*texts: Optional[str]) -> Optional[int]:
    """从 label/paper 抽取单一年份；区间/多个年份取不到唯一值返回 None。"""
    years = set()
    for t in texts:
        if not t:
            continue
        for m in _YEAR_RE.finditer(str(t)):
            y = m.group(1)
            y = int(y) if len(y) == 4 else (2000 + int(y) if int(y) < 40 else 1900 + int(y))
            if 1990 <= y <= 2035:
                years.add(y)
    if len(years) == 1:
        return years.pop()
    return None

#: 违禁学科（0854 无关内容，触红线 3：只清不删，报告交用户）
_OFFTOPIC_LABEL_RE = re.compile(
    r"管综|管理类联考|法硕|法律硕士|西医|中医|临床|执业医师|植物生理|教育学|心理学统考")


def baseline(db) -> dict:
    q = lambda sql, **kw: db.execute(text(sql), kw).scalar()  # noqa: E731
    return {
        "total": q("SELECT count(*) FROM quiz_questions"),
        "no_options": q("SELECT count(*) FROM quiz_questions WHERE options IS NULL OR jsonb_array_length(options)=0"),
        "choice_no_options": q("SELECT count(*) FROM quiz_questions WHERE (options IS NULL OR jsonb_array_length(options)=0) AND question_type IN ('single','multiple')"),
        "options_gt4": q("SELECT count(*) FROM quiz_questions WHERE options IS NOT NULL AND jsonb_array_length(options)>4"),
        "answer_empty": q("SELECT count(*) FROM quiz_questions WHERE answer IS NULL OR btrim(answer)=''"),
        "needs_review": q("SELECT count(*) FROM quiz_questions WHERE needs_review IS TRUE"),
        "unavailable": q("SELECT count(*) FROM quiz_questions WHERE is_available IS FALSE"),
        "is_junk": q("SELECT count(*) FROM quiz_questions WHERE is_junk IS TRUE"),
        "past_exam": q("SELECT count(*) FROM quiz_questions WHERE source_kind='past_exam'"),
        "textbook_wrong_pastexam": q(
            "SELECT count(*) FROM quiz_questions WHERE source_kind='textbook' AND (source_label LIKE '%真题%' OR source_label ~ '[0-9]{2}-[0-9]{2}')"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行清洗（默认 dry-run）")
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        before = baseline(db)
        print("=== 清洗前基线 ===")
        for k, v in before.items():
            print(f"  {k:<28} {v}")

        stats = Counter()
        samples = {"fixed_options": [], "offline": [], "source_fixed": [], "offtopic": []}
        last_id = 0
        while True:
            rows = db.execute(text("""
                SELECT id, content, options, answer, analysis, rubric,
                       question_type, source_kind, source_label, is_junk, needs_review, is_available,
                       year, paper
                FROM quiz_questions
                WHERE id > :lid ORDER BY id LIMIT :lim
            """), {"lid": last_id, "lim": args.batch}).fetchall()
            if not rows:
                break
            for r in rows:
                last_id = r[0]
                qid, content, options, answer, analysis, rubric = r[0], r[1], r[2], r[3], r[4], r[5]
                qtype, source_kind, source_label = r[6], r[7], r[8]
                is_junk, needs_review, is_available = r[9], r[10], r[11]
                cur_year, paper = r[12], r[13]

                # 已判为 junk（违禁科目/废弃）的行不再参与其他纠偏
                if is_junk:
                    continue

                # ---- P4 违禁科目（优先标记）----
                if not is_junk and source_label and _OFFTOPIC_LABEL_RE.search(source_label):
                    stats["offtopic"] += 1
                    if len(samples["offtopic"]) < 5:
                        samples["offtopic"].append({"id": qid, "label": source_label[:60]})
                    if args.apply:
                        db.execute(text("UPDATE quiz_questions SET is_junk=TRUE, updated_at=now() WHERE id=:i"), {"i": qid})
                    continue

                # ---- P1 字段清洗 ----
                cleaned, issues = sanitize_question_fields({
                    "content": content, "options": options, "answer": answer,
                    "analysis": analysis, "rubric": rubric, "question_type": qtype,
                })
                changed = (cleaned.get("content") != content
                           or cleaned.get("options") != options
                           or cleaned.get("answer") != answer
                           or cleaned.get("analysis") != analysis)
                if changed:
                    stats["fields_cleaned"] += 1
                    if "options_from_inline" in issues and len(samples["fixed_options"]) < 5:
                        samples["fixed_options"].append({"id": qid, "issues": issues})
                if any(i.startswith("watermark_removed") for i in issues):
                    stats["watermark_cleaned"] += 1

                # ---- P3 坏题下线：选择题无选项 ----
                new_needs_review = needs_review
                new_available = is_available
                vissues = validate_question(cleaned)
                hard_bad = {"choice_without_options", "content_mojibake",
                            "content_empty", "content_too_short"} & set(vissues)
                if "options_all_duplicate" in issues:
                    hard_bad.add("options_all_duplicate")  # 选项全重复=坏题
                if hard_bad:
                    stats["choice_offline"] += 1
                    new_needs_review = True
                    new_available = False
                    if len(samples["offline"]) < 5:
                        samples["offline"].append({"id": qid, "content": (content or "")[:40]})
                elif needs_review and not vissues:
                    # 清洗后可修复的复核题自动解除
                    new_needs_review = False

                # ---- P2 source 纠偏：真题文件但标 textbook ----
                # 仅当能确定单一年份（year 已有 或 label/paper 可抽取）才升级，
                # 区间卷（如"真题16-21"跨多年）不猜年份，保留 textbook 并报备。
                new_kind = source_kind
                new_year = cur_year
                if source_kind == "textbook" and source_label and _PAST_EXAM_LABEL_RE.search(source_label):
                    yr = cur_year or _extract_year(source_label, paper)
                    if yr:
                        new_kind = "past_exam"
                        new_year = yr
                        stats["source_fixed"] += 1
                        if len(samples["source_fixed"]) < 5:
                            samples["source_fixed"].append({"id": qid, "label": source_label[:60], "year": yr})
                    else:
                        stats["source_ambiguous"] += 1

                if args.apply and (changed or new_kind != source_kind
                                   or new_year != cur_year
                                   or new_needs_review != needs_review
                                   or new_available != is_available):
                    db.execute(text("""
                        UPDATE quiz_questions SET
                            content=:content, options=CAST(:options AS jsonb),
                            answer=:answer, analysis=:analysis, rubric=:rubric,
                            source_kind=CAST(:source_kind AS source_kind),
                            year=:year,
                            needs_review=:needs_review, is_available=:is_available,
                            updated_at=now()
                        WHERE id=:id
                    """), {
                        "id": qid,
                        "content": cleaned.get("content"),
                        "options": json.dumps(cleaned["options"], ensure_ascii=False) if cleaned.get("options") else None,
                        "answer": cleaned.get("answer"), "analysis": cleaned.get("analysis"),
                        "rubric": cleaned.get("rubric"),
                        "source_kind": new_kind,
                        "year": new_year,
                        "needs_review": new_needs_review,
                        "is_available": new_available,
                    })
            if args.apply:
                db.commit()
                print(f"  ... progress id={last_id} cleaned={stats['fields_cleaned']}", flush=True)

        after = baseline(db)
        print()
        print("=== 清洗动作统计（%s）===" % ("APPLIED" if args.apply else "DRY-RUN"))
        for k, v in stats.items():
            print(f"  {k:<24} {v}")
        print()
        print("=== 清洗后基线 ===")
        for k, v in after.items():
            delta = v - before[k]
            mark = f" ({delta:+d})" if delta else ""
            print(f"  {k:<28} {v}{mark}")
        if samples["offline"]:
            print("\n=== 坏题样本（选择题无选项，已下线待修）===")
            for s in samples["offline"][:5]:
                print(f"  id={s['id']} {s['content']!r}")
        if samples["offtopic"]:
            print("\n=== 违禁科目样本（已标 is_junk，待你确认删除）===")
            for s in samples["offtopic"][:5]:
                print(f"  id={s['id']} {s['label']!r}")
        if samples["source_fixed"]:
            print("\n=== source 纠偏样本（textbook→past_exam）===")
            for s in samples["source_fixed"][:5]:
                print(f"  id={s['id']} {s['label']!r}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
