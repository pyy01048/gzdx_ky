"""AI 路由。"""

import asyncio
import datetime
import json
import logging
import os
import threading
import time
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.dbapi_compat import wrap_conn
from database import SessionLocal, get_db
from models import AIProvider, PlatformConfig
from schemas import (
    AIProviderCreate, AIProviderUpdate,
    ChatRequest, ExplainRequest, EssayGradeRequest,
    SentenceAnalyzeRequest, GeneratePlanRequest, SummarizeTrendRequest,
    RAGSearchRequest,
)
from services.ai_service import AIService
from services import retrieval_gate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])

# 向量构建异步任务状态（P2：避免阻塞主服务）
_embedding_tasks: dict = {}

# ---------------------------------------------------------------------------
# AI 调用失败原因分类（P0-5）
#
# 线上实测：POST /api/ai/chat 直接 502，但响应体只有一句「AI 服务暂时不可用」，
# 真实原因（哪个服务商失败、是 Key 缺失还是连不上、本地 Ollama 是否可用）只在
# 服务端日志里 —— 前端拿不到任何可区分的信息，只能对用户显示一句空话。
#
# 这里把异常归到**可安全对外展示**的原因码：
#   · 原始异常文本仍不回传（含服务商地址 / 401 原文 / Key 片段，见 E2E2-002）；
#   · 分类码同时写进响应体 detail 与 X-AI-Error-Code 响应头，SSE 也带 code 字段，
#     前端据此给用户不同的可操作提示。
# ---------------------------------------------------------------------------
_AI_ERROR_HINTS = {
    "no_provider": "没有可用的 AI 服务商（未配置，或全部被停用）",
    "provider_auth": "已配置服务商的 API Key 缺失或无效（上游返回 401/403）",
    "provider_unreachable": "连不上已配置的服务商（网络不可达、DNS 失败或超时）",
    "local_unavailable": "本地 Ollama 不可用（未启动，或模型未下载完成）",
    "all_providers_failed": "已启用的服务商全部调用失败，且本地 Ollama 也不可用",
    "upstream_error": "服务商返回了错误响应",
    "internal_error": "服务端内部错误",
}


def _classify_ai_error(exc: BaseException) -> Tuple[str, str]:
    """把 AI 调用异常归类为 (reason_code, 可展示提示)。"""
    text = str(exc) or ""
    low = f"{type(exc).__name__}: {text}".lower()
    t = text.lower()
    if "没有可用的 ai 服务商" in t or "服务商" in t and "不存在" in t:
        return "no_provider", _AI_ERROR_HINTS["no_provider"]
    if "本地模型调用失败" in text:
        return "local_unavailable", _AI_ERROR_HINTS["local_unavailable"]
    if "所有 ai 服务商调用失败" in text.lower():
        # 兜底错误里仍带着最后一个服务商的失败原因，二次归类便于用户直接定位
        if "401" in text or "403" in text or "unauthorized" in low or "forbidden" in low:
            return "provider_auth", _AI_ERROR_HINTS["provider_auth"]
        if "timed out" in low or "timeout" in low or "connect" in low or "name or service not known" in low:
            return "provider_unreachable", _AI_ERROR_HINTS["provider_unreachable"]
        return "all_providers_failed", _AI_ERROR_HINTS["all_providers_failed"]
    if "401" in text or "403" in text or "unauthorized" in low or "forbidden" in low:
        return "provider_auth", _AI_ERROR_HINTS["provider_auth"]
    if "timed out" in low or "timeout" in low or "connect" in low or "name or service not known" in low:
        return "provider_unreachable", _AI_ERROR_HINTS["provider_unreachable"]
    return "upstream_error", _AI_ERROR_HINTS["upstream_error"]


