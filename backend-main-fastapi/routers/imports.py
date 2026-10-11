"""本地数据导入路由。

扫描本地目录（如 D:\\考研资料数据集V1.0）或上传文件，
解析为纯文本后写入应用自有数据库（documents 表），
并切分为知识分块写入 knowledge_chunks + FTS5（RAG 可检索）。

P0-1 修复：原实现只写 doc.content，知识库从不进入 RAG；
现解析后立即调用 kb_service.ingest_document 生成分块，
AI 问答即可检索到导入的资料。
可选 enrich：用本地模型（qwen3.5:4b）提炼文档要点，追加为知识分块（"边训练边导入"）。
"""

import json
import os
import threading
import time
import urllib.request
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Document
from services.document_parser import DocumentParser
from services.kb_service import ingest_document, ingest_text

router = APIRouter(prefix="/api/imports", tags=["imports"])

SUPPORTED_EXT = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".txt", ".md"}

# 内存中的扫描任务状态
_scans: dict = {}
_scan_lock = threading.Lock()

# Ollama 本地模型地址
_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"


# --------------------------------------------------------------------------- #
# 本地模型（Ollama）提炼要点
# --------------------------------------------------------------------------- #
def _ollama_chat(model: str, prompt: str, timeout: int = 420) -> Optional[str]:
    """调用本地 Ollama（/api/chat），返回**干净的答案文本**或 None。纯本地、数据不出网。

    ⚠️ 两个实测坑（2026-10 修）：

    1. **不要传 `"think": false`。** 原代码注释写"必须显式 think:false 才能拿到正文"，
       那描述的是 `qwen3.5:4b` 的行为。实测 `qwen3:4b` **正好相反**：
       传 `think:false` 会把**整个推理过程倒进 `content`**
       （3529 字的"首先，用户要求我提炼…"），默认不传才有干净答案（70 字）。
       后果是把思维链当知识要点写进了知识库。现在改为不传 think，
       并用 `llm_output.extract_answer()` 兜底清洗 —— 不管模型怎么变都不会中招。

    2. **超时原来只有 90 秒，远远不够。** 实测 4B 模型提炼一次要约 220-320 秒
       （思考模式本身很慢）。原超时会导致提炼**几乎总是失败**。
    """
    from services.llm_output import build_payload, extract_answer

    try:
        payload = json.dumps(
            build_payload(model, prompt, temperature=0.3, num_predict=1024),
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            _OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        answer = extract_answer(data.get("message", {}) or {})
        if not answer:
            print(f"[imports] {model} 未返回可用正文（可能只给了思考过程），已跳过")
            return None
        return answer
    except Exception as e:
        print(f"[imports] Ollama 调用失败({model}): {e}")
        return None


def _ollama_enrich(text: str, model: str) -> Optional[str]:
    """用本地文档处理模型提炼资料要点，返回结构化摘要。

    仅取前 ~1500 字即可，过长会让本地小模型超时；要点提炼不需要全文。
    """
    if not text or len(text.strip()) < 100:
        return None
    excerpt = text[:1500]
    prompt = (
        "你是一位考研资料整理助手。请阅读以下资料片段，提炼出【核心知识点】与"
        "【关键公式/结论】，用简洁的中文分条列出（每条不超过60字），便于后续检索与复习。"
        "不要解释，只要要点。\n\n资料：\n" + excerpt
    )
    return _ollama_chat(model, prompt, timeout=420)


class ScanRequest(BaseModel):
    directory: str
    recursive: bool = True
    use_ocr: bool = True
    enrich: bool = True                       # 用本地模型提炼要点追加进知识库
    enrich_model: str = "qwen3:8b"          # 文档处理模型（用户已下载）
    cap_chars: int = 120000                   # 单文档入库文本上限（防 KB 膨胀）
    force: bool = False                        # 强制重新解析已导入文档


def _scan_worker(
    task_id: str,
    directory: str,
    recursive: bool,
    use_ocr: bool,
    enrich: bool,
    enrich_model: str,
    cap_chars: int,
    force: bool,
    db_factory,
):
    """后台扫描导入任务：解析 -> 切分入库(RAG) -> 可选本地模型提炼。"""
    parser = DocumentParser()
    stats = {"scanned": 0, "imported": 0, "skipped": 0, "failed": 0, "enriched": 0, "errors": []}
    start = time.time()
    try:
        if not os.path.isdir(directory):
            stats["errors"].append(f"目录不存在: {directory}")
            _scans[task_id]["status"] = "failed"
            _scans[task_id]["stats"] = stats
            return

        db = db_factory()
        try:
            file_list = []
            if recursive:
                for root, _dirs, files in os.walk(directory):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in SUPPORTED_EXT:
                            file_list.append(os.path.join(root, f))
            else:
                for f in os.listdir(directory):
                    full = os.path.join(directory, f)
                    if os.path.isfile(full) and os.path.splitext(f)[1].lower() in SUPPORTED_EXT:
                        file_list.append(full)

            for idx, path in enumerate(file_list):
                if _scans[task_id]["status"] == "cancelled":
                    break
                stats["scanned"] += 1
                _scans[task_id]["progress"] = round(idx / max(len(file_list), 1) * 100, 1)

                fname = os.path.basename(path)
                try:
                    exists = db.query(Document).filter(Document.file_path == path).first()

                    # 幂等：已导入且非强制则跳过
                    if exists and exists.index_status == "indexed" and not force:
                        stats["skipped"] += 1
                        continue

                    text = parser.parse(path)
                    if not text or not text.strip():
                        stats["failed"] += 1
                        stats["errors"].append(f"{path}: 解析为空")
                        continue

                    # 入库 Document
                    if exists:
                        doc = exists
                    else:
                        doc = Document(
                            file_name=fname,
                            file_path=path,
                            file_type=DocumentParser.file_type(fname),
                            size=os.path.getsize(path),
                        )
                        db.add(doc)
                    doc.content = text[:500000]
                    doc.index_status = "indexing"
                    doc.parse_progress = 0.3
                    db.commit()
                    db.refresh(doc)

                    # 切分入库：写 knowledge_chunks + FTS5，RAG 可检索
                    body = text if len(text) <= cap_chars else text[:cap_chars]
                    chunk_count = ingest_document(db, doc, replace=True)
                    doc.knowledge_point_count = chunk_count
                    doc.parse_progress = 0.8

                    # 本地模型提炼要点（"训练"：qwen3.5:4b 处理文档），追加为知识分块
                    enriched = 0
                    if enrich:
                        summary = _ollama_enrich(text, enrich_model)
                        if summary:
                            enriched = ingest_text(
                                db, doc.id, doc.file_name + " ·AI提炼",
                                summary, subject=doc.subject, replace=False,
                            )
                    doc.index_status = "indexed" if chunk_count > 0 else "failed"
                    doc.parse_progress = 1.0
                    db.commit()
                    stats["imported"] += 1
                    if enriched:
                        stats["enriched"] += 1
                except Exception as e:
                    stats["failed"] += 1
                    stats["errors"].append(f"{path}: {e}")
                    db.rollback()
        finally:
            db.close()

        _scans[task_id]["stats"] = stats
        _scans[task_id]["status"] = "done"
    except Exception as e:
        _scans[task_id]["status"] = "failed"
        _scans[task_id]["stats"] = stats
        _scans[task_id]["stats"]["errors"].append(str(e))
    finally:
        _scans[task_id]["elapsed"] = round(time.time() - start, 1)


@router.post("/scan")
async def start_scan(req: ScanRequest, db: Session = Depends(get_db)):
    """启动目录扫描导入任务（后台执行）。"""
    from database import SessionLocal

    task_id = f"scan_{int(time.time() * 1000)}"
    _scans[task_id] = {
        "status": "running",
        "progress": 0,
        "stats": None,
        "elapsed": None,
        "directory": req.directory,
    }

    t = threading.Thread(
        target=_scan_worker,
        args=(
            task_id, req.directory, req.recursive, req.use_ocr,
            req.enrich, req.enrich_model, req.cap_chars, req.force, SessionLocal,
        ),
        daemon=True,
    )
    t.start()
    return {"task_id": task_id, "status": "running", "directory": req.directory}


@router.get("/scan/{task_id}")
async def get_scan_status(task_id: str):
    """查询扫描任务状态。"""
    if task_id not in _scans:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _scans[task_id]


@router.post("/scan/{task_id}/cancel")
async def cancel_scan(task_id: str):
    """取消扫描任务。"""
    if task_id not in _scans:
        raise HTTPException(status_code=404, detail="任务不存在")
    _scans[task_id]["status"] = "cancelled"
    return {"status": "cancelled"}


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """文档库统计。"""
    total = db.query(Document).count()
    indexed = db.query(Document).filter(Document.index_status == "indexed").count()
    failed = db.query(Document).filter(Document.index_status == "failed").count()
    pending = db.query(Document).filter(Document.index_status == "pending").count()
    total_size = db.query(Document).with_entities(
        __import__("sqlalchemy").func.coalesce(__import__("sqlalchemy").func.sum(Document.size), 0)
    ).scalar()
    return {
        "total": total,
        "indexed": indexed,
        "failed": failed,
        "pending": pending,
        "total_size": int(total_size or 0),
    }
