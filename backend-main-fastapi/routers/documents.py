"""文档路由。"""

import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from database import get_db, BASE_DIR
from models import Document, KnowledgePoint, KnowledgeChunk

router = APIRouter(prefix="/api/documents", tags=["documents"])

UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 最大文件大小 100MB
MAX_FILE_SIZE = 100 * 1024 * 1024


def _safe_filename(filename: str) -> str:
    """清洗文件名，防止路径遍历攻击。"""
    # 只保留文件名部分，去掉路径
    name = Path(filename).name
    # 替换危险字符
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    # 防止空文件名
    if not name or name == '.':
        name = 'unknown'
    return name


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传文档。"""
    file_name = _safe_filename(file.filename or "unknown")
    file_ext = os.path.splitext(file_name)[1].lower()
    file_type = {
        ".pdf": "pdf",
        ".doc": "doc",
        ".docx": "docx",
        ".txt": "txt",
        ".ppt": "ppt",
        ".pptx": "pptx",
    }.get(file_ext, "other")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"文件过大，最大支持 {MAX_FILE_SIZE // (1024*1024)}MB")

    save_path = os.path.join(UPLOAD_DIR, file_name)
    with open(save_path, "wb") as f:
        f.write(content)

    doc = Document(
        file_name=file_name,
        file_path=save_path,
        file_type=file_type,
        size=len(content),
        index_status="pending",
        parse_progress=0,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"id": doc.id, "file_name": doc.file_name, "size": doc.size, "message": "上传成功"}


@router.get("")
async def list_documents(
    subject: str = None,
    doc_type: str = None,
    ocr_only: bool = False,
    db: Session = Depends(get_db),
):
    """文档列表（可按学科 / 资料层级 / 是否扫描件过滤）。"""
    q = db.query(Document)
    if subject:
        q = q.filter(Document.subject == subject)
    if doc_type:
        # raw 原始层 / note 加工层 / index 索引层
        q = q.filter(Document.doc_type == doc_type)
    if ocr_only:
        q = q.filter(Document.ocr_used == True)  # noqa: E712
    docs = q.order_by(Document.created_at.desc()).all()
    # 一次性聚合每个文档的分块数，避免 N+1 查询
    from sqlalchemy import func
    chunk_counts = dict(
        db.query(KnowledgeChunk.document_id, func.count(KnowledgeChunk.id))
        .filter(KnowledgeChunk.document_id.in_([d.id for d in docs]))
        .group_by(KnowledgeChunk.document_id).all()
    ) if docs else {}
    result = []
    for d in docs:
        result.append({
            "id": d.id,
            "file_name": d.file_name,
            "file_type": d.file_type,
            "size": d.size,
            "index_status": d.index_status,
            "knowledge_point_count": d.knowledge_point_count,
            "parse_progress": d.parse_progress,
            "subject": d.subject,
            # 文档组织三层结构 + 扫描件标记（前端据此筛选与降权）
            "doc_type": d.doc_type,
            "structure_level": d.structure_level,
            "ocr_used": bool(d.ocr_used),
            "summary": (d.content or "")[:200],
            "content_length": len(d.content or ""),
            "chunk_count": chunk_counts.get(d.id, 0),
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })
    return result


@router.get("/subjects")
async def list_subjects(db: Session = Depends(get_db)):
    """学科分类统计（文档数 + 分块数）。"""
    from sqlalchemy import func
    doc_rows = db.query(Document.subject, func.count(Document.id)).group_by(
        Document.subject
    ).all()
    chunk_rows = db.query(KnowledgeChunk.subject, func.count(KnowledgeChunk.id)).group_by(
        KnowledgeChunk.subject
    ).all()
    chunk_map = dict(chunk_rows)
    doc_total = db.query(Document).count()
    chunk_total = db.query(KnowledgeChunk).count()
    subjects = [
        {
            "name": name or "未分类",
            "document_count": cnt,
            "chunk_count": chunk_map.get(name, 0),
        }
        for name, cnt in doc_rows
    ]
    return {
        "total_documents": doc_total,
        "total_chunks": chunk_total,
        "subjects": subjects,
    }


@router.post("/{doc_id}/parse")
async def parse_document(doc_id: int, db: Session = Depends(get_db)):
    """解析文档（本地 DocumentParser：PDF/DOCX/PPTX/TXT，扫描版 PDF 走 OCR）。"""
    from services.document_parser import DocumentParser
    from services.ai_service import AIService

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    doc.index_status = "indexing"
    doc.parse_progress = 0.1
    db.commit()

    # 使用本地 DocumentParser 提取全文
    parser = DocumentParser()
    if doc.file_path and os.path.exists(doc.file_path):
        try:
            content_text = parser.parse(doc.file_path)
        except Exception as e:
            doc.index_status = "failed"
            db.commit()
            raise HTTPException(status_code=500, detail=f"文档解析失败：{str(e)}")
        if not content_text or not content_text.strip():
            content_text = f"[{doc.file_type} 文件，未能提取到文本内容] 文件名：{doc.file_name}"
    else:
        content_text = f"[文件缺失或未落盘] 文件名：{doc.file_name}"

    doc.content = content_text
    doc.parse_progress = 0.5
    db.commit()

    # —— 知识库闭环（P0-1）：文本 -> 分块 -> knowledge_chunks + FTS —— #
    # 这一步让上传的文档真正进入 RAG 知识库，可被 AI 检索引用。
    from services.kb_service import ingest_document, detect_doc_meta
    chunk_count = 0
    try:
        chunk_count = ingest_document(db, doc, replace=True)
        doc.parse_progress = 0.8
    except Exception as e:
        # 分块失败不影响文档内容，记录但不致命
        print(f"[kb] 文档 {doc.id} 分块入库失败: {e}")

    # 标记资料层级 / 结构化程度 / 是否扫描件 OCR
    meta = {}
    try:
        meta = detect_doc_meta(db, doc)
    except Exception as e:
        print(f"[kb] 文档 {doc.id} 元信息判定失败: {e}")

    # AI 提取知识点（best-effort，失败不再让整个解析失败）
    knowledge_point_count = 0
    try:
        ai = AIService(db)
        result = await ai.chat([
            {
                "role": "system",
                "content": "你是一位知识提取专家。请从文档中提取关键知识点，"
                "以 JSON 数组格式返回，每个元素包含 name（名称）和 description（描述）。",
            },
            {"role": "user", "content": f"请分析以下文档内容并提取知识点：\n\n{content_text[:8000]}"},
        ])
        doc.parse_progress = 0.9

        # 尝试解析知识点
        import json
        try:
            # 尝试从 AI 回复中提取 JSON
            text = result["content"]
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                kps = json.loads(text[start:end])
                for kp in kps:
                    name = kp.get("name", "")
                    desc = kp.get("description", "")
                    if name:
                        new_kp = KnowledgePoint(
                            name=name,
                            description=desc,
                            document_id=doc_id,
                        )
                        db.add(new_kp)
                knowledge_point_count = len(kps)
                doc.knowledge_point_count = knowledge_point_count
        except (json.JSONDecodeError, ValueError):
            pass
    except Exception as e:
        # AI 抽取失败不影响"已入库可检索"的结果
        print(f"[ai] 文档 {doc.id} 知识点提取失败（不影响入库）: {e}")

    # 只要文本已解析并分块入库，即视为 indexed（可被 RAG 检索）
    doc.index_status = "indexed"
    doc.parse_progress = 1.0
    db.commit()
    return {
        "id": doc.id,
        "index_status": doc.index_status,
        "knowledge_point_count": knowledge_point_count,
        "chunk_count": chunk_count,
        "content_length": len(content_text),
        "preview": content_text[:500],
        "doc_type": meta.get("doc_type"),
        "structure_level": meta.get("structure_level"),
        "ocr_used": meta.get("ocr_used", False),
        "message": (
            f"扫描版文档已 OCR 识别，生成 {chunk_count} 个知识分块并入库"
            if meta.get("ocr_used") and chunk_count
            else (f"文档解析完成，已生成 {chunk_count} 个知识分块并入库" if chunk_count
                  else "文档解析完成（分块未生成）")
        ),
    }


@router.get("/{doc_id}/knowledge-points")
async def get_knowledge_points(doc_id: int, db: Session = Depends(get_db)):
    """提取的知识点（按文档过滤）。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    kps = db.query(KnowledgePoint).filter(
        KnowledgePoint.document_id == doc_id
    ).all()
    return [
        {
            "id": kp.id,
            "name": kp.name,
            "subject": kp.subject,
            "chapter": kp.chapter,
            "mastery": kp.mastery,
            "exam_frequency": kp.exam_frequency,
            "description": kp.description,
        }
        for kp in kps
    ]


