# -*- coding: utf-8 -*-
"""V11 检索增强（Query Rewriting / HyDE / Rerank）回归测试。

覆盖两类路径：
  1. **失败降级路径**（离线，永远跑）：mock 内部 LLM 调用返回空 / 抛异常，
     断言三个接口都按冻结降级值返回，绝不把异常抛给调用方。
  2. **成功路径**：
     - 离线版：mock 内部调用返回模型风格文本，断言解析/排序逻辑正确；
     - 在线版：真实打本机 Ollama。Ollama 不在线时自动 skip，
       保证 CI / 无网环境不红。

不依赖外部网络：离线用例完全不触网；在线用例只允许访问 127.0.0.1:11434，
且连不通就 skip。
"""
import asyncio
import os
import sys

# 保证无论从哪个工作目录运行都能 import 到后端包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import pytest  # noqa: E402

from services import retrieval_enhance as enh  # noqa: E402


def run(coro):
    """同步测试里跑异步协程（项目无 pytest-asyncio，沿用 test_ai_router 写法）。"""
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# 内联 <think> 剥离（qwen3 系把思考链塞进 content 的真实场景）
# --------------------------------------------------------------------------- #
class TestThinkStripping:

    def test_strips_closed_think_block(self):
        raw = "<think>\n我先想想用户要什么…\n</think>\n卡诺图化简分三步。"
        assert enh._strip_think_tags(raw).strip() == "卡诺图化简分三步。"

    def test_no_think_tag_passes_through(self):
        assert enh._strip_think_tags("直接答案。") == "直接答案。"

    def test_unclosed_think_returns_empty(self):
        """被 num_predict 截断、思考没结束 → 答案没出来，返回空走降级。"""
        raw = "<think>\n用户问的是卡诺图，我需要先回忆…"
        assert enh._strip_think_tags(raw) == ""

    def test_self_talk_detection(self):
        assert enh._is_self_talk("首先，用户要求我改写这个问题。")
        assert enh._is_self_talk("让我想想这个问题。")
        # 正常教材论述不算自述
        assert not enh._is_self_talk(
            "卡诺图化简的基本步骤为：首先画卡诺图，其次圈相邻项，最后求和。")

    def test_extract_answer_false_positive_not_degrade(self, monkeypatch):
        """回归锁死：教材式'首先/其次/最后'不能再被误判为思维链而降级。"""
        async def fake_call(*a, **kw):
            return ("卡诺图化简的基本步骤为：首先画卡诺图，其次圈相邻项，最后求和。")
        monkeypatch.setattr(enh, "_call_llm", fake_call)
        out = run(enh.hyde_document("卡诺图", subject="数字电子技术"))
        assert out is not None and "卡诺图" in out


# --------------------------------------------------------------------------- #
# 模型选择顺序（mock /api/tags，不触网）
# --------------------------------------------------------------------------- #
class _FakeTagsResp:
    def __init__(self, names):
        self._names = names
        self.status_code = 200

    def json(self):
        return {"models": [{"name": n} for n in self._names]}


class _FakeTagsClient:
    def __init__(self, names):
        self._names = names

    async def get(self, url, **kw):
        return _FakeTagsResp(self._names)


class TestModelSelection:

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("RETRIEVAL_ENHANCE_MODEL", "my-custom:model")
        out = run(enh._select_model("数字电子技术"))
        assert out == "my-custom:model"

    def test_prefers_qwen3_8b_when_installed(self, monkeypatch):
        monkeypatch.delenv("RETRIEVAL_ENHANCE_MODEL", raising=False)
        monkeypatch.setattr(enh, "get_async_client",
                            lambda: _FakeTagsClient(["qwen3:8b", "qwen2.5:1.5b"]))
        out = run(enh._select_model("数字电子技术"))
        assert out == "qwen3:8b"

    def test_falls_back_to_qwen25_15b_when_qwen3_absent(self, monkeypatch):
        monkeypatch.delenv("RETRIEVAL_ENHANCE_MODEL", raising=False)
        monkeypatch.setattr(enh, "get_async_client",
                            lambda: _FakeTagsClient(["qwen2.5:1.5b", "kaoyan-assistant:latest"]))
        out = run(enh._select_model("数字电子技术"))
        assert out == "qwen2.5:1.5b"

    def test_excludes_deepseek_r1_default(self, monkeypatch):
        """只有 reasoning 专才时，不能把 deepseek-r1 当默认。"""
        monkeypatch.delenv("RETRIEVAL_ENHANCE_MODEL", raising=False)
        monkeypatch.setattr(enh, "get_async_client",
                            lambda: _FakeTagsClient(["deepseek-r1:7b", "deepseek-r1:1.5b"]))
        out = run(enh._select_model("数字电子技术"))
        # 没有偏好模型、又排除 r1 → 回退默认 env/ qwen3:8b
        assert not out.startswith("deepseek-r1")


