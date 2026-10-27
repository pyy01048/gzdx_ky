# -*- coding: utf-8 -*-
"""P0 防复发回归测试：推理型模型（云知声 u2-flash）只输出 reasoning_content 时，
AI 对话/流式接口必须仍然返回可读文本，而不是 content=null / 空流挂起。

背景（2026-10-23 线上走查）：
- 默认链路选中的云知声 u2-flash 在复杂问题上先输出大量 reasoning_content 思维链，
  被 max_tokens 截断后 content 仍为 null。
- 旧实现 ``_parse_response`` 直接返回 content=null → /api/ai/chat 返回 content:null；
  ``_call_provider_stream`` 只收集 delta.content → 流式没有任何 delta 事件，
  前端一直"生成中…"最终 ERR_ABORTED。

本测试不触网、不连真实 Ollama：
- ``_parse_response`` 直接喂构造的响应体断言兜底；
- ``_call_provider_stream`` 用假 httpx 流（只吐 reasoning_content）断言流结束会
  把 reasoning_content 作为兜底 content 输出。
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from services.ai_service import AIService  # noqa: E402


# --------------------------------------------------------------------------- #
# _parse_response：content=null 时用 reasoning_content 兜底
# --------------------------------------------------------------------------- #
def _make_provider(provider_type="custom"):
    from models import AIProvider

    return AIProvider(
        name="yun",
        provider_type=provider_type,
        base_url="https://maas-api.unisound.com/v1",
        api_key="sk-test",
        model_name="u2-flash",
        is_enabled=True,
    )


def test_parse_response_content_null_falls_back_to_reasoning():
    ai = AIService.__new__(AIService)  # 不触发 __init__
    provider = _make_provider()
    data = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "这是思维链内容",
            }
        }],
        "usage": {"total_tokens": 10},
    }
    content, usage = ai._parse_response(provider, data)
    assert content == "这是思维链内容"
    assert usage == {"total_tokens": 10}


def test_parse_response_normal_content_unchanged():
    ai = AIService.__new__(AIService)
    provider = _make_provider()
    data = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "正常回答",
                "reasoning_content": "内部思考",
            }
        }],
    }
    content, _usage = ai._parse_response(provider, data)
    assert content == "正常回答"


def test_parse_response_both_empty_returns_empty_string():
    ai = AIService.__new__(AIService)
    provider = _make_provider()
    data = {"choices": [{"message": {"role": "assistant", "content": None}}]}
    content, _usage = ai._parse_response(provider, data)
    assert content == ""


# --------------------------------------------------------------------------- #
# _call_provider_stream：流式只吐 reasoning_content 时，流结束必须兜底输出
# --------------------------------------------------------------------------- #
class _FakeStreamResponse:
    """模拟 httpx.stream 的异步上下文，只返回 SSE 推理块，无 content。"""

    def __init__(self, chunks, status_code=200):
        self._chunks = chunks
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    async def aiter_text(self):
        for c in self._chunks:
            yield c


def _make_fake_client(stream_resp):
    """构造假的 get_async_client() 返回对象。"""

    class _FakeStreamCtx:
        """异步上下文管理器包装，模拟 httpx 的 ``async with client.stream(...)``。"""

        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, *exc):
            return False

    class _FakeClient:
        def stream(self, method, url, headers=None, json=None, timeout=None):
            return _FakeStreamCtx(_FakeStreamResponse(stream_resp))

    return _FakeClient()


def _sse_chunk(rc_text):
    import json

    obj = {
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "reasoning_content": rc_text},
            "finish_reason": None,
        }]
    }
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _run_stream(monkeypatch, chunks):
    from services import ai_service as ai_mod

    ai = AIService.__new__(AIService)
    provider = _make_provider()
    fake_client = _make_fake_client(chunks)
    monkeypatch.setattr(ai_mod, "get_async_client", lambda: fake_client)

    events = []

    async def _collect():
        async for ev in ai._call_provider_stream(provider, [{"role": "user", "content": "q"}]):
            events.append(ev)

    # 某些 pytest 插件会在当前线程跑事件循环，asyncio.run 会报
    # "cannot be called from a running event loop"；用独立 loop 运行。
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_collect())
    finally:
        loop.close()
    return events


def test_call_provider_stream_reasoning_only_falls_back(monkeypatch):
    chunks = [
        _sse_chunk("我们需要"),
        _sse_chunk("分析泰勒公式"),
        "data: [DONE]\n\n",
    ]
    events = _run_stream(monkeypatch, chunks)

    # 流式过程不把思维链当 delta 输出（避免泄露内部推理）
    deltas = [e for e in events if e["type"] == "delta"]
    assert deltas == []

    # 流结束：content 为空时必须用 reasoning_content 兜底，不能空流挂起
    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert done[0]["content"] == "我们需要分析泰勒公式"


def test_call_provider_stream_normal_content_still_works(monkeypatch):
    """正常模型（流式有 content）行为不变：delta 实时输出。"""
    import json

    obj = {
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": "正常回答"},
            "finish_reason": None,
        }]
    }
    chunks = [f"data: {json.dumps(obj, ensure_ascii=False)}\n\n", "data: [DONE]\n\n"]
    events = _run_stream(monkeypatch, chunks)

    deltas = [e for e in events if e["type"] == "delta"]
    assert [e["content"] for e in deltas] == ["正常回答"]
    done = [e for e in events if e["type"] == "done"]
    assert done[0]["content"] == "正常回答"


# --------------------------------------------------------------------------- #
# 2026-10-23 P0 增强：推理缓冲阈值主动输出
# u2-flash 复杂问题会长时间只吐 reasoning_content（甚至耗尽 max_tokens 仍无
# content）。若流不主动输出任何 delta，前端永远"生成中…"。当累积思维链超过
# 阈值（120 字符，原 2000 过高导致首屏长时间无进展）且从未输出过 content 时，
# 必须把思维链作为 delta 主动输出。
# --------------------------------------------------------------------------- #
def test_call_provider_stream_reasoning_overflow_flushes_delta(monkeypatch):
    """只吐思维链且累积超过阈值时，流中途必须主动输出 delta，避免前端挂起。"""
    # 每次 600 字符，4 次共 2400 > 120 阈值，应触发主动输出
    chunks = [
        _sse_chunk("推" * 600),
        _sse_chunk("理" * 600),
        _sse_chunk("内" * 600),
        _sse_chunk("容" * 600),
        "data: [DONE]\n\n",
    ]
    events = _run_stream(monkeypatch, chunks)

    # 流开始必须先发 status=thinking，前端据此展示「模型思考中…」
    statuses = [e for e in events if e["type"] == "status"]
    assert statuses and statuses[0]["status"] == "thinking"

    deltas = [e for e in events if e["type"] == "delta"]
    # 必须至少有一个 delta 主动输出（不是空流挂起）
    assert len(deltas) == 1
    assert len(deltas[0]["content"]) >= 120

    # done 事件仍要兜底，保证 content 非空
    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert len(done[0]["content"]) == 2400


def test_call_provider_stream_reasoning_below_threshold_no_flush(monkeypatch):
    """思维链未超阈值且流正常结束时：不主动输出 delta，仅 done 兜底（原行为）。"""
    chunks = [
        _sse_chunk("短思维链"),
        "data: [DONE]\n\n",
    ]
    events = _run_stream(monkeypatch, chunks)

    deltas = [e for e in events if e["type"] == "delta"]
    assert deltas == []

    done = [e for e in events if e["type"] == "done"]
    assert done[0]["content"] == "短思维链"