async def _rag_system_prompt(query: str, ai: AIService) -> Tuple[str, dict]:
    """构建带本地知识库上下文的 system prompt（RAG，异步混合检索）。

    返回 ``(prompt, gate_meta)``：
      - prompt：注入 system 的检索上下文（无可注入片段时为 ""）；
      - gate_meta：检索门控（B-1）的判定结果，用于 observe 打点 / 暴露 would_abstain 率。

    门控策略（见 retrieval_gate.py / §5.3）：
      - 当前 RETRIEVAL_GATE_MODE="observe"：只记录 would_abstain 率，不做硬拦截，
        照常返回检索上下文让模型作答；
      - 若未来切到 "enforce" 且 decision=="abstain"：直接返回拒答话术，不再硬答。
    门控本身失败绝不影响 RAG 主链路（try/except 兜底）。
    """
    # 优先使用 FTS5+向量混合检索，失败回退到同步 FTS
    try:
        hits = await ai.search_knowledge_base_hybrid(query, limit=4)
    except Exception:
        hits = ai.search_knowledge_base(query, limit=4)

    # B-1：对检索结果跑质量门控。这里复用现有 hits（其 score 为 RRF 分，
    # evaluate_gate 会走 score 回退分支），仅做 observe 打点，不改变检索本身。
    gate_meta: dict = {}
    try:
        gate = retrieval_gate.evaluate_gate(
            hits or [], query, is_complex=retrieval_gate.is_complex_query(query)
        )
        gate_meta = {
            "mode": retrieval_gate.RETRIEVAL_GATE_MODE,
            "decision": gate["decision"],
            "reason_codes": gate.get("reason_codes", []),
            "metrics": gate.get("metrics", {}),
            "would_abstain": bool(gate.get("would_abstain")),
        }
        logger.info(
            "[retrieval_gate] query=%r decision=%s would_abstain=%s metrics=%s",
            query[:30], gate_meta["decision"], gate_meta["would_abstain"], gate_meta["metrics"],
        )
    except Exception as e:  # 门控异常绝不影响 RAG 回答
        logger.warning("retrieval_gate 判定失败，跳过门控: %s", e)
        gate_meta = {"mode": retrieval_gate.RETRIEVAL_GATE_MODE, "decision": "error",
                     "reason_codes": [], "metrics": {}, "would_abstain": False}

    if not hits:
        return "", gate_meta

    # enforce 模式 + 应拒答 → 返回拒答话术，不让模型基于不足依据硬编（§5.3）
    if (retrieval_gate.RETRIEVAL_GATE_MODE == "enforce"
            and gate_meta.get("decision") == "abstain"):
        return retrieval_gate.build_abstain_message(query), gate_meta

    blocks = []
    for i, h in enumerate(hits, 1):
        blocks.append(
            f"[片段{i}｜来源：{h['source']}｜{h['title']}]\n{h['content']}"
        )
    context = "\n\n".join(blocks)
    return (
        "以下是来自用户本地知识库（考研资料文档/知识点）的检索片段，请优先参考这些"
        "内容回答，并结合你的专业知识补充。若片段与问题无关可忽略。\n\n"
        f"{context}\n\n"
        "若用户询问的是题目作答/答疑类问题，请遵守：\n"
        "1. 只针对题目作答，选择题给出选项字母与内容，主观题给出结论与分步推导；\n"
        "2. 严禁编造答案，条件不足时明确标注“存疑”并说明需补充的信息；\n"
        "3. 引用检索片段时注明来源编号，不输出片段之外未经授权的内容。"
    ), gate_meta


@router.get("/providers")
async def list_providers(db: Session = Depends(get_db)):
    """AI 服务商列表。"""
    providers = db.query(AIProvider).order_by(AIProvider.fallback_priority.asc()).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "provider_type": p.provider_type,
            "base_url": p.base_url,
            "model_name": p.model_name,
            "temperature": p.temperature,
            "is_default": p.is_default,
            "is_enabled": p.is_enabled,
            "fallback_priority": p.fallback_priority,
            "has_api_key": bool(p.api_key),
        }
        for p in providers
    ]