@router.get("/{doc_id}/chunks")
async def get_document_chunks(doc_id: int, db: Session = Depends(get_db)):
    """查看某文档的 RAG 知识分块。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    chunks = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.document_id == doc_id
    ).order_by(KnowledgeChunk.chunk_id).all()
    return {
        "document_id": doc.id,
        "file_name": doc.file_name,
        "subject": doc.subject,
        "count": len(chunks),
        "chunks": [
            {
                "id": c.id,
                "chunk_id": c.chunk_id,
                "doc_name": c.doc_name,
                "subject": c.subject,
                "text": c.text,
            }
            for c in chunks
        ],
    }


@router.post("/{doc_id}/generate-quiz")
async def generate_quiz(doc_id: int, db: Session = Depends(get_db)):
    """从文档生成题目。"""
    from services.ai_service import AIService
    from models import QuizQuestion

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    content = doc.content or ""
    if not content:
        raise HTTPException(status_code=400, detail="文档尚未解析，请先解析")

    ai = AIService(db)
    try:
        result = await ai.chat([
            {
                "role": "system",
                "content": "你是一位考研出题专家。请根据文档内容生成 5 道选择题，"
                "以 JSON 数组格式返回，每个元素包含 content（题干）、options（选项数组）、"
                "answer（正确答案字母）、analysis（解析）。",
            },
            {"role": "user", "content": f"请根据以下内容生成题目：\n\n{content[:5000]}"},
        ])

        import json
        questions_created = 0
        try:
            text = result["content"]
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                questions = json.loads(text[start:end])
                for q in questions:
                    new_q = QuizQuestion(
                        content=q.get("content", ""),
                        options=q.get("options", []),
                        answer=q.get("answer", ""),
                        analysis=q.get("analysis", ""),
                        source=f"文档生成：{doc.file_name}",
                        question_type="single",
                    )
                    db.add(new_q)
                    questions_created += 1
                db.commit()
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "questions_created": questions_created,
            "preview": result["content"][:500],
            "message": f"从文档生成了 {questions_created} 道题目",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"题目生成失败：{str(e)}")


# --------------------------------------------------------------------------- #
# 文档删除
# --------------------------------------------------------------------------- #
@router.delete("/{doc_id}")
async def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """删除文档（同时删除文件、分块、知识点）。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 删除文件
    if doc.file_path and os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except OSError:
            pass

    # 删除关联的分块和知识点
    db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc_id).delete()
    db.query(KnowledgePoint).filter(KnowledgePoint.document_id == doc_id).delete()

    # 删除文档
    db.delete(doc)
    db.commit()
    return {"id": doc_id, "message": "文档已删除，关联分块和知识点已清理"}


