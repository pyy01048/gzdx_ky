# -*- coding: utf-8 -*-
"""AI-P0-1 防复发回归测试（批次 A-5）。

锁死这个真实事故：
    services/ai_router.py 在调用本地引擎时误写成 ``route.get("subject")``，
    但该作用域里只有 ``route_result``，于是抛 ``NameError``。
    异常被 ``chat_with_router`` 外层 ``except Exception`` 吞掉，静默回退到云端，
    本地引擎长期 0% 生效而无人发现。

本测试不真正加载模型、不访问网络、不调用云端：
    - 用假的异步 HTTP 客户端拦截 ``_chat_local`` 内部对 Ollama 的请求；
    - 用假的模型选型避免 ``_pick_local_model`` 去 ping /api/tags。
若将来再有人把 ``route_result`` 改回 ``route``（或本地路径再次静默失败），
``engine_used`` 就不会是 ``"local"``，本测试立即变红。
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

# 保证无论从哪个工作目录运行都能 import 到后端包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ai_router  # noqa: E402
from services.ai_router import AIRouter  # noqa: E402


# ============================================================================ #
# V11 模块4：_chat_rag Agentic 轻量状态机测试（不触网、不连 Ollama）
# ----------------------------------------------------------------------------
# 三个冻结模块全部 monkeypatch：
#   - services.answer_cache.get_cached / set_cached
#   - services.retrieval_enhance.rewrite_query / hyde_document / rerank
# ai_service 是 MagicMock：hybrid 检索(异步)/同步检索(同步)/chat(异步) 都被替换。
# ============================================================================ #

def _patch_cache(monkeypatch, *, hit=None):
    """把 answer_cache 的读写换成假实现；hit=None 表示未命中。"""
    import services.answer_cache as ac_mod
    monkeypatch.setattr(ac_mod, "get_cached", lambda query, subject=None: hit)
    monkeypatch.setattr(ac_mod, "set_cached", lambda *a, **k: None)


def _patch_enhance(monkeypatch, *, queries=None, hyde=None, rerank_impl=None):
    """把检索增强三函数换成假实现（不碰 Ollama）。

    rerank_impl 缺省时按原序截断 top_k；传 None 函数名可抛异常测降级。
    """
    import services.retrieval_enhance as re_mod

    async def _rewrite(question, subject=None):
        if queries is not None:
            return queries
        return [question]

    async def _hyde(question, subject=None):
        return hyde

    async def _rerank(candidates, query, top_k=5):
        if rerank_impl is not None:
            return rerank_impl(candidates, query, top_k)
        return list(candidates)[:top_k]

    monkeypatch.setattr(re_mod, "rewrite_query", _rewrite)
    monkeypatch.setattr(re_mod, "hyde_document", _hyde)
    monkeypatch.setattr(re_mod, "rerank", _rerank)


def _fake_chunk(cid, text):
    return {
        "score": 0.8, "source": "知识分块", "title": "讲义" + str(cid),
        "content": text, "doc_id": 1, "chunk_id": cid,
    }


def _make_ai_service(*, chat_side_effect=None, hybrid_hits=None, sync_hits=None):
    """构造离线 ai_service。chat_side_effect 可为 str（固定返回）或 list（按次返回）。"""
    svc = MagicMock()
    if isinstance(chat_side_effect, list):
        svc.chat = AsyncMock(side_effect=[{"content": s} for s in chat_side_effect])
    else:
        svc.chat = AsyncMock(return_value={"content": chat_side_effect or "默认答案。"})
    svc.search_knowledge_base_hybrid = AsyncMock(return_value=hybrid_hits or [])
    svc.search_knowledge_base = MagicMock(return_value=sync_hits or [])
    return svc


# 一个能通过自检的答案：长度>20、含结论词
_GOOD = "因此卡诺图是化简组合逻辑函数的图形工具，用于快速化简布尔表达式。"


def test_chat_rag_return_fields_compatible(monkeypatch):
    """返回字段兼容：content / retrieved_chunks 仍在，并带 agentic_steps/cache_hit。"""
    _patch_cache(monkeypatch)
    _patch_enhance(monkeypatch, queries=["卡诺图 定义"])
    ai = _make_ai_service(
        chat_side_effect=_GOOD,
        hybrid_hits=[_fake_chunk(1, "卡诺图定义"), _fake_chunk(2, "卡诺图化简")],
    )
    router = AIRouter(db=None)
    out = asyncio.run(router._chat_rag("根据数电资料，什么是卡诺图？", ai, None))

    assert "content" in out and out["content"]
    assert "retrieved_chunks" in out
    assert isinstance(out["agentic_steps"], list) and out["agentic_steps"]
    assert out["cache_hit"] is False
    # 资料题应走到 rerank 步骤
    assert any(s.startswith("rerank:") for s in out["agentic_steps"])


def test_chat_rag_cache_hit_returns_early(monkeypatch):
    """缓存命中 → 直接返回，不检索、不调 chat。"""
    _patch_cache(monkeypatch, hit={"answer": "缓存里的卡诺图答案。", "source": "exact"})
    _patch_enhance(monkeypatch)
    ai = _make_ai_service(chat_side_effect="不该被用到")
    router = AIRouter(db=None)
    out = asyncio.run(router._chat_rag("什么是卡诺图", ai, None))

    assert out["cache_hit"] is True
    assert "缓存里的卡诺图答案" in out["content"]
    assert out["retrieved_chunks"] == []
    ai.chat.assert_not_called()
    ai.search_knowledge_base_hybrid.assert_not_called()


def test_chat_rag_classify_failure_falls_back_to_default(monkeypatch):
    """分类失败 → 走默认资料路径，主链不抛异常。"""
    _patch_cache(monkeypatch)
    _patch_enhance(monkeypatch)
    ai = _make_ai_service(chat_side_effect=_GOOD)
    router = AIRouter(db=None)

    def _boom(question):
        raise RuntimeError("分类器炸了")

    monkeypatch.setattr(router, "classify_question", _boom)
    out = asyncio.run(router._chat_rag("根据资料讲讲竞争冒险", ai, None))

    assert out["content"]
    assert any(s.startswith("分类:") for s in out["agentic_steps"])


def test_chat_rag_rewrite_failure_uses_original_query(monkeypatch):
    """改写失败 → 用原查询检索（hybrid 首次调用入参即原问题）。"""
    import services.retrieval_enhance as re_mod

    _patch_cache(monkeypatch)

    async def _boom(question, subject=None):
        raise RuntimeError("改写炸了")

    monkeypatch.setattr(re_mod, "rewrite_query", _boom)
    async def _hyde_none(q, subject=None):
        return None
    monkeypatch.setattr(re_mod, "hyde_document", _hyde_none)
    async def _rerank_pass(c, query, top_k=5):
        return list(c)[:top_k]
    monkeypatch.setattr(re_mod, "rerank", _rerank_pass)

    ai = _make_ai_service(chat_side_effect=_GOOD, hybrid_hits=[_fake_chunk(1, "x")])
    router = AIRouter(db=None)
    out = asyncio.run(router._chat_rag("什么是戴维南定理？", ai, None))

    assert out["content"]
    first_call = ai.search_knowledge_base_hybrid.await_args_list[0]
    assert first_call.args[0] == "什么是戴维南定理？"


def test_chat_rag_retrieval_failure_generates_without_context(monkeypatch):
    """检索（hybrid + 同步）都失败 → 无上下文仍生成，不抛异常。"""
    _patch_cache(monkeypatch)
    _patch_enhance(monkeypatch, queries=["卡诺图"])
    ai = _make_ai_service(chat_side_effect=_GOOD)
    ai.search_knowledge_base_hybrid = AsyncMock(side_effect=RuntimeError("hybrid挂了"))
    ai.search_knowledge_base = MagicMock(side_effect=RuntimeError("fts也挂了"))
    router = AIRouter(db=None)
    out = asyncio.run(router._chat_rag("根据资料讲卡诺图", ai, None))

    assert out["content"]
    assert out["retrieved_chunks"] == []


def test_chat_rag_rerank_failure_keeps_original_order(monkeypatch):
    """rerank 抛异常 → 保持原序截断 top5，不改变候选顺序。"""
    import services.retrieval_enhance as re_mod

    _patch_cache(monkeypatch)
    chunks = [_fake_chunk(i, f"资料{i}") for i in range(3)]
    ai = _make_ai_service(chat_side_effect=_GOOD, hybrid_hits=chunks)
    _patch_cache(monkeypatch)

    async def _rewrite(q, subject=None):
        return [q]
    monkeypatch.setattr(re_mod, "rewrite_query", _rewrite)
    async def _hyde(q, subject=None):
        return None
    monkeypatch.setattr(re_mod, "hyde_document", _hyde)
    async def _rerank_boom(candidates, query, top_k=5):
        raise RuntimeError("rerank炸了")
    monkeypatch.setattr(re_mod, "rerank", _rerank_boom)

    router = AIRouter(db=None)
    out = asyncio.run(router._chat_rag("根据资料讲卡诺图", ai, None))

    assert out["content"]
    assert [c["chunk_id"] for c in out["retrieved_chunks"]] == [0, 1, 2]


def test_chat_rag_cache_read_write_failure_is_silent(monkeypatch):
    """缓存读写都抛异常 → 静默降级，照常生成，cache_hit=False。"""
    import services.answer_cache as ac_mod

    def _boom_read(query, subject=None):
        raise RuntimeError("读缓存炸了")
    monkeypatch.setattr(ac_mod, "get_cached", _boom_read)

    def _boom_write(*a, **k):
        raise RuntimeError("写缓存炸了")
    monkeypatch.setattr(ac_mod, "set_cached", _boom_write)

    _patch_enhance(monkeypatch, queries=["卡诺图"])
    ai = _make_ai_service(chat_side_effect=_GOOD, hybrid_hits=[_fake_chunk(1, "x")])
    router = AIRouter(db=None)
    out = asyncio.run(router._chat_rag("根据资料讲卡诺图", ai, None))

    assert out["content"]
    assert out["cache_hit"] is False


def test_chat_rag_selfcheck_fail_triggers_exactly_one_supplemental_retrieval(monkeypatch):
    """自检不过 → 补充检索恰好一次后重生成；hybrid 总调用数 = 主链1次 + 补充1次。"""
    _patch_cache(monkeypatch)
    # 改写只返回原查询 → 主链 hybrid 调用 1 次
    _patch_enhance(monkeypatch, queries=["什么是卡诺图"])
    # chat 第一次给太短的失败答案，第二次给通过自检的答案
    ai = _make_ai_service(
        chat_side_effect=["略", _GOOD],
        hybrid_hits=[_fake_chunk(1, "卡诺图")],
    )
    router = AIRouter(db=None)
    out = asyncio.run(router._chat_rag("根据资料，什么是卡诺图？", ai, None))

    assert out["content"] == _GOOD
    assert any("自检未通过:补充检索1次" in s for s in out["agentic_steps"])
    assert any("自检通过(补充检索后)" in s for s in out["agentic_steps"])
    # 主链 1 次 + 补充 1 次 = 2 次，恰好一次补充检索
    assert ai.search_knowledge_base_hybrid.await_count == 2


def test_chat_rag_circuit_question_records_no_image_channel(monkeypatch):
    """电路题 → agentic_steps 记录'已就绪但当前 chat 入口无图片通道'。"""
    _patch_cache(monkeypatch)
    _patch_enhance(monkeypatch, queries=["戴维南 定理"])
    ai = _make_ai_service(chat_side_effect=_GOOD, hybrid_hits=[_fake_chunk(1, "戴维南")])
    router = AIRouter(db=None)
    out = asyncio.run(router._chat_rag("用戴维南定理求等效电阻", ai, None))

    assert out["content"]
    assert any("分类:circuit" in s for s in out["agentic_steps"])
    assert any("无图片通道" in s for s in out["agentic_steps"])


class _FakeOllamaResponse:
    """模拟 Ollama /api/chat 的 200 响应。"""

    status_code = 200

    def json(self):
        # extract_answer 只认 content；给一段干净正文
        return {"message": {"content": "卡诺图是化简组合逻辑函数的图形工具。"}}


class _FakeOllamaClient:
    """模拟异步 HTTP 客户端：记录最后一次 POST，不触网。"""

    def __init__(self):
        self.last_post = None

    async def post(self, url, **kwargs):
        self.last_post = {"url": url, "json": kwargs.get("json", {})}
        return _FakeOllamaResponse()

    async def get(self, url, **kwargs):
        # 仅兜底：本用例不应走到这里
        return _FakeOllamaResponse()


def _make_router(monkeypatch) -> AIRouter:
    """构造一个完全离线的 AIRouter：本地 HTTP 与模型选型都被替换。"""
    router = AIRouter(db=None)

    fake_client = _FakeOllamaClient()
    # 替换模块级导入的 get_async_client，_chat_local 内部用的就是它
    monkeypatch.setattr(ai_router, "get_async_client", lambda: fake_client)

    # 模型选型固定返回一个名字，避免 _pick_local_model 去 GET /api/tags
    async def _fixed_pick(subject=None):
        return "qwen3:8b"

    monkeypatch.setattr(router, "_pick_local_model", _fixed_pick)
    router._fake_client = fake_client  # 供断言读取

    return router


def test_force_local_uses_local_engine(monkeypatch):
    """A-5 核心断言：force_engine='local' 时 engine_used 必须是 'local'。

    若 AI-P0-1（route 未定义 NameError）复发，本地分支会抛错并被外层 except
    吞掉，回退到 api，最终 engine_used 不再是 'local' —— 本用例随之失败。
    """
    router = _make_router(monkeypatch)
    # ai_service 只在走云端分支时才会被用到；做成异步 mock 避免意外真调用
    ai_service = MagicMock()
    ai_service.chat = AsyncMock(return_value={"content": "云端不该被用到"})

    result = asyncio.run(
        router.chat_with_router(
            question="什么是卡诺图？",          # 命中“卡诺图”→识别为数字电子技术
            ai_service=ai_service,
            context=None,
            force_engine="local",               # 即前端 request.force_local=True
        )
    )

    # 核心断言
    assert result["engine_used"] == "local", (
        f"force_local 时 engine_used 必须是 local，实际是 {result['engine_used']!r}"
        f"（很可能本地分支再次静默失败并回退，last_error={result.get('error')}）"
    )
    # 本地成功就不应触发回退
    assert result["fallback_used"] is False
    # 内容必须来自本地假响应，而不是云端
    assert "卡诺图是化简组合逻辑函数" in result["content"]


def test_local_engine_actually_posted_to_ollama(monkeypatch):
    """补充断言：本地路径真的走到了对 Ollama 的 POST（而不是被静默跳过）。"""
    router = _make_router(monkeypatch)
    ai_service = MagicMock()
    ai_service.chat = AsyncMock(return_value={"content": "x"})

    asyncio.run(
        router.chat_with_router(
            question="什么是卡诺图？",
            ai_service=ai_service,
            context=None,
            force_engine="local",
        )
    )

    posted = router._fake_client.last_post
    assert posted is not None, "本地引擎应当真的发起一次 Ollama /api/chat 请求"
    assert posted["url"].endswith("/api/chat"), posted["url"]
    # 模型名来自被固定的 _pick_local_model；subject 由 route_result 正确透传
    assert posted["json"]["model"] == "qwen3:8b"