@router.post("/providers")
async def create_provider(provider: AIProviderCreate, db: Session = Depends(get_db)):
    """添加 AI 配置。"""
    # 如果设为默认，取消其他默认
    if provider.is_default:
        db.query(AIProvider).update({AIProvider.is_default: False})

    new_provider = AIProvider(**provider.model_dump())
    db.add(new_provider)
    db.commit()
    db.refresh(new_provider)
    return {"id": new_provider.id, "message": "AI 配置添加成功"}


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: int, provider: AIProviderUpdate, db: Session = Depends(get_db)):
    """更新配置。"""
    db_provider = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not db_provider:
        raise HTTPException(status_code=404, detail="AI 配置不存在")

    # 如果设为默认，取消其他默认
    if provider.is_default:
        db.query(AIProvider).filter(AIProvider.id != provider_id).update(
            {AIProvider.is_default: False}
        )

    update_data = provider.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_provider, key, value)

    db.commit()
    return {"id": db_provider.id, "message": "AI 配置更新成功"}


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: int, db: Session = Depends(get_db)):
    """删除配置。"""
    db_provider = db.query(AIProvider).filter(AIProvider.id == provider_id).first()
    if not db_provider:
        raise HTTPException(status_code=404, detail="AI 配置不存在")

    db.delete(db_provider)
    db.commit()
    return {"message": "AI 配置已删除"}


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: int, db: Session = Depends(get_db)):
    """测试 AI API 连通性。"""
    ai = AIService(db)
    try:
        result = await ai.test_provider(provider_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------- T1：AI 路由模式（设置页热切换） ---------------- #
_ROUTING_KEY = "ai_routing"


class RoutingModeRequest(BaseModel):
    mode: str


@router.get("/routing")
async def get_routing(db: Session = Depends(get_db)):
    """当前 AI 路由模式与可选值说明（前端设置页渲染用）。"""
    from services import model_gateway as gw

    cfg = (
        db.query(PlatformConfig)
        .filter(PlatformConfig.platform_name == _ROUTING_KEY)
        .first()
    )
    mode = None
    if cfg and cfg.extra:
        mode = (cfg.extra or {}).get("mode")
    if mode not in gw.ROUTING_MODES:
        mode = gw.get_routing_mode()  # 回退 env/默认（也会校验合法值）
    return {
        "mode": mode,
        "options": [
            {"mode": m, "label": gw.ROUTING_MODE_LABELS[m]} for m in gw.ROUTING_MODES
        ],
    }


@router.put("/routing")
async def set_routing(req: RoutingModeRequest, db: Session = Depends(get_db)):
    """设置 AI 路由模式并立即生效（清网关缓存，无需重启）。"""
    from services import model_gateway as gw

    if req.mode not in gw.ROUTING_MODES:
        raise HTTPException(400, f"非法路由模式：{req.mode}，可选 {list(gw.ROUTING_MODES)}")
    cfg = (
        db.query(PlatformConfig)
        .filter(PlatformConfig.platform_name == _ROUTING_KEY)
        .first()
    )
    if cfg:
        cfg.extra = {"mode": req.mode}
    else:
        db.add(PlatformConfig(platform_name=_ROUTING_KEY, extra={"mode": req.mode}))
    db.commit()
    gw.reset_routing_cache()
    return {"mode": req.mode, "message": f"路由模式已切换为 {gw.ROUTING_MODE_LABELS[req.mode]}，立即生效"}


def _format_bank_answer(b: dict) -> str:
    """题库确定性答案 → 用户可读文本直出（不经过模型，零幻觉）。"""
    lines = ["【题库命中 · 确定性答案】", ""]
    lines.append((b.get("content") or "").strip())
    opts = b.get("options")
    if isinstance(opts, dict) and opts:
        lines.append("")
        lines.append("选项：" + "  ".join(f"{k}. {v}" for k, v in sorted(opts.items(), key=lambda kv: str(kv[0]))))
    elif isinstance(opts, list) and opts:
        lines.append("")
        lines.append("选项：" + "  ".join(str(o) for o in opts))
    ans = (b.get("answer") or "").strip()
    if ans:
        lines.append("")
        lines.append(f"答案：{ans}")
    an = (b.get("analysis") or "").strip()
    if an:
        lines.append("")
        lines.append(f"解析：{an}")
    meta = []
    if b.get("subject"):
        meta.append(str(b["subject"]))
    if b.get("year"):
        meta.append(f"{b['year']}年")
    if b.get("source_label"):
        meta.append(str(b["source_label"]))
    meta.append(f"题库 #{b.get('id')} · answer_source={b.get('answer_source')}")
    lines.append("")
    lines.append(f"（来源：{' · '.join(meta)}；如需针对本题深入讲解，请继续提问）")
    return "\n".join(lines)


@router.post("/chat")
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """AI 对话（统一接口，自动选择启用的服务商，可选 RAG 知识库增强 + 智能路由）。"""
    ai = AIService(db)
    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        # —— 答疑「题库确定性答案优先」（云端方案第三步①）——
        # 高置信来源（bank/source_extract/user_confirmed）的题被用户问题句级命中时，
        # 直接返回「题目+答案+解析」，不进模型自由发挥；查不到才走 RAG + 模型。
        if request.use_rag and messages:
            _last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            try:
                from services.qa_foundation import find_bank_answer
                _bank = find_bank_answer(db, _last_user)
            except Exception as _be:
                logger.warning("bank_answer 查询失败，继续 RAG: %s", _be)
                _bank = None
            if _bank:
                return {
                    "content": _format_bank_answer(_bank),
                    "answer_source": _bank["answer_source"],
                    "bank_answer": {
                        "id": _bank["id"], "subject": _bank["subject"],
                        "question_type": _bank["question_type"],
                        "answer_source": _bank["answer_source"],
                        "answer_confidence": _bank["answer_confidence"],
                        "year": _bank["year"], "source_label": _bank["source_label"],
                    },
                    "rag": False,
                    "bank_hit": True,
                }
        # RAG：把最后一条用户消息作为查询，检索本地知识库注入 system
        rag_prompt = ""
        gate_meta = None
        if request.use_rag and messages:
            last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            rag_prompt, gate_meta = await _rag_system_prompt(last_user, ai)
            if rag_prompt:
                messages = [
                    {"role": "system", "content": rag_prompt},
                    *messages,
                ]
        # KB 感知路由：统计本地知识库对当前问题的命中数
        kb_hit_count = 0
        if request.use_routing and not request.provider_id and messages:
            last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            try:
                kb_hit_count = len(ai.search_knowledge_base(last_user, limit=4))
            except Exception:
                kb_hit_count = 0
        result = await ai.chat(
            messages,
            provider_id=request.provider_id,
            kb_hit_count=kb_hit_count,
            force_local=request.force_local,
        )
        result["rag"] = bool(rag_prompt) if request.use_rag else False
        # observe 模式：把门控判定（would_abstain 率）透传给前端，便于灰度观测
        if gate_meta is not None:
            result["retrieval_gate"] = gate_meta
        return result
    except HTTPException:
        raise
    except Exception as e:
        # E2E2-002：detail 不再透传原始异常（会暴露服务商地址与 401 原文），原文只进服务端日志。
        # P0-5：但也不能只回一句笼统的「暂时不可用」——把**分类后的原因码**回传，
        # 让前端能区分「没配服务商 / Key 失效 / 连不上 / 本地 Ollama 没起」，给用户可操作的提示。
        code, hint = _classify_ai_error(e)
        logger.exception("AI 对话失败（reason=%s）", code)
        raise HTTPException(
            status_code=502,
            detail=f"AI 服务暂时不可用（{code}）：{hint}。请到「设置 → AI 服务」检查配置后重试。",
            headers={"X-AI-Error-Code": code},
        )


# ---------------- T4：电路读图图片上传 ---------------- #
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_IMAGE_MAX_MB = 10


@router.post("/upload-image")
async def upload_chat_image(file: UploadFile = File(...)):
    """答疑页图片上传（电路读图题用）。

    保存到 uploads/chat_images/，返回本地绝对路径；前端随后在
    /chat/router 请求里带 image_path，Agentic 状态机识别后触发
    circuit_analysis（qwen2.5vl VLM 读图 + RapidOCR 标签）。
    """
    import uuid
    from pathlib import Path

    ext = Path(file.filename or "").suffix.lower()
    if ext not in _IMAGE_EXT:
        raise HTTPException(400, f"仅支持图片文件：{sorted(_IMAGE_EXT)}")
    save_dir = Path(__file__).resolve().parent.parent / "uploads" / "chat_images"
    save_dir.mkdir(parents=True, exist_ok=True)
    dest = save_dir / f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > _IMAGE_MAX_MB * 1024 * 1024:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(400, f"图片超过 {_IMAGE_MAX_MB}MB 上限")
            out.write(chunk)
    return {"path": str(dest), "filename": file.filename, "size": size}


@router.post("/chat/router")
async def chat_with_router(request: ChatRequest, db: Session = Depends(get_db)):
    """V3.0 AI 智能路由对话（自动选择本地/API/RAG引擎，带失败回退）。"""
    from services.ai_router import get_ai_router
    ai = AIService(db)
    router = get_ai_router(db)

    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

        # —— 题库确定性答案优先（第三步①）：命中即直返，不走引擎状态机 ——
        try:
            from services.qa_foundation import find_bank_answer
            _bank = find_bank_answer(db, last_user)
        except Exception as _be:
            logger.warning("bank_answer 查询失败，继续路由引擎: %s", _be)
            _bank = None
        if _bank:
            return {
                "content": _format_bank_answer(_bank),
                "engine_used": "bank",
                "classification": "bank_answer",
                "fallback_used": False,
                "latency_ms": 0,
                "reason": "题库确定性答案命中，跳过模型",
                "reasoning_steps": [],
                "retrieved_chunks": [],
                "cache_hit": False,
                "from_cache": False,
                "reranker_backend": "none",
                "answer_source": _bank["answer_source"],
                "bank_answer": {
                    "id": _bank["id"], "subject": _bank["subject"],
                    "question_type": _bank["question_type"],
                    "answer_source": _bank["answer_source"],
                    "answer_confidence": _bank["answer_confidence"],
                    "year": _bank["year"], "source_label": _bank["source_label"],
                },
            }

        # 强制引擎
        force_engine = None
        if request.force_local:
            force_engine = "local"
        elif request.use_rag:
            force_engine = "rag"

        context = messages[:-1] if len(messages) > 1 else None
        # T4 电路读图：图片路径注入上下文（ai_router._extract_image_path 按正则识别
        # Windows 绝对路径后触发 circuit_analysis 分支，无需改动状态机本身）
        if request.image_path:
            context = (context or []) + [
                {"role": "user", "content": f"[图片] {request.image_path}"}
            ]

        result = await router.chat_with_router(
            question=last_user,
            ai_service=ai,
            context=context,
            force_engine=force_engine,
        )

        return {
            "content": result["content"],
            "engine_used": result["engine_used"],
            "classification": result["classification"],
            "fallback_used": result["fallback_used"],
            "latency_ms": result.get("latency_ms", 0),
            "reason": result.get("reason", ""),
            # V11：Agentic 状态机推理步骤 + 检索溯源，字段恒定（无则给空默认）
            "reasoning_steps": result.get("reasoning_steps", []),
            "retrieved_chunks": result.get("retrieved_chunks", []),
            "cache_hit": result.get("cache_hit", False),
            "from_cache": result.get("from_cache", False),
            "reranker_backend": result.get("reranker_backend", "none"),
        }
    except HTTPException:
        raise
    except Exception as e:
        code, hint = _classify_ai_error(e)
        logger.exception("AI 路由对话失败（reason=%s）", code)
        raise HTTPException(
            status_code=502,
            detail=f"AI 服务暂时不可用（{code}）：{hint}。请到「设置 → AI 服务」检查配置后重试。",
            headers={"X-AI-Error-Code": code},
        )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """AI 对话 SSE 流式输出（可选 RAG 知识库增强）。"""
    ai = AIService(db)

    async def event_gen():
        # P0-5：整段包在 try 里。旧实现只把 ai.chat_stream(...) 包了 try，
        # 而 RAG 检索（_rag_system_prompt）在 try **之外**——它一抛异常，
        # StreamingResponse 就在发出任何事件前直接断开：HTTP 状态仍是 200，
        # 但流里既没有 delta 也没有 error 事件，前端表现为"点了没反应、也不报错"。
        try:
            messages = [{"role": m.role, "content": m.content} for m in request.messages]
            rag_used = False
            gate_meta = None
            if request.use_rag and messages:
                last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
                rag_prompt, gate_meta = await _rag_system_prompt(last_user, ai)
                if rag_prompt:
                    messages = [
                        {"role": "system", "content": rag_prompt},
                        *messages,
                    ]
                    rag_used = True
            # KB 感知路由：统计命中数
            kb_hit_count = 0
            if request.use_routing and not request.provider_id and messages:
                last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
                try:
                    kb_hit_count = len(ai.search_knowledge_base(last_user, limit=4))
                except Exception:
                    kb_hit_count = 0
            # observe 模式：meta 事件带上检索门控判定，便于灰度观测 would_abstain 率
            # V12 修复：SSE 必须按 "data: {json}\n\n" 逐事件输出，前端按行切分。
            # 旧实现 yield 紧凑 JSON 无换行 → 前端 indexOf('\n') 永远 -1 → 流永不渲染，
            # AI 助手卡"生成中…"。
            yield f"data: {json.dumps({'type': 'meta', 'rag': rag_used, 'retrieval_gate': gate_meta}, ensure_ascii=False)}\n\n"
            async for ev in ai.chat_stream(
                messages,
                provider_id=request.provider_id,
                provider_override=request.provider_override,
                kb_hit_count=kb_hit_count,
                force_local=request.force_local,
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            # 与 /chat 同源分类：code 让前端区分失败原因，原始异常只进日志。
            code, hint = _classify_ai_error(e)
            logger.exception("AI 流式对话失败（reason=%s）", code)
            yield f"data: {json.dumps({'type': 'error', 'code': code, 'message': f'AI 服务暂时不可用（{code}）：{hint}。请到「设置 → AI 服务」检查配置后重试。'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/rag-search")
async def rag_search(request: RAGSearchRequest, db: Session = Depends(get_db)):
    """本地知识库检索（RAG 调试/前端提示展示）。支持学科过滤。"""
    ai = AIService(db)
    hits = ai.search_knowledge_base(
        request.query, limit=request.limit or 6, subject=request.subject
    )
    return {"query": request.query, "subject": request.subject, "hits": hits, "count": len(hits)}


@router.get("/search-status")
async def search_status(db: Session = Depends(get_db)):
    """检索索引状态（FTS/向量索引统计）。"""
    from services.search_service import get_index_stats
    return get_index_stats(db)


@router.post("/rebuild-fts")
async def rebuild_fts(db: Session = Depends(get_db)):
    """重建 FTS5 全文检索索引（删除并重新同步 5164 条分块）。"""
    from services.search_service import ensure_fts_table
    conn = wrap_conn(db.connection().connection)
    conn.execute("DROP TABLE IF EXISTS knowledge_chunks_fts")
    conn.commit()
    ensure_fts_table(conn)
    count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks_fts").fetchone()[0]
    return {"success": True, "fts_indexed": count, "message": f"FTS 索引重建完成，共 {count} 条记录"}


@router.post("/build-embeddings")
async def build_embeddings(force: bool = False):
    """构建知识分块的 embedding 向量索引（完全离线，后台异步执行，不阻塞服务）。

    Args:
        force: 是否强制重新生成（清空旧向量后整体重建）

    返回任务 ID，可用 GET /api/ai/build-embeddings/status/{task_id} 查询进度。
    """
    from services.embedding_service import build_all_embeddings

    task_id = f"emb_{int(time.time() * 1000)}"
    _embedding_tasks[task_id] = {"status": "running", "progress": 0, "result": None}

    def _run():
        db = SessionLocal()
        try:
            result = asyncio.run(build_all_embeddings(db, force=force))
            _embedding_tasks[task_id]["result"] = result
            _embedding_tasks[task_id]["status"] = "done"
        except Exception as e:
            _embedding_tasks[task_id]["status"] = "failed"
            _embedding_tasks[task_id]["result"] = {"error": str(e)}
        finally:
            db.close()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"success": True, "task_id": task_id, "status": "running",
            "message": "向量索引构建已在后台启动（离线，不联网）"}


