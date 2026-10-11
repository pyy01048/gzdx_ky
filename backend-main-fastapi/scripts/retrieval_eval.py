# -*- coding: utf-8 -*-
"""检索评测脚本（2026-10，子任务8）：
对固定 50 题回归集（scripts/data/retrieval_eval_set.json）逐条调用
search_service.hybrid_search（FTS+RRF+术语加权精排），按"相关文档集（gold）"
计算 Recall@1/5/10 与 MRR@10，并按科目汇总。

gold 判定：该 query 的 subject 下，documents.content 命中任一 rel_keyword 的文档。
输出 JSON 报告到 TEMP_DIR/retrieval_eval_result.json。
"""
from __future__ import annotations

import io
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

from database import SessionLocal  # noqa: E402
from services import search_service  # noqa: E402

EVAL_SET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "retrieval_eval_set.json")
OUT_PATH = os.path.join(os.environ.get("TEMP_DIR", BASE_DIR), "retrieval_eval_result.json")
TOP_K = 10


def main() -> None:
    buf = io.StringIO()
    try:
        with open(EVAL_SET, encoding="utf-8") as f:
            cases = json.load(f)
        db = SessionLocal()
        try:
            # 预加载全部文档（id, subject, file_name, content）避免逐条查询
            docs = db.connection().connection.execute(
                "SELECT id, subject, file_name, content FROM documents"
            ).fetchall()
            doc_by_id = {r[0]: r for r in docs}
            # gold 文档集：每个 case 的 (subject, rel_keywords) -> set[doc_id]
            gold_cache = {}
            for c in cases:
                key = (c["subject"], tuple(c["rel_keywords"]))
                if key in gold_cache:
                    continue
                gold = set()
                for d in docs:
                    if d[1] != c["subject"]:
                        continue
                    content = (d[3] or "") + " " + (d[2] or "")
                    if any(kw in content for kw in c["rel_keywords"]):
                        gold.add(d[0])
                gold_cache[key] = gold

            per_case = []
            for c in cases:
                gold = gold_cache.get((c["subject"], tuple(c["rel_keywords"])), set())
                results = search_service.hybrid_search(
                    db, c["query"], query_vec=None, limit=TOP_K, subject=c["subject"]
                )
                # 检索结果去重到文档级（chunk/point/document 都映射到 document_id）
                seen_docs = []
                for r in results:
                    did = r.get("document_id") or 0
                    if did not in seen_docs:
                        seen_docs.append(did)
                rec1 = sum(1 for d in seen_docs[:1] if d in gold)
                rec5 = sum(1 for d in seen_docs[:5] if d in gold)
                rec10 = sum(1 for d in seen_docs[:10] if d in gold)
                if gold:
                    rec1 = rec1 / min(1, len(gold))
                    rec5 = rec5 / min(5, len(gold))
                    rec10 = rec10 / min(10, len(gold))
                mrr = 0.0
                for rank, d in enumerate(seen_docs, start=1):
                    if d in gold:
                        mrr = 1.0 / rank
                        break
                per_case.append({
                    "id": c["id"], "query": c["query"], "subject": c["subject"],
                    "gold_count": len(gold), "recall@1": round(rec1, 4),
                    "recall@5": round(rec5, 4), "recall@10": round(rec10, 4),
                    "mrr@10": round(mrr, 4),
                    "top_docs": [doc_by_id.get(d, ("", "", "", ""))[2] or "" for d in seen_docs[:5]],
                })

            # 汇总
            total = len(per_case)
            agg = {
                "case_count": total,
                "recall@1": round(sum(x["recall@1"] for x in per_case) / total, 4),
                "recall@5": round(sum(x["recall@5"] for x in per_case) / total, 4),
                "recall@10": round(sum(x["recall@10"] for x in per_case) / total, 4),
                "mrr@10": round(sum(x["mrr@10"] for x in per_case) / total, 4),
            }
            by_subject = {}
            for c in per_case:
                s = c["subject"]
                b = by_subject.setdefault(s, {"n": 0, "r1": 0.0, "r5": 0.0, "r10": 0.0, "mrr": 0.0})
                b["n"] += 1
                b["r1"] += c["recall@1"]
                b["r5"] += c["recall@5"]
                b["r10"] += c["recall@10"]
                b["mrr"] += c["mrr@10"]
            for s, b in by_subject.items():
                n = b["n"]
                b["recall@1"] = round(b.pop("r1") / n, 4)
                b["recall@5"] = round(b.pop("r5") / n, 4)
                b["recall@10"] = round(b.pop("r10") / n, 4)
                b["mrr@10"] = round(b.pop("mrr") / n, 4)

            report = {"aggregate": agg, "by_subject": by_subject, "cases": per_case}
            buf.write(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            db.close()
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        print("RESULT_WRITTEN " + OUT_PATH)
    except Exception:
        import traceback
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print("ERROR_WRITTEN " + OUT_PATH)


if __name__ == "__main__":
    main()
