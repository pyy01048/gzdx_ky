"""AI 服务统一封装。

支持多服务商切换与降级策略，所有密钥从数据库读取。
支持 OpenAI 兼容接口的 SSE 流式输出与本地知识库 RAG 检索。
"""

import asyncio
import json
import os
import re
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from models import AIProvider, Document, KnowledgePoint, KnowledgeChunk
from services import search_service
from services.embedding_service import EmbeddingService
from utils.http_client import get_async_client

# --------------------------------------------------------------------------- #
# Ollama 可用性探测的模块级共享缓存（2026-10-14）
#
# 原实现把缓存挂在 AIService 实例上，但路由每次请求都新建实例，
# 导致"5 分钟缓存"从不生效 —— Ollama 未启动时每个请求都要真连一次，
# 实测把 GET /api/ai/local/status 拖到 27 秒。
# 改成模块级后，跨实例跨请求真正生效。
# --------------------------------------------------------------------------- #
_OLLAMA_CACHE: Dict[str, float | bool] = {"value": False, "time": 0.0}
_OLLAMA_TTL = 300.0        # 默认缓存有效期（秒）
_FORCE_RECENT_TTL = 30.0   # 用户点"检测"时的最大容忍陈旧度（秒）
_OLLAMA_TIMEOUT = 3.0      # 单次探测超时（秒）—— 必须远小于上游网关阈值

# qwen3 思维链标签：成对剥离；模型被 max_tokens 截断时只剩开标签，也要清掉
_THINK_TAG_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.S | re.I)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>", re.I)


