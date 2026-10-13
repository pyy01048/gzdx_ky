"""文档路由。"""

import mimetypes
import os
import re
from urllib.parse import quote
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from database import get_db, BASE_DIR
from models import Document, KnowledgePoint, KnowledgeChunk
from services.doc_naming import apply_display_name
from services.smart_ingest import gate_for_write
from services.quiz_content_gate import admit as gate_admit
from services.quiz_content_gate import gate_log_summary
from services.delete_guard import require_physical_delete_enabled
from services import quiz_dedupe as _quiz_dedupe
from services import subject_vocab

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


# --------------------------------------------------------------------------- #
# 原文文件读取（浏览器内预览 + 一键下载）
# --------------------------------------------------------------------------- #
#: 允许读取的根目录：路径必须落在其中之一，否则一律拒绝（防遍历）。
#: 实测 2611 篇里在盘的 1857 篇只分布在两处 —— backend-main-fastapi 373 篇、
#: knowledge_base 1484 篇，故白名单就列这两个；不把整个项目根放进来，
#: 免得 kaoyan.db / 模型权重这类文件有机会被这个端点读出去。
#: 测试通过 monkeypatch 本常量换成临时目录。
LOCAL_FILE_ROOTS = [os.path.realpath(BASE_DIR)]
_KB_ROOT = os.path.realpath(os.path.join(BASE_DIR, os.pardir, "knowledge_base"))
if os.path.isdir(_KB_ROOT):
    LOCAL_FILE_ROOTS.append(_KB_ROOT)

#: 分块大小：单次驻留内存的上限，908 MB 的原书也不会整读
_STREAM_CHUNK = 1 << 20


def _media_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _inside_roots(abspath: str) -> bool:
    return any(abspath == root or abspath.startswith(root + os.sep)
               for root in LOCAL_FILE_ROOTS)


def _resolve_local_file(doc: Document, *, strict: bool = False):
    """返回 (可读绝对路径, 不可读原因)。原因写成给用户看的话，用于 404 detail。

    `strict=True`（真要打开文件时）额外做 realpath 校验，挡符号链接逃逸；
    列表页只判断按钮可用性，用字符串级的 abspath —— 实测 1934 篇
    abspath+isfile 10.4 ms、realpath 388.6 ms，差 37 倍。
    """
    raw = (doc.file_path or "").strip()
    if not raw:
        return None, "该文档没有登记原文路径，只有解析文本"
    if not os.path.isabs(raw):
        # IMA 导入的 238 篇把媒体号写在 file_path 上，本地从来没有这个文件
        media = getattr(doc, "ima_media_id", None) or raw[:32]
        return None, f"原文在外部知识库（媒体号 {media}），本地未下载该文件"
    abspath = os.path.abspath(raw)
    if not _inside_roots(abspath):
        return None, "原文路径越出允许目录，已拒绝读取"
    if not os.path.isfile(abspath):
        return None, "原文文件已不在磁盘上（可能被移动或删除）"
    if strict:
        real = os.path.realpath(abspath)
        if not _inside_roots(real):
            return None, "原文经符号链接指向了允许目录之外，已拒绝读取"
    return abspath, None


def _content_disposition(name: str, doc_id: int, disposition: str) -> str:
    """RFC 5987：中文名走 filename*，filename 只放 ASCII 兜底。"""
    fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip() or f"document_{doc_id}"
    return (f"{disposition}; filename=\"{fallback}\"; "
            f"filename*=UTF-8''{quote(name, safe='')}")


def _parse_range(header: str, size: int):
    """解析单区间 Range。返回 (start, length)，越界返回 None 交由调用方发 416。"""
    m = re.match(r"^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$", header or "")
    if not m or size == 0:
        return 0, size
    first, last = m.group(1), m.group(2)
    if first == "" and last == "":
        return 0, size
    if first == "":
        # 后缀区间：最后 N 字节；bytes=-0 是不可满足区间
        n = min(int(last), size)
        return None if n <= 0 else (size - n, n)
    start = int(first)
    if start >= size:
        return None
    end = int(last) if last else size - 1
    end = min(end, size - 1)
    return start, end - start + 1


