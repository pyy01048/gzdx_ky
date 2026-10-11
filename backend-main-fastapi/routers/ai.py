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


@router.post("/chat")
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """AI 对话（统一接口，自动选择启用的服务商，可选 RAG 知识库增强 + 智能路由）。"""
    ai = AIService(db)
    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 对话失败：{str(e)}")


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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI路由对话失败：{str(e)}")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """AI 对话 SSE 流式输出（可选 RAG 知识库增强）。"""
    ai = AIService(db)

    async def event_gen():
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
        yield json.dumps({"type": "meta", "rag": rag_used, "retrieval_gate": gate_meta},
                         ensure_ascii=False)
        try:
            async for ev in ai.chat_stream(
                messages,
                provider_id=request.provider_id,
                provider_override=request.provider_override,
                kb_hit_count=kb_hit_count,
                force_local=request.force_local,
            ):
                yield json.dumps(ev, ensure_ascii=False)
        except Exception as e:
            yield json.dumps({"type": "error", "message": f"AI 对话失败：{str(e)}"}, ensure_ascii=False)

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
    conn = db.connection().connection
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
    except Exception:
        pass

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
    """本地 Ollama 模型可用性检测（强制实时探测，不吃 5 分钟缓存）。"""
    import os

    ai = AIService(db)
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    available = await ai._check_ollama_available(force_check=True)

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
        except Exception:
            pass

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