@router.get("/build-embeddings/status/{task_id}")
async def build_embeddings_status(task_id: str):
    """查询向量构建任务进度。"""
    if task_id not in _embedding_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _embedding_tasks[task_id]


@router.post("/explain")
async def explain(request: ExplainRequest, db: Session = Depends(get_db)):
    """知识点讲解。"""
    ai = AIService(db)
    try:
        result = await ai.explain_knowledge(request.topic)
        return {"content": result, "topic": request.topic}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"知识点讲解失败：{str(e)}")


@router.post("/grade-essay")
async def grade_essay(request: EssayGradeRequest, db: Session = Depends(get_db)):
    """作文批改。"""
    ai = AIService(db)
    try:
        result = await ai.grade_essay(request.content, request.type)
        return {"content": result, "type": request.type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"作文批改失败：{str(e)}")


@router.post("/analyze-sentence")
async def analyze_sentence(request: SentenceAnalyzeRequest, db: Session = Depends(get_db)):
    """长难句分析。"""
    ai = AIService(db)
    try:
        result = await ai.analyze_sentence(request.sentence)
        return {"content": result, "sentence": request.sentence}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"长难句分析失败：{str(e)}")


@router.post("/generate-plan")
async def generate_plan(request: GeneratePlanRequest, db: Session = Depends(get_db)):
    """生成复习计划。"""
    ai = AIService(db)
    try:
        result = await ai.generate_plan(request.goal, request.available_time)
        return {"content": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成计划失败：{str(e)}")


@router.post("/summarize-trend")
async def summarize_trend(request: SummarizeTrendRequest, db: Session = Depends(get_db)):
    """真题规律总结。"""
    ai = AIService(db)
    try:
        result = await ai.summarize_trend(request.questions)
        return {"content": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"规律总结失败：{str(e)}")


# ------------------------------------------------------------------ #
# 本地模型（Ollama）管理接口
# ------------------------------------------------------------------ #
@router.get("/models/catalog")
async def model_catalog(db: Session = Depends(get_db)):
    """模型选型报告：硬件画像 + 全部模型档案 + 本机适配判定 + 分科建议。

    这是"该装哪个模型"的唯一权威答案 —— 依据是本机实际显存，
    而不是排行榜上的参数量。
    """
    from services import model_registry as mr

    installed = set()
    try:
        import httpx
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{host}/api/tags")
            if r.status_code == 200:
                installed = {m.get("name", "") for m in r.json().get("models", [])}
                # Ollama 有时给 name 带 ":latest"，统一裁掉便于匹配
                installed |= {n.split(":")[0] for n in list(installed)}
    except Exception as _exc:  # noqa: BLE001
        # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
        # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
        logging.getLogger(__name__).warning(
            '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
        )

    return mr.full_report(installed=installed)


@router.get("/models/recommend")
async def model_recommend(subject: Optional[str] = None, task: Optional[str] = None):
    """按科目（或任务类型）推荐模型。

    `subject=数学` → 推理型；`subject=政治` → 中文型；
    `task=doc_process` → 轻量快速型。
    """
    from services import model_registry as mr

    if not subject and not task:
        raise HTTPException(status_code=400, detail="至少提供 subject 或 task 之一")

    resolved_task = task or mr.route_for_subject(subject)
    if resolved_task not in mr.TASK_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"未知任务类型 {resolved_task}，可选：{list(mr.TASK_KINDS)}",
        )
    recs = mr.recommend_for_task(resolved_task, subject=subject)
    return {
        "subject": subject,
        "task": resolved_task,
        "task_desc": mr.TASK_KINDS[resolved_task],
        "recommendations": recs,
        "top": recs[0] if recs else None,
    }