def _iter_file(path: str, start: int, length: int):
    with open(path, "rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            data = fh.read(min(_STREAM_CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def _file_response(doc: Document, request: Request, disposition: str):
    path, reason = _resolve_local_file(doc, strict=True)
    if path is None:
        raise HTTPException(status_code=404, detail=reason)
    size = os.path.getsize(path)
    start, length = 0, size
    status_code = 200
    range_header = request.headers.get("range")
    parsed = _parse_range(range_header, size) if range_header else (0, size)
    if parsed is None:
        # 直接构造响应而不是 raise：全局异常处理器会丢掉 headers，
        # 而 416 必须带 Content-Range: bytes */size 才合 RFC 7233
        return JSONResponse(status_code=416,
                            content={"detail": f"Range 越界（文件共 {size} 字节）",
                                     "path": request.url.path},
                            headers={"Content-Range": f"bytes */{size}",
                                     "Accept-Ranges": "bytes"})
    start, length = parsed
    if range_header and length != size:
        status_code = 206
    name = doc.file_name or os.path.basename(path)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": _content_disposition(name, doc.id, disposition),
        # 重新导入会换文件，缓存住会看到旧原文
        "Cache-Control": "no-cache",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{start + length - 1}/{size}"
    return StreamingResponse(_iter_file(path, start, length),
                             status_code=status_code,
                             media_type=_media_type(path), headers=headers)


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
    stage: str = None,
    content_type: str = None,
    subject_source: str = None,
    db: Session = Depends(get_db),
):
    """文档列表（可按学科 / 资料层级 / 是否扫描件 / 备考阶段 / 内容性质 / 来源过滤）。

    新增三个筛选维度用于 IMA 知识库资料（与既有 doc_type 正交，互不影响）：
      - stage        : 初试 / 复试
      - content_type : 知识 / 试题 / 单词
      - subject_source : ima（IMA 导入）/ 其它
    """
    q = db.query(Document)
    if subject:
        # 词表对齐（docx/16 §1.5-E）：documents.subject 的写法比 knowledge_chunks.subject 多，
        # 「公共课-数学」「数模电」「408」这些在分块侧没有同名值。等值过滤会让选「数学」的人
        # 看不到 31 篇「公共课-数学」、选「数字电子技术」看不到 186 篇「数模电」。
        # 归一只发生在查询层：把原值展开成 in_，库里一个字段都不改（改库要逐科人批）。
        group = subject_vocab.doc_subject_group(subject)
        q = q.filter(Document.subject.in_(list(group)))
    if doc_type:
        # raw 原始层 / note 加工层 / index 索引层
        q = q.filter(Document.doc_type == doc_type)
    if ocr_only:
        q = q.filter(Document.ocr_used == True)  # noqa: E712
    if stage:
        q = q.filter(Document.stage == stage)
    if content_type:
        q = q.filter(Document.content_type == content_type)
    if subject_source:
        q = q.filter(Document.subject_source == subject_source)
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
        local_path, local_note = _resolve_local_file(d)
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
            # IMA 导入相关：备考阶段 / 内容性质 / 来源 / IMA 目录（前端据此分栏展示）
            "stage": d.stage,
            "content_type": d.content_type,
            "subject_source": d.subject_source,
            "folder_path": d.folder_path,
            "ima_media_id": d.ima_media_id,
            # 原文可不可读在前端就要知道：置灰按钮 + 说明原因，比点了报 404 好
            "has_local_file": local_path is not None,
            "local_file_note": local_note,
            "summary": (d.content or "")[:200],
            "content_length": len(d.content or ""),
            "chunk_count": chunk_counts.get(d.id, 0),
            "created_at": d.created_at.isoformat() if d.created_at else None,
        })
    return result


