# -*- coding: utf-8 -*-
"""2026-11-22 AI 答疑 502 根治回归。

锁定三件事：
1. 全服务商失败 → 离线知识库兜底（degraded=True），不再抛 502 / 不再丢 error 空流；
2. 聚合错误逐段归因，「鉴权(401/403)优先于连通性(connect/timeout)」——换 Key 比查网络更可行动；
3. chat() 降级链里的本地 Ollama 服务商必须走 _call_ollama，而不是被当云端 OpenAI POST。

不触网、不连真实 Ollama：monkeypatch 服务商调用与知识库检索。
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.ai.ai import _classify_ai_error, _reason_from_text  # noqa: E402
from services.ai_service import AIService  # noqa: E402

from models import AIProvider  # noqa: E402


# --------------------------------------------------------------------------- #
# 归因：鉴权优先于连通性
# --------------------------------------------------------------------------- #
def test_reason_from_text_single_segment():
    assert _reason_from_text("403 Forbidden") == "provider_auth"
    assert _reason_from_text("401 Unauthorized") == "provider_auth"
    assert _reason_from_text("All connection attempts failed") == "provider_unreachable"
    assert _reason_from_text("request timed out") == "provider_unreachable"
    assert _reason_from_text("500 internal boom") == "upstream_error"


def test_classify_aggregated_auth_beats_connect():
    # 线上真因：云知声 Key 失效 403 在链首，链尾 Ollama 连接错误是噪声，不得盖住真因。
    exc = RuntimeError(
        "所有 AI 服务商调用失败，最后错误：云知声: 403 Forbidden; "
        "本地学术答疑: All connection attempts failed; 文档处理: All connection attempts failed"
    )
    code, hint = _classify_ai_error(exc)
    assert code == "provider_auth"
    assert "Key" in hint


def test_classify_aggregated_connect_only():
    exc = RuntimeError("所有 AI 服务商调用失败，最后错误：本地学术答疑: All connection attempts failed")
    assert _classify_ai_error(exc)[0] == "provider_unreachable"


def test_classify_no_provider_and_local():
    assert _classify_ai_error(ValueError("没有可用的 AI 服务商配置"))[0] == "no_provider"
    assert _classify_ai_error(RuntimeError("本地模型调用失败：connect"))[0] == "local_unavailable"


# --------------------------------------------------------------------------- #
# 离线兜底结果结构
# --------------------------------------------------------------------------- #
def _kb_hits():
    return [{"source": "doc", "title": "数电讲义", "content": "卡诺图是化简组合逻辑函数的方格图。"}]


def test_offline_fallback_result_structure():
    ai = AIService.__new__(AIService)
    ai.search_knowledge_base = lambda query, limit=6, min_score=1.0, subject=None: _kb_hits()
    res = ai._offline_fallback_result("什么是卡诺图", ["云知声: 403 Forbidden"], "智能路由")
    assert res["provider"] == "offline-kb"
    assert res["route"] == "offline"
    assert res["degraded"] is True
    assert res["provider_errors"] == ["云知声: 403 Forbidden"]
    assert "卡诺图" in res["content"]
    assert "智能路由" in res["route_reason"]


def test_offline_fallback_empty_kb_guidance():
    ai = AIService.__new__(AIService)
    ai.search_knowledge_base = lambda *a, **k: []
    res = ai._offline_fallback_result("冷门问题", [])
    assert res["degraded"] is True
    assert "离线" in res["content"]


# --------------------------------------------------------------------------- #
# chat() / chat_stream() 全链失败 → 离线兜底
# --------------------------------------------------------------------------- #
def _wire_failing_chain(ai, calls=None):
    cloud = AIProvider(name="云知声", provider_type="custom", api_key="sk-x", is_enabled=True)
    local = AIProvider(name="本地学术答疑", provider_type="ollama", is_enabled=True)
    ai.is_unsafe = lambda text: False
    ai._route_query = lambda messages, kb_hit_count=0: ("online", "智能路由")
    ai._get_provider = lambda provider_id=None: cloud
    ai._get_fallback_providers = lambda exclude_id: [local]
    ai.search_knowledge_base = lambda query, limit=6, min_score=1.0, subject=None: _kb_hits()

    async def fail_provider(p, messages, temperature=None):
        if calls is not None:
            calls.append("provider")
        raise RuntimeError("403 Forbidden")

    async def fail_ollama(p, messages, temperature=None):
        if calls is not None:
            calls.append("ollama")
        raise RuntimeError("All connection attempts failed")

    ai._call_provider = fail_provider
    ai._call_ollama = fail_ollama
    return cloud, local


def test_chat_full_chain_failure_returns_offline_not_502():
    ai = AIService.__new__(AIService)
    calls = []
    _wire_failing_chain(ai, calls)
    res = asyncio.run(ai.chat([{"role": "user", "content": "什么是卡诺图"}], use_routing=True, offline_fallback=True))
    assert res["provider"] == "offline-kb"
    assert res["route"] == "offline"
    assert res["degraded"] is True
    assert any("403" in e for e in res["provider_errors"])
    assert "卡诺图" in res["content"]
    # 降级链里的本地服务商必须走 _call_ollama，而不是被当云端 POST
    assert "ollama" in calls


def test_chat_stream_full_chain_failure_done_degraded():
    ai = AIService.__new__(AIService)
    _wire_failing_chain(ai)

    async def fail_stream(p, messages, temperature=None):
        raise RuntimeError("403 Forbidden")
        yield {}  # 使其成为异步生成器（不可达）

    ai._call_provider_stream = fail_stream

    async def collect():
        return [ev async for ev in ai.chat_stream([{"role": "user", "content": "什么是卡诺图"}], offline_fallback=True)]

    events = asyncio.run(collect())
    done = [e for e in events if e.get("type") == "done"]
    assert done, "全链失败必须产出 done 事件而不是 error/空流"
    last = done[-1]
    assert last["degraded"] is True
    assert last["route"] == "offline"
    assert "卡诺图" in last["content"]
    assert not any(e.get("type") == "error" for e in events)


def test_chat_default_raises_to_protect_internal_callers():
    # 内部/批处理调用方（文档知识点提取、作文批改等）默认 offline_fallback=False：
    # 全链失败必须抛异常，绝不能返回 KB 片段被当结构化数据写入污染下游。
    ai = AIService.__new__(AIService)
    _wire_failing_chain(ai)
    with pytest.raises(RuntimeError, match="所有 AI 服务商调用失败"):
        asyncio.run(ai.chat([{"role": "user", "content": "提取知识点"}]))


def test_chat_stream_default_yields_error_not_offline():
    ai = AIService.__new__(AIService)
    _wire_failing_chain(ai)

    async def fail_stream(p, messages, temperature=None):
        raise RuntimeError("403 Forbidden")
        yield {}  # 使其成为异步生成器（不可达）

    ai._call_provider_stream = fail_stream

    async def collect():
        return [ev async for ev in ai.chat_stream([{"role": "user", "content": "x"}])]

    events = asyncio.run(collect())
    assert any(e.get("type") == "error" for e in events)
    assert not any(e.get("type") == "done" and e.get("degraded") for e in events)