class AIService:
    """统一 AI 调用封装。"""

    # 各服务商默认 Base URL
    DEFAULT_BASE_URLS: Dict[str, str] = {
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
        "deepseek": "https://api.deepseek.com/v1",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "gpt": "https://api.openai.com/v1",
        "claude": "https://api.anthropic.com/v1",
        "ollama": "http://127.0.0.1:11434/v1",  # 本地 Ollama（OpenAI 兼容接口）
        "local": "http://127.0.0.1:11434/v1",   # 本地模型别名
    }

    # 各服务商默认模型名
    DEFAULT_MODELS: Dict[str, str] = {
        "doubao": "doubao-pro-32k",
        "deepseek": "deepseek-chat",
        "qwen": "qwen-plus",
        "gpt": "gpt-3.5-turbo",
        "claude": "claude-3-haiku-20240307",
        "ollama": "kaoyan-assistant",  # 本地考研微调模型（Ollama）
        "local": "kaoyan-assistant",   # 本地模型别名
    }

    # 智能路由配置
    ROUTING_CONFIG = {
        "local_max_tokens": 900,       # 本地模型最大输出 token（500 时答疑常被截断）
        "local_max_input_chars": 2000, # 本地模型最大输入字符数
        "simple_keywords": [            # 简单问题关键词，优先走本地
            "你好", "hello", "hi", "谢谢", "感谢", "再见", "bye",
            "现在几点", "今天几号", "星期几", "日期", "时间",
            "什么是", "定义", "概念", "解释一下", "简单说",
            "翻译", "translate", "同义词", "反义词",
        ],
        "complex_keywords": [           # 复杂问题关键词，强制走在线
            "详细分析", "深度", "论文", "研究", "报告",
            "代码", "编程", "debug", "算法", "复杂",
            "长文本", "总结", "摘要", "写作", "作文",
            "数学题", "证明", "推导", "计算",
        ],
        "sensitive_keywords": [         # 敏感内容，优先本地（数据不出网）
            "我的", "个人", "隐私", "成绩", "排名", "错题",
            "学习计划", "目标", "院校", "专业",
        ],
    }

    # ------------------------------------------------------------------ #
    # 有害/违规内容拦截（先于任何模型调用；遵守内容安全规范，数据不出网）
    # ------------------------------------------------------------------ #
    UNSAFE_PATTERNS = [
        # 违法与人身伤害
        r"制作炸弹", r"爆炸物", r"自制武器", r"制毒", r"毒品配方", r"冰毒",
        r"怎么自杀", r"自杀方法", r"自残方法", r"怎样伤害自己",
        r"网络诈骗", r"盗取密码", r"入侵网站", r"ddos", r"黑客攻击",
        r"裸聊", r"约炮", r"卖淫", r"色情网站",
        # 政治敏感（按中国法律不予回答）
        r"颠覆国家", r"分裂国家", r"煽动叛乱", r"政治体制评价",
    ]

    @staticmethod
    def is_unsafe(text: str) -> bool:
        """判断是否为有害/违规内容（需拦截）。"""
        if not text:
            return False
        low = text.lower()
        for pat in AIService.UNSAFE_PATTERNS:
            if re.search(pat, low):
                return True
        return False

    @staticmethod
    def guard_message() -> str:
        """有害内容的标准安全拒答。"""
        return (
            "抱歉，该问题涉及违规或不适宜的内容，我无法为你解答。"
            "如果你有考研学习相关的问题（如知识点讲解、复习规划、真题分析等），我很乐意帮你。"
        )

    def answer_offline(self, query: str, kb_hits: List[Dict[str, Any]]) -> str:
        """无本地模型、无在线 API 时的离线兜底：直接呈现本地知识库检索结果。

        完全离线、无需任何 LLM，数据不出网。
        """
        if not kb_hits:
            return (
                "（本地知识库离线模式）\n"
                "当前未配置本地模型，也未接入在线 AI，且知识库中未检索到与问题直接相关的内容。\n"
                "你可以：\n"
                "· 在「网盘」中把备考资料「入库到知识库」，我会基于这些资料离线回答；\n"
                "· 在「设置」中配置本地 Ollama（如 qwen3.5:9b）或在线 AI 以获得更智能的回答。"
            )
        blocks = []
        for i, h in enumerate(kb_hits, 1):
            blocks.append(f"[片段{i}｜来源：{h.get('source')}｜{h.get('title','')}]\n{h.get('content','')}")
        return (
            "（本地知识库离线回答 · 未使用任何 AI 模型，数据不出网）\n\n"
            + "\n\n".join(blocks)
            + "\n\n以上为本地资料库中与问题最相关的片段，供你参考。"
        )

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_local_provider(p: AIProvider) -> bool:
        return (p.provider_type or "") in ("ollama", "local")

    @classmethod
    def _provider_usable(cls, p: AIProvider) -> bool:
        """服务商是否真的可调用。

        2026-10-20 答疑链路 502 根因之一：库里「豆包 / DeepSeek」两个云端
        服务商是启用状态但 **api_key 为空**，请求必然 401；旧实现把它们排在
        降级链最前面，每个问题都先白打两次 401，本地 Ollama 一旦探测失败
        就直接 `所有 AI 服务商调用失败` → 502。这里把「无 Key 的云端服务商」
        视为不可用，直接跳过（显式 provider_id 仍原样返回，便于设置页测连通性）。
        """
        return cls._is_local_provider(p) or bool((p.api_key or "").strip())

    def _get_provider(self, provider_id: Optional[int] = None) -> AIProvider:
        """获取指定服务商或默认/最高优先级启用的服务商。"""
        if provider_id:
            provider = self.db.query(AIProvider).filter(AIProvider.id == provider_id).first()
            if not provider:
                raise ValueError(f"AI 服务商 {provider_id} 不存在")
            return provider

        enabled = (
            self.db.query(AIProvider)
            .filter(AIProvider.is_enabled == True)
            .order_by(AIProvider.fallback_priority.asc())
            .all()
        )
        usable = [p for p in enabled if self._provider_usable(p)]
        # 默认服务商优先，但必须是可调用的（有 Key 或本地模型）
        for p in usable:
            if p.is_default:
                return p
        if usable:
            return usable[0]

        raise ValueError("没有可用的 AI 服务商配置（已启用的服务商均缺少 API Key，且本地 Ollama 未配置）")

    def _get_fallback_providers(self, exclude_id: int) -> List[AIProvider]:
        """获取备用服务商列表（按降级优先级排序，跳过无 Key 的云端服务商）。"""
        rows = (
            self.db.query(AIProvider)
            .filter(AIProvider.is_enabled == True, AIProvider.id != exclude_id)
            .order_by(AIProvider.fallback_priority.asc())
            .all()
        )
        return [p for p in rows if self._provider_usable(p)]

    def _build_headers(self, provider: AIProvider) -> Dict[str, str]:
        """构造请求头。"""
        if provider.provider_type == "claude":
            return {
                "x-api-key": provider.api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        return {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

    def _get_base_url(self, provider: AIProvider) -> str:
        return provider.base_url or self.DEFAULT_BASE_URLS.get(
            provider.provider_type or "", "https://api.openai.com/v1"
        )

    # ------------------------------------------------------------------ #
    # 本地模型 + 智能路由（V2.0 修复：本地+API双AI混合）
    # ------------------------------------------------------------------ #
    def _get_local_provider(self) -> Optional[AIProvider]:
        """获取本地 Ollama 服务商（数据库中配置的，或临时创建）。"""
        # 先查数据库（已登记的本地模型，如 kaoyan-assistant / qwen3.5:9b / qwen3.5:4b）
        providers = (
            self.db.query(AIProvider)
            .filter(AIProvider.provider_type.in_(["ollama", "local"]), AIProvider.is_enabled == True)
            .all()
        )
        if providers:
            # 优先用考研微调模型 kaoyan-assistant
            for p in providers:
                if "kaoyan" in (p.model_name or "").lower():
                    return p
            # 其次用名称含 9b 的模型做学术答疑（高数/线代/专业课）
            for p in providers:
                if "9b" in (p.model_name or ""):
                    return p
            return providers[0]
        # 数据库没有则临时创建（不写入数据库）。
        # 2026-10-20 配置对齐：本机 Ollama 实际模型名是 kaoyan-assistant-v4，
        # 旧默认值 kaoyan-assistant 在 /api/tags 里不存在（404→502）。改由
        # OLLAMA_MODEL 环境变量指定，默认取已安装的 v4。
        return AIProvider(
            name="本地考研微调模型",
            provider_type="ollama",
            base_url="http://127.0.0.1:11434/v1",
            api_key="ollama",  # Ollama 不需要真实 key
            model_name=os.getenv("OLLAMA_MODEL", "kaoyan-assistant-v4"),
            temperature=0.7,
            is_enabled=True,
            fallback_priority=99,
        )

    async def _check_ollama_available(
        self,
        force_check: bool = False,
        force_recent: bool = False,
) -> bool:
        """检查本地 Ollama 服务是否可用（默认 5 分钟缓存）。

        :param force_check: 忽略缓存强制探测。**仅供后台任务使用**——
            同步接口请用 ``force_recent``，否则会把单次探测的延迟
            直接摊到用户请求上。
        :param force_recent: 仅当缓存已超过 ``_FORCE_RECENT_TTL``（30 秒）
            时才重新探测。用于"用户点了检测按钮"这类既要新鲜、
            又不能每次都付一次超时的场景。
        """
        import os
        import time

        now = time.time()
        # 模块级缓存：见函数 docstring「历史缺陷」
        cache = _OLLAMA_CACHE
        if not force_check:
            ttl = _FORCE_RECENT_TTL if force_recent else _OLLAMA_TTL
            if now - cache["time"] < ttl:
                return cache["value"]
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        try:
            client = get_async_client()
            resp = await client.get(f"{host}/api/tags", timeout=_OLLAMA_TIMEOUT)
            result = resp.status_code == 200
        except Exception:
            result = False
        cache["value"] = result
        cache["time"] = now
        return result

    def _route_query(
        self, messages: List[Dict[str, str]], kb_hit_count: int = 0
    ) -> Tuple[str, str]:
        """智能路由决策：判断该走本地模型还是在线 API。

        结合「问题复杂度」「隐私」「本地知识库覆盖度」综合判断。
        Returns:
            (route, reason): route 为 "local"/"online"，reason 为决策原因
        """
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "")
                break

        if not user_msg:
            return "online", "空消息"

        msg_len = len(user_msg)

        # 0. 隐私类内容优先本地（数据不出网）
        for kw in self.ROUTING_CONFIG["sensitive_keywords"]:
            if kw in user_msg:
                return "local", f"涉及隐私内容（含'{kw}'），优先本地处理"

        # 1. 复杂/创作类问题 -> 在线（需要更强模型）
        for kw in self.ROUTING_CONFIG["complex_keywords"]:
            if kw in user_msg:
                return "online", f"复杂问题（含'{kw}'），需要更强模型"

        # 2. 输入过长 -> 在线（本地模型上下文有限）
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if total_chars > self.ROUTING_CONFIG["local_max_input_chars"]:
            return "online", f"输入过长（{total_chars}字符），超出本地模型能力"

        # 3. 本地知识库可高置信覆盖的事实/定义类问题 -> 本地（离线、精准、数据不出网）
        if kb_hit_count >= 2:
            for kw in ["什么是", "定义", "概念", "解释", "怎么理解", "公式", "定理", "区别", "原理", "特点"]:
                if kw in user_msg:
                    return "local", f"本地知识库已覆盖（命中{kb_hit_count}条），本地精准回答"

        # 4. 短问题 / 简单关键词 -> 本地（秒回）
        if msg_len < 50:
            return "local", "短问题，本地模型可处理"
        for kw in self.ROUTING_CONFIG["simple_keywords"]:
            if kw in user_msg:
                return "local", f"简单问题（含'{kw}'），本地秒回"

        # 5. 默认在线（保证质量）
        return "online", "默认走在线API保证回答质量"

    async def _call_ollama(
        self, provider: AIProvider, messages: List[Dict[str, str]], temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """调用本地 Ollama 模型（OpenAI 兼容接口）。"""
        base = (provider.base_url or "http://127.0.0.1:11434/v1").rstrip("/")
        url = f"{base}/chat/completions"
        model = provider.model_name or "kaoyan-assistant"
        temp = temperature if temperature is not None else (provider.temperature or 0.7)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": self.ROUTING_CONFIG["local_max_tokens"],
            "stream": False,
        }

        client = get_async_client()
        resp = await client.post(url, json=payload, timeout=120.0)
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices", [])
        content = choices[0]["message"]["content"] if choices else ""
        # qwen3 系列会在正文前输出 <think>…</think> 思维链。答疑接口面向学生，
        # 思维链属于内部推理，直接展示既冗长又容易把未定稿的猜测当成结论；
        # 非流式出口统一剥离（流式不动，避免破坏增量渲染）。
        content = _THINK_TAG_RE.sub("", content or "")
        content = _THINK_OPEN_RE.sub("", content).strip()
        usage = data.get("usage", {})
        return {"content": content, "usage": usage}

    def _get_model_name(self, provider: AIProvider) -> str:
        return provider.model_name or self.DEFAULT_MODELS.get(
            provider.provider_type or "", "gpt-3.5-turbo"
        )

    def _get_chat_url(self, provider: AIProvider) -> str:
        base = self._get_base_url(provider).rstrip("/")
        if provider.provider_type == "claude":
            return f"{base}/messages"
        return f"{base}/chat/completions"

    def _build_payload(
        self, provider: AIProvider, messages: List[Dict[str, str]], temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """构造请求体。"""
        model = self._get_model_name(provider)
        temp = temperature if temperature is not None else (provider.temperature or 0.7)

        if provider.provider_type == "claude":
            # Claude API 格式
            system_msg = ""
            chat_msgs = []
            for m in messages:
                if m["role"] == "system":
                    system_msg += m["content"] + "\n"
                else:
                    chat_msgs.append({"role": m["role"], "content": m["content"]})
            return {
                "model": model,
                "max_tokens": 4096,
                "temperature": temp,
                "system": system_msg.strip(),
                "messages": chat_msgs,
            }
        # OpenAI 兼容格式
        return {
            "model": model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": 4096,
        }

    def _parse_response(self, provider: AIProvider, data: Dict[str, Any]) -> Tuple[str, Optional[Dict]]:
        """解析响应。"""
        if provider.provider_type == "claude":
            content_parts = data.get("content", [])
            content = "".join(p.get("text", "") for p in content_parts)
            usage = data.get("usage", {})
        else:
            choices = data.get("choices", [])
            content = choices[0]["message"]["content"] if choices else ""
            usage = data.get("usage", {})
        return content, usage

    # ------------------------------------------------------------------ #
    # 核心对话
    # ------------------------------------------------------------------ #
    async def chat(
        self,
        messages: List[Dict[str, str]],
        provider_id: Optional[int] = None,
        temperature: Optional[float] = None,
        use_routing: bool = True,
        kb_hit_count: int = 0,
        force_local: bool = False,
    ) -> Dict[str, Any]:
        """统一对话接口，支持智能路由（本地+API自动选择）与降级。

        Args:
            messages: 对话消息
            provider_id: 指定服务商ID（非None时跳过路由）
            temperature: 温度
            use_routing: 是否启用智能路由（默认True）
            kb_hit_count: 本地知识库对当前问题的命中数（KB 感知路由）
            force_local: 强制本地（绝不回退在线；本地不可用则走离线知识库兜底）
        """
        # 有害/违规内容拦截（先于任何模型调用）
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        if self.is_unsafe(last_user):
            return {
                "content": self.guard_message(),
                "provider": "guard",
                "route": "blocked",
                "route_reason": "内容安全拦截",
                "model": None,
            }

        # 智能路由：判断走本地还是在线
        route = "online"
        route_reason = ""
        local_provider = None

        if use_routing and provider_id is None:
            route, route_reason = self._route_query(messages, kb_hit_count=kb_hit_count)
            if force_local:
                # 强制本地：无论如何先尝试本地模型
                route = "local"
                route_reason = route_reason or "强制本地模式"
            if route == "local":
                ollama_available = await self._check_ollama_available()
                if ollama_available:
                    local_provider = self._get_local_provider()
                elif force_local:
                    # 无本地模型也不回退在线，改为离线知识库兜底
                    route = "offline"
                    route_reason = "本地Ollama不可用，使用本地知识库离线回答"
                else:
                    route = "online"
                    route_reason += "（本地Ollama不可用，回退在线）"

        # 本地知识库离线兜底（无模型、无在线）
        if route == "offline":
            kb_hits = self.search_knowledge_base(last_user, limit=4)
            answer = self.answer_offline(last_user, kb_hits)
            return {
                "content": answer,
                "provider": "offline-kb",
                "route": "offline",
                "route_reason": route_reason or "本地知识库离线回答",
                "model": None,
            }

        # 本地模型路径
        if local_provider is not None:
            try:
                result = await self._call_ollama(local_provider, messages, temperature)
                result["provider"] = local_provider.name
                result["route"] = "local"
                result["route_reason"] = route_reason
                result["model"] = local_provider.model_name or "kaoyan-assistant"
                return result
            except Exception as e:
                if force_local:
                    # 本地调用失败也不回退在线，走离线知识库兜底
                    kb_hits = self.search_knowledge_base(last_user, limit=4)
                    return {
                        "content": self.answer_offline(last_user, kb_hits),
                        "provider": "offline-kb",
                        "route": "offline",
                        "route_reason": f"本地调用失败（{str(e)[:50]}），离线知识库兜底",
                        "model": None,
                    }
                route = "online"
                route_reason = f"本地调用失败（{str(e)[:50]}），回退在线"

        # 在线 API 路径（多服务商降级）
        provider = self._get_provider(provider_id)

        # 如果指定的服务商是本地 Ollama 类型，直接走本地模型路径
        if provider.provider_type in ("ollama", "local"):
            try:
                result = await self._call_ollama(provider, messages, temperature)
                result["provider"] = provider.name
                result["route"] = "local"
                result["route_reason"] = route_reason or "指定本地模型"
                result["model"] = provider.model_name or "kaoyan-assistant"
                return result
            except Exception as e:
                if force_local:
                    kb_hits = self.search_knowledge_base(last_user, limit=4)
                    return {
                        "content": self.answer_offline(last_user, kb_hits),
                        "provider": "offline-kb",
                        "route": "offline",
                        "route_reason": f"本地调用失败（{str(e)[:50]}），离线知识库兜底",
                        "model": None,
                    }
                raise RuntimeError(f"本地模型调用失败：{str(e)}")

        fallbacks = self._get_fallback_providers(provider.id)
        all_providers = [provider] + fallbacks

        last_error = None
        for p in all_providers:
            try:
                result = await self._call_provider(p, messages, temperature)
                result["provider"] = p.name
                result["route"] = "online"
                result["route_reason"] = route_reason or "在线API"
                result["model"] = self._get_model_name(p)
                return result
            except Exception as e:
                last_error = str(e)
                continue

        raise RuntimeError(f"所有 AI 服务商调用失败，最后错误：{last_error}")

    async def _call_provider(
        self, provider: AIProvider, messages: List[Dict[str, str]], temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """调用单个服务商。"""
        headers = self._build_headers(provider)
        url = self._get_chat_url(provider)
        payload = self._build_payload(provider, messages, temperature)

        client = get_async_client()
        resp = await client.post(url, headers=headers, json=payload, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()

        content, usage = self._parse_response(provider, data)
        return {"content": content, "usage": usage}

    # ------------------------------------------------------------------ #
    # 流式对话（SSE）
    # ------------------------------------------------------------------ #
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        provider_id: Optional[int] = None,
        temperature: Optional[float] = None,
        provider_override: Optional[Dict[str, Any]] = None,
        kb_hit_count: int = 0,
        force_local: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        """SSE 流式对话接口，支持降级。

        provider_override：前端直传的临时服务商配置（{base_url, api_key, model,
        name, provider_type, temperature}），存在时优先使用，无需写入数据库。
        force_local：强制本地模式（不回退在线；无本地模型时走离线知识库兜底）。

        yield 的事件：
          {"type": "delta", "content": str}   文本增量
          {"type": "provider", "name": str}   实际使用的服务商
          {"type": "done", "content": str}    完整文本（流结束）
          {"type": "error", "message": str}   错误
        """
        # 有害/违规内容拦截
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
        )
        if self.is_unsafe(last_user):
            yield {"type": "provider", "name": "guard"}
            yield {"type": "delta", "content": self.guard_message()}
            yield {"type": "done", "content": self.guard_message()}
            return

        # 智能路由：自动判断走本地还是在线（非force_local、非provider_override时）
        if not force_local and not provider_override and provider_id is None:
            route, route_reason = self._route_query(messages, kb_hit_count=kb_hit_count)
            if route == "local":
                ollama_available = await self._check_ollama_available()
                if ollama_available:
                    # 路由到本地：调用 chat() 获取完整结果，再以单 delta 流式返回
                    try:
                        res = await self.chat(
                            messages,
                            provider_id=None,
                            temperature=temperature,
                            use_routing=True,
                            kb_hit_count=kb_hit_count,
                            force_local=True,
                        )
                        content = res.get("content", "")
                        yield {"type": "provider", "name": res.get("provider", "本地Ollama")}
                        yield {"type": "delta", "content": content}
                        yield {
                            "type": "done",
                            "content": content,
                            "route": "local",
                            "route_reason": route_reason,
                            "model": res.get("model"),
                        }
                        return
                    except Exception as e:
                        # 本地调用失败，回退在线
                        route = "online"
                        route_reason = f"本地调用失败（{str(e)[:50]}），回退在线"
                else:
                    # 本地不可用，回退在线
                    route = "online"
                    route_reason = "本地Ollama不可用，回退在线"

        # 强制本地：复用 chat() 的统一路由/离线兜底逻辑，再以单 delta 流式返回
        if force_local and not provider_override:
            res = await self.chat(
                messages,
                provider_id=provider_id,
                temperature=temperature,
                use_routing=True,
                kb_hit_count=kb_hit_count,
                force_local=True,
            )
            content = res.get("content", "")
            yield {"type": "provider", "name": res.get("provider", "local")}
            yield {"type": "delta", "content": content}
            yield {
                "type": "done",
                "content": content,
                "route": res.get("route"),
                "route_reason": res.get("route_reason"),
            }
            return

        if provider_override:
            temp_provider = AIProvider(
                name=provider_override.get("name") or "临时服务商",
                provider_type=provider_override.get("provider_type") or "openai",
                base_url=provider_override.get("base_url") or "",
                api_key=provider_override.get("api_key") or "",
                model_name=provider_override.get("model") or "",
                temperature=provider_override.get("temperature") or 0.7,
                is_enabled=True,
            )
            try:
                yield {"type": "provider", "name": temp_provider.name}
                async for ev in self._call_provider_stream(temp_provider, messages, temperature):
                    yield ev
                return
            except Exception as e:
                yield {"type": "error", "message": f"AI 服务商调用失败：{str(e)}"}
                return

        provider = self._get_provider(provider_id)
        fallbacks = self._get_fallback_providers(provider.id)
        all_providers = [provider] + fallbacks

        last_error = None
        for p in all_providers:
            try:
                yield {"type": "provider", "name": p.name}
                async for ev in self._call_provider_stream(p, messages, temperature):
                    yield ev
                return
            except Exception as e:
                last_error = str(e)
                continue

        yield {"type": "error", "message": f"所有 AI 服务商调用失败，最后错误：{last_error}"}

    async def _call_provider_stream(
        self, provider: AIProvider, messages: List[Dict[str, str]], temperature: Optional[float] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式调用单个服务商（OpenAI 兼容 SSE / Claude 非流式兜底）。"""
        headers = self._build_headers(provider)
        url = self._get_chat_url(provider)
        payload = self._build_payload(provider, messages, temperature)
        payload["stream"] = True

        if provider.provider_type == "claude":
            # Claude 不支持标准 SSE 文本流，回退一次性调用
            result = await self._call_provider(provider, messages, temperature)
            yield {"type": "delta", "content": result["content"]}
            yield {"type": "done", "content": result["content"]}
            return

        full = []
        client = get_async_client()
        async with client.stream("POST", url, headers=headers, json=payload, timeout=120.0) as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        full.append(text)
                        yield {"type": "delta", "content": text}
        yield {"type": "done", "content": "".join(full)}

    # ------------------------------------------------------------------ #
    # 知识库检索（RAG）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """简单分词：中文按字符 2-gram，英文按单词。"""
        tokens = []
        if not text:
            return tokens
        # 英文/数字词
        for w in re.findall(r"[a-zA-Z0-9]{2,}", text.lower()):
            tokens.append(w)
        # 中文 2-gram
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
        for i in range(len(cjk) - 1):
            tokens.append(cjk[i : i + 2])
        return tokens

    def search_knowledge_base(
        self, query: str, limit: int = 6, min_score: float = 1.0, subject: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """在本地知识库中检索与 query 相关的片段（同步版本，仅 FTS5 BM25）。

        使用 FTS5 全文检索（BM25 打分）替换原 TF 词频检索，精度更高、速度更快。
        向量检索请使用 search_knowledge_base_hybrid（异步）。

        subject：可选学科过滤（如"数字电子技术"），为空则检索全部。
        """
        if not query:
            return []

        # 1) 知识分块：FTS5 BM25 检索（主数据源）
        try:
            chunk_hits = search_service.hybrid_search(
                self.db, query, query_vec=None, limit=limit * 2, subject=subject
            )
            chunk_results = [
                {
                    "score": h.get("score", 0.5),
                    "source": "知识分块",
                    "title": h.get("document_title", ""),
                    "content": (h.get("content", ""))[:600],
                    "doc_id": h.get("document_id"),
                    "chunk_id": h.get("chunk_id"),
                    "subject": h.get("subject"),
                    # 引用溯源字段（2026-10-20）：回答末尾的来源标注依赖这三项
                    "doc_name": h.get("doc_name") or h.get("document_title") or "",
                    "page_start": h.get("page_start"),
                    "page_end": h.get("page_end"),
                    "chunk_index": h.get("chunk_index"),
                    "source_type": h.get("source_type"),
                }
                for h in chunk_hits
            ]
        except Exception:
            # FTS 不可用时回退到原 TF 检索
            chunk_results = self._tf_search_chunks(query, subject)

        # 2) 知识点：TF 检索（数据量小，TF 足够）
        kp_results = []
        kp_q = self.db.query(KnowledgePoint).filter(KnowledgePoint.description.isnot(None))
        # 2) 知识点：SQL 侧精确过滤（2026-10-14 重构）
        #
        # 原实现把知识点整表拉进 Python 逐行分词算 Jaccard（`limit(3000)`），
        # 实测导致 /api/ai/rag-search 单次耗时 16.7 秒。改为在 SQL 侧按关键词
        # 过滤后再打分，返回行数从 3000 降到个位数量级。
        #
        # 3) 文档段落级检索：**已移除**。
        #    原因：分块检索（第 1 步的 hybrid_search）本就是按 chunk 粒度做的，
        #    而 chunk 正是文档切分而来 —— 再用 `limit(2000)` 把整篇文档拉回来
        #    逐段重扫，是同一份内容的重复检索，纯属浪费（且它最慢）。
        #    文档级的"按文件名命中"需求由分块结果的 document_title 覆盖。
        kp_results = []
        q_tokens = set(self._tokenize(query))
        if not q_tokens:
            # 查询词无法分词，直接返回分块结果
            return sorted(chunk_results, key=lambda x: -x["score"])[:limit]

        # 取查询里最长的 3 个词做 SQL LIKE 预筛（长词区分度高，漏召回少）
        probe_terms = sorted({t for t in q_tokens if len(t) >= 2},
                             key=len, reverse=True)[:3]
        if probe_terms:
            from sqlalchemy import or_ as _or
            cond = _or(*[
                KnowledgePoint.name.ilike(f"%{t}%")
                for t in probe_terms
            ] + [
                KnowledgePoint.description.ilike(f"%{t}%")
                for t in probe_terms
            ])
            kp_q = self.db.query(KnowledgePoint).filter(cond)
            if subject:
                kp_q = kp_q.filter(KnowledgePoint.subject == subject)
            # SQL 侧已筛过，上限 200 足够（原 3000 是全表扫描）
            for kp in kp_q.limit(200).all():
                hay = f"{kp.name or ''} {kp.description or ''} {kp.chapter or ''}"
                tokens = set(self._tokenize(hay))
                if not tokens:
                    continue
                score = len(q_tokens & tokens) / len(q_tokens)
                if score >= 0.15:
                    kp_results.append(
                        {
                            "score": score,
                            "source": "知识点",
                            "title": kp.name or "",
                            "content": (kp.description or "")[:600],
                            "doc_id": kp.document_id,
                        }
                    )

        all_results = sorted(chunk_results + kp_results, key=lambda x: -x["score"])[:limit]
        return all_results

    def _tf_search_chunks(self, query: str, subject: Optional[str] = None) -> List[Dict[str, Any]]:
        """TF 词频检索回退（FTS 不可用时使用）。"""
        q_tokens = set(self._tokenize(query))
        if not q_tokens:
            return []
        chunk_q = self.db.query(KnowledgeChunk).filter(
            KnowledgeChunk.text.isnot(None), KnowledgeChunk.text != ""
        )
        if subject:
            chunk_q = chunk_q.filter(KnowledgeChunk.subject == subject)
        chunks = chunk_q.limit(8000).all()
        results = []
        for c in chunks:
            tokens = set(self._tokenize(c.text))
            if not tokens:
                continue
            score = len(q_tokens & tokens) / len(q_tokens)
            if score >= 0.20:
                results.append(
                    {
                        "score": score,
                        "source": "知识分块",
                        "title": c.doc_name or "",
                        "content": (c.text or "")[:600],
                        "doc_id": c.document_id,
                        "chunk_id": c.chunk_id,
                        "subject": c.subject,
                        "doc_name": c.doc_name or "",
                        "page_start": getattr(c, "page_start", None),
                        "page_end": getattr(c, "page_end", None),
                        "chunk_index": getattr(c, "chunk_index", None),
                        "source_type": "chunk",
                    }
                )
        return results

    async def search_knowledge_base_hybrid(
        self, query: str, limit: int = 6, subject: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """混合检索（异步）：FTS5 BM25 + 向量 KNN + RRF 融合。

        优先使用向量检索（如果已构建 embedding 索引），否则回退到纯 FTS。
        """
        if not query:
            return []

        # 生成查询向量（离线引擎，绝不联网）
        query_vec = None
        try:
            emb_svc = EmbeddingService(self.db)
            vecs, _engine = await emb_svc.generate_embeddings([query[:2000]], allow_online=False)
            if vecs:
                query_vec = vecs[0]
        except Exception:
            query_vec = None  # 向量生成失败，回退到纯 FTS

        # 混合检索
        try:
            hits = search_service.hybrid_search(
                self.db, query, query_vec=query_vec, limit=limit * 2, subject=subject
            )
            return [
                {
                    "score": h.get("score", 0.5),
                    "source": "知识分块",
                    "title": h.get("document_title", ""),
                    "content": (h.get("content", ""))[:600],
                    "doc_id": h.get("document_id"),
                    "chunk_id": h.get("chunk_id"),
                    "subject": h.get("subject"),
                    # 引用溯源字段（2026-10-20）
                    "doc_name": h.get("doc_name") or h.get("document_title") or "",
                    "page_start": h.get("page_start"),
                    "page_end": h.get("page_end"),
                    "chunk_index": h.get("chunk_index"),
                    "source_type": h.get("source_type"),
                }
                for h in hits[:limit]
            ]
        except Exception:
            # 混合检索失败，回退到同步 FTS 检索
            return self.search_knowledge_base(query, limit=limit, subject=subject)

    def build_rag_context(self, query: str, limit: int = 4, subject: Optional[str] = None) -> Tuple[str, List[Dict[str, Any]]]:
        """构建 RAG 上下文 prompt 片段。返回 (context_text, hits)。"""
        hits = self.search_knowledge_base(query, limit=limit, subject=subject)
        if not hits:
            return "", []
        blocks = []
        for i, h in enumerate(hits, 1):
            blocks.append(
                f"[片段{i}｜来源：{h['source']}｜{h['title']}]\n{h['content']}"
            )
        return "\n\n".join(blocks), hits

    # ------------------------------------------------------------------ #
    # 测试连通性
    # ------------------------------------------------------------------ #
    async def test_provider(self, provider_id: int) -> Dict[str, Any]:
        """测试 API 连通性。"""
        provider = self.db.query(AIProvider).filter(AIProvider.id == provider_id).first()
        if not provider:
            raise ValueError(f"AI 服务商 {provider_id} 不存在")

        start = time.time()
        try:
            test_messages = [{"role": "user", "content": "请回复 OK"}]
            if provider.provider_type in ("ollama", "local"):
                result = await self._call_ollama(provider, test_messages)
            else:
                result = await self._call_provider(provider, test_messages)
            elapsed = round(time.time() - start, 2)
            return {
                "success": True,
                "response_time": elapsed,
                "usage": result.get("usage"),
                "preview": result["content"][:200],
            }
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return {
                "success": False,
                "response_time": elapsed,
                "error": str(e),
            }

    # ------------------------------------------------------------------ #
    # 高级功能
    # ------------------------------------------------------------------ #
    async def explain_knowledge(self, topic: str) -> str:
        """知识点讲解。"""
        messages = [
            {
                "role": "system",
                "content": "你是一位经验丰富的考研辅导老师，擅长用通俗易懂的方式讲解知识点。"
                "请对用户给出的知识点进行详细讲解，包括概念定义、核心要点、常见考点和易错提示。",
            },
            {"role": "user", "content": f"请讲解以下知识点：{topic}"},
        ]
        result = await self.chat(messages)
        return result["content"]

    async def grade_essay(self, content: str, essay_type: str = "english") -> str:
        """作文批改。"""
        lang_desc = "英语作文" if essay_type == "english" else "中文作文"
        messages = [
            {
                "role": "system",
                "content": f"你是一位专业的考研{lang_desc}阅卷老师。请对用户的作文进行批改，"
                "给出分数预估、具体问题分析和改进建议。",
            },
            {"role": "user", "content": f"请批改以下{lang_desc}：\n\n{content}"},
        ]
        result = await self.chat(messages)
        return result["content"]

    async def analyze_sentence(self, sentence: str) -> str:
        """长难句分析。"""
        messages = [
            {
                "role": "system",
                "content": "你是一位英语语法专家，擅长分析考研英语长难句。"
                "请从句子结构、语法成分、翻译技巧三个维度进行分析。",
            },
            {"role": "user", "content": f"请分析以下长难句：\n\n{sentence}"},
        ]
        result = await self.chat(messages)
        return result["content"]

    async def generate_plan(self, goal: Optional[str] = None, available_time: Optional[str] = None) -> str:
        """生成复习计划。"""
        prompt_parts = ["请根据以下信息生成一份详细的考研复习计划："]
        if goal:
            prompt_parts.append(f"目标：{goal}")
        if available_time:
            prompt_parts.append(f"可用时间：{available_time}")
        prompt_parts.append("计划应包括每日任务安排、各科时间分配和阶段性目标。")

        messages = [
            {
                "role": "system",
                "content": "你是一位考研规划专家，擅长制定科学合理的复习计划。",
            },
            {"role": "user", "content": "\n".join(prompt_parts)},
        ]
        result = await self.chat(messages)
        return result["content"]

    async def summarize_trend(self, questions: Optional[List[str]] = None) -> str:
        """真题规律总结。"""
        q_text = "\n".join(questions) if questions else "请基于考研历年真题进行分析。"
        messages = [
            {
                "role": "system",
                "content": "你是一位考研真题研究专家。请分析题目规律，总结考点分布、"
                "出题趋势和高频知识点，为考生备考提供指导。",
            },
            {"role": "user", "content": f"请分析以下真题的规律：\n\n{q_text}"},
        ]
        result = await self.chat(messages)
        return result["content"]
