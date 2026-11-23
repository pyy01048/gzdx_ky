# -*- coding: utf-8 -*-
"""性能波（2026-11-23）契约测试。

只锁"改动的行为契约"，不锁耗时数字（耗时见会话报告与
``.optimize_*`` 计时脚本口径）：

1. 检索词抽取与 tsquery 拼接的健壮性（PG 全文主查的入参安全）；
2. 首屏热力图三档：默认仍是逐日连续（W1 已提交契约），sparse 只回非零日 + 区间；
3. 检索链路预热的开关与幂等（SEARCH_WARMUP=0 不起线程）。
"""

from __future__ import annotations

import datetime

from utils.timeutil import local_today


# --------------------------------------------------------------------------- #
# 1. 检索词 / tsquery
# --------------------------------------------------------------------------- #
def test_query_terms_prefers_long_tokens_and_drops_stopwords():
    from services.search_service import query_terms

    core, terms = query_terms("卡诺图化简的原则是什么")
    assert core == "卡诺图化简的原则是什么"
    assert terms, "分词后必须有可用关键词"
    assert "的" not in terms and "什么" not in terms
    assert len(terms) <= 5
    assert terms == sorted(terms, key=len, reverse=True), "长词优先（区分度高）"


def test_query_terms_empty_input():
    from services.search_service import query_terms

    assert query_terms("") == ("", [])
    assert query_terms("   ") == ("", [])


def test_tsquery_or_quotes_and_strips_unsafe_chars():
    """词元必须逐个加引号，且不能把 `'` / 反斜杠 拼进字面量（会让 to_tsquery 语法报错）。"""
    from services.search_service import _tsquery_or

    assert _tsquery_or(["卡诺图", "化简"]) == "'卡诺图' | '化简'"
    assert _tsquery_or(["it's", "a\\b"]) == "'its' | 'ab'"
    assert _tsquery_or([]) == ""


# --------------------------------------------------------------------------- #
# 2. 热力图档位
# --------------------------------------------------------------------------- #
def _ledger_with_two_active_days():
    from services import study_calendar

    today = study_calendar.local_today()
    ledger = {}
    for offset, focus in ((0, 60), (3, 0), (10, 25)):
        d = today - datetime.timedelta(days=offset)
        act = study_calendar.DayActivity(date=d, focus_minutes=focus)
        ledger[d.isoformat()] = act
    return ledger, today


def test_heatmap_payload_default_is_contiguous_compact_series():
    """默认档（compact）契约不能动：前端按位置切片（days[-1] 必须是今天）。"""
    from services import study_calendar

    ledger, today = _ledger_with_two_active_days()
    block = study_calendar.heatmap_payload(ledger)
    assert block["mode"] == "compact"
    assert block["weeks"] == study_calendar.HEATMAP_WEEKS
    days = block["days"]
    assert days[-1]["date"] == today.isoformat()
    assert len(days) >= study_calendar.HEATMAP_WEEKS * 7
    assert set(days[0].keys()) == {"date", "focus_minutes", "questions_done", "words_done", "is_effective"}
    assert "range" not in block, "compact 档不带区间元数据（无稀疏语义）"


def test_heatmap_payload_sparse_only_returns_nonzero_days():
    from services import study_calendar

    ledger, today = _ledger_with_two_active_days()
    block = study_calendar.heatmap_payload(ledger, mode="sparse")
    days = block["days"]
    assert block["mode"] == "sparse"
    # 零日子被省略，只留下有产出/有效的日子
    assert days and all(d["focus_minutes"] or d["questions_done"] or d["words_done"] or d["is_effective"] for d in days)
    assert len(days) < block["range"]["day_count"]
    assert block["range"]["end"] == today.isoformat()
    assert block["omitted_zero_days"] == block["range"]["day_count"] - len(days)
    # 区间起点仍对齐到周一（前端据此铺 53×7 格子）
    assert datetime.date.fromisoformat(block["range"]["start"]).weekday() == 0
    assert (today - datetime.date.fromisoformat(block["range"]["start"])).days + 1 == block["range"]["day_count"]


