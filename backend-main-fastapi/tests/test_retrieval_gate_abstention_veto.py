"""检索弃权闸门为什么必须留在 observe（docx/16 §2.9；实测 2026-10-13，eval_runs #12）。

离线定档由 ``scripts/retrieval_abstention_eval.py`` 产出（50 题 gold 集，跑在 SQLite
backup API 复制出来的库副本上，生产文件未改）。实测数字：

* **rrf 路**（现网 RAG 实际用的 ``hybrid_search`` 名次分）：中位 0.0164、最大 99.02，
  50 条里 35 条落在 relevance 阈值 0.50 **以下**，而弃权带 ``[0.50, 0.60)`` 里
  **一条都没有** → 把 mode 改成 enforce 也永远不会拒答，只会让每个 query 多跑一次
  step_back 改写（白花一次 LLM）。
* **rerank 路**（``_term_boost`` 每命中 +2.0 的加法分）：中位 0.7231、最大 198.67，
  弃权带里只有 4 条，且这 4 条**全是 gold（本来答得出的题）** → enforce 只会误杀。
* 两路对 gold 的 AUC = **0.568 / 0.531**，都远低于定档门槛 0.75（≈抛硬币）。
* 学科量纲差两个数量级（数字电子技术中位 38.0 vs 政治 0.0164），
  所以「一个全局阈值」在这个分数上根本不成立。

本文件钉住的是**这条否决本身**：谁把 ``RETRIEVAL_GATE_MODE`` 改成 enforce，
或把阈值改成 0..1 相似度口径却不带新的实测，都会在这里变红。

红线：只用 conftest 的临时库，绝不碰 D:\\平台\\database\\kaoyan.db。
"""
from __future__ import annotations

import os

import pytest

LIVE_DB = r"D:\平台\database\kaoyan.db"


@pytest.fixture(autouse=True)
def _guard_live_db_untouched():
    stat = os.stat(LIVE_DB)
    before = (stat.st_mtime, stat.st_size)
    yield
    after = os.stat(LIVE_DB)
    assert (after.st_mtime, after.st_size) == before, "检索门控测试动了生产库"


def _hit(score, document_id=1):
    """构造一条只有分数的检索结果：evaluate_gate 无 rerank_score 时回退读 score。"""
    return {"score": score, "document_id": document_id, "content": "x" * 50}


def test_gate_must_stay_in_observe_until_re_calibrated():
    """模式守卫：没有新的可分实测之前，enforce 不许开（详见模块 docstring 的四个数）。"""
    from services import retrieval_gate

    assert retrieval_gate.RETRIEVAL_GATE_MODE == "observe", (
        "弃权阈值实测 AUC 只有 0.531/0.568（门槛 0.75），enforce 等于大面积误杀或永不拒答；"
        "要切必须先重跑 scripts/retrieval_abstention_eval.py 并拿出 can_set_threshold=true"
    )


def test_rrf_scale_never_reaches_the_abstain_band():
    """现网名次分（中位 0.0164）远低于 relevance 阈值：判成 retry 而非 abstain。

    这正是「enforce 等于没开闸门」的机理性证据 —— 不是概率小，是分数压根进不了弃权带。
    """
    from services.retrieval_gate import evaluate_gate

    gate = evaluate_gate([_hit(0.0164), _hit(0.0163), _hit(0.0162)], "极限的定义", is_complex=False)

    assert gate["decision"] == "retry"
    assert gate["reason_codes"] == ["low_relevance"]
    assert gate["would_abstain"] is False


def test_subject_scale_spans_the_threshold_by_two_orders():
    """同一组阈值：政治的名次分走 retry，数电的加法分直接 accept，弃权带被跨过。"""
    from services.retrieval_gate import evaluate_gate

    politics = evaluate_gate([_hit(0.0164), _hit(0.0160)], "马原 物质范畴", is_complex=False)
    electronics = evaluate_gate([_hit(38.0161), _hit(30.5)], "卡诺图 化简", is_complex=False)

    assert politics["decision"] == "retry"
    assert electronics["decision"] == "accept"
    assert electronics["would_abstain"] is False


def test_abstain_band_is_the_narrow_window_between_the_two_thresholds():
    """唯一会拒答的区间就是 [relevance, accept)，实测该区间里 4/4 都是可答题。"""
    from services.retrieval_gate import (
        RERANKER_RELEVANCE_THRESHOLD, RETRIEVAL_ACCEPT_TOP1_THRESHOLD, evaluate_gate)

    mid = (RERANKER_RELEVANCE_THRESHOLD + RETRIEVAL_ACCEPT_TOP1_THRESHOLD) / 2
    assert RERANKER_RELEVANCE_THRESHOLD < mid < RETRIEVAL_ACCEPT_TOP1_THRESHOLD

    gate = evaluate_gate([_hit(mid), _hit(0.1)], "whatever", is_complex=False)
    assert gate["decision"] == "accept", "observe 下不许真的拒答"
    assert gate["would_abstain"] is True, "弃权带判定必须仍可观测，否则定档没有数据"


def test_complex_query_uses_released_thresholds_but_same_scale_problem():
    """复杂题放宽到 0.35/0.45，但名次分仍整体低于该区间 → 放宽并不解决量纲问题。"""
    from services.retrieval_gate import (
        COMPLEX_ACCEPT_TOP1_THRESHOLD, COMPLEX_RELEVANCE_THRESHOLD, evaluate_gate)

    assert COMPLEX_RELEVANCE_THRESHOLD < COMPLEX_ACCEPT_TOP1_THRESHOLD

    gate = evaluate_gate([_hit(0.0164)], "(1) 求极限 (2) 说明理由", is_complex=True)
    assert gate["decision"] == "retry"
