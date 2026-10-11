# -*- coding: utf-8 -*-
"""V11 检索增强：Query Rewriting / HyDE / Rerank（模块 1/2/3）。

### 这是什么

在向量检索（recall）之后、生成答案之前插三道"提质"工序：

1. **rewrite_query**：把用户那句模糊的大白话问题，改写成 1~3 条更精确、
   带学科术语的检索查询，让向量召回更准。
2. **hyde_document**：让本地模型先"假装知道答案"，写一段假想的参考资料片段，
   用它去和知识库做向量相似度（Hypothetical Document Embeddings）。
3. **rerank**：本地 LLM 对召回的候选逐条打 1-10 相关性分，重排后取 top_k，
   修正向量相似度"形似神不似"的错排。

### 硬约束（冻结，后续 Agentic 升级按此接线，签名不可改）

- **只走本地 Ollama（127.0.0.1:11434），绝不联网**。
- **任何失败都按冻结降级值返回，绝不抛异常**：
  - rewrite_query 失败 -> 返回 ``[question]``（原查询单元素列表）
  - hyde_document   失败 -> 返回 ``None``
  - rerank           失败 -> 保持候选原序截断 top_k
- 模块开关：
  - ``RETRIEVAL_ENHANCE_ENABLED``（env ``RETRIEVAL_ENHANCE_ENABLED``，默认开启）
    关掉后三个函数直接走降级值，不碰 Ollama。
  - ``USE_BGE_RERANKER``（默认 False）：仅作开关占位。本模块**不下载、不安装、
    不引入 sentence-transformers**；即便该开关打开，检测到 bge 不可用时也只是
    记日志并继续走 LLM 打分路径。

### 复用的现有代码（不重复造轮子）

- ``services/model_registry.py``：``route_for_subject`` / ``pick_best_available``
  做"按科目挑本机已装模型"。
- ``services/llm_output.py``：``extract_answer``（从 thinking 模型的 message 里
  取干净正文）/ ``build_payload``（构造 /api/chat 请求体，默认不传 think）。
- ``utils/http_client.py``：``get_async_client``（复用全局连接池）。
- Ollama 调用口径对齐 ``services/ai_router.py`` 的 ``_chat_local``：
  ``stream=False``、``keep_alive="10m"``、超时 360s、**不传 ``think:false``**
  （实测对 qwen3 系会把思考过程倒进 content）。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from utils.http_client import get_async_client

logger = logging.getLogger(__name__)

#: Ollama 地址（只认本机，杜绝出网）
_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
#: 单次对话超时：qwen3 系是思考模型，实测单问 60-320s，必须给够
_CHAT_TIMEOUT = 360.0
#: 探测已装模型清单的超时（短超时，失败不影响主流程）
_TAGS_TIMEOUT = 5.0
#: 并行单元部署的 bge-reranker 微服务地址（8140）。可用则用它重排（CPU 约 1.3s/6条），
#: 不可用才回退本地 LLM 逐条打分（慢，是 60s 504 主因之一）。
_BGE_RERANK_URL = os.getenv("BGE_RERANKER_URL", "http://127.0.0.1:8140").rstrip("/")
_BGE_PROBE = {"ok": None, "at": 0.0}

#: 检索增强固定偏好顺序（短文本结构化任务：改写/假设答案/打分）。
#  实测 deepseek-r1 这类 reasoning 专才对这类任务会吐乱码，**不作为默认**。
_PREFERRED_MODELS = ("qwen3:8b", "qwen2.5:1.5b")
#: 默认排除的 reasoning 专才系列前缀（科目路由兜底命中时跳过）
_EXCLUDE_PREFIXES = ("deepseek-r1",)

#: 部分 Ollama 版本/模型把思考链内联在 content 的 <think>...</think> 里。
#  llm_output.extract_answer 是为「thinking 字段独立分离」设计的，
#  遇到内联 <think> 会整段拒收 —— 这里在喂给 extract_answer 前先剥掉。
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think_tags(text: str) -> str:
    """剥掉 content 里的内联 ``<think>...</think>`` 块。

    - 有闭合 ``</think>``：取其后的正文（真正答案）；
    - 没有闭合标签：说明被 ``num_predict`` 截断、思考没结束、答案根本没出来，
      返回空串（让上层走降级，不要把半段思考当答案）。
    """
    if not text or "<think>" not in text.lower():
        return text or ""
    if "</think>" in text.lower():
        return text.split("</think>", 1)[1]
    return ""


#: 第一人称自述式开头（模型自我复述任务）。剥掉 <think> 后，只剩这种开头
#  才视为"思考泄漏"；正常教材式论述里的"首先/其次/最后"不算。
_SELF_TALK_OPENERS = (
    "首先，", "首先用户", "用户要求", "用户问", "用户想要", "用户需要",
    "我需要", "我得", "我要", "让我", "我来", "我们来", "让我想想",
    "好的，我", "这个问题的", "分析一下", "让我分析",
    "the user", "i need", "i should", "let me", "first,", "okay,",
)


def _is_self_talk(text: str) -> bool:
    """判断剥掉 <think> 后的正文是否仍是第一人称自述（思考泄漏）。"""
    head = (text or "").strip()[:40].lower()
    if not head:
        return False
    return any(head.startswith(o) for o in _SELF_TALK_OPENERS)


# --------------------------------------------------------------------------- #
# 开关读取（每次调用时读 env，方便测试 monkeypatch / 运行时热切换）
# --------------------------------------------------------------------------- #
def _env_flag(name: str, default: bool) -> bool:
    """读布尔型 env 开关。"0/false/no/off"（不区分大小写）视为关。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _enhance_enabled() -> bool:
    return _env_flag("RETRIEVAL_ENHANCE_ENABLED", True)