@router.get("/models/hardware")
async def model_hardware():
    """本机硬件画像（显存/内存/档位）。"""
    from dataclasses import asdict

    from services import model_registry as mr

    hw = mr.detect_hardware()
    return {**asdict(hw), "tier": hw.tier, "fit_levels": mr.FIT_LEVELS}


@router.get("/local/status")
async def local_model_status(db: Session = Depends(get_db)):
    """本地 Ollama 模型可用性检测。

    2026-10-14 变更：原先 ``force_check=True`` 完全绕过缓存，导致该接口
    **每次调用都真连一次 Ollama**；Ollama 未启动时连接挂到超时，
    实测单请求 27 秒。这里改为 ``force_recent=True``：
    只在缓存超过 30 秒时才重新探测，既保证"用户点按钮能立刻看到
    Ollama 刚启动的状态"，又不会把接口变成慢查询。
    """
    import os

    ai = AIService(db)
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    available = await ai._check_ollama_available(force_recent=True)

    # 可用时顺带把已装模型列出来，用户一眼看到"本地有什么能用"
    models: list = []
    if available:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{host}/api/tags")
                if resp.status_code == 200:
                    models = [
                        {"name": m.get("name"),
                         "size_gb": round((m.get("size") or 0) / (1024 ** 3), 2)}
                        for m in resp.json().get("models", [])
                    ]
        except Exception as _exc:  # noqa: BLE001
            # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
            # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
            logging.getLogger(__name__).warning(
                '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
            )

    return {
        "available": available,
        "host": host,
        "default_model": os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        "models": models,
        "model_count": len(models),
        "message": (
            f"本地 Ollama 服务运行中，已安装 {len(models)} 个模型"
            if available else
            "本地 Ollama 服务未启动。安装后执行 ollama pull qwen3.5:4b；"
            "未启动时平台会自动回退到云端 API。"
        ),
    }


@router.get("/local/models")
async def local_model_list(db: Session = Depends(get_db)):
    """获取本地已安装的模型列表。"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://127.0.0.1:11434/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = []
                for m in data.get("models", []):
                    models.append({
                        "name": m.get("name"),
                        "size": m.get("size"),
                        "size_gb": round(m.get("size", 0) / (1024**3), 2),
                        "modified_at": m.get("modified_at"),
                    })
                return {"available": True, "models": models, "count": len(models)}
            return {"available": False, "models": [], "count": 0, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"available": False, "models": [], "count": 0, "error": str(e)}


@router.post("/local/test")
async def local_model_test(
    model: str = "qwen3:8b",
    prompt: str = "你好，请用一句话介绍你自己。",
    db: Session = Depends(get_db),
):
    """测试本地模型调用。"""
    try:
        import httpx
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "temperature": 0.7,
            "num_predict": 200,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "http://127.0.0.1:11434/api/generate",
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "success": True,
                    "model": model,
                    "response": data.get("response", ""),
                    "eval_count": data.get("eval_count", 0),
                    "total_duration_ms": round(data.get("total_duration", 0) / 1e6, 2),
                }
            return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