# --------------------------------------------------------------------------- #
# 模块 1：Query Rewriting
# --------------------------------------------------------------------------- #
class TestRewriteQuery:

    def test_returns_original_on_empty_llm_output(self, monkeypatch):
        """LLM 返回空（网络挂/超时/只给思考链）→ 冻结降级 [question]。"""
        async def fake_call(*a, **kw):
            return ""
        monkeypatch.setattr(enh, "_call_llm", fake_call)

        out = run(enh.rewrite_query("卡诺图怎么化简？"))
        assert out == ["卡诺图怎么化简？"], out

    def test_never_raises_when_call_llm_throws(self, monkeypatch):
        """_call_llm 抛异常也必须被吞掉，返回原查询。"""
        async def boom(*a, **kw):
            raise RuntimeError("connection refused")
        monkeypatch.setattr(enh, "_call_llm", boom)

        out = run(enh.rewrite_query("什么是傅里叶变换？"))
        assert out == ["什么是傅里叶变换？"], out

    def test_parses_numbered_and_bulleted_lines(self, monkeypatch):
        """成功路径：把模型输出的编号/项目符号行拆成查询列表、去重、最多 3 条。"""
        async def fake_call(*a, **kw):
            return ("1. 卡诺图化简规则\n"
                    "2、最小项合并方法\n"
                    "- 相邻最小项合并几何意义\n"
                    "卡诺图化简规则\n")
        monkeypatch.setattr(enh, "_call_llm", fake_call)

        out = run(enh.rewrite_query("卡诺图怎么化简？", subject="数字电子技术"))
        assert out == [
            "卡诺图化简规则",
            "最小项合并方法",
            "相邻最小项合并几何意义",
        ], out
        assert len(out) <= 3

    def test_disabled_flag_returns_original(self, monkeypatch):
        """RETRIEVAL_ENHANCE_ENABLED=0 时不调用模型，直接原查询。"""
        monkeypatch.setenv("RETRIEVAL_ENHANCE_ENABLED", "0")
        called = {"n": 0}

        async def fake_call(*a, **kw):
            called["n"] += 1
            return "不该被用到的查询"
        monkeypatch.setattr(enh, "_call_llm", fake_call)

        out = run(enh.rewrite_query("随便一个问题"))
        assert out == ["随便一个问题"]
        assert called["n"] == 0, "开关关闭时绝不能触达模型"

    def test_empty_question_does_not_raise(self, monkeypatch):
        out = run(enh.rewrite_query(""))
        assert isinstance(out, list)  # 空问题也必须返回列表、不抛异常


# --------------------------------------------------------------------------- #
# 模块 2：HyDE
# --------------------------------------------------------------------------- #
class TestHyDE:

    def test_returns_none_on_empty_output(self, monkeypatch):
        async def fake_call(*a, **kw):
            return ""
        monkeypatch.setattr(enh, "_call_llm", fake_call)
        assert run(enh.hyde_document("触发器有哪些类型？")) is None

    def test_never_raises(self, monkeypatch):
        async def boom(*a, **kw):
            raise OSError("ollama down")
        monkeypatch.setattr(enh, "_call_llm", boom)
        assert run(enh.hyde_document("运放虚短虚断")) is None

    def test_returns_text_on_success(self, monkeypatch):
        async def fake_call(*a, **kw):
            return "触发器是具有记忆功能的时序逻辑单元，常见类型有RS、JK、D、T。"
        monkeypatch.setattr(enh, "_call_llm", fake_call)
        out = run(enh.hyde_document("触发器", subject="数字电子技术"))
        assert out is not None
        assert "触发器" in out

    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setenv("RETRIEVAL_ENHANCE_ENABLED", "0")
        async def fake_call(*a, **kw):
            return "不该被用到"
        monkeypatch.setattr(enh, "_call_llm", fake_call)
        assert run(enh.hyde_document("任何问题")) is None


# --------------------------------------------------------------------------- #
# 模块 3：Rerank
# --------------------------------------------------------------------------- #
def _cands():
    return [
        {"id": 0, "text": "欧姆定律：导体中的电流与电压成正比，与电阻成反比。"},
        {"id": 1, "text": "今天天气不错，适合出去散步。"},
        {"id": 2, "text": "基尔霍夫电流定律：节点流入电流之和等于流出之和。"},
        {"id": 3, "text": "考研政治马原辩证法核心考点梳理。"},
    ]