# --------------------------------------------------------------------------- #
# 文档内容预览
# --------------------------------------------------------------------------- #
@router.get("/{doc_id}/content")
async def get_document_content(doc_id: int, limit: int = 5000, db: Session = Depends(get_db)):
    """获取文档解析后的文本内容（用于预览）。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.content:
        return {"id": doc_id, "file_name": doc.file_name, "content": "", "message": "文档尚未解析"}
    return {
        "id": doc_id,
        "file_name": doc.file_name,
        "file_type": doc.file_type,
        "content_length": len(doc.content),
        "content": doc.content[:limit],
        "truncated": len(doc.content) > limit,
    }


# --------------------------------------------------------------------------- #
# 图片 OCR 识别（单独的图片上传识别）
# --------------------------------------------------------------------------- #
@router.post("/ocr")
async def ocr_image(file: UploadFile = File(...)):
    """上传图片进行 OCR 识别（支持 png/jpg/bmp 等）。"""
    from services.ocr_service import OCRService

    file_name = file.filename or "image.png"
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp"):
        raise HTTPException(status_code=400, detail="仅支持图片格式（png/jpg/bmp/tiff/webp）")

    # 保存临时文件
    import tempfile
    content = await file.read()
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp.write(content)
    tmp.close()

    try:
        ocr = OCRService()
        text = ocr.recognize(tmp.name)
        return {
            "file_name": file_name,
            "text": text,
            "char_count": len(text),
            "message": "OCR 识别完成" if text.strip() else "未识别到文字",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR 识别失败：{str(e)}")
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 批量解析所有未解析的文档
# --------------------------------------------------------------------------- #
@router.post("/parse-all")
async def parse_all_documents(db: Session = Depends(get_db)):
    """批量解析所有状态为 pending 的文档。"""
    pending_docs = db.query(Document).filter(Document.index_status == "pending").all()
    if not pending_docs:
        return {"parsed": 0, "message": "没有待解析的文档"}

    from services.document_parser import DocumentParser
    from services.kb_service import ingest_document

    parser = DocumentParser()
    parsed_count = 0
    results = []

    for doc in pending_docs:
        try:
            doc.index_status = "indexing"
            doc.parse_progress = 0.1
            db.commit()

            # 解析文本
            if doc.file_path and os.path.exists(doc.file_path):
                content_text = parser.parse(doc.file_path)
            else:
                content_text = f"[文件缺失] 文件名：{doc.file_name}"

            doc.content = content_text
            doc.parse_progress = 0.5
            db.commit()

            # 分块入库
            chunk_count = 0
            try:
                chunk_count = ingest_document(db, doc, replace=True)
            except Exception as e:
                print(f"[kb] 文档 {doc.id} 分块失败: {e}")

            doc.index_status = "indexed"
            doc.parse_progress = 1.0
            db.commit()
            parsed_count += 1
            results.append({"id": doc.id, "file_name": doc.file_name, "chunks": chunk_count, "status": "success"})
        except Exception as e:
            doc.index_status = "failed"
            db.commit()
            results.append({"id": doc.id, "file_name": doc.file_name, "error": str(e), "status": "failed"})

    return {
        "parsed": parsed_count,
        "total": len(pending_docs),
        "results": results,
        "message": f"批量解析完成，成功 {parsed_count}/{len(pending_docs)}",
    }


# --------------------------------------------------------------------------- #
# 文档智能分析（V2.0 新增：长文本识别 + 自动分类知识点/题目/真题）
# --------------------------------------------------------------------------- #
@router.post("/{doc_id}/analyze")
async def analyze_document(
    doc_id: int,
    extract_kp: bool = True,
    extract_questions: bool = True,
    rebuild_chunks: bool = False,
    db: Session = Depends(get_db),
):
    """智能分析文档：长文本分块 → AI提取知识点 → AI识别题目/真题并分类入库。

    - extract_kp: 是否提取知识点（默认True）
    - extract_questions: 是否识别题目（默认True）
    - rebuild_chunks: 是否重建知识库分块（默认False）
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.content:
        raise HTTPException(status_code=400, detail="文档尚未解析，请先调用 /parse")

    from services.document_analyzer import analyze_document as do_analyze
    from services.ai_service import AIService

    ai = AIService(db)
    result = await do_analyze(
        db, doc, ai,
        extract_kp=extract_kp,
        extract_questions=extract_questions,
        rebuild_chunks=rebuild_chunks,
    )
    return {
        "id": doc_id,
        "file_name": doc.file_name,
        **result,
        "message": f"分析完成：{result.get('knowledge_points', 0)}个知识点，{result.get('questions', 0)}道题目",
    }


