# -*- coding: utf-8 -*-
"""构建 RAG golden 集候选（完善方案 10 §3.1/§3.2）。

从库里自动生成**候选**，人工审核后另存为正式 golden：

    tests/eval/retrieval_candidates.jsonl  → 审核后 → retrieval_golden.jsonl
    tests/eval/qa_candidates.jsonl         → 审核后 → qa_golden.jsonl

候选来源：
  1. 真题/题目题干（优先 is_past_exam 的数电/模电/电路）→ 挂靠知识点及其分块
  2. 知识点名称 + 描述 → query="什么是<name>"，gold=该知识点及其来源分块

每行带 ``verified: false``，审核后另存为 golden。
**未审核的候选不得作为评测基线**——题目挂错知识点是常见噪声，审核步骤不可省。

用法：
    python scripts/tools/build_rag_eval_set.py --limit 400
    python scripts/tools/build_rag_eval_set.py --subject 数字电子技术 --limit 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

from sqlalchemy import text  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"写入 {len(rows)} 条 → {path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--subject", default="")
    ap.add_argument("--out-dir", default=str(BASE / "tests" / "eval"))
    args = ap.parse_args()

    from core.db_session import IS_POSTGRES, build_database_url  # noqa: PLC0415
    from sqlalchemy import create_engine  # noqa: PLC0415

    if not IS_POSTGRES:
        print("[x] 仅支持 PostgreSQL")
        return 2
    engine = create_engine(build_database_url())
    subject_filter = f"%{args.subject}%" if args.subject else None

    retrieval: list[dict] = []
    qa: list[dict] = []
    with engine.connect() as conn:
        # 1) 题目 → 知识点 → 分块
        q_sql = (
            "SELECT q.id, q.content, q.answer, q.subject, q.question_type, "
            "       kp.id AS kp_id, "
            "       array_agg(DISTINCT kc.id) FILTER (WHERE kc.id IS NOT NULL) AS chunk_ids "
            "FROM quiz_questions q "
            "LEFT JOIN question_knowledge_links qkl ON qkl.question_id = q.id "
            "LEFT JOIN knowledge_points kp ON kp.id = qkl.knowledge_point_id "
            "LEFT JOIN knowledge_chunks kc ON kc.knowledge_point_id = kp.id "
            "WHERE q.is_available IS TRUE AND length(btrim(q.content)) BETWEEN 12 AND 400 "
        )
        params: dict = {"lim": args.limit}
        if subject_filter:
            q_sql += "AND q.subject ILIKE :subj "
            params["subj"] = subject_filter
        q_sql += "GROUP BY q.id, kp.id ORDER BY q.is_past_exam DESC NULLS LAST, q.id LIMIT :lim"
        for r in conn.execute(text(q_sql), params).mappings():
            chunks = [int(x) for x in (r["chunk_ids"] or []) if x]
            if not chunks:
                continue
            retrieval.append(
                {
                    "id": f"r{len(retrieval) + 1:04d}",
                    "query": r["content"][:80],
                    "gold_chunk_ids": chunks[:5],
                    "gold_kp_ids": [int(r["kp_id"])] if r["kp_id"] else [],
                    "subject": r["subject"],
                    "verified": False,
                    "source": f"quiz:{r['id']}",
                }
            )
            if r["answer"]:
                qa.append(
                    {
                        "id": f"q{len(qa) + 1:04d}",
                        "subject": r["subject"],
                        "question": r["content"][:200],
                        "answer_points": [str(r["answer"])[:60]],
                        "gold_doc_ids": [],
                        "type": r["question_type"],
                        "verified": False,
                        "source": f"quiz:{r['id']}",
                    }
                )

        # 2) 知识点名称
        kp_sql = (
            "SELECT kp.id, kp.name, kp.subject, "
            "       array_agg(DISTINCT kc.id) FILTER (WHERE kc.id IS NOT NULL) AS chunk_ids "
            "FROM knowledge_points kp LEFT JOIN knowledge_chunks kc ON kc.knowledge_point_id = kp.id "
            "WHERE kp.name IS NOT NULL AND length(btrim(kp.name)) >= 2 "
        )
        if subject_filter:
            kp_sql += "AND kp.subject ILIKE :subj "
        kp_sql += "GROUP BY kp.id ORDER BY kp.id LIMIT :lim"
        for r in conn.execute(text(kp_sql), params).mappings():
            chunks = [int(x) for x in (r["chunk_ids"] or []) if x]
            if not chunks:
                continue
            retrieval.append(
                {
                    "id": f"r{len(retrieval) + 1:04d}",
                    "query": f"什么是{r['name']}",
                    "gold_chunk_ids": chunks[:5],
                    "gold_kp_ids": [int(r["id"])],
                    "subject": r["subject"],
                    "verified": False,
                    "source": f"kp:{r['id']}",
                }
            )

    out_dir = Path(args.out_dir)
    _write(out_dir / "retrieval_candidates.jsonl", retrieval)
    _write(out_dir / "qa_candidates.jsonl", qa)
    print(
        "下一步：人工审核（每条 1 分钟：gold 是否真的能回答 query），把 verified 改成 true 后"
        "另存为 retrieval_golden.jsonl / qa_golden.jsonl。审核记录写在 tests/eval/README.md。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
