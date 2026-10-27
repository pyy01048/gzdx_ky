# -*- coding: utf-8 -*-
"""统一模型调用层 ModelGateway（集各家所长：本地 Ollama + 云端 API 灵活路由）。

设计目标（对应任务「底层模型调用灵活化」）：
- 统一入口：chat() 一次调用，自动在「本地 Ollama + 云端 API」之间选择与切换；
- 按科目路由：复用 model_registry.route_for_subject / recommend_for_task（学科强项优先）；
- 按显存适配：复用 model_registry.detect_hardware（HardwareProfile.tier），显存不足自动跳过本地大模型；
- 可配置优先级：环境变量 MODEL_GATEWAY_STRATEGY = auto | local_first | cloud_first；
  云端供应商优先级来自 AIProvider 表 fallback_priority（is_enabled=True）；
- 快速失败切换：单次超时/异常即记录并切换下一候选，不阻塞调用方；
- 延迟感知：返回 latency_ms 与 attempts 明细，供上层统计与后续调优。

纯新增模块，不改动 ai_router / model_registry（红线：外科手术式改动）。
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from utils.ollama_host import resolve_ollama_host

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
STRATEGY = os.environ.get("MODEL_GATEWAY_STRATEGY", "auto").strip().lower()

# --------------------------------------------------------------------------- #
# 运行时路由模式（T1：设置页热切换，不再依赖 env 重启）
#   auto         自动：学术/专业科目本地优先，文档/通用云端优先，失败互备
#   local_first  本地优先：本地失败自动切云端
#   cloud_first  云端优先：云端失败自动切本地
#   local_only   仅本地：禁用云端（数据不出网）
#   cloud_only   仅云端：禁用本地
# 存放位置：platform_configs(platform_name='ai_routing').extra.mode
# --------------------------------------------------------------------------- #
ROUTING_MODES = ("auto", "local_first", "cloud_first", "local_only", "cloud_only")
ROUTING_MODE_LABELS = {
    "auto": "自动（本地/云端互备）",
    "local_first": "本地优先，失败转云端",
    "cloud_first": "云端优先，失败转本地",
    "local_only": "仅本地（禁用云端）",
    "cloud_only": "仅云端（禁用本地）",
}
_ROUTING_CACHE_TTL = 15.0  # 秒；热路径每次 chat 都会读，避免每请求查库
_routing_cache = {"ts": 0.0, "mode": None}


def get_routing_mode() -> str:
    """当前路由模式：读 platform_configs 的 ai_routing 行（15s 进程内缓存）。

    只读 sqlite 直连（不建 ORM 会话）：该函数在 chat 热路径上，必须廉价。
    读取失败/未配置 → 回退 env MODEL_GATEWAY_STRATEGY → auto。
    """
    now = time.time()
    if _routing_cache["mode"] and now - _routing_cache["ts"] < _ROUTING_CACHE_TTL:
        return _routing_cache["mode"]
    mode = None
    try:
        # 2026-10-14 修复：原实现用裸 `sqlite3.connect(f"file:{dbfile}?mode=ro")` 直连，
        # 切到 PostgreSQL 后 `engine.url.database` 是库名 "kaoyan"，
        # sqlite3 会去打开一个叫 kaoyan 的本地文件 → 必然失败 → 异常被吞 →
        # **用户在设置页切换的路由模式永不生效**（永远回退到 env 默认值）。
        # 改为走 SQLAlchemy 引擎（跨后端），并显式区分"没配置"与"读取失败"。
        from sqlalchemy import text as _sql_text

        from database import engine

        with engine.connect() as conn:
            row = conn.execute(_sql_text(
                "SELECT extra FROM platform_configs WHERE platform_name = 'ai_routing'"
            )).fetchone()
            if row and row[0]:
                extra = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                m = (extra or {}).get("mode")
                if m in ROUTING_MODES:
                    mode = m
    except Exception as exc:  # noqa: BLE001
        # 不再静默：读取失败必须可见，否则"设置不生效"会再次变成无从排查的幽灵问题
        logger.warning("读取 AI 路由模式失败，回退 env 默认值：%s", exc)
        mode = None
    if not mode:
        mode = STRATEGY if STRATEGY in ("auto", "local_first", "cloud_first") else "auto"
    _routing_cache.update(ts=now, mode=mode)
    return mode


def reset_routing_cache() -> None:
    """设置页改完路由模式后立即生效（否则要等 15s TTL 过期）。"""
    _routing_cache.update(ts=0.0, mode=None)
LOCAL_TIMEOUT = float(os.environ.get("MODEL_GATEWAY_LOCAL_TIMEOUT", "360"))
CLOUD_TIMEOUT = float(os.environ.get("MODEL_GATEWAY_CLOUD_TIMEOUT", "60"))
OLLAMA_BASE = resolve_ollama_host(os.environ.get("OLLAMA_BASE", ""))
OLLAMA_V1 = f"{OLLAMA_BASE}/v1/chat/completions"
OLLAMA_TAGS = f"{OLLAMA_BASE}/api/tags"

# --------------------------------------------------------------------------- #
# 状态快照缓存（P0-2）：status 冷路径跑 nvidia-smi + Ollama tags + 云厂商表，
# 实测 1.4–2.8s，被 /api/kb/ingest/status 轮询吃满。TTL 与 OCR 侧对齐。
# --------------------------------------------------------------------------- #
_STATUS_TTL = 30.0
_status_cache: Dict[str, tuple] = {}
_status_lock = threading.Lock()

#: 云端供应商类型（来自 AIProvider.provider_type）
CLOUD_PROVIDER_TYPES = {"doubao", "deepseek", "qwen", "openai", "gpt", "kimi", "glm", "moonshot", "zhipu", "api"}

#: 专有答疑模型类型（本地 retrieval 服务，如 127.0.0.1:8765/v1）
RETRIEVAL_PROVIDER_TYPES = {"local-retrieval"}

#: 真题类问题特征：命中即优先路由到专有答疑模型
_EXAM_QUERY_RE = re.compile(r"\d+\s*题|真题|试题|题目|解析|解答|错题|刷题|计算题|选择题|大题|问答题")
#: 生成类任务标记（变式题/答案解析生成等），此类 prompt 应走生成模型而非真题检索
_GENERATION_TASK_RE = re.compile(r"仅输出 JSON|生成\s*1\s*道|变式题|命题专家|请基于下面这道题")

#: 任务类型（对齐 model_registry 的 task 域）
TASK_ALIASES = {
    "学术答疑": "qa_academic", "答疑": "qa_academic", "qa": "qa_academic",
    "文档处理": "doc_process", "总结": "doc_process", "改写": "doc_process",
    "代码": "code", "编程": "code",
    "通用": "general", "闲聊": "general", "chat": "general",
}


def normalize_task(task: Optional[str]) -> str:
    if not task:
        return "general"
    return TASK_ALIASES.get(task, task)


# --------------------------------------------------------------------------- #
# 云端供应商（AIProvider 表）
# --------------------------------------------------------------------------- #
def _list_cloud_providers(db) -> List[Dict[str, Any]]:
    """读取 AIProvider 表中启用的云端供应商，按 fallback_priority 升序。"""
    from models import AIProvider

    rows = db.query(AIProvider).filter(
        AIProvider.is_enabled.is_(True),
        AIProvider.provider_type.in_(CLOUD_PROVIDER_TYPES),
        AIProvider.base_url.isnot(None),
    ).order_by(AIProvider.fallback_priority.asc()).all()
    out = []
    for r in rows:
        out.append({
            "kind": "cloud",
            "provider": r.provider_type,
            "name": r.name,
            "base_url": (r.base_url or "").rstrip("/"),
            "api_key": r.api_key or "",
            "model": r.model_name,
            "temperature": r.temperature if r.temperature is not None else 0.7,
            "priority": r.fallback_priority or 99,
        })
    return out


# --------------------------------------------------------------------------- #
# 专有答疑 Provider（local-retrieval）
# --------------------------------------------------------------------------- #
def _list_retrieval_providers(db) -> List[Dict[str, Any]]:
    """读取 AIProvider 表中启用的专有答疑模型（provider_type=local-retrieval）。"""
    from models import AIProvider

    rows = db.query(AIProvider).filter(
        AIProvider.is_enabled.is_(True),
        AIProvider.provider_type.in_(RETRIEVAL_PROVIDER_TYPES),
        AIProvider.base_url.isnot(None),
    ).order_by(AIProvider.fallback_priority.asc()).all()
    out = []
    for r in rows:
        out.append({
            "kind": "retrieval",
            "provider": r.provider_type,
            "name": r.name,
            "base_url": (r.base_url or "").rstrip("/"),
            "api_key": r.api_key or "local",
            "model": r.model_name,
            "temperature": r.temperature if r.temperature is not None else 0.3,
            "priority": r.fallback_priority or 99,
        })
    return out


def is_exam_query(question: Optional[str]) -> bool:
    """判断是否为真题类问题（错题答疑 / 题目解析场景）。"""
    if not question:
        return False
    return bool(_EXAM_QUERY_RE.search(question))


# --------------------------------------------------------------------------- #
# 本地 Ollama
# --------------------------------------------------------------------------- #
def _ollama_installed() -> List[str]:
    """本机已下载的 Ollama 模型名列表（8s 超时，避免 CLI 阻塞）。"""
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(OLLAMA_TAGS)
            resp.raise_for_status()
            data = resp.json()
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def _build_local_candidates(subject: Optional[str], task: str, installed: List[str]) -> List[Dict[str, Any]]:
    """按科目/任务/显存从 model_registry 取本地候选。"""
    from services import model_registry

    if not installed:
        return []
    installed_set = set(installed)
    try:
        best = model_registry.pick_best_available(task, subject=subject, installed=installed_set)
    except Exception:
        best = None
    cands = []
    if best:
        cands.append({
            "kind": "local", "provider": "ollama", "name": "本地最佳", "base_url": OLLAMA_BASE,
            "api_key": "ollama", "model": best.get("ollama_name") or best.get("model_name") or best.get("name") or "", "temperature": 0.7,
            "priority": 0, "fit": best.get("fit_verdict", best.get("fit", "")),
        })
    return cands


def _chat_openai_compat(cfg: Dict[str, Any], messages: List[Dict[str, str]], timeout: float) -> Dict[str, Any]:
    """OpenAI 兼容 /v1/chat/completions 调用。返回 {text, latency_ms}。"""
    base = cfg["base_url"].rstrip("/")
    if cfg.get("kind") == "local" and not base.endswith("/v1"):
        base = f"{base}/v1"
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.get('api_key') or 'ollama'}"}
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.7),
        "stream": False,
    }
    if cfg.get("kind") == "local":
        # 不要传 think:false！llm_output.py 的实测结论：qwen3 系在 think:false 时
        # 会把推理过程泄漏进 content（恰与直觉相反）；默认行为下 content 才是干净答案、
        # 推理走 message.thinking。qwen3 的 <think> 内联在 /v1 端点的 content 里，
        # 思考+作答容易超出默认上限被截断——用标准 OpenAI 参数 max_tokens 放宽
        # （Ollama /v1 不认原生 options 字段，此前传 options 是无效的）。
        payload["max_tokens"] = 4096
    t0 = time.time()
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    latency = (time.time() - t0) * 1000
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        text = data.get("text") or json.dumps(data, ensure_ascii=False)
    return {"text": text, "latency_ms": latency}


# --------------------------------------------------------------------------- #
# 网关
# --------------------------------------------------------------------------- #
class ModelGateway:
    """统一模型调用网关。"""

    def __init__(self, strategy: Optional[str] = None):
        # strategy 显式传入时优先（单测/特定调用方用）；None = 运行时动态读用户设置
        # （get_routing_mode），支持设置页热切换路由模式。
        self.strategy = strategy if (strategy is None or strategy in ROUTING_MODES) else None

    def _candidate_chain(
        self, db, *, subject: Optional[str], task: str, prefer: Optional[str]
    ) -> List[Dict[str, Any]]:
        """构建候选链（按策略排序）。"""
        installed = _ollama_installed()
        local = _build_local_candidates(subject, task, installed)
        cloud = _list_cloud_providers(db)
        retrieval = _list_retrieval_providers(db)

        if prefer == "retrieval":
            return retrieval + local + cloud
        if prefer == "local":
            return local + cloud
        if prefer == "cloud":
            return cloud + local
        # 用户设置的路由模式（设置页可热切换）
        mode = self.strategy or get_routing_mode()
        if mode == "local_only":
            return local  # 禁用云端：数据不出网
        if mode == "cloud_only":
            return cloud  # 禁用本地
        if mode == "local_first":
            return local + cloud
        if mode == "cloud_first":
            return cloud + local
        # auto：学术/专业科目优先本地（数据不出网 + 精度），文档/通用优先云端（速度）
        auto_cloud_first_tasks = {"doc_process", "general", "code"}
        if task in auto_cloud_first_tasks and cloud:
            return cloud + local
        return local + cloud

    def chat(
        self,
        question: str,
        *,
        subject: Optional[str] = None,
        task: Optional[str] = None,
        context: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prefer: Optional[str] = None,
        db=None,
    ) -> Dict[str, Any]:
        """统一对话入口。自动路由 + 快速失败切换。

        Args:
            question: 用户问题
            subject: 科目（数学/英语/政治/数字电子技术/模拟电子技术/...）
            task: 任务类型（学术答疑/文档处理/代码/通用）
            context: 附加上下文（如 RAG 检索片段）
            system_prompt: 自定义系统提示（缺省用内置考研助手提示）
            prefer: local / cloud / None(auto)
            db: SQLAlchemy Session（云端供应商列表用；缺省自动创建）

        Returns:
            {answer, engine, provider, model, strategy, latency_ms, fallback_used, attempts}
        """
        task = normalize_task(task)
        close_db = False
        if db is None:
            from database import SessionLocal

            db = SessionLocal()
            close_db = True
        try:
            # 真题类问题（错题答疑/题目解析）优先路由到专有答疑模型（local-retrieval）；
            # 生成类任务（变式题/答案解析生成）豁免，避免误走检索导致 JSON 指令丢失
            if (
                task == "qa_academic"
                and is_exam_query(question)
                and not _GENERATION_TASK_RE.search(question)
            ):
                prefer = "retrieval"
            chain = self._candidate_chain(db, subject=subject, task=task, prefer=prefer)
            if not chain:
                return {
                    "answer": "", "engine": "none", "provider": "", "model": "",
                    "strategy": self.strategy or get_routing_mode(), "latency_ms": 0, "fallback_used": True,
                    "attempts": [], "error": "无可用模型：本地 Ollama 未运行且无云端供应商配置",
                }

            default_sys = (
                "你是考研备考助手，熟悉数学、英语、政治、数字电子技术、模拟电子技术等科目。"
                "回答准确、简洁，必要时给出推导或出处。"
            )
            messages: List[Dict[str, str]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            else:
                messages.append({"role": "system", "content": default_sys})
            if context:
                messages.append({"role": "system", "content": f"参考资料（RAG）：\n{context}"})
            messages.append({"role": "user", "content": question})

            attempts: List[Dict[str, Any]] = []
            fallback_used = len(chain) > 1
            for cfg in chain:
                timeout = LOCAL_TIMEOUT if cfg["kind"] in ("local", "retrieval") else CLOUD_TIMEOUT
                attempt_t0 = time.time()
                try:
                    out = _chat_openai_compat(cfg, messages, timeout=timeout)
                    answer = (out["text"] or "").strip()
                    latency = out["latency_ms"]
                    attempts.append({
                        "kind": cfg["kind"], "provider": cfg.get("provider"),
                        "model": cfg["model"], "status": "ok", "latency_ms": round(latency, 1),
                    })
                    return {
                        "answer": answer,
                        "engine": cfg["kind"],
                        "provider": cfg.get("provider", ""),
                        "model": cfg["model"],
                        "strategy": self.strategy or get_routing_mode(),
                        "latency_ms": round(latency, 1),
                        "fallback_used": fallback_used,
                        "attempts": attempts,
                        "error": None,
                    }
                except Exception as e:
                    attempts.append({
                        "kind": cfg["kind"], "provider": cfg.get("provider"),
                        "model": cfg["model"], "status": "failed",
                        "error": f"{type(e).__name__}: {str(e)[:200]}",
                        "latency_ms": round((time.time() - attempt_t0) * 1000, 1),
                    })
                    continue

            return {
                "answer": "", "engine": "none", "provider": "", "model": "",
                "strategy": self.strategy or get_routing_mode(), "latency_ms": 0, "fallback_used": True,
                "attempts": attempts, "error": "全部模型候选均失败",
            }
        finally:
            if close_db:
                db.close()

    def status(self, db=None) -> Dict[str, Any]:
        """网关状态快照（P0-2：带 TTL 缓存）。

        冷路径要跑 nvidia-smi 子进程 + Ollama ``/api/tags`` HTTP（8s 超时）+
        云厂商表查询，实测 **1.4–2.8s/次**；``/api/kb/ingest/status`` 每次轮询都吃它。
        硬件画像与已装模型清单在秒级窗口内不会变，按 :data:`_STATUS_TTL` 缓存，
        并发走双检加锁 —— 过期后的首个调用者付一次探测成本，其余命中快照。
        返回 ``deepcopy``：调用方（含路由层 JSON 序列化）不该改到共享快照。
        """
        key = self.strategy or get_routing_mode()
        now = time.time()
        hit = _status_cache.get(key)
        if hit is not None and now - hit[0] < _STATUS_TTL:
            return copy.deepcopy(hit[1])

        with _status_lock:
            hit = _status_cache.get(key)
            if hit is not None and time.time() - hit[0] < _STATUS_TTL:
                return copy.deepcopy(hit[1])
            payload = self._status_uncached(db)
            _status_cache[key] = (time.time(), payload)
            return copy.deepcopy(payload)

    def _status_uncached(self, db=None) -> Dict[str, Any]:
        """无缓存的真实探测（仅 :meth:`status` 的缓存未命中路径调用）。"""
        close_db = False
        if db is None:
            from database import SessionLocal

            db = SessionLocal()
            close_db = True
        try:
            from services import model_registry

            hw = model_registry.detect_hardware()
            installed = _ollama_installed()
            cloud = _list_cloud_providers(db)
            return {
                "strategy": self.strategy or get_routing_mode(),
                "hardware": {"gpu": hw.gpu_name, "vram_gb": hw.vram_gb, "tier": hw.tier, "ram_gb": hw.ram_gb},
                "local_models": installed,
                "cloud_providers": [{"provider": c["provider"], "model": c["model"], "priority": c["priority"]} for c in cloud],
                "timeouts": {"local_s": LOCAL_TIMEOUT, "cloud_s": CLOUD_TIMEOUT},
            }
        finally:
            if close_db:
                db.close()


_gateway: Optional[ModelGateway] = None


def get_gateway(strategy: Optional[str] = None) -> ModelGateway:
    global _gateway
    if _gateway is None or strategy:
        _gateway = ModelGateway(strategy=strategy)
    return _gateway