def test_heatmap_payload_rejects_unknown_mode():
    from services import study_calendar

    try:
        study_calendar.heatmap_payload({}, mode="tiny")
    except ValueError:
        return
    raise AssertionError("未知档位必须报错，不能静默回退")


def test_dashboard_summary_sparse_via_route(client):
    """路由档位：默认 compact 连续，sparse 显式请求才稀疏（前端适配前不换默认）。"""
    dense = client.get("/api/dashboard/summary")
    assert dense.status_code == 200, dense.text
    body = dense.json()["heatmap"]
    assert body["mode"] == "compact"
    assert body["days"][-1]["date"] == local_today().isoformat()

    sparse = client.get("/api/dashboard/summary?heatmap=sparse")
    assert sparse.status_code == 200, sparse.text
    sb = sparse.json()["heatmap"]
    assert sb["mode"] == "sparse"
    assert len(sb["days"]) <= len(body["days"])
    assert sb["range"]["day_count"] == len(body["days"])


# --------------------------------------------------------------------------- #
# 3. 预热开关
# --------------------------------------------------------------------------- #
def test_search_warmup_disabled_by_env(monkeypatch):
    import services.search_warmup as sw

    monkeypatch.setenv("SEARCH_WARMUP", "0")
    monkeypatch.setattr(sw, "_started", False)
    assert sw.start_search_warmup() is False, "SEARCH_WARMUP=0 必须不起线程（测试/低配机器可关）"


def test_search_warmup_is_idempotent(monkeypatch):
    import services.search_warmup as sw

    monkeypatch.setenv("SEARCH_WARMUP", "1")
    monkeypatch.setattr(sw, "_started", False)
    monkeypatch.setattr(sw, "run_search_warmup", lambda: {"jieba": 0.0, "embedding": 0.0, "exam_index": 0.0})
    assert sw.start_search_warmup() is True
    assert sw.start_search_warmup() is False, "重复调用不得再起第二个预热线程"


def test_run_search_warmup_never_raises(monkeypatch):
    """预热的任一步炸了都只能告警：不能把异常带回启动流程。"""
    import services.search_warmup as sw

    def _boom():
        raise RuntimeError("模型缺失")

    monkeypatch.setattr(sw, "_warm_jieba", _boom)
    monkeypatch.setattr(sw, "_warm_embedding", _boom)
    monkeypatch.setattr(sw, "_warm_exam_index", _boom)
    out = sw.run_search_warmup()
    assert set(out) == {"jieba", "embedding", "exam_index"}


# --------------------------------------------------------------------------- #
# 4. 检索端点仍是 async 外壳 + 线程内同步链（不阻塞事件循环）
# --------------------------------------------------------------------------- #
def test_rag_search_endpoint_returns_hits(client):
    resp = client.post("/api/ai/rag-search", json={"query": "卡诺图", "limit": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "卡诺图"
    assert isinstance(body["hits"], list) and body["count"] == len(body["hits"])


def test_taxonomy_tree_include_points_contract(client):
    """增量档：只回章节聚合（无 knowledge_points 键），默认档契约逐字不变。"""
    full = client.get("/api/taxonomy/tree")
    assert full.status_code == 200, full.text
    fbody = full.json()
    assert fbody["points_included"] is True
    chapters = [c for s in fbody["tree"] for c in s["chapters"]]
    if chapters:
        assert "knowledge_points" in chapters[0]

    lite = client.get("/api/taxonomy/tree?include_points=false")
    assert lite.status_code == 200, lite.text
    lbody = lite.json()
    assert lbody["points_included"] is False
    for s in lbody["tree"]:
        for c in s["chapters"]:
            assert "knowledge_points" not in c
            assert c["knowledge_point_count"] >= 0  # 聚合数仍在，格子画得出来
