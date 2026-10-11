# -*- coding: utf-8 -*-
"""V11：/api/ai/chat/router HTTP 层透传断言。

钉死后端把 Agentic 状态机 / 检索溯源字段真正透到 JSON 响应：
    reasoning_steps / retrieved_chunks(带 provenance) / cache_hit / from_cache /
    reranker_backend；同时保持旧字段 content 不变、向后兼容。

不触网、不连 Ollama：通过 monkeypatch ``get_ai_router`` 注入假 router。
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


def _fake_router_result():
    """模拟 _chat_rag 走完状态机后的返回。"""
    return {
        "content": "卡诺图是化简组合逻辑函数的方格图。",
        "engine_used": "rag",
        "classification": {"type": "knowledge", "need_rag": True},
        "fallback_used": False,
        "latency_ms": 123,
        "reason": "知识库问题",
        "reasoning_steps": [
            {"step": "plan", "question_type": "knowledge", "need_retrieval": True},
            {"step": "cache", "hit": False},
            {"step": "retrieval", "round": 1, "hit_count": 2,
             "reranker_backend": "bge", "degraded": []},
            {"step": "selfcheck", "grounded": True, "action": "answer"},
        ],
        "retrieved_chunks": [
            {"id": "chunk:1", "text": "卡诺图定义", "title": "数电讲义",
             "source_type": "chunk", "score": 0.1, "rerank_score": 0.99,
             "provenance": ["原问题"]},
        ],
        "cache_hit": False,
        "from_cache": False,
        "reranker_backend": "bge",
    }


@pytest.fixture()
def patched_router(monkeypatch):
    fake = SimpleNamespace(chat_with_router=AsyncMock(return_value=_fake_router_result()))
    monkeypatch.setattr("services.ai_router.get_ai_router", lambda db: fake)
    return fake


def test_chat_router_response_contract(client, patched_router):  # noqa: ARG001
    resp = client.post("/api/ai/chat/router", json={
        "messages": [{"role": "user", "content": "什么是卡诺图？"}],
        "use_rag": True,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 旧字段向后兼容
    assert data["content"].startswith("卡诺图")
    assert data["engine_used"] == "rag"
    assert "classification" in data
    assert "fallback_used" in data

    # V11 新增字段存在且结构正确
    assert isinstance(data["reasoning_steps"], list)
    steps = [s["step"] for s in data["reasoning_steps"]]
    assert "plan" in steps and "retrieval" in steps and "selfcheck" in steps

    assert isinstance(data["retrieved_chunks"], list)
    ch = data["retrieved_chunks"][0]
    assert "provenance" in ch and "score" in ch and "title" in ch

    assert data["cache_hit"] is False
    assert data["from_cache"] is False
    assert data["reranker_backend"] == "bge"


def test_chat_router_cache_hit_field(client, patched_router):  # noqa: ARG001
    """缓存命中场景：from_cache / cache_hit 透传为 True。"""
    hit = _fake_router_result()
    hit["cache_hit"] = True
    hit["from_cache"] = True
    hit["reasoning_steps"] = [
        {"step": "plan", "question_type": "knowledge", "need_retrieval": True},
        {"step": "cache", "hit": True, "score": 0.97},
    ]
    patched_router.chat_with_router.return_value = hit

    resp = client.post("/api/ai/chat/router", json={
        "messages": [{"role": "user", "content": "什么是卡诺图？"}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["cache_hit"] is True
    assert data["from_cache"] is True
    assert data["reasoning_steps"][-1]["step"] == "cache"
