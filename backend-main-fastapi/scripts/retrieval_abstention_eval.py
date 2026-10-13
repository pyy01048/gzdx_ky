# -*- coding: utf-8 -*-
"""检索弃权阈值离线定档（docx/16 §1.5-D / §2.9）。

要回答的问题
------------
``services/retrieval_gate.py`` 的双阈值（相关 0.50 / 放行 0.60）打在 ``rerank_score``
上（无该字段时回退 ``score``），但本仓库这两个量都不是 0..1 的相似度：

* ``rerank_results()`` 是**加法启发式**：``_term_boost`` 每命中一次核心术语 +2.0、
  段首再 +3.0、噪声词 −8.0，再乘 source/length 权重；
* ``hybrid_search()`` 是 **RRF 融合名次分**，量级 0.01~0.2，而现网 RAG
  （``routers/ai.py::_rag_system_prompt`` → ``search_knowledge_base_hybrid``）用的正是这一路。

所以「mode 能不能从 observe 切到 enforce」不能靠手感答，本脚本实测两件事：

1. 两条分数路各自能不能把「top1 真的相关」与「top1 不相关」分开（Mann-Whitney AUC）；
2. 若能分开，误杀率（有答案却弃权）/ 漏答率（没答案却硬答）在哪个阈值上可同时接受。

gold 口径（与 scripts/retrieval_eval.py 一致，不另起炉灶）
---------------------------------------------------------
``scripts/data/retrieval_eval_set.json`` 每条给 ``subject`` + ``rel_keywords``；
gold 文档集 = 该学科下 ``documents.content`` 或 ``file_name`` 命中任一关键词的文档；
top1 记为「相关」当其 ``document_id`` ∈ gold。这是**弱标注**（词面命中≠语义正确），
因此结果只用于「能否定档」的相对比较与留痕，不当准确率宣传。

安全
----
默认只读：不写库、不调 LLM、不需要 Ollama（``query_vec=None``，走 FTS+关键词路）。
建议 ``--db`` 指向一份 SQLite backup API 复制出来的库，别拿生产文件跑。
只有显式 ``--record`` / ``--record-only`` 才往 ``eval_runs`` 插一条
``kind=retrieval_abstention`` 的留痕行。

用法::

    python scripts/retrieval_abstention_eval.py --db D:/tmp/kaoyan_eval_corpus.db
    python scripts/retrieval_abstention_eval.py --record-only        # 复述既有报表并入库
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
EVAL_SET = os.path.join(BASE_DIR, "scripts", "data", "retrieval_eval_set.json")
TOP_K = 6
# 扫描网格：同时覆盖 RRF 量级（0.05~0.5）与 rerank 加法分量级（1~200）
GRID = [0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 1.0, 2.0, 5.0, 10.0, 30.0, 70.0, 120.0]
# 定档门槛：AUC 低于它就不许切 enforce
MIN_AUC_FOR_ENFORCE = 0.75


def build_gold(conn, cases):
    """gold 文档集：学科相等 + 词面命中任一关键词（同 retrieval_eval.py 口径）。"""
    docs = conn.execute("SELECT id, subject, file_name, content FROM documents").fetchall()
    gold = {}
    for c in cases:
        key = (c["subject"], tuple(c["rel_keywords"]))
        if key in gold:
            continue
        gold[key] = {
            d[0] for d in docs
            if (d[1] or "") == c["subject"]
            and any(kw in ((d[3] or "") + " " + (d[2] or "")) for kw in c["rel_keywords"])
        }
    return gold


def auc(pos, neg):
    """Mann-Whitney AUC = P(正例分 > 负例分)，打平记 0.5。"""
    if not pos or not neg:
        return None
    wins = ties = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return round((wins + 0.5 * ties) / (len(pos) * len(neg)), 4)


def sweep(scores, labels, grid):
    """阈值曲线：误杀=有 gold 却弃权，漏答=无 gold 却放行。"""
    n_pos = sum(1 for y in labels if y)
    n_neg = len(labels) - n_pos
    rows = []
    for th in grid:
        fa = sum(1 for s, y in zip(scores, labels) if y and s < th)
        ms = sum(1 for s, y in zip(scores, labels) if (not y) and s >= th)
        rows.append({
            "threshold": th,
            "abstain_rate": round(sum(1 for s in scores if s < th) / len(scores), 4),
            "false_abstain_n": fa,
            "false_abstain_rate": round(fa / n_pos, 4) if n_pos else None,
            "missed_abstain_n": ms,
            "missed_abstain_rate": round(ms / n_neg, 4) if n_neg else None,
        })
    return rows, n_pos, n_neg


def _pct(vals, q):
    if not vals:
        return None
    return round(statistics.quantiles(vals, n=100)[q - 1], 4) if len(vals) > 1 else round(vals[0], 4)


def arm_stats(rows, relevance_threshold, accept_threshold):
    """把一路（arm）的逐条结果压成统计块。"""
    have = [c for c in rows if c["top1_score"] is not None]
    scores = [c["top1_score"] for c in have]
    labels = [c["top1_is_gold"] for c in have]
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]

    extra = []
    if pos:
        extra.append(round(statistics.median(pos), 3))
    if neg:
        extra.append(round(min(neg), 3))
        if len(neg) >= 4:
            extra.append(round(statistics.quantiles(neg, n=4)[0], 3))
    grid = sorted({*GRID, *[v for v in extra if v > 0]})
    curve, n_pos, n_neg = sweep(scores, labels, grid) if scores else ([], 0, 0)

    by_subj = {}
    for c in have:
        by_subj.setdefault(c["subject"], []).append(c["top1_score"])

    # 现阈值把样本切成三段，对应 enforce 的三种行为。真正决定「切了会怎样」的是这三个数，
    # 而不是单一阈值高低：中间那段（弃权带）如果为空，enforce 等于永远不弃权；
    # 如果非空却全是 gold，说明弃权带里装的都是「本来答得出的题」。
    def _band(pred):
        sub = [(s, y) for s, y in zip(scores, labels) if pred(s)]
        return {
            "n": len(sub),
            "gold_n": sum(1 for _, y in sub if y),
            "non_gold_n": sum(1 for _, y in sub if not y),
        }

    bands = {
        "below_relevance_走retry": _band(lambda s: s < relevance_threshold),
        "abstain带_relevance<=s<accept": _band(lambda s: relevance_threshold <= s < accept_threshold),
        "above_accept_放行": _band(lambda s: s >= accept_threshold),
    }

    return {
        "n_cases": len(rows),
        "n_with_results": len(have),
        "n_empty_recall": len(rows) - len(have),
        "score_scale": {
            "min": round(min(scores), 4) if scores else None,
            "p25": _pct(scores, 25), "median": _pct(scores, 50),
            "p75": _pct(scores, 75), "p90": _pct(scores, 90),
            "max": round(max(scores), 4) if scores else None,
        },
        # 同一阈值在各学科上的实际效果差多少个数量级 —— 这是「全局阈值不成立」的直接证据
        "by_subject_median_score": {s: round(statistics.median(v), 4) for s, v in sorted(by_subj.items())},
        "decision_bands": bands,
        "discrimination": {
            "top1_gold_hit_rate": round(sum(labels) / len(labels), 4) if labels else None,
            "any_topk_gold_hit_rate": (
                round(sum(1 for c in have if c["any_topk_is_gold"]) / len(have), 4) if have else None),
            "auc_top1_score_vs_gold": auc(pos, neg),
            "pos_median": _pct(pos, 50), "neg_median": _pct(neg, 50),
            "n_pos": n_pos, "n_neg": n_neg,
        },
        "threshold_curve": curve,
        "current_threshold_effect": {
            "accept_threshold": accept_threshold,
            "would_abstain_n": sum(1 for s in scores if s < accept_threshold),
            "would_abstain_rate": (
                round(sum(1 for s in scores if s < accept_threshold) / len(scores), 4) if scores else None),
            "false_abstain_among_answerable": (
                round(sum(1 for s, y in zip(scores, labels) if y and s < accept_threshold) / n_pos, 4)
                if n_pos else None),
        },
    }


def run_eval(db_path, out_path):
    if db_path:
        os.environ["DATABASE_PATH"] = db_path
    os.chdir(BASE_DIR)  # database.py 里的相对路径（data/、.env）以此为准

    from database import SessionLocal            # noqa: E402  （必须在 DATABASE_PATH 覆盖之后）
    from services import search_service          # noqa: E402
    from services.retrieval_gate import (        # noqa: E402
        RERANKER_RELEVANCE_THRESHOLD, RETRIEVAL_ACCEPT_TOP1_THRESHOLD,
        COMPLEX_RELEVANCE_THRESHOLD, COMPLEX_ACCEPT_TOP1_THRESHOLD,
        RETRIEVAL_GATE_MODE, evaluate_gate, is_complex_query,
    )

    with open(EVAL_SET, encoding="utf-8") as f:
        cases = json.load(f)

    def labelled(res, gset, query):
        top = res[0] if res else None
        score = None
        if top is not None:
            raw = top.get("rerank_score")
            if raw is None:
                raw = top.get("score", 0.0)
            score = float(raw)
        gate = evaluate_gate(res, query, is_complex=is_complex_query(query))
        return {
            "top1_score": None if score is None else round(score, 4),
            "top1_is_gold": bool(res) and ((top or {}).get("document_id") or 0) in gset,
            "any_topk_is_gold": bool(gset) and any((r.get("document_id") or 0) in gset for r in res),
            "decision": gate["decision"],
            "reason_codes": gate["reason_codes"],
            "would_abstain": bool(gate["would_abstain"]),
        }

    db = SessionLocal()
    try:
        gold = build_gold(db.connection().connection, cases)
        rerank_rows, rrf_rows = [], []
        for c in cases:
            gset = gold.get((c["subject"], tuple(c["rel_keywords"])), set())
            base = {"id": c["id"], "query": c["query"], "subject": c["subject"], "gold_count": len(gset)}
            rr = search_service.hybrid_search_with_rerank(
                db, c["query"], query_vec=None, limit=TOP_K, subject=c["subject"]) or []
            rf = search_service.hybrid_search(
                db, c["query"], query_vec=None, limit=TOP_K, subject=c["subject"]) or []
            rerank_rows.append({**base, "recall_n": len(rr), **labelled(rr, gset, c["query"])})
            rrf_rows.append({**base, "recall_n": len(rf), **labelled(rf, gset, c["query"])})
    finally:
        db.close()

    arms = {
        "rerank": arm_stats(rerank_rows, RERANKER_RELEVANCE_THRESHOLD, RETRIEVAL_ACCEPT_TOP1_THRESHOLD),
        "rrf": arm_stats(rrf_rows, RERANKER_RELEVANCE_THRESHOLD, RETRIEVAL_ACCEPT_TOP1_THRESHOLD),
    }
    report = {
        "eval_set": EVAL_SET,
        "db": os.environ.get("DATABASE_PATH", ""),
        "top_k": TOP_K,
        "gate_constants": {
            "mode": RETRIEVAL_GATE_MODE,
            "relevance_threshold": RERANKER_RELEVANCE_THRESHOLD,
            "accept_threshold": RETRIEVAL_ACCEPT_TOP1_THRESHOLD,
            "complex_relevance": COMPLEX_RELEVANCE_THRESHOLD,
            "complex_accept": COMPLEX_ACCEPT_TOP1_THRESHOLD,
        },
        "arms": arms,
        "verdict": None,
        "cases": {"rerank": rerank_rows, "rrf": rrf_rows},
    }
    report["verdict"] = verdict(report)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def verdict(report):
    """两路 AUC + 弃权带实占 → 一句可执行结论（能否定档）。"""
    aucs = {k: (v["discrimination"]["auc_top1_score_vs_gold"] or 0.0) for k, v in report["arms"].items()}
    best = max(aucs.values())
    ok = best >= MIN_AUC_FOR_ENFORCE

    # 弃权带（relevance<=top1<accept）才是 enforce 真正会「拒答」的区间：
    # 带内为空 → enforce 永不拒答；带内全是 gold → 拒的全是本来答得出的题。
    bands = {
        k: v.get("decision_bands", {}).get("abstain带_relevance<=s<accept")
        for k, v in report["arms"].items()
    }
    band_note = "；".join(
        f"{k} 弃权带 {v['n']} 条（其中可答 {v['gold_n']} 条）" if v else f"{k} 无弃权带数据"
        for k, v in bands.items()
    )
    return {
        "auc_by_arm": aucs,
        "best_auc": round(best, 4),
        "min_auc_for_enforce": MIN_AUC_FOR_ENFORCE,
        "abstain_band": bands,
        "can_set_threshold": ok,
        "reason": (
            "存在可分阈值，按 threshold_curve 选点后即可把 RETRIEVAL_GATE_MODE 切到 enforce"
            if ok else
            "两条分数路对 gold 的区分度都接近抛硬币（AUC < %.2f）：%s —— "
            "阈值切在加法分/名次分上，enforce 要么永不拒答、要么只拒可答题，"
            "所以保持 observe；要定档得先把阈值改写到归一化信号上（如学科内分位）"
            % (MIN_AUC_FOR_ENFORCE, band_note)
        ),
    }


def record(report, out_path):
    from database import SessionLocal
    from services.eval_store import record_eval_run, text_fingerprint

    summary = {k: v for k, v in report.items() if k != "cases"}
    v = summary["verdict"] or verdict(report)
    with open(EVAL_SET, encoding="utf-8") as f:
        cases = json.load(f)
    db = SessionLocal()
    try:
        # 留痕必须落在「看板读得到的那个库」上。用 --db 指向副本跑评测时，
        # 忘了再指一次就会把 eval_runs 写进副本里，看着成功、其实没人看得见。
        target = os.environ.get("DATABASE_PATH", "")
        print(f"eval_runs 写入目标：{target or '（.env 里的 DATABASE_PATH）'}")
        run_id = record_eval_run(
            "retrieval_abstention",
            arm="离线 50 题 gold 集，双分数路（rerank 加法分 / RRF 名次分），无向量无 LLM",
            metrics=summary,
            primary_metric=v["best_auc"],
            n_samples=summary["arms"]["rerank"]["n_cases"],
            fingerprint=text_fingerprint([c["query"] for c in cases]),
            notes=(f"best AUC {v['best_auc']}（rerank {v['auc_by_arm']['rerank']} / "
                   f"rrf {v['auc_by_arm']['rrf']}），定档门槛 {v['min_auc_for_enforce']}；"
                   f"top1 gold 命中率 rerank {summary['arms']['rerank']['discrimination']['top1_gold_hit_rate']} / "
                   f"rrf {summary['arms']['rrf']['discrimination']['top1_gold_hit_rate']}；{v['reason']}"),
            report_path=out_path,
            db=db,
        )
        print(f"入库：eval_runs #{run_id}" if run_id else "eval_runs 入库失败")
        return run_id
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="", help="评测用库（建议传 backup API 出来的副本）")
    ap.add_argument("--out", default=os.path.join(os.environ.get("TEMP_DIR", BASE_DIR),
                                                  "retrieval_abstention_eval.json"))
    ap.add_argument("--record", action="store_true", help="跑完即写一条 eval_runs")
    ap.add_argument("--record-only", action="store_true", help="只把 --out 里的既有报表写进 eval_runs")
    args = ap.parse_args()

    if args.record_only:
        if args.db:
            os.environ["DATABASE_PATH"] = args.db
        os.chdir(BASE_DIR)
        with open(args.out, encoding="utf-8") as f:
            report = json.load(f)
        if not report.get("verdict"):
            report["verdict"] = verdict(report)
    else:
        report = run_eval(args.db, args.out)

    print(json.dumps(report["arms"], ensure_ascii=False, indent=2))
    print("VERDICT " + json.dumps(report["verdict"], ensure_ascii=False))
    print("REPORT " + args.out)

    if args.record or args.record_only:
        record(report, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