@router.post("/{doc_id}/extract-knowledge-points")
async def extract_knowledge_points(doc_id: int, db: Session = Depends(get_db)):
    """仅提取文档中的知识点并入库。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.content:
        raise HTTPException(status_code=400, detail="文档尚未解析")

    from services.document_analyzer import smart_chunk_text, extract_knowledge_points as do_extract
    from services.ai_service import AIService

    chunks = smart_chunk_text(doc.content)
    ai = AIService(db)
    kps = await do_extract(db, doc, chunks, ai)
    return {
        "id": doc_id,
        "extracted": len(kps),
        "knowledge_points": [{"id": kp.id, "name": kp.name, "subject": kp.subject} for kp in kps],
        "message": f"提取了 {len(kps)} 个知识点",
    }


@router.post("/{doc_id}/extract-questions")
async def extract_questions(doc_id: int, db: Session = Depends(get_db)):
    """仅识别文档中的题目/真题并分类入库。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.content:
        raise HTTPException(status_code=400, detail="文档尚未解析")

    from services.document_analyzer import smart_chunk_text, extract_questions as do_extract
    from services.ai_service import AIService

    chunks = smart_chunk_text(doc.content)
    ai = AIService(db)
    questions = await do_extract(db, doc, chunks, ai)

    # 按题型和来源统计
    type_count = {}
    source_count = {}
    for q in questions:
        type_count[q.question_type] = type_count.get(q.question_type, 0) + 1
        source_count[q.source] = source_count.get(q.source, 0) + 1

    return {
        "id": doc_id,
        "extracted": len(questions),
        "by_type": type_count,
        "by_source": source_count,
        "questions": [{"id": q.id, "type": q.question_type, "source": q.source, "content": q.content[:100]} for q in questions[:20]],
        "message": f"识别了 {len(questions)} 道题目（真题/模拟题/课后习题已自动分类）",
    }


