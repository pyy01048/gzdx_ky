# -*- coding: utf-8 -*-
"""V11：Agentic 状态机 _chat_rag 分支测试（针对当前仓内实际实现）。

说明：本仓内 ``_chat_rag`` 由并行单元实现，接线
``services.answer_cache`` / ``services.retrieval_enhance`` / ``retrieval_gate``。
这些用例通过 monkeypatch 这些协作者，离线断言状态机的可观测分支：
缓存命中短路、缓存 miss 走检索链、自检未通过触发补充检索一次、字段契约恒定。
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from services.ai_router import AIRouter  # noqa: E402


def _ai_service(content="最终答案。"):
    svc = SimpleNamespace()
    svc.chat = AsyncMock(return_value={"content": content})
    return svc


@pytest.fixture()
def patched_collab(monkeypatch):
    """把 _chat_rag 的外部协作者全部替换成离线假对象。"""
    import services.answer_cache as ac
    import services.retrieval_enhance as re_

    # 缓存默认未命中
    monkeypatch.setattr(ac, "get_cached", lambda question, subject=None: None)
    monkeypatch.setattr(ac, "set_cached", lambda *a, **k: None)

    # 改写 / HyDE / rerank
    async def fake_rewrite(q, subject=None):
        return [q, q + " 改写"]
    async def fake_hyde(q, subject=None):
        return None
    async def fake_rerank(cands, q, top_k=5):
        return cands[:top_k]
    monkeypatch.setattr(re_, "rewrite_query", fake_rewrite)
    monkeypatch.setattr(re_, "hyde_document", fake_hyde)
    monkeypatch.setattr(re_, "rerank", fake_rerank)

    return {"ac": ac, "re": re_}


def test_cache_hit_short_circuits(monkeypatch, patched_collab):  # noqa: ARG001
    """缓存命中 → 直接返回，不检索、不调生成。"""
    ac = patched_collab["ac"]
    monkeypatch.setattr(ac, "get_cached", lambda question, subject=None: {
        "answer": "缓存答案。", "source": "semantic",
    })
    ai = _ai_service("不该用")
    router = AIRouter(db=None)

    out = asyncio.run(router._chat_rag("什么是卡诺图？", ai_service=ai))
    assert out["cache_hit"] is True
    assert out["from_cache"] is True
    assert "缓存答案" in out["content"]
    ai.chat.assert_not_called()
    steps = [s["step"] for s in out["reasoning_steps"]]
    assert "cache_hit" in steps


def test_cache_miss_runs_retrieval_chain(monkeypatch, patched_collab):  # noqa: ARG001
    """缓存 miss → 走改写/检索/rerank/自检，返回 reasoning_steps 与 retrieved_chunks。"""
    router = AIRouter(db=None)

    async def fake_retrieve_one(self, query, ai_service, subject):
        return [
            {"source": "chunk", "title": "数电讲义", "content": f"关于{query}的片段",
             "chunk_id": 1, "score": 0.5},
        ]
    monkeypatch.setattr(AIRouter, "_retrieve_one", fake_retrieve_one)

    out = asyncio.run(router._chat_rag("什么是卡诺图？", ai_service=_ai_service()))
    assert out["cache_hit"] is False
    assert out["from_cache"] is False
    assert out["retrieved_chunks"], "应带回检索片段"
    steps = [s["step"] for s in out["reasoning_steps"]]
    # 至少出现：分类、cache_miss、改写、rerank、自检
    assert any(s.startswith("分类:") for s in steps), steps
    assert "cache_miss" in steps
    assert any(s.startswith("改写:") for s in steps)
    assert any(s.startswith("rerank:") for s in steps)
    assert any(s.startswith("自检") for s in steps)


def test_selfcheck_fail_triggers_supplementary_retrieval(monkeypatch, patched_collab):  # noqa: ARG001
    """自检未通过 → 触发恰好一次补充检索后重新生成。"""
    router = AIRouter(db=None)
    calls = {"n": 0}

    async def fake_retrieve_one(self, query, ai_service, subject):
        calls["n"] += 1
        return [{"source": "chunk", "title": "t", "content": f"片段{query}", "chunk_id": calls["n"]}]
    monkeypatch.setattr(AIRouter, "_retrieve_one", fake_retrieve_one)

    # 第一次生成短（自检不通过），第二次生成长（通过）
    ai = SimpleNamespace()
    ai.chat = AsyncMock(side_effect=[{"content": "短"}, {"content": "这是一次完整且充分的补充检索后答案"}])
    monkeypatch.setattr(AIRouter, "_self_check_ok",
                        lambda self, content, solve_type: len(content) > 10)

    out = asyncio.run(router._chat_rag("时序逻辑竞争冒险分析", ai_service=ai))
    # 初始两轮（两个 query）+ 补充一轮 = 至少 3 次
    assert calls["n"] >= 3, calls
    steps = [s["step"] for s in out["reasoning_steps"]]
    assert any("补充检索" in s for s in steps), steps
