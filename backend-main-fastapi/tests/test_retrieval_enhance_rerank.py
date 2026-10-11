# -*- coding: utf-8 -*-
"""V11：retrieval_enhance rerank 优先走 8140 bge 微服务的测试。"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import services.retrieval_enhance as re_  # noqa: E402


def _cands():
    return [
        {"content": "卡诺图定义", "title": "a"},
        {"content": "牛顿第二定律", "title": "b"},
    ]


def test_rerank_uses_bge_when_available(monkeypatch):
    """bge 返回分数时，rerank 用 bge 结果排序，且不调用 LLM 打分。"""
    async def fake_bge(cands, q):
        return {0: 0.9, 1: 0.1}
    monkeypatch.setattr(re_, "_bge_rerank_scores", fake_bge)

    llm_called = {"n": 0}
    async def fake_llm(cands, q):
        llm_called["n"] += 1
        return {0: 5}
    monkeypatch.setattr(re_, "_llm_scores", fake_llm)

    out = asyncio.run(re_.rerank(_cands(), "什么是卡诺图", top_k=2))
    assert out[0]["title"] == "a"  # bge 判 a 更相关
    assert llm_called["n"] == 0, "bge 可用时不应再调 LLM 打分"


def test_rerank_falls_back_to_llm_when_bge_down(monkeypatch):
    """bge 不可用(None) → 回退 LLM 打分。"""
    async def fake_bge(cands, q):
        return None
    monkeypatch.setattr(re_, "_bge_rerank_scores", fake_bge)
    monkeypatch.setattr(re_, "_llm_scores", AsyncMock(return_value={0: 2, 1: 9}))

    out = asyncio.run(re_.rerank(_cands(), "什么是卡诺图", top_k=2))
    # LLM 判 1(b) 更相关
    assert out[0]["title"] == "b"


def test_rerank_keeps_order_when_all_fail(monkeypatch):
    """bge 与 LLM 都无分数 → 保持原序截断。"""
    monkeypatch.setattr(re_, "_bge_rerank_scores", AsyncMock(return_value=None))
    monkeypatch.setattr(re_, "_llm_scores", AsyncMock(return_value={}))
    out = asyncio.run(re_.rerank(_cands(), "q", top_k=1))
    assert out[0]["title"] == "a"