@router.get("/subjects")
async def list_subjects(db: Session = Depends(get_db)):
    """学科分类统计（文档数 + 分块数）。

    M0-4 学科统一收口：数据源改为 `services.subject_registry` 唯一聚合器，
    既有字段（``name / document_count / chunk_count``）口径不变；§1.5-E 只**新增**
    ``aliases / alias_of / merged_document_count`` 和顶层 ``merged_count_note``，
    老前端忽略新字段即可，不需要改动。

    口径说明：科目集合以 ``subject_config`` 字典为权威，附带"字典未登记但
    业务表出现过"的科目；文档数为 0 的字典科目也会列出（便于提示"该科还没资料"）。
    """
    from services import subject_registry, subject_vocab

    data = subject_registry.list_subjects(db)["subjects"]
    # 文档侧原值分组计数：组内各原值互斥（一篇文档只有一个 subject 写法），
    # 所以「折叠后的合并文档数」就是逐原值求和，不会重复计数。
    from sqlalchemy import func
    doc_counts = dict(
        db.query(Document.subject, func.count(Document.id))
        .group_by(Document.subject).all()
    )
    subjects = []
    for s in data:
        group = subject_vocab.doc_subject_group(s["subject"])
        subjects.append({
            "name": s["subject"],
            "document_count": s["document_count"],
            "chunk_count": s["chunk_count"],
            # 只增字段：老前端忽略即可。aliases 是折进本行的文档侧写法，alias_of 说明
            # 本行自己只是某个规范名的别名；merged_document_count 才是选这科能拿到的篇数。
            "aliases": [g for g in group if g != s["subject"]],
            "alias_of": subject_vocab.alias_parent(s["subject"]),
            "merged_document_count": sum(int(doc_counts.get(g, 0) or 0) for g in group),
        })
    # 兼容旧排序：文档数降序（字典项 document_count=0 自然沉底）
    subjects.sort(key=lambda it: (-it["document_count"], it["name"]))

    doc_total = db.query(Document).count()
    chunk_total = db.query(KnowledgeChunk).count()
    return {
        "total_documents": doc_total,
        # 折叠后的行之间会重叠（「数模电」同时计入数电和模电），
        # 所以各科 merged_document_count 不能相加，总量只看 total_documents。
        "merged_count_note": "merged_document_count 含别名/合并口径折叠，跨行相加会重复计数",
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

    # 导入时预清洗行内水印（东坡哥微信/haodongpo、公众号/QQ群/淘宝店等）：
    # 与存量清洗脚本 scripts/clean_document_watermarks.py 同源（services.extraction_noise），
    # 在**质量闸门之前**做，避免水印文本干扰空正文/乱码判定。
    from services.kb_service import preclean_watermarks
    content_text, _wm_dropped, _wm_mixed = preclean_watermarks(content_text)

    # 质量闸门：空正文/占位提示/乱码/二进制残留/同文重复一律拒绝。
    # 拒绝时**不覆盖** doc.content（老正文可能仍有用），状态置 failed 并把原因
    # 透给前端 —— 静默写进库才是这一轮审计里最难发现的那种损坏。
    verdict = gate_for_write(db, content_text, path=doc.file_path or "", doc_id=doc.id)
    if not verdict["ok"]:
        doc.index_status = "failed"
        db.commit()
        raise HTTPException(status_code=422,
                            detail="质量闸门拒绝入库：" + "；".join(verdict["reasons"]))

    doc.content = content_text
    doc.parse_progress = 0.5
    # #27 按内容定显示名：必须在分块入库前改，chunk.doc_name 才会带新名
    apply_display_name(db, doc, content_text)
    db.commit()

    # —— 知识库闭环（P0-1）：文本 -> 分块 -> knowledge_chunks + FTS —— #
    # 这一步让上传的文档真正进入 RAG 知识库，可被 AI 检索引用。
    from services.kb_service import (detect_doc_meta, has_searchable_chunks,
                                     ingest_document)
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

    # 状态口径：indexed 必须等于「库里真有可检索的分块」。
    # 以前这里无条件写 indexed，分块失败只 print 一句就吞掉，
    # 库里于是攒出「UI 显示已入库、检索永远搜不到」的文档（实测存量 89 篇）。
    doc.index_status = "indexed" if has_searchable_chunks(db, doc.id) else "failed"
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
        # ===== 入库前内容闸门（docx/16 §1.5-H）=====
        # 原先这条路径把模型返回的 JSON 直接 db.add，不过 quiz_content_gate，
        # 也不填 subject，是「题目格式没有统一标准」的两个源头之一。
        rejected_by_gate: dict[str, int] = {}
        parse_error = ""
        questions: list = []
        try:
            text = result["content"]
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                if isinstance(parsed, list):
                    questions = parsed
                else:
                    parse_error = "模型返回的不是 JSON 数组"
            else:
                parse_error = "模型输出中找不到 JSON 数组"
        except (json.JSONDecodeError, ValueError) as exc:
            parse_error = f"JSON 解析失败：{exc}"

        src = f"文档生成：{doc.file_name}"[:200]
        seen: set[str] = set()
        candidates: list[tuple[str, list, dict]] = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            stem = (q.get("content") or "").strip()
            opts = q.get("options") or []
            ok, reason = gate_admit(
                stem,
                options=opts,
                answer=q.get("answer"),
                source=src,
            )
            if not ok:
                rejected_by_gate[reason] = rejected_by_gate.get(reason, 0) + 1
                continue
            key = stem[:100]
            if key in seen:
                continue
            seen.add(key)
            candidates.append((stem, opts if isinstance(opts, list) else [], q))

        questions_created = 0
        if candidates:
            for stem, opts, q in candidates:
                db.add(QuizQuestion(
                    content=stem[:5000],
                    options=opts,
                    answer=(q.get("answer") or "")[:500],
                    analysis=(q.get("analysis") or "")[:2000],
                    subject=(doc.subject or "其他")[:50],
                    knowledge_point="",
                    difficulty=3,
                    source=src,
                    question_type="single",
                    ai_generated=True,
                    verified=False,
                ))
            try:
                db.commit()
                questions_created = len(candidates)
            except Exception:
                db.rollback()
                questions_created = 0
                parse_error = parse_error or "题目写入失败，已回滚"

        return {
            "questions_created": questions_created,
            "model_returned": len(questions),
            "rejected_by_gate": rejected_by_gate,
            "parse_error": parse_error,
            "preview": result["content"][:500],
            "message": (
                f"从文档生成了 {questions_created} 道题目"
                + (f"（闸门拦截 {sum(rejected_by_gate.values())} 条）" if rejected_by_gate else "")
            ),
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

    # 物理删除闸门：knowledge_chunks 的 DELETE 不可逆。删文档会连带清空
    # 全部分块，是最容易造成大规模数据损失的路径，必须显式放行。
    require_physical_delete_enabled("knowledge_chunks")
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


@router.get("/{doc_id}/raw")
async def get_document_raw(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """原文文件字节流（浏览器内预览用，支持 Range）。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _file_response(doc, request, "inline")


@router.get("/{doc_id}/download")
async def download_document_raw(doc_id: int, request: Request, db: Session = Depends(get_db)):
    """原文文件下载（中文名按 RFC 5987 编码，走 attachment）。"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _file_response(doc, request, "attachment")


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
    from services.kb_service import has_searchable_chunks, ingest_document, preclean_watermarks

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

            # 导入时预清洗行内水印（与单篇解析同源，见 services.extraction_noise）
            content_text, _wm_dropped, _wm_mixed = preclean_watermarks(content_text)

            verdict = gate_for_write(db, content_text, path=doc.file_path or "", doc_id=doc.id)
            if not verdict["ok"]:
                # 批量任务不能因一篇坏文件整体失败：跳过写入、标 failed、原因进结果
                doc.index_status = "failed"
                doc.parse_progress = 1.0
                db.commit()
                results.append({"id": doc.id, "file_name": doc.file_name,
                                "status": "rejected",
                                "error": "；".join(verdict["reasons"])})
                continue

            doc.content = content_text
            doc.parse_progress = 0.5
            apply_display_name(db, doc, content_text)
            db.commit()

            # 分块入库
            chunk_count = 0
            try:
                chunk_count = ingest_document(db, doc, replace=True)
            except Exception as e:
                print(f"[kb] 文档 {doc.id} 分块失败: {e}")

            # indexed 的口径 = 库里真有分块；本轮返回 0 但旧块还在，仍算已入库
            indexed = has_searchable_chunks(db, doc.id)
            doc.index_status = "indexed" if indexed else "failed"
            doc.parse_progress = 1.0
            db.commit()
            if indexed:
                parsed_count += 1
            results.append({"id": doc.id, "file_name": doc.file_name, "chunks": chunk_count,
                            "status": "success" if indexed else "no_chunks"})
        except Exception as e:
            doc.index_status = "failed"
            db.commit()
            results.append({"id": doc.id, "file_name": doc.file_name, "error": str(e), "status": "failed"})

    rejected = sum(1 for r in results if r.get("status") == "rejected")
    return {
        "parsed": parsed_count,
        "rejected": rejected,
        "total": len(pending_docs),
        "results": results,
        "message": f"批量解析完成，成功 {parsed_count}/{len(pending_docs)}"
                   + (f"，质量闸门拒绝 {rejected} 篇" if rejected else ""),
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
                    # 统一剥离选项自带字母前缀（A. / B、 / C: 等），避免与前端自动编号重复
                    opt_str = re.sub(r'^[A-F][\.、:：]\s*', '', opt_str)
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
                for _q in _regex_extract(chunk["text"][:6000],
                                         source_hint=doc.file_name or ""):
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

    # ===== 去重 =====
    # 旧逻辑只用题干前 100 字，且**只在source 含当前文档名的行里**比对
    #（existing_contents 的来源）。同一道题承载在另一篇文档里时匹配不到 →
    # 同一题入库两次，是跨来源重复的根因。
    # 现在叠加一层**跨来源指纹判重**（services/quiz_dedupe），命中即合并溯源、
    # 不再插入；原来源内判重保留为快速路径。开关：QUIZ_DEDUPE_CROSS_SOURCE（默认开）。
    existing_contents = {
        (q.content or "")[:100] for q in db.query(QuizQuestion).filter(
            QuizQuestion.source.like(f"%{doc.file_name}%")
        ).all()
    }
    _cross_dedupe = _quiz_dedupe.dedupe_enabled()
    _dd_index = (
        _quiz_dedupe.build_index_from_db(db) if _cross_dedupe else None
    )
    _dd_stats = _quiz_dedupe.DedupeStats()

    imported = 0
    skipped = 0
    merged_dup = 0
    rejected_by_gate: dict[str, int] = {}
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

        # ===== 入库前内容闸门（防讲义/PPT 正文混入题库）=====
        _src = (q_data.get("source") or f"文档提取：{doc.file_name}")[:200]
        _ok, _reason = gate_admit(
            content,
            options=q_data.get("options") or [],
            answer=q_data.get("answer"),
            source=_src,
        )
        if not _ok:
            rejected_by_gate[_reason] = rejected_by_gate.get(_reason, 0) + 1
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
            source=_src,
            question_type=(q_data.get("question_type") or "single")[:50],
        )
        # ===== 跨来源判重（入库前最后一道闸）=====
        # 命中则不插入：把本源合并进已有题的溯源，并补齐缺失字段。
        _decision = _quiz_dedupe.decide_insert(
            db, content, _src, _dd_index,
            answer=q_data.get("answer"),
            analysis=q_data.get("analysis"),
            options=q_data.get("options"),
            stats=_dd_stats,
        )
        if not _decision.is_insert:
            merged_dup += 1
            continue

        db.add(q)
        existing_contents.add(content_key)
        imported += 1

    db.commit()
    if rejected_by_gate:
        gate_log_summary()
    return {
        "doc_id": doc_id,
        "imported": imported,
        "skipped": skipped,
        "total": len(questions),
        "merged_cross_source": merged_dup,
        "cross_source_dedupe": _cross_dedupe,
        "dedupe_stats": _dd_stats.as_dict(),
        "message": f"确认入库：成功 {imported} 道，跳过 {skipped} 道，"
                   f"跨来源合并 {merged_dup} 道",
    }


# --------------------------------------------------------------------------- #
# chunk 三层标签（docx/14 阶段 A：三路融合打标 + 聚合 + 人工修正回流）
# --------------------------------------------------------------------------- #
@router.post("/{doc_id}/classify-chunks")
async def classify_doc_chunks(
    doc_id: int,
    use_llm: bool = True,
    only_unlabeled: bool = False,
    background: bool = True,
    background_tasks: BackgroundTasks = None,  # noqa: B008
    db: Session = Depends(get_db),
):
    """对文档全部 chunk 跑三路融合打标。默认后台执行（LLM 兜底可能分钟级）。"""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    from services import chunk_classifier

    chunk_classifier.ensure_chunk_label_columns(db)
    if not background:
        return chunk_classifier.classify_document(
            db, doc_id, use_llm=use_llm, only_unlabeled=only_unlabeled)

    def _run():
        from database import SessionLocal
        s = SessionLocal()
        try:
            chunk_classifier.classify_document(
                s, doc_id, use_llm=use_llm, only_unlabeled=only_unlabeled)
        finally:
            s.close()

    background_tasks.add_task(_run)
    return {"doc_id": doc_id, "started": True,
            "message": "已提交后台打标，完成后用 classify-summary 查看"}


@router.get("/{doc_id}/classify-summary")
async def classify_summary(doc_id: int, db: Session = Depends(get_db)):
    """chunk 标签聚合视图：学科占比 / L3 分布 / 置信度均值 / 是否混合文档。"""
    from sqlalchemy import func
    from services import chunk_classifier

    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    rows = (
        db.query(KnowledgeChunk.subject, KnowledgeChunk.l3_content_type,
                 func.count(KnowledgeChunk.id), func.avg(KnowledgeChunk.classify_confidence))
        .filter(KnowledgeChunk.document_id == doc_id)
        .group_by(KnowledgeChunk.subject, KnowledgeChunk.l3_content_type)
        .all()
    )
    total = sum(r[2] for r in rows) or 1
    subject_shares: dict = {}
    l3_dist: dict = {}
    for subj, l3, cnt, conf in rows:
        subject_shares[subj or "未标"] = round(subject_shares.get(subj or "未标", 0) + cnt / total, 4)
        l3_dist[l3 or "未标"] = l3_dist.get(l3 or "未标", 0) + cnt
    return {
        "doc_id": doc_id,
        "doc_subject": doc.subject,
        "total_chunks": len([r for r in db.query(KnowledgeChunk.id).filter(KnowledgeChunk.document_id == doc_id).all()]),
        "subject_shares": subject_shares,
        "l3_distribution": l3_dist,
        "mixed": bool(subject_shares) and max(subject_shares.values()) < 0.85,
        "main_subject": chunk_classifier.aggregate_document(db, doc_id)["main_subject"],
    }


@router.post("/chunks/{chunk_id}/label")
async def fix_chunk_label(chunk_id: int, payload: dict, db: Session = Depends(get_db)):
    """人工修正 chunk 标签；修正样本自动回流 annotation_samples（docx/14 评估闭环）。"""
    from models import AnnotationSample
    from services.chunk_classifier import L3_TYPES, _normalize_subject

    chunk = db.get(KnowledgeChunk, chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail="分块不存在")
    l1 = _normalize_subject(str(payload.get("subject", "") or ""))
    l3 = str(payload.get("l3_content_type", "") or "").strip()
    if not l1 and "subject" in payload:
        raise HTTPException(status_code=400, detail=f"非法学科标签: {payload.get('subject')}")
    if l3 and l3 not in L3_TYPES:
        raise HTTPException(status_code=400, detail=f"非法 L3 类型: {l3}")
    if l1:
        chunk.subject = l1
    if l3:
        chunk.l3_content_type = l3
    if "l2_chapter" in payload:
        chunk.l2_chapter = str(payload["l2_chapter"] or "")[:200]
    chunk.classify_source = "manual"
    db.add(AnnotationSample(
        chunk_id=chunk_id, chunk_text=chunk.text or "",
        label_l1=chunk.subject, label_l2=chunk.l2_chapter,
        label_l3=chunk.l3_content_type,
        annotate_user=str(payload.get("user", "admin")), source="manual_fix",
    ))
    db.commit()
    # 人工修正同样要落进检索镜像：学科过滤读的是 fts/vec 的 subject 拷贝，
    # 不同步就出现"标签已改、检索照旧"（口径见 docx/14 §9.10）。
    from services.chunk_classifier import sync_mirror_subjects
    mirror = sync_mirror_subjects(db, [chunk_id])
    return {"chunk_id": chunk_id, "subject": chunk.subject,
            "l3_content_type": chunk.l3_content_type,
            "mirror_synced": mirror, "message": "已修正并回流标注集"}


# --------------------------------------------------------------------------- #
# 文档治理（学习文库 / 文档知识库）
#   · GET  /{doc_id}/export?fmt=md|txt|pdf   导出统一快照
#   · GET  /{doc_id}/snapshot                Markdown 快照预览（不落盘）
#   · POST /{doc_id}/archive                 归档源文件（走归档目录，非删除）
#   · POST /bulk                             批量（归档 / 标记删除 / 改科目 / 物理删除）
#   · POST /scan-root                        扫描 knowledge_base 根目录 → 按科目归档
# 说明：按科目归档走「先移动成功 → 再写回 DB file_path」的原子流程；断链文档
#       只统计不处理，绝不因找不到文件整体抛异常（存量 315 篇断链实测）。
# --------------------------------------------------------------------------- #


@router.get("/{doc_id}/snapshot")
async def get_document_snapshot(doc_id: int, db: Session = Depends(get_db)):
    """返回该文档的 Markdown 快照（前端详情抽屉预览用，**只读、不写盘**）。"""
    from services.kb_service import build_markdown_snapshot, snapshot_path

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    path = snapshot_path(doc.id)
    md = build_markdown_snapshot(doc)
    return {
        "id": doc_id,
        "file_name": doc.file_name,
        "subject": doc.subject,
        "snapshot_path": path,
        "snapshot_exists": os.path.isfile(path),
        "markdown": md,
        "content_length": len(doc.content or ""),
    }


@router.get("/{doc_id}/export")
async def export_document(doc_id: int, fmt: str = "md", db: Session = Depends(get_db)):
    """导出文档统一快照：fmt=md|txt|pdf。

    - md：YAML front-matter + 正文的 Markdown 快照；
    - txt：纯正文（UTF-8 BOM，方便 Windows 记事本）；
    - pdf：reportlab 渲染中文；依赖/字体不可用时**降级为 md**，并在响应头
      ``X-Export-Degraded: 1`` + 正文提示，前端据此明确告知用户（不静默失败）。
    """
    from io import BytesIO

    from services.kb_service import export_document as do_export

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if fmt not in ("md", "txt", "pdf"):
        raise HTTPException(status_code=400, detail="fmt 仅支持 md / txt / pdf")

    result = do_export(doc, fmt)
    headers = {
        "Content-Disposition": _content_disposition(result["filename"], doc.id, "attachment"),
        "Cache-Control": "no-cache",
    }
    if result.get("degraded"):
        # 非 ASCII 提示不能放 HTTP 头（latin-1 编码限制），用 ASCII 标记 + 文件名兜底
        headers["X-Export-Degraded"] = "1"
        headers["X-Export-Note"] = "pdf-deps-missing-fallback-to-md"
    return StreamingResponse(BytesIO(result["data"]), media_type=result["media_type"], headers=headers)


@router.post("/{doc_id}/archive")
async def archive_document_file(doc_id: int, db: Session = Depends(get_db)):
    """归档该文档的源文件到 knowledge_base/_archive/（默认归档而非删除）。

    走「移动文件 → 写回 file_path」；文件断链只返回原因，不报 500。
    """
    from services.kb_service import archive_source_file, ensure_write_backup

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    ensure_write_backup()
    result = archive_source_file(doc)
    if result["archived"]:
        doc.file_path = result["new_path"]
        db.commit()
        return {"id": doc_id, "archived": True, "new_path": result["new_path"],
                "message": "源文件已归档到 knowledge_base/_archive/"}
    return {"id": doc_id, "archived": False, "reason": result["reason"],
            "message": f"未归档：{result['reason']}"}


@router.post("/bulk")
async def bulk_documents(payload: dict, db: Session = Depends(get_db)):
    """批量操作文档。

    body::

        {"action": "archive"|"mark_delete"|"set_subject"|"purge",
         "doc_ids": [1,2,3],
         "subject": "数字电子技术"}   # set_subject 时必填

    行为边界（对齐 delete_guard 铁律）：``archive`` / ``mark_delete`` 只移动源文件，
    不物理删除任何数据；``purge`` 是**物理删除**，必须由环境变量
    ``KAOYAN_ALLOW_PHYSICAL_DELETE=1`` 显式开启，否则 403。
    """
    from services.delete_guard import PhysicalDeleteBlocked, require_physical_delete_enabled
    from services.kb_service import (
        archive_source_file, ensure_write_backup, soft_delete_source_file,
    )

    action = (payload.get("action") or "").strip()
    raw_ids = payload.get("doc_ids") or []
    doc_ids = [int(x) for x in raw_ids if str(x).strip()]
    if not doc_ids:
        raise HTTPException(status_code=400, detail="缺少 doc_ids")
    if action not in ("archive", "mark_delete", "set_subject", "purge"):
        raise HTTPException(status_code=400, detail="action 仅支持 archive / mark_delete / set_subject / purge")

    docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
    found = {d.id for d in docs}
    missing = [i for i in doc_ids if i not in found]

    if action == "set_subject":
        subject = (payload.get("subject") or "").strip()
        if not subject:
            raise HTTPException(status_code=400, detail="set_subject 需要 subject")
        ensure_write_backup()
        for d in docs:
            d.subject = subject
        db.commit()
        return {"action": action, "subject": subject, "updated": len(docs),
                "missing": missing, "message": f"已将 {len(docs)} 篇文档科目改为「{subject}」"}

    if action == "purge":
        # 物理删除闸门：knowledge_chunks 的 DELETE 不可逆，必须显式放行
        try:
            require_physical_delete_enabled("knowledge_chunks")
        except PhysicalDeleteBlocked as e:
            raise HTTPException(status_code=403, detail=str(e))
        ensure_write_backup()
        removed = 0
        for d in docs:
            if d.file_path and os.path.isfile(d.file_path):
                try:
                    os.remove(d.file_path)
                except OSError:
                    pass
            db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == d.id).delete()
            db.query(KnowledgePoint).filter(KnowledgePoint.document_id == d.id).delete()
            db.delete(d)
            removed += 1
        db.commit()
        return {"action": action, "purged": removed, "missing": missing,
                "message": f"已物理删除 {removed} 篇文档及其分块/知识点"}

    # archive / mark_delete 都只移动源文件，不物理删除
    ensure_write_backup()
    moved, skipped = 0, []
    for d in docs:
        if action == "mark_delete":
            result = soft_delete_source_file(d)
            if result["archived"]:
                d.file_path = result["new_path"]
                d.index_status = "deleted"
                moved += 1
            else:
                skipped.append({"id": d.id, "reason": result["reason"]})
        else:
            result = archive_source_file(d)
            if result["archived"]:
                d.file_path = result["new_path"]
                moved += 1
            else:
                skipped.append({"id": d.id, "reason": result["reason"]})
    db.commit()
    return {
        "action": action,
        "moved": moved,
        "skipped": skipped,
        "missing": missing,
        "message": (
            f"已{'标记删除' if action == 'mark_delete' else '归档'} {moved} 篇"
            + (f"，跳过 {len(skipped)} 篇（断链/文件缺失）" if skipped else "")
        ),
    }


@router.post("/scan-root")
async def scan_root(payload: dict | None = None, db: Session = Depends(get_db)):
    """扫描 knowledge_base 根目录 → 按科目归档 → 同步 DB file_path。

    body: ``{"dry_run": false}``（缺省 false，dry_run=true 时只预览不落盘）。

    ⚠️ 性能/交互：``dry_run=false`` 时**同步**执行一次全库 SQLite 备份
    （``ensure_write_backup`` → ``services/backup_service.create_backup``，走
    ``sqlite3 src.backup()``；真库实测约 639 MB、耗时 **30-40 秒**，期间该请求
    阻塞直至备份完成）。**前端必须给"正在备份，请勿关闭"的等待提示**，避免用户
    以为卡死而刷新/关闭。本轮有意**不做异步化**：异步会让"备份成功"与"开始写入"
    之间出现竞态（写入可能先于备份落盘），风险大于收益。

    Returns:
        ``{moved, skipped, broken, unclassified, errors, moved_items, ...}``。
        ``broken`` = file_path 指向知识库内但文件已不存在的文档数（**逐条实测**
        ``os.path.isfile``，非抽样估算；明细见 ``broken_items`` 前 50 条）。
    """
    from services.kb_service import ensure_write_backup, scan_root_and_archive

    dry_run = bool((payload or {}).get("dry_run"))
    if not dry_run:
        ensure_write_backup()
    report = scan_root_and_archive(db, dry_run=dry_run)
    report["message"] = (
        f"{'预览' if dry_run else '归档'}完成：移动 {report['moved']} 篇"
        f"（其中待分类 {report['unclassified']} 篇），跳过 {report['skipped']}，"
        f"断链 {report['broken']}，失败 {report['errors']}"
    )
    return report