@router.post("/analyze-batch")
async def batch_analyze(payload: dict, db: Session = Depends(get_db)):
    """批量智能分析多个文档。

    请求体：{"doc_ids": [1,2,3], "extract_kp": true, "extract_questions": true}
    """
    doc_ids = payload.get("doc_ids") or []
    if not doc_ids:
        raise HTTPException(status_code=400, detail="缺少 doc_ids")

    extract_kp = payload.get("extract_kp", True)
    extract_questions = payload.get("extract_questions", True)

    from services.document_analyzer import batch_analyze_documents
    from services.ai_service import AIService

    ai = AIService(db)
    results = await batch_analyze_documents(
        db, doc_ids, ai,
        extract_kp=extract_kp,
        extract_questions=extract_questions,
    )

    total_kp = sum(r.get("knowledge_points", 0) for r in results)
    total_q = sum(r.get("questions", 0) for r in results)
    return {
        "total": len(results),
        "total_knowledge_points": total_kp,
        "total_questions": total_q,
        "results": results,
        "message": f"批量分析完成：{total_kp}个知识点，{total_q}道题目",
    }


# --------------------------------------------------------------------------- #
# V3.0 题目预览与人工编辑（先预览，确认后入库）
# --------------------------------------------------------------------------- #
@router.post("/{doc_id}/preview-questions")
async def preview_questions(doc_id: int, db: Session = Depends(get_db)):
    """预览文档中的题目（AI识别但不入库，供人工编辑）。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.content:
        raise HTTPException(status_code=400, detail="文档尚未解析")

    from services.document_analyzer import smart_chunk_text, QUESTION_EXTRACT_PROMPT
    from services.ai_service import AIService
    import json

    chunks = smart_chunk_text(doc.content)
    ai = AIService(db)

    preview_questions = []
    existing_contents = set()

    # 全局 25s 截止：配合 TimeoutGuardMiddleware（写请求 60s）保证接口必返，
    # 超时后剩余分块不再处理（预览为 best-effort，全量识别走 kb-import/scan）。
    import time
    _deadline = time.monotonic() + 25
    for chunk in chunks:
        if time.monotonic() > _deadline:
            break
        try:
            # AI 识别带超时保护：云端 Key 未配置或本地模型不可用时，单块 6s 即降级，
            # 避免整接口 504（V9 收尾修复：AI 不可用不再挂起）。
            import asyncio
            result = await asyncio.wait_for(
                ai.chat([
                    {"role": "system", "content": "你是题库建设专家，只返回JSON。"},
                    {"role": "user", "content": QUESTION_EXTRACT_PROMPT.format(content=chunk["text"][:6000])}
                ]),
                timeout=2,
            )
            text = result.get("content", "")
            start = text.find("[")
            end = text.rfind("]") + 1
            if start < 0 or end <= start:
                continue
            questions = json.loads(text[start:end])

            for q_data in questions:
                content = (q_data.get("content") or "").strip()
                if not content or len(content) < 10:
                    continue
                content_key = content[:100]
                if content_key in existing_contents:
                    continue

                # V3.0 强制后处理：过滤异常选项
                options = q_data.get("options") or []
                if not isinstance(options, list):
                    options = []
                metadata_prefixes = ["答案", "答：", "参考答案", "解析", "分析", "详解",
                                     "科目", "学科", "分类", "知识点", "考点", "章节",
                                     "难度", "来源", "题型", "正确答案"]
                cleaned_options = []
                for opt in options:
                    opt_str = str(opt).strip()
                    if not opt_str or any(opt_str.startswith(p) for p in metadata_prefixes):
                        continue
                    cleaned_options.append(opt_str)
                if len(cleaned_options) > 6:
                    cleaned_options = cleaned_options[:4]

                # 答案校验
                answer = (q_data.get("answer") or "").strip()
                q_type = (q_data.get("question_type") or "single").lower()
                if q_type in ("single", "multiple") and cleaned_options:
                    import re
                    answer_match = re.search(r'[A-E]', answer.upper())
                    answer = answer_match.group() if answer_match else "A"

                preview_questions.append({
                    "content": content[:5000],
                    "options": cleaned_options,
                    "answer": answer[:500],
                    "analysis": (q_data.get("analysis") or "")[:2000],
                    "question_type": q_type[:50],
                    "difficulty": min(5, max(1, int(q_data.get("difficulty", 3)))),
                    "source": (q_data.get("source") or f"文档提取：{doc.file_name}")[:200],
                    "subject": (doc.subject or "其他")[:50],
                    "chapter": (chunk.get("heading") or "")[:200],
                    "selected": True,  # 默认选中，用户可取消
                })
                existing_contents.add(content_key)
        except Exception as e:
            # AI 不可用/超时降级：本地正则引擎识别（纯本地、无 AI 依赖，保证接口可用）
            try:
                from services.qbank_builder import extract_questions as _regex_extract
                for _q in _regex_extract(chunk["text"][:6000]):
                    _content = (_q.get("content") or "").strip()
                    if not _content or len(_content) < 10:
                        continue
                    _ck = _content[:100]
                    if _ck in existing_contents:
                        continue
                    _opts = _q.get("options") or []
                    if not isinstance(_opts, list):
                        _opts = []
                    _qt = (_q.get("question_type") or "single").lower()
                    preview_questions.append({
                        "content": _content[:5000],
                        "options": [str(o).strip()[:120] for o in _opts if str(o).strip()][:6],
                        "answer": ((_q.get("answer") or "").strip())[:500],
                        "analysis": (_q.get("analysis") or "")[:2000],
                        "question_type": _qt[:50],
                        "difficulty": min(5, max(1, int(_q.get("difficulty", 3) or 3))),
                        "source": f"文档提取：{doc.file_name}",
                        "subject": (doc.subject or "其他")[:50],
                        "chapter": (chunk.get("heading") or "")[:200],
                        "selected": True,
                    })
                    existing_contents.add(_ck)
            except Exception:
                pass
            continue

    return {
        "doc_id": doc_id,
        "doc_name": doc.file_name,
        "total": len(preview_questions),
        "questions": preview_questions,
        "message": f"预览识别到 {len(preview_questions)} 道题目，请人工审核后确认入库",
    }


@router.post("/{doc_id}/confirm-questions")
async def confirm_questions(doc_id: int, payload: dict, db: Session = Depends(get_db)):
    """确认入库用户编辑后的题目。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    from models import QuizQuestion

    questions = payload.get("questions") or []
    if not questions:
        raise HTTPException(status_code=400, detail="没有题目需要入库")

    # 去重
    existing_contents = {
        (q.content or "")[:100] for q in db.query(QuizQuestion).filter(
            QuizQuestion.source.like(f"%{doc.file_name}%")
        ).all()
    }

    imported = 0
    skipped = 0
    for q_data in questions:
        if not q_data.get("selected", True):
            skipped += 1
            continue

        content = (q_data.get("content") or "").strip()
        if not content or len(content) < 10:
            skipped += 1
            continue

        content_key = content[:100]
        if content_key in existing_contents:
            skipped += 1
            continue

        q = QuizQuestion(
            content=content[:5000],
            options=q_data.get("options") or [],
            answer=(q_data.get("answer") or "")[:500],
            analysis=(q_data.get("analysis") or "")[:2000],
            subject=(q_data.get("subject") or doc.subject or "其他")[:50],
            chapter=(q_data.get("chapter") or "")[:200],
            knowledge_point="",
            difficulty=min(5, max(1, int(q_data.get("difficulty", 3)))),
            source=(q_data.get("source") or f"文档提取：{doc.file_name}")[:200],
            question_type=(q_data.get("question_type") or "single")[:50],
        )
        db.add(q)
        existing_contents.add(content_key)
        imported += 1

    db.commit()
    return {
        "doc_id": doc_id,
        "imported": imported,
        "skipped": skipped,
        "total": len(questions),
        "message": f"确认入库：成功 {imported} 道，跳过 {skipped} 道",
    }
