# -*- coding: utf-8 -*-
"""RAG 评测（完善方案 10-AI与RAG质量保障）。

两类 suite：

* ``retrieval``：query → 应命中的分块/知识点，走**真实生产检索链**
  （``services.search_service.hybrid_search``），输出 Hit@5 / MRR@10。
* ``qa``：问题 → 要点/应引用来源，评测**已生成的答案文件**（由线上或批处理产出），
  输出要点覆盖率 / 引用正确率 / 拒答正确率。把生成与评测解耦：
  换模型、换嵌入、改分块后，同一批问题重跑答案文件即可对比，不需要评测环境能起大模型。

变更回归闸：``--compare tests/eval/baseline.json``，关键指标低于基线 -2% → 退出码 1
（可直接作为 CI/部署闸，写入 CONTRIBUTING）。

用法：
    python -m services.rag_eval --suite retrieval
    python -m services.rag_eval --suite qa --answers tests/eval/qa_answers.jsonl
    python -m services.rag_eval --suite all --compare tests/eval/baseline.json --write-baseline

输入格式（JSONL，UTF-8）：
    retrieval: {"id","query","gold_chunk_ids":[...],"gold_kp_ids":[...],"subject"}
    qa:        {"id","question","answer_points":[...],"gold_doc_ids":[...],"expect_refuse":false}
    answers:   {"id","answer","cited_doc_ids":[...]}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

DEFAULT_RETRIEVAL = BASE / "tests" / "eval" / "retrieval_golden.jsonl"
DEFAULT_QA = BASE / "tests" / "eval" / "qa_golden.jsonl"
DEFAULT_ANSWERS = BASE / "tests" / "eval" / "qa_answers.jsonl"
DEFAULT_BASELINE = BASE / "tests" / "eval" / "baseline.json"
#: 关键指标相对基线的最大可接受衰减
TOLERANCE = 0.02
#: 拒答语义（知识库没有的题必须承认没有）
REFUSE_MARKERS = ("没有找到", "暂无相关", "资料不足", "未收录", "无法回答", "知识库中没有", "没有相关资料")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            items.append(json.loads(line))
    return items


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


# --------------------------------------------------------------------------- #
# retrieval
# --------------------------------------------------------------------------- #
def eval_retrieval(golden: list[dict], top_k: int = 10) -> dict:
    from database import SessionLocal

    from services.search_service import hybrid_search

    hits, reciprocal = [], []
    details = []
    db = SessionLocal()
    try:
        for case in golden:
            results = hybrid_search(db, case["query"], limit=max(top_k, 6), subject=case.get("subject"))
            ids = [r.get("chunk_id") for r in results]
            gold = set(case.get("gold_chunk_ids") or [])
            kp_gold = set(case.get("gold_kp_ids") or [])
            kp_ids = [r.get("point_id") for r in results if r.get("source_type") in ("knowledge_point", "kp")]
            hit = any(i in gold for i in ids[:5]) or any(i in kp_gold for i in kp_ids[:5])
            rank = next((n + 1 for n, i in enumerate(ids[:top_k]) if i in gold), None)
            hits.append(1.0 if hit else 0.0)
            reciprocal.append(1.0 / rank if rank else 0.0)
            details.append({"id": case.get("id"), "hit": bool(hit), "rank": rank, "top_ids": ids[:5]})
    finally:
        db.close()
    return {
        "suite": "retrieval",
        "n": len(golden),
        "hit@5": round(mean(hits), 4) if hits else None,
        "mrr@10": round(mean(reciprocal), 4) if reciprocal else None,
        "cases": details,
    }


# --------------------------------------------------------------------------- #
# qa（离线评测答案文件）
# --------------------------------------------------------------------------- #
def _point_covered(point: str, answer: str) -> bool:
    p = _norm(point)
    a = _norm(answer)
    if not p:
        return True
    if p in a:
        return True
    # 要点是短公式/关键词时允许字符集覆盖（BD 与 B'D' 这类化简结果不适用，需完整命中）
    return len(p) <= 3 and p in re.sub(r"[^0-9a-z]", "", a)


def eval_qa(golden: list[dict], answers: list[dict]) -> dict:
    answer_map = {str(a.get("id")): a for a in answers}
    coverage, citation, refusal = [], [], []
    details = []
    missing = 0
    for case in golden:
        cid = str(case.get("id"))
        ans = answer_map.get(cid)
        if ans is None:
            missing += 1
            details.append({"id": cid, "missing_answer": True})
            continue
        text = str(ans.get("answer") or "")
        points = case.get("answer_points") or []
        covered = [p for p in points if _point_covered(p, text)]
        if points:
            coverage.append(len(covered) / len(points))
        gold_docs = set(str(x) for x in (case.get("gold_doc_ids") or []))
        cited = set(str(x) for x in (ans.get("cited_doc_ids") or []))
        if gold_docs:
            citation.append(1.0 if cited and cited <= gold_docs else 0.0)
        if case.get("expect_refuse"):
            refusal.append(1.0 if any(m in text for m in REFUSE_MARKERS) else 0.0)
        details.append(
            {
                "id": cid,
                "coverage": round(len(covered) / len(points), 3) if points else None,
                "missing_points": [p for p in points if p not in covered][:5],
                "citation_ok": (cited <= gold_docs) if (gold_docs and cited) else None,
                "refused": any(m in text for m in REFUSE_MARKERS),
            }
        )
    return {
        "suite": "qa",
        "n": len(golden),
        "answered": len(golden) - missing,
        "missing_answers": missing,
        "answer_coverage": round(mean(coverage), 4) if coverage else None,
        "citation_accuracy": round(mean(citation), 4) if citation else None,
        "refusal_accuracy": round(mean(refusal), 4) if refusal else None,
        "cases": details,
    }


# --------------------------------------------------------------------------- #
# 基线比较 + 报告
# --------------------------------------------------------------------------- #
def compare(report: dict, baseline: dict) -> list[str]:
    regressions = []
    for suite, metrics in baseline.items():
        current = report.get(suite) or {}
        for key, base_val in (metrics or {}).items():
            if not isinstance(base_val, int | float):
                continue
            cur = current.get(key)
            if not isinstance(cur, int | float):
                regressions.append(f"{suite}.{key}：当前无数据（基线 {base_val}）")
                continue
            if cur < base_val - TOLERANCE:
                regressions.append(f"{suite}.{key}：{cur:.4f} < 基线 {base_val:.4f} - {TOLERANCE}（回归）")
    return regressions


def write_report(reports: dict, out_dir: Path) -> Path:
    from utils.timeutil import local_now

    ts = local_now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"rag-eval-{ts}.md"
    lines = [f"# RAG 评测报告（{ts}）", "", "## 指标", "", "| suite | 指标 | 数值 |", "|---|---|---|"]
    for suite, data in reports.items():
        for k, v in data.items():
            if k in ("cases", "suite"):
                continue
            lines.append(f"| {suite} | {k} | {v} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / f"rag-eval-{ts}.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["retrieval", "qa", "all"], default="all")
    ap.add_argument("--retrieval", default=str(DEFAULT_RETRIEVAL))
    ap.add_argument("--qa", default=str(DEFAULT_QA))
    ap.add_argument("--answers", default=str(DEFAULT_ANSWERS))
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--out", default=str(BASE.parent / "docs" / "reports"))
    args = ap.parse_args(argv)

    reports: dict = {}
    if args.suite in ("retrieval", "all"):
        golden = load_jsonl(Path(args.retrieval))
        if not golden:
            print(f"[!] 检索 golden 集为空：{args.retrieval}（先跑 scripts/tools/build_rag_eval_set.py）")
        else:
            reports["retrieval"] = eval_retrieval(golden)
    if args.suite in ("qa", "all"):
        golden = load_jsonl(Path(args.qa))
        answers = load_jsonl(Path(args.answers))
        if not golden:
            print(f"[!] 答疑 golden 集为空：{args.qa}")
        else:
            reports["qa"] = eval_qa(golden, answers)

    if not reports:
        return 2
    path = write_report(reports, Path(args.out))
    print(f"报告：{path}")
    for suite, data in reports.items():
        metrics = {k: v for k, v in data.items() if k not in ("cases", "suite")}
        print(f"[{suite}] {metrics}")

    if args.write_baseline:
        baseline = {s: {k: v for k, v in d.items() if isinstance(v, int | float)} for s, d in reports.items()}
        Path(args.baseline).write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"基线已写入 {args.baseline}")

    if args.compare:
        baseline_path = Path(args.baseline)
        if not baseline_path.exists():
            print(f"[x] 基线不存在：{baseline_path}")
            return 2
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        regressions = compare(reports, baseline)
        if regressions:
            print("[x] 指标回归：")
            for r in regressions:
                print("   ", r)
            return 1
        print("[✓] 无回归（关键指标不低于基线 -2%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
