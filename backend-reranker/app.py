"""
bge-reranker-v2-m3 CPU 重排微服务
=====================================
POST /rerank  {query: str, documents: [{id: str, text: str}]}
           -> {results: [{id: str, score: float}]}   (按 score 降序)

启动: uvicorn app:app --host 127.0.0.1 --port 8140
"""
import os
import sys
import time
import logging
from typing import List, Optional

# ---------------------------------------------------------------------------
# 模型路径与环境变量
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "data", "models", "bge-reranker-v2-m3")

# 优先本地权重目录；若不存在则从 HF 在线加载（仍走 hf-mirror）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reranker")

# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="bge-reranker-v2-m3", version="1.0.0")


# 主后端经隧道调用：设了 COMPUTE_SERVICE_TOKEN 就要求 X-Service-Token 匹配（/health 留给探活）
_SERVICE_TOKEN = os.getenv("COMPUTE_SERVICE_TOKEN", "").strip()


@app.middleware("http")
async def _require_service_token(request, call_next):
    if _SERVICE_TOKEN and request.url.path != "/health":
        import hmac
        from fastapi.responses import JSONResponse
        if not hmac.compare_digest(request.headers.get("x-service-token", ""), _SERVICE_TOKEN):
            return JSONResponse({"detail": "invalid service token"}, status_code=401)
    return await call_next(request)

# 全局模型实例（懒加载）
_reranker = None
_model_load_error: Optional[str] = None


def get_reranker():
    """懒加载 FlagEmbedding FlagReranker（CPU）。"""
    global _reranker, _model_load_error
    if _reranker is not None:
        return _reranker
    if _model_load_error is not None:
        return None
    try:
        from FlagEmbedding import FlagReranker
        logger.info(f"Loading reranker model from: {MODEL_DIR}")
        t0 = time.time()
        _reranker = FlagReranker(
            MODEL_DIR if os.path.isdir(MODEL_DIR) else "BAAI/bge-reranker-v2-m3",
            use_fp16=False,   # CPU 不支持 fp16
        )
        logger.info(f"Model loaded in {time.time() - t0:.1f}s")
        return _reranker
    except Exception as e:
        _model_load_error = f"{type(e).__name__}: {e}"
        logger.error(f"Failed to load reranker: {_model_load_error}")
        return None


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------
class Document(BaseModel):
    id: str = Field(..., description="文档唯一标识")
    text: str = Field(..., description="文档文本")


class RerankRequest(BaseModel):
    query: str = Field(..., description="查询语句")
    documents: List[Document] = Field(..., description="待重排文档列表")


class RerankResult(BaseModel):
    id: str
    score: float


class RerankResponse(BaseModel):
    results: List[RerankResult]
    model: str = "bge-reranker-v2-m3"
    took_ms: float = 0.0


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    """健康检查：模型是否就绪。"""
    r = get_reranker()
    return {
        "status": "ok" if r is not None else "unavailable",
        "model": "bge-reranker-v2-m3",
        "error": _model_load_error,
    }


@app.post("/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest):
    """对 documents 按 query 相关性重排，返回降序 score。"""
    t0 = time.time()
    r = get_reranker()

    if r is None:
        # 模型不可用：原序返回 score=0，调用方应自行兜底
        logger.warning("Reranker unavailable, returning documents in original order with score=0")
        return RerankResponse(
            results=[RerankResult(id=d.id, score=0.0) for d in req.documents],
            took_ms=(time.time() - t0) * 1000,
        )

    if not req.documents:
        return RerankResponse(results=[], took_ms=(time.time() - t0) * 1000)

    # 构造 (query, text) 对
    pairs = [[req.query, d.text] for d in req.documents]

    # FlagReranker.compute_score 返回 list[float]
    scores = r.compute_score(pairs, normalize=True)
    if not isinstance(scores, list):
        scores = [scores]

    # 组装并按 score 降序
    results = [
        RerankResult(id=d.id, score=float(s))
        for d, s in zip(req.documents, scores)
    ]
    results.sort(key=lambda x: x.score, reverse=True)

    took_ms = (time.time() - t0) * 1000
    logger.info(f"Reranked {len(req.documents)} docs in {took_ms:.1f}ms | query='{req.query[:40]}'")

    return RerankResponse(results=results, took_ms=took_ms)


# ---------------------------------------------------------------------------
# 直接运行入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    # 启动时预热模型
    get_reranker()
    uvicorn.run(
        app,
        host=os.getenv("SERVICE_HOST", "127.0.0.1"),  # 云端经 Tailscale 调用时设为本机 tailscale IP，勿用 0.0.0.0
        port=int(os.getenv("SERVICE_PORT", "8140")),
        log_level="info",
    )