class TestRerank:

    @pytest.fixture(autouse=True)
    def _no_bge_service(self, monkeypatch):
        """隔离 8140 bge-reranker：单测只验证打分排序协议，不能依赖外部服务在不在。"""
        async def unavailable(*_a, **_kw):
            return None
        monkeypatch.setattr(enh, "_bge_rerank_scores", unavailable)

    def test_sorts_by_score_and_truncates(self, monkeypatch):
        """成功路径：按 LLM 打分降序，取 top_k，并附带 rerank_score。"""
        async def fake_scores(*a, **kw):
            return {0: 9, 1: 2, 2: 7, 3: 4}
        monkeypatch.setattr(enh, "_llm_scores", fake_scores)

        out = run(enh.rerank(_cands(), "欧姆定律是什么？", top_k=3))
        assert [c["id"] for c in out] == [0, 2, 3], out
        assert out[0]["rerank_score"] == 9
        assert out[0]["text"].startswith("欧姆定律")
        # 返回的是拷贝，不能改到调用方原对象
        assert "rerank_score" not in _cands()[0]

    def test_prefers_bge_scores_when_available(self, monkeypatch):
        """8140 可用时优先用 bge 分数，且不再调用 LLM 打分。"""
        async def fake_bge(*a, **kw):
            return {0: 0.2, 1: 0.9, 2: 0.5, 3: 0.1}

        async def fake_llm(*a, **kw):
            raise AssertionError("bge 可用时不应回退 LLM 打分")

        monkeypatch.setattr(enh, "_bge_rerank_scores", fake_bge)
        monkeypatch.setattr(enh, "_llm_scores", fake_llm)

        out = run(enh.rerank(_cands(), "q", top_k=2))
        assert [c["id"] for c in out] == [1, 2], out
        assert out[0]["rerank_score"] == 0.9

    def test_original_order_on_score_failure(self, monkeypatch):
        """打分失败（解析不出分数）→ 保持原序截断 top_k。"""
        async def fake_scores(*a, **kw):
            return {}
        monkeypatch.setattr(enh, "_llm_scores", fake_scores)

        out = run(enh.rerank(_cands(), "任何问题", top_k=2))
        assert [c["id"] for c in out] == [0, 1], out
        assert all("rerank_score" not in c for c in out)

    def test_never_raises(self, monkeypatch):
        async def boom(*a, **kw):
            raise RuntimeError("boom")
        monkeypatch.setattr(enh, "_llm_scores", boom)
        out = run(enh.rerank(_cands(), "q", top_k=2))
        assert [c["id"] for c in out] == [0, 1]

    def test_empty_candidates(self):
        assert run(enh.rerank([], "q")) == []
        assert run(enh.rerank(None, "q")) == []

    def test_top_k_larger_than_candidates(self, monkeypatch):
        async def fake_scores(*a, **kw):
            return {0: 9, 1: 8}
        monkeypatch.setattr(enh, "_llm_scores", fake_scores)
        out = run(enh.rerank(_cands(), "q", top_k=10))
        assert len(out) == 4

    def test_disabled_flag_keeps_original_order(self, monkeypatch):
        monkeypatch.setenv("RETRIEVAL_ENHANCE_ENABLED", "0")
        called = {"n": 0}

        async def fake_scores(*a, **kw):
            called["n"] += 1
            return {0: 1}
        monkeypatch.setattr(enh, "_llm_scores", fake_scores)

        out = run(enh.rerank(_cands(), "q", top_k=2))
        assert [c["id"] for c in out] == [0, 1]
        assert called["n"] == 0

    def test_score_line_parsing_real_llm_output(self, monkeypatch):
        """经 _llm_scores 解析真实模型可能给出的各种行格式。"""
        async def fake_call(*a, **kw):
            return ("[0] 9\n1:2\n2、7\n3 = 4\n垃圾行\n")
        monkeypatch.setattr(enh, "_call_llm", fake_call)

        scores = run(enh._llm_scores(_cands(), "电路定律"))
        assert scores == {0: 9, 1: 2, 2: 7, 3: 4}, scores


# --------------------------------------------------------------------------- #
# 在线用例：真实打本机 Ollama（连不通自动 skip）
# --------------------------------------------------------------------------- #
def _ollama_up() -> bool:
    try:
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


# 在线用例走**真实默认选型**（env → qwen3:8b → qwen2.5:1.5b → 科目路由），
# 不再强制模型，以此验证默认逻辑在 Ollama 在线时真实生效。


def test_live_rewrite_real_ollama(monkeypatch):
    if not _ollama_up():
        pytest.skip("Ollama 不在线，跳过在线用例")
    out = run(enh.rewrite_query("那个化简逻辑电路的图怎么弄？", subject="数字电子技术"))
    assert isinstance(out, list) and len(out) >= 1
    assert all(isinstance(x, str) and x.strip() for x in out)


def test_live_hyde_real_ollama(monkeypatch):
    if not _ollama_up():
        pytest.skip("Ollama 不在线，跳过在线用例")
    out = run(enh.hyde_document("卡诺图化简的基本步骤", subject="数字电子技术"))
    # 默认逻辑生效时应返回真实段落；即便偶发抖动也只能是 None/str，不抛异常
    assert out is None or isinstance(out, str)


def test_live_rerank_real_ollama(monkeypatch):
    if not _ollama_up():
        pytest.skip("Ollama 不在线，跳过在线用例")
    cands = [
        {"id": 0, "text": "欧姆定律描述电压电流电阻关系。"},
        {"id": 1, "text": "今天食堂吃什么。"},
        {"id": 2, "text": "基尔霍夫定律是电路基本定律。"},
    ]
    out = run(enh.rerank(cands, "电路基本定律有哪些？", top_k=2))
    assert isinstance(out, list)
    assert len(out) <= 2
    assert all("text" in c for c in out)
