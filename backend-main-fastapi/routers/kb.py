# -*- coding: utf-8 -*-
"""知识库健康路由：体检 + 一键自愈。

给前端「知识地图」和「文档知识库」页提供"我的知识库现在什么状态、
缺什么、能不能一键修"的能力 —— 不用去命令行跑脚本。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from services import kb_pipeline

router = APIRouter(prefix="/api/kb", tags=["知识库健康"])

#: 后台任务状态（单机单用户，内存态足够）
_heal_task: dict = {"running": False, "stage": "", "detail": "", "result": None, "error": None}


@router.get("/health")
async def kb_health(db: Session = Depends(get_db)):
    """知识库体检：状态分布、空正文、缺向量、缺元信息，以及缺口清单。

    这是"自主本地知识库建立"的入口 —— 先看清缺什么，再决定修什么。
    """
    return kb_pipeline.health_report(db)


def _run_heal(use_ocr: bool, do_embeddings: bool):
    """后台执行自愈。"""
    global _heal_task
    db = SessionLocal()
    try:
        _heal_task.update(running=True, stage="start", detail="", error=None, result=None)

        def on_progress(name: str, payload: dict):
            _heal_task["stage"] = name
            _heal_task["detail"] = str(payload)[:300]

        result = kb_pipeline.heal(
            db, use_ocr=use_ocr, do_embeddings=do_embeddings, progress=on_progress
        )
        _heal_task.update(result=result, stage="done", running=False)
    except Exception as e:
        _heal_task.update(error=f"{type(e).__name__}: {e}", running=False, stage="failed")
    finally:
        db.close()


@router.post("/heal")
async def kb_heal(
    background: BackgroundTasks,
    use_ocr: bool = True,
    do_embeddings: bool = False,
):
    """一键修复：状态归一化 → 找回源文件路径 → 空正文重解析（含 OCR）→ 补向量。

    扫描件 OCR 很慢（每篇数秒到数十秒），所以走后台任务，
    用 `GET /api/kb/heal/status` 轮询进度。
    """
    if _heal_task["running"]:
        return {"accepted": False, "message": "已有修复任务在运行", "status": _heal_task}
    background.add_task(_run_heal, use_ocr, do_embeddings)
    _heal_task.update(running=True, stage="queued", detail="已加入队列")
    return {"accepted": True, "message": "修复任务已启动，可轮询 /api/kb/heal/status 查看进度"}


@router.get("/heal/status")
async def kb_heal_status():
    """修复进度。"""
    return _heal_task


@router.post("/repair-paths")
async def kb_repair_paths(db: Session = Depends(get_db)):
    """只做一件事：把失效的源文件路径重新指回项目内实际文件。

    很快（纯文件系统匹配），且是"重新解析扫描件"的前置条件。
    """
    return kb_pipeline.repair_file_paths(db)


@router.post("/normalize-status")
async def kb_normalize_status(db: Session = Depends(get_db)):
    """统一 index_status 口径（历史遗留的 ready → indexed）。"""
    return {"changed": kb_pipeline.normalize_status(db)}


@router.get("/pipeline")
async def kb_pipeline_info():
    """说明知识库的完整建立链路（给前端展示流程用）。"""
    return {
        "steps": [
            {"key": "scan", "name": "扫描入库", "desc": "指定目录递归扫描，按扩展名过滤（PDF/Word/PPT/TXT/MD）"},
            {"key": "parse", "name": "解析正文", "desc": "pypdf → pdfplumber 提取文本层；无文本层判定为扫描件"},
            {"key": "ocr", "name": "扫描件 OCR", "desc": "pypdfium2 逐页渲染 → 本地 RapidOCR（可选 PP-OCRv5 微服务）"},
            {"key": "chunk", "name": "分块", "desc": "按段落/句子切分，块间带重叠，保留上下文"},
            {"key": "fts", "name": "全文索引", "desc": "jieba 分词写入 FTS5，支持 BM25 检索"},
            {"key": "embed", "name": "向量索引", "desc": "bge-small-zh-v1.5 本地嵌入，支持向量召回"},
            {"key": "structure", "name": "结构化", "desc": "识别章节树，生成「章节→知识点→题型」三级结构"},
            {"key": "meta", "name": "元信息标记", "desc": "doc_type（原始/加工/索引层）+ 扫描件标记"},
        ],
        "entry_points": [
            "POST /api/imports/scan   —— 从本地目录批量导入",
            "POST /api/documents/upload —— 上传单个文件",
            "POST /api/netdisk/ingest —— 从百度网盘下载入库",
            "POST /api/kb/heal        —— 体检后一键修复缺口",
            "POST /api/kb/ingest-file —— 知识库快速入库（单个文件）",
            "POST /api/kb/ingest-inbox —— 扫描 knowledge_base/inbox 批量快速入库",
        ],
    }


# --------------------------------------------------------------------------- #
# 集各家所长 · 新文件快速入库（inbox → 解析/OCR → 分块 → 向量化 → 写库）
# --------------------------------------------------------------------------- #
@router.post("/ingest-file")
async def kb_ingest_file(payload: dict, db: Session = Depends(get_db)):
    """快速入库单个文件。

    body: {
        "file_path": "绝对路径或 knowledge_base/inbox 下的相对文件名",
        "ocr_backend": "auto | local-gpu | paddleocr | rapidocr | chineseocr-lite",
        "do_embeddings": true,
        "move_to_documents": true,
        "dry_run": false
    }
    """
    from services import kb_ingest

    file_path = str(payload.get("file_path", "")).strip()
    if not file_path:
        raise HTTPException(400, "缺少 file_path")
    if not os.path.isabs(file_path):
        file_path = os.path.join(kb_ingest.INBOX_DIR, file_path)
    return kb_ingest.ingest_file(
        db,
        file_path,
        ocr_backend=str(payload.get("ocr_backend", "auto")),
        do_embeddings=bool(payload.get("do_embeddings", True)),
        move_to_documents=bool(payload.get("move_to_documents", True)),
        dry_run=bool(payload.get("dry_run", False)),
    )


@router.post("/ingest-inbox")
async def kb_ingest_inbox(payload: dict = None, db: Session = Depends(get_db)):
    """扫描 knowledge_base/inbox 批量快速入库（支持 dry_run 预演）。"""
    from services import kb_ingest

    payload = payload or {}
    return kb_ingest.scan_inbox(
        db,
        ocr_backend=str(payload.get("ocr_backend", "auto")),
        do_embeddings=bool(payload.get("do_embeddings", True)),
        move_to_documents=bool(payload.get("move_to_documents", True)),
        dry_run=bool(payload.get("dry_run", False)),
        recursive=bool(payload.get("recursive", False)),
    )


@router.get("/ingest/status")
async def kb_ingest_status(db: Session = Depends(get_db)):
    """知识库快速入库能力状态：OCR 路由可用后端 + 模型网关配置 + knowledge_base 目录。"""
    from services.ocr_router import get_ocr_router
    from services.model_gateway import get_gateway
    from services import kb_ingest

    return {
        "knowledge_base": {
            "root": kb_ingest.KB_ROOT,
            "inbox": kb_ingest.INBOX_DIR,
            "exists": all(os.path.isdir(d) for d in (kb_ingest.INBOX_DIR, kb_ingest.DOCUMENTS_DIR, kb_ingest.META_DIR)),
        },
        "ocr_router": get_ocr_router().status(),
        "model_gateway": get_gateway().status(db=db),
    }
