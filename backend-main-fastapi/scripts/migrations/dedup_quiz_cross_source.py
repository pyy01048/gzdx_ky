# -*- coding: utf-8 -*-
"""跨源题目去重（完善方案 11 §3.2）。

规则（与 ADR-003 canonical schema 对齐）：
  * 判重键 = 归一化题干 + 科目 + 章节；真题额外带 year（跨年同题是合法重复，保留年份标注）
  * 保留优先级：真题 > 教材 > 其他；同优先级保留解析最全者（再按 id 小者）
  * 存储层合并：不物理删除，重复题置 is_available=false + is_junk=true（可回滚）
  * 外键迁移：错题/作答/试卷/知识点关联的记录改挂到保留题（避免孤儿 attempt）

默认 dry-run（只出报告），``--apply`` 才写库。写库前自动备份 ``bak_quiz_dedup_<ts>``。

用法：
    python scripts/migrations/dedup_quiz_cross_source.py                 # dry-run + 报告
    python scripts/migrations/dedup_quiz_cross_source.py --apply         # 执行合并
    python scripts/migrations/dedup_quiz_cross_source.py --limit 100     # 只处理前 100 组
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from services.quiz_validator import dedup_key  # noqa: E402
from sqlalchemy import text  # noqa: E402

#: 引用 quiz_questions(id) 的表 → 列名（存在才迁移；favorites 为通用 item 表，未纳入）
REF_TABLES = {
    "error_records": "question_id",
    "answer_records": "question_id",
    "exam_answers": "question_id",
    "study_events": "question_id",
    "misconceptions": "question_id",
    "question_knowledge_links": "question_id",
    "paper_questions": "question_id",
    "paper_answers": "question_id",
    "quiz_attempts": "question_id",
}

SOURCE_PRIORITY = {"past_exam": 3, "textbook": 2}


def _load(conn) -> list[dict]:
    rows = (
        conn.execute(
            text(
                "SELECT id, content, subject, chapter, answer, analysis, source_kind, "
                "       year, is_past_exam, is_available "
                "FROM quiz_questions WHERE is_available IS TRUE"
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def _priority(q: dict) -> tuple:
    kind = (
        "past_exam" if (q.get("is_past_exam") or q.get("source_kind") == "past_exam") else (q.get("source_kind") or "")
    )
    return (
        SOURCE_PRIORITY.get(kind, 1),
        len(q.get("analysis") or ""),
        -int(q["id"]),
    )


def build_groups(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for q in rows:
        key = dedup_key(q)
        if q.get("is_past_exam") or q.get("source_kind") == "past_exam":
            key += f"|year={q.get('year')}"
        groups[key].append(q)
    return {k: v for k, v in groups.items() if len(v) > 1}


def _table_columns(conn) -> dict[str, set[str]]:
    rows = conn.execute(
        text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = current_schema()")
    ).all()
    out: dict[str, set[str]] = defaultdict(set)
    for t, c in rows:
        out[t].add(c)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="执行合并（默认 dry-run）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 组（0=全部）")
    ap.add_argument("--out", default=str(BASE.parent / "docs" / "reports"))
    args = ap.parse_args()

    from core.db_session import IS_POSTGRES, build_database_url  # noqa: PLC0415
    from sqlalchemy import create_engine  # noqa: PLC0415

    if not IS_POSTGRES:
        print("[x] 仅支持 PostgreSQL")
        return 2
    engine = create_engine(build_database_url())
    with engine.connect() as conn:
        rows = _load(conn)
        cols = _table_columns(conn)
    groups = build_groups(rows)
    if args.limit:
        groups = dict(list(groups.items())[: args.limit])

    plan = []
    for key, items in groups.items():
        keep = max(items, key=_priority)
        dups = [x for x in items if x["id"] != keep["id"]]
        plan.append({"key": key[:120], "keep": keep["id"], "dups": [d["id"] for d in dups]})

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    report = {
        "generated_at": ts,
        "mode": "apply" if args.apply else "dry-run",
        "total_available": len(rows),
        "dup_groups": len(plan),
        "dup_questions": sum(len(p["dups"]) for p in plan),
        "groups": plan,
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"quiz-dedup-{ts}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        f"# 跨源题目去重报告（{ts}）",
        "",
        f"- 模式：{'APPLY' if args.apply else 'DRY-RUN'}",
        f"- 可用题：{len(rows)}｜重复组：{len(plan)}｜可合并题：{report['dup_questions']}",
        "",
        "| 组键（截断） | 保留 | 合并 |",
        "|---|---|---|",
    ]
    md += [f"| `{p['key']}` | {p['keep']} | {', '.join(map(str, p['dups']))} |" for p in plan[:200]]
    (out_dir / f"quiz-dedup-{ts}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"报告：{out_dir / f'quiz-dedup-{ts}.md'}")
    print(f"重复组 {len(plan)}｜涉及题 {report['dup_questions']}")

    if not args.apply:
        print("[dry-run] 未写库。确认报告后加 --apply 执行。")
        return 0
    if not plan:
        return 0

    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS bak_quiz_dedup_{ts.replace('-', '')} AS "
                "SELECT id, is_available, is_junk FROM quiz_questions"
            )
        )
        for p in plan:
            for dup in p["dups"]:
                for table, col in REF_TABLES.items():
                    if table in cols and col in cols[table]:
                        conn.execute(
                            text(f'UPDATE "{table}" SET {col} = :keep WHERE {col} = :dup'),
                            {"keep": p["keep"], "dup": dup},
                        )
                conn.execute(
                    text("UPDATE quiz_questions SET is_available = false, is_junk = true WHERE id = :i"),
                    {"i": dup},
                )
    print(f"[✓] 已合并 {report['dup_questions']} 道重复题（备份表 bak_quiz_dedup_{ts.replace('-', '')}）")
    print(
        "回滚：UPDATE quiz_questions q SET is_available=b.is_available, is_junk=b.is_junk "
        f"FROM bak_quiz_dedup_{ts.replace('-', '')} b WHERE q.id=b.id;"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
