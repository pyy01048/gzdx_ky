# -*- coding: utf-8 -*-
"""
A3 RAG 检索门控（services/retrieval_gate.py）
=============================================
双阈值门控（借鉴 edu-rag 设计，代码自研）：
  RERANKER_RELEVANCE_THRESHOLD   0.50  —— 管"算不算相关"
  RETRIEVAL_ACCEPT_TOP1_THRESHOLD 0.60 —— 管"能不能放行"，必须 > 上面
  复杂问题（解答题/多问）放宽：0.35 / 0.45
  RETRIEVAL_GATE_MODE = "observe"       —— observe 灰度（收集 would_abstain）/ enforce

四条硬规则：
  1. 只信 rerank_score 做阈值（RRF 只定序）
  2. 拒答是节点不是 if-else：固定话术 + abstain_reason
  3. observe 灰度先收集 would_abstain 率，再切 enforce
  4. reason_codes 驱动重试策略，不随机重试：empty_recall→HyDE，low_relevance→step_back

每轮打点落库 retrieval_gate_logs。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# 配置分层
# --------------------------------------------------------------------------- #
RERANKER_RELEVANCE_THRESHOLD = 0.50
RETRIEVAL_ACCEPT_TOP1_THRESHOLD = 0.60
COMPLEX_RELEVANCE_THRESHOLD = 0.35
COMPLEX_ACCEPT_TOP1_THRESHOLD = 0.45
RETRIEVAL_GATE_MODE = "observe"  # observe | enforce
MAX_RETRY_DEPTH = 1              # 每个 query 最多重试 1 轮（HyDE 或 step_back）

_ABSTAIN_TEMPLATE = (
    "当前资料未覆盖【{gap}】，无法据此可靠回答。\n"
    "已给出可答部分：{partial}\n"
    "（引用：{citations}）\n"
    "已列入待补充清单，建议补充【{suggestion}】。"
)


def is_complex_query(query: str) -> bool:
    """启发式判断复杂问题：含子问序号 / 多问连词 / 长题干。"""
    q = (query or "").strip()
    if not q:
        return False
    markers = ["(1)", "（1）", "(2)", "（2）", "①", "②", "第一问", "第二问", "分别", "并且", "以及"]
    if any(m in q for m in markers):
        return True
    return len(q) >= 60


def evaluate_gate(
    results: List[Dict[str, Any]],
    query: str,
    is_complex: bool = False,
) -> Dict[str, Any]:
    """门控评估。返回 {decision, reason_codes, metrics, would_abstain}。

    decision: accept | retry | abstain | abort
    reason_codes: 驱动重试策略（empty_recall→HyDE / low_relevance→step_back）
    """
    rel_t = COMPLEX_RELEVANCE_THRESHOLD if is_complex else RERANKER_RELEVANCE_THRESHOLD
    acc_t = COMPLEX_ACCEPT_TOP1_THRESHOLD if is_complex else RETRIEVAL_ACCEPT_TOP1_THRESHOLD

    results = results or []
    if not results:
        return {
            "decision": "retry",
            "reason_codes": ["empty_recall"],
            "metrics": {"top1_score": 0.0, "topk_mean": 0.0, "top1_margin": 0.0, "distinct_doc_count": 0},
            "would_abstain": False,
        }

    # 只信 rerank_score
    def _score(r: Dict[str, Any]) -> float:
        s = r.get("rerank_score")
        if s is None:
            s = r.get("score", 0.0)
        try:
            return float(s)
        except (TypeError, ValueError):
            return 0.0

    top1 = _score(results[0])
    topk_mean = sum(_score(r) for r in results) / len(results)
    top1_margin = top1 - _score(results[1]) if len(results) >= 2 else top1
    distinct_doc_count = len({(r.get("document_id") or r.get("chunk_id") or r.get("doc_id")) for r in results})

    metrics = {
        "top1_score": round(top1, 4),
        "topk_mean": round(topk_mean, 4),
        "top1_margin": round(top1_margin, 4),
        "distinct_doc_count": distinct_doc_count,
    }

    # 重排器不可用（无任何分数）→ 按 mode 决定
    if all(_score(r) <= 0 for r in results):
        decision = "abort" if RETRIEVAL_GATE_MODE == "enforce" else "accept"
        return {
            "decision": decision,
            "reason_codes": ["reranker_down"],
            "metrics": metrics,
            "would_abstain": decision != "accept",
        }

    if top1 < rel_t:
        return {
            "decision": "retry",
            "reason_codes": ["low_relevance"],
            "metrics": metrics,
            "would_abstain": False,
        }
    if top1 < acc_t:
        decision = "abstain" if RETRIEVAL_GATE_MODE == "enforce" else "accept"
        return {
            "decision": decision,
            "reason_codes": ["below_accept"],
            "metrics": metrics,
            "would_abstain": True,  # observe 模式下"若 enforce 会拒答"
        }
    return {
        "decision": "accept",
        "reason_codes": [],
        "metrics": metrics,
        "would_abstain": False,
    }


# --------------------------------------------------------------------------- #
# 重试改写（reason_codes 驱动，不随机重试）
# --------------------------------------------------------------------------- #
def _chat_gateway(question: str, *, subject: Optional[str], task: str, system_prompt: str, db) -> str:
    from services.model_gateway import get_gateway

    res = get_gateway().chat(
        question=question,
        subject=subject,
        task=task,
        context=None,
        system_prompt=system_prompt,
        prefer=None,
        db=db,
    )
    return (res.get("answer") or "").strip()


def hyde_rewrite(query: str, *, subject: Optional[str] = None, db=None) -> str:
    """HyDE：生成假设答案，再以假设答案为检索查询。"""
    prompt = (
        "请针对下面这个问题，先写出你假设的、内容完整的参考答案（不必保证正确，"
        "但必须包含解题关键词、公式、专有名词），然后原样输出该参考答案文本：\n" + query
    )
    ans = _chat_gateway(
        query,
        subject=subject,
        task="qa_academic",
        system_prompt=prompt,
        db=db,
    )
    return ans if ans and len(ans) >= 8 else query


def step_back_rewrite(query: str, *, subject: Optional[str] = None, db=None) -> str:
    """step_back：回溯更宽泛概念（泛化查询，提高召回）。"""
    prompt = (
        "请把下面这个问题抽象为更宽泛、更基础的概念性问题（保留原问题的学科与核心概念，"
        "去掉具体数字/年份/选项），只输出改写后的宽泛问题：\n" + query
    )
    ans = _chat_gateway(
        query,
        subject=subject,
        task="qa_academic",
        system_prompt=prompt,
        db=db,
    )
    return ans if ans and len(ans) >= 8 else query


# --------------------------------------------------------------------------- #
# 拒答话术（节点式，先给可答部分 + 引用，再说明缺口）
# --------------------------------------------------------------------------- #
def build_abstain_message(
    query: str,
    *,
    partial: str = "",
    citations: List[str] = None,
    gap: str = "相关资料缺失或不足",
    suggestion: str = "该知识点的教材/真题解析资料",
) -> str:
    return _ABSTAIN_TEMPLATE.format(
        gap=gap,
        partial=partial or "暂无可靠依据",
        citations="、".join(citations or ["（无引用）"]),
        suggestion=suggestion,
    )


# --------------------------------------------------------------------------- #
# 落库
# --------------------------------------------------------------------------- #
def log_gate(
    db,
    *,
    query: str,
    is_complex: bool,
    decision: str,
    reason_codes: List[str],
    metrics: Dict[str, Any],
    would_abstain: bool,
    latency_ms: int,
) -> None:
    """每轮打点落库 retrieval_gate_logs。"""
    try:
        from services.module_a_schema import ensure_module_a_schema

        ensure_module_a_schema(db)
        conn = db.connection().connection
        from services.db_retry import exec_retry

        exec_retry(
            conn,
            """
            INSERT INTO retrieval_gate_logs
            (query, is_complex, decision, reason_codes, top1_score, topk_mean,
             top1_margin, distinct_doc_count, gate_mode, would_abstain, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query[:2000],
                1 if is_complex else 0,
                decision,
                json.dumps(reason_codes, ensure_ascii=False),
                metrics.get("top1_score", 0.0),
                metrics.get("topk_mean", 0.0),
                metrics.get("top1_margin", 0.0),
                metrics.get("distinct_doc_count", 0),
                RETRIEVAL_GATE_MODE,
                1 if would_abstain else 0,
                latency_ms,
            ),
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# 主入口：检索 + 门控 + 重试 + 落库
# --------------------------------------------------------------------------- #
def gate_and_retrieve(
    db,
    query: str,
    query_vec=None,
    limit: int = 6,
    subject: Optional[str] = None,
    is_complex: Optional[bool] = None,
    use_exam_lane: bool = True,
) -> Dict[str, Any]:
    """检索 + 门控主入口（A3 对外接口）。

    返回 {query, decision, reason_codes, metrics, would_abstain,
          results, retry_used, abstain_message, latency_ms}
    """
    t0 = time.time()
    from services.search_service import hybrid_search_with_rerank

    if is_complex is None:
        is_complex = is_complex_query(query)

    results = hybrid_search_with_rerank(db, query, query_vec=query_vec, limit=limit, subject=subject) or []

    gate = evaluate_gate(results, query, is_complex=is_complex)
    retry_used = False

    # reason_codes 驱动重试（每 query 最多 1 轮）
    if gate["decision"] == "retry" and gate["reason_codes"]:
        retry_used = True
        rc = gate["reason_codes"]
        rewritten = None
        if "empty_recall" in rc:
            rewritten = hyde_rewrite(query, subject=subject, db=db)
        elif "low_relevance" in rc:
            rewritten = step_back_rewrite(query, subject=subject, db=db)
        if rewritten and rewritten != query:
            results = hybrid_search_with_rerank(db, rewritten, query_vec=None, limit=limit, subject=subject) or []
            gate = evaluate_gate(results, query, is_complex=is_complex)
            gate["retry_query"] = rewritten

    latency_ms = round((time.time() - t0) * 1000)
    log_gate(
        db,
        query=query,
        is_complex=is_complex,
        decision=gate["decision"],
        reason_codes=gate.get("reason_codes") or [],
        metrics=gate.get("metrics") or {},
        would_abstain=bool(gate.get("would_abstain")),
        latency_ms=latency_ms,
    )

    abstain_message = ""
    if gate["decision"] == "abstain" or (gate["decision"] == "accept" and gate.get("would_abstain")):
        abstain_message = build_abstain_message(
            query,
            partial=results[0].get("content", "")[:200] if results else "",
            citations=[(results[0].get("document_title") or "")[:50]] if results else [],
        )

    return {
        "query": query,
        "decision": gate["decision"],
        "reason_codes": gate.get("reason_codes") or [],
        "metrics": gate.get("metrics") or {},
        "would_abstain": bool(gate.get("would_abstain")),
        "results": results,
        "retry_used": retry_used,
        "retry_query": gate.get("retry_query"),
        "abstain_message": abstain_message,
        "latency_ms": latency_ms,
    }


if __name__ == "__main__":  # pragma: no cover
    print("gate constants:", RERANKER_RELEVANCE_THRESHOLD, RETRIEVAL_ACCEPT_TOP1_THRESHOLD, RETRIEVAL_GATE_MODE)