def _use_bge_reranker() -> bool:
    """bge-reranker 开关占位：本模块不安装它，开了也只记日志。"""
    return _env_flag("USE_BGE_RERANKER", False)


# --------------------------------------------------------------------------- #
# 模型选择 + 统一 LLM 调用（所有失败都吞掉，返回空串给上层降级）
# --------------------------------------------------------------------------- #
async def _select_model(subject: Optional[str]) -> str:
    """挑本机已装模型。固定顺序：

    1. env ``RETRIEVAL_ENHANCE_MODEL`` 显式指定（最高优先，ops 兜底）；
    2. ``qwen3:8b``（若已装）—— 中文强、短文本可用；
    3. ``qwen2.5:1.5b``（若已装）—— 非思考模型、快、结构化输出稳；
    4. 科目路由结果兜底（走 ``model_registry``），但**排除 reasoning 专才**
       （deepseek-r1 系列，实测对这类轻量结构化任务吐乱码）；
    5. 最终回退 env ``OLLAMA_MODEL`` 或 ``qwen3:8b``。

    任何异常都不抛，返回一个可用的模型名。
    """
    default = os.getenv("OLLAMA_MODEL", "qwen3:8b")

    # 1. 显式 env 覆盖
    env_model = os.getenv("RETRIEVAL_ENHANCE_MODEL", "").strip()
    if env_model:
        return env_model

    try:
        installed: set[str] = set()
        try:
            client = get_async_client()
            resp = await client.get(f"{_OLLAMA_HOST}/api/tags", timeout=_TAGS_TIMEOUT)
            if resp.status_code == 200:
                installed = {m.get("name", "") for m in resp.json().get("models", [])}
                # 同时记不带 tag 的短名（"qwen3:8b" -> "qwen3"）
                installed |= {n.split(":")[0] for n in installed if n}
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[检索增强] 拉取已装模型清单失败，用默认模型: {e}")
            return default

        if not installed:
            return default

        # 2/3. 固定偏好顺序
        for cand in _PREFERRED_MODELS:
            if cand in installed:
                logger.info(f"[检索增强] 选用固定偏好模型 {cand}（科目={subject or '未识别'}）")
                return cand

        # 4. 科目路由兜底，但排除 reasoning 专才
        try:
            from services import model_registry as mr

            task = mr.route_for_subject(subject) if subject else "general"
            best = mr.pick_best_available(task, subject=subject, installed=installed)
            if best and best.get("ollama_name"):
                name = best["ollama_name"]
                if not name.startswith(_EXCLUDE_PREFIXES):
                    logger.info(f"[检索增强] 选用科目路由模型 {name}（科目={subject or '未识别'}）")
                    return name
                logger.info(f"[检索增强] 科目路由命中 reasoning 专才 {name}，跳过")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[检索增强] 科目路由兜底失败: {e}")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[检索增强] 模型选型异常，用默认模型: {e}")
    return default


async def _call_llm(
    prompt: str,
    subject: Optional[str],
    *,
    num_predict: int = 512,
    temperature: float = 0.2,
) -> str:
    """统一的 Ollama /api/chat 调用。

    返回模型正文；任何失败（网络/超时/非 200/只返回思考链/空）一律返回 ``""``。
    **本函数绝不抛异常**——上层靠空串走冻结降级。
    """
    try:
        model = await _select_model(subject)
        # 复用 llm_output 的载荷构造：stream=False、keep_alive=10m、默认不带 think
        from services.llm_output import build_payload, extract_answer

        payload = build_payload(
            model, prompt, temperature=temperature, num_predict=num_predict,
        )
        client = get_async_client()
        resp = await client.post(
            f"{_OLLAMA_HOST}/api/chat", json=payload, timeout=_CHAT_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning(f"[检索增强] Ollama 返回 {resp.status_code}，按失败降级")
            return ""
        data = resp.json()
        msg = dict(data.get("message", {}) or {})
        # 部分 Ollama 版本把思考链内联在 content 的 <think>...</think> 里。
        # 剥掉之后剩余的就是模型最终作答 —— 直接信任，只挡第一人称自述式开头。
        # （extract_answer 的思维链启发式会把教材里"首先/其次/最后"误判为思考链，
        #   导致 hyde 这种正常论述被误降级。）
        raw = msg.get("content") or ""
        clean = _strip_think_tags(raw)
        if clean.strip() and not _is_self_talk(clean):
            return clean.strip()
        # 回退：thinking 字段独立分离的模型（extract_answer 原设计路径）
        msg["content"] = clean
        answer = extract_answer(msg)
        return answer.strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[检索增强] 本地 LLM 调用失败，按失败降级: {e}")
        return ""


# --------------------------------------------------------------------------- #
# 模块 1：Query Rewriting
# --------------------------------------------------------------------------- #
def _parse_queries(text: str) -> List[str]:
    """把模型输出拆成查询列表：去编号/项目符号、去空、去重、最多 3 条。"""
    out: List[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        # 去掉行首编号（1. / 1) / 1、）和项目符号（- * •）
        s = re.sub(r"^\s*(?:\d+\s*[\.\)、:]?\s*|[-*•·]\s*)", "", s).strip()
        # 去掉包裹引号
        s = s.strip("《》\"'“”‘’")
        if not s:
            continue
        if s not in out:
            out.append(s)
    return out[:3]


async def rewrite_query(question: str, subject: Optional[str] = None) -> List[str]:
    """把模糊问题改写为 1~3 个精确检索查询。

    冻结签名：``(question: str, subject: Optional[str] = None) -> List[str]``。
    任何失败返回 ``[question]``。
    """
    fallback = [question]
    try:
        if not _enhance_enabled() or not question or not question.strip():
            return fallback

        subj_hint = subject or "相关学科"
        prompt = (
            "把下面这个用户问题改写成 1~3 个更精确的检索查询，"
            f"尽量使用「{subj_hint}」的专业术语，便于在知识库中检索。\n"
            "要求：每个查询单独占一行；只输出查询本身；"
            "不要编号、不要项目符号、不要解释、不要引号。\n\n"
            f"用户问题：{question}"
        )
        text = await _call_llm(prompt, subject, num_predict=768, temperature=0.2)
        queries = _parse_queries(text)
        if not queries:
            logger.info("[检索增强] 查询改写无有效输出，降级为原查询")
            return fallback
        logger.info(f"[检索增强] 查询改写: {question[:30]}... -> {len(queries)} 条")
        return queries
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[检索增强] rewrite_query 异常，降级为原查询: {e}")
        return fallback


# --------------------------------------------------------------------------- #
# 模块 2：HyDE
# --------------------------------------------------------------------------- #
async def hyde_document(query: str, subject: Optional[str] = None) -> Optional[str]:
    """生成一段"假设答案"文本（HyDE 用）。

    冻结签名：``(query: str, subject: Optional[str] = None) -> Optional[str]``。
    失败返回 ``None``。
    """
    try:
        if not _enhance_enabled() or not query or not query.strip():
            return None

        subj_hint = subject or "该学科"
        prompt = (
            f"假设你是一本「{subj_hint}」教材。针对下面这个检索问题，"
            "写一段 100~200 字的假想参考资料片段，"
            "就像知识库中恰好命中这段文字一样：直接陈述知识点、定义或结论。\n"
            "要求：不要说\"假设\"、不要解释你在做什么、不要分点、不要附加说明。\n\n"
            f"检索问题：{query}"
        )
        text = await _call_llm(prompt, subject, num_predict=768, temperature=0.3)
        if not text:
            logger.info("[检索增强] HyDE 无有效输出，返回 None")
            return None
        return text
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[检索增强] hyde_document 异常，返回 None: {e}")
        return None


# --------------------------------------------------------------------------- #
# 模块 3：Rerank
# --------------------------------------------------------------------------- #
def _candidate_text(cand: Dict[str, Any], limit: int = 180) -> str:
    """从候选 dict 里尽量取出正文片段。"""
    for key in ("text", "content", "chunk", "snippet", "summary", "title"):
        val = cand.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().replace("\n", " ")[:limit]
    return ""


#: 打分行格式宽松匹配：兼容 "[0] 9" / "1:2" / "2、7" / "3 = 4" 等写法
_SCORE_LINE_RE = re.compile(r"(\d+)[\s\]\)\:：\.\、\=\-]*(\d{1,2})")


async def _llm_scores(
    candidates: List[Dict[str, Any]], query: str,
) -> Dict[int, int]:
    """让 LLM 给候选打 1-10 分，返回 {下标: 分数}。解析失败返回空 dict。"""
    # 候选太多时只送前 20 条（向量召回通常 10~20 条，足够重排）
    budget = candidates[:20]
    lines = []
    for i, cand in enumerate(budget):
        lines.append(f"[{i}] {_candidate_text(cand)}")
    prompt = (
        "你是检索结果排序裁判。根据用户问题，给下面每条候选资料打相关性分数："
        "1~10 的整数，10=完全切题、1=完全无关。\n"
        "要求：只输出\"编号 分数\"，每行一条，不要解释、不要多余文字。\n\n"
        f"用户问题：{query}\n\n候选资料：\n" + "\n".join(lines)
    )
    text = await _call_llm(prompt, None, num_predict=512, temperature=0.0)
    scores: Dict[int, int] = {}
    for line in (text or "").splitlines():
        m = _SCORE_LINE_RE.search(line)
        if not m:
            continue
        idx = int(m.group(1))
        if not (0 <= idx < len(budget)):
            continue
        score = max(1, min(10, int(m.group(2))))
        scores[idx] = score
    return scores


async def _bge_rerank_scores(
    candidates: List[Dict[str, Any]], query: str,
) -> Optional[Dict[int, float]]:
    """探测并调用 8140 bge-reranker 微服务，返回 {候选下标: 分数}；不可用/失败返回 None。

    协议：GET /health 探测（300s 缓存），POST /rerank {query, documents:[{id,text}]}
    返回 {results:[{id,score}]}。任何异常都返回 None，绝不抛。
    """
    import time
    try:
        client = get_async_client()
        now = time.time()
        if _BGE_PROBE["ok"] is None or (now - _BGE_PROBE["at"]) > 300:
            try:
                r = await client.get(f"{_BGE_RERANK_URL}/health", timeout=2.0)
                _BGE_PROBE["ok"] = (r.status_code == 200)
            except Exception:
                _BGE_PROBE["ok"] = False
            _BGE_PROBE["at"] = now
        if not _BGE_PROBE["ok"]:
            return None

        docs = [
            {"id": str(i), "text": (c.get("content") or c.get("text") or "")[:1000]}
            for i, c in enumerate(candidates)
        ]
        r = await client.post(
            f"{_BGE_RERANK_URL}/rerank",
            json={"query": str(query), "documents": docs},
            timeout=8.0,
        )
        if r.status_code != 200:
            _BGE_PROBE["ok"] = False
            return None
        payload = r.json() or {}
        scores: Dict[int, float] = {}
        for item in payload.get("results", []):
            try:
                scores[int(item["id"])] = float(item["score"])
            except Exception:
                continue
        return scores or None
    except Exception as e:  # noqa: BLE001
        logger.debug("[检索增强] bge rerank 不可用，回退 LLM: %s", e)
        return None


async def rerank(
    candidates: List[Dict[str, Any]], query: str, top_k: int = 5,
) -> List[Dict[str, Any]]:
    """对候选按相关性重排，返回前 top_k。

    冻结签名：``(candidates, query, top_k=5) -> List[Dict]``。
    打分失败/开关关闭时**保持原序截断 top_k**，绝不抛异常。
    返回的 dict 为浅拷贝（成功路径附带 ``rerank_score``），不污染调用方原对象。
    """
    def _take_original(order: int) -> List[Dict[str, Any]]:
        """原序截断 top_k（返回浅拷贝）。"""
        if order <= 0:
            return []
        return [dict(c) for c in candidates[:order]]

    try:
        if not isinstance(candidates, list) or not candidates:
            return []
        if top_k is None or top_k <= 0:
            return []
        if not query or not str(query).strip():
            return _take_original(top_k)
        if not _enhance_enabled():
            return _take_original(top_k)

        # 优先用 8140 bge-reranker 微服务（快）；不可用才回退本地 LLM 逐条打分（慢）
        scores = await _bge_rerank_scores(candidates, str(query))
        backend = "bge"
        if not scores:
            scores = await _llm_scores(candidates, str(query))
            backend = "llm"
        if not scores:
            logger.info("[检索增强] 重排打分无有效结果，保持原序截断")
            return _take_original(top_k)


        # 已打分的按下分降序（同分保持原序），未打分的按原序补在后面
        indexed = list(range(len(candidates)))
        scored = [i for i in indexed if i in scores]
        unscored = [i for i in indexed if i not in scores]
        scored.sort(key=lambda i: (-scores[i], i))
        ordered = scored + unscored

        result: List[Dict[str, Any]] = []
        for i in ordered[:top_k]:
            item = dict(candidates[i])
            if i in scores:
                item["rerank_score"] = scores[i]
            result.append(item)
        logger.info(f"[检索增强] rerank[{backend}]: {len(candidates)} 条候选 -> {len(result)} 条"
                    f"（{len(scored)} 条已打分）")
        return result
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[检索增强] rerank 异常，降级为原序截断: {e}")
        try:
            return _take_original(top_k)
        except Exception:  # noqa: BLE001
            return []
