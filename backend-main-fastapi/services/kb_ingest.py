# -*- coding: utf-8 -*-
"""知识库快速入库机制（集各家所长：internal-kb-agent 的 inbox 自动入库 + 现有 kb_service/kb_pipeline/embedding_service）。

流程：扫描 knowledge_base/inbox 新文件
    → 解析（图片走三层 OCR 路由；PDF/TXT/DOCX/PPTX 走 DocumentParser，无文本层自动 OCR 回退）
    → 学科分类（kb_service.classify_subject）
    → 分块入库（kb_service.ingest_document → knowledge_chunks + FTS）
    → 增量向量化（embedding_service.build_all_embeddings，只补缺向量的分块）
    → 原件归档（移动到 knowledge_base/documents，按年份/科目组织）
    → 元数据记录（knowledge_base/meta/manifest.jsonl 追加）

纯新增模块；不修改表结构、不修改既有接口（红线）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import Document

# --------------------------------------------------------------------------- #
# 路径常量（一律经 services.kb_service.resolve_kb_root 推导）
# --------------------------------------------------------------------------- #
# 单一权威解析：KAOYAN_KB_ROOT > 仓库同级 knowledge_base。本模块曾自带
# ``os.environ.get("KB_ROOT", r"D:\平台\knowledge_base")`` —— 同一个目录两个环境变量、
# 其中一个是本机绝对路径，换机器即失效、测试也无法注入临时目录。
from services.kb_service import resolve_kb_root

KB_ROOT = resolve_kb_root()
INBOX_DIR = os.path.join(KB_ROOT, "inbox")
DOCUMENTS_DIR = os.path.join(KB_ROOT, "documents")
CHUNKS_DIR = os.path.join(KB_ROOT, "chunks")
META_DIR = os.path.join(KB_ROOT, "meta")
MANIFEST_PATH = os.path.join(META_DIR, "manifest.jsonl")

#: 图片类扩展名（直接走 OCR 路由）
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
#: 文本类扩展名（DocumentParser 直接解析）
TEXT_EXTS = {".txt", ".md", ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".csv", ".xlsx", ".xls", ".xlsm"}
#: 允许入库的扩展名全集
ALLOWED_EXTS = IMAGE_EXTS | TEXT_EXTS

#: 归档子目录：documents/<年份>/<科目>
SUBJECT_DIR_MAP = {
    "数学": "数学", "英语": "英语", "政治": "政治",
    "数字电子技术": "数电", "模拟电子技术": "模电", "专业课": "专业课", "真题综合": "真题",
}


def ensure_dirs() -> None:
    for d in (INBOX_DIR, DOCUMENTS_DIR, CHUNKS_DIR, META_DIR):
        os.makedirs(d, exist_ok=True)


def file_md5(file_path: str) -> str:
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest_hashes() -> Dict[str, str]:
    """读取 manifest.jsonl，返回 {md5: 原始文件名}。"""
    out: Dict[str, str] = {}
    if not os.path.exists(MANIFEST_PATH):
        return out
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("md5"):
                        out[rec["md5"]] = rec.get("file", "")
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def _append_manifest(record: dict) -> None:
    ensure_dirs()
    with open(MANIFEST_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def _parse_content(file_path: str, ocr_backend: str = "auto") -> Dict[str, Any]:
    """解析文件正文。返回 {text, engine, ocr_used}。

    - 图片 → OCRRouter.recognize_file（三层路由）
    - 其他 → DocumentParser.parse（PDF 无文本层时自带 RapidOCR 回退；保留既有解析逻辑）
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in IMAGE_EXTS:
        from services.ocr_router import get_ocr_router

        router = get_ocr_router(prefer=ocr_backend)
        result = router.recognize_file(file_path)
        return {
            "text": result.text,
            "engine": result.backend or result.engine,
            "ocr_used": result.backend or result.engine or "",
            "ocr_error": result.error,
        }

    from services.document_parser import DocumentParser

    parser = DocumentParser()
    try:
        text = parser.parse(file_path)
    except Exception as e:
        return {"text": "", "engine": "parser", "ocr_used": "", "ocr_error": f"解析失败: {e}"}

    # 关键修复（2026-10-12）：DocumentParser.parse 在失败时**返回**
    # `[解析失败 .ppt: ...]` 这样的字符串而不是抛异常，旧逻辑会把它当正文写库，
    # 造成"解析失败的内容"污染 documents（实测 .ppt/.doc 老格式全部中招）。
    # 这里显式识别该标记并按失败处理，避免脏数据入库。
    if isinstance(text, str) and text.lstrip().startswith("[解析失败"):
        return {"text": "", "engine": "parser", "ocr_used": "",
                "ocr_error": text.strip()[:200]}

    # 解析结果过短且形如错误堆栈/占位，同样拒收
    if isinstance(text, str) and len(text.strip()) < 8:
        return {"text": "", "engine": "parser", "ocr_used": "",
                "ocr_error": "解析结果为空或过短"}
    ocr_used = ""
    if ext == ".pdf" and not text:
        # 无文本层的扫描件 PDF：尝试用三层 OCR 路由逐页识别（走兜底；DocumentParser 已内置 RapidOCR，
        # 这里仅当内置结果为空时再路由更高级后端，保持解析器逻辑不被重写）
        ocr_used = "document-parser-rapidocr"
    return {"text": text, "engine": "parser", "ocr_used": ocr_used, "ocr_error": None}


# --------------------------------------------------------------------------- #
# 单文件入库
# --------------------------------------------------------------------------- #
def ingest_file(
    db: Session,
    file_path: str,
    *,
    ocr_backend: str = "auto",
    do_embeddings: bool = True,
    move_to_documents: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """快速入库单个文件。

    Returns:
        {file, status, subject, chunks, engine, ocr_used, md5, target_path, detail}
    """
    file_path = os.path.abspath(file_path)
    if not os.path.isfile(file_path):
        return {"file": file_path, "status": "failed", "detail": "文件不存在"}
    ext = os.path.splitext(file_path)[1].lower()

    # E6 入库前置校验：格式 / 尺寸 / DPI，不合格直接拒收
    from services.ingest_precheck import precheck_file

    pre = precheck_file(file_path)
    if not pre["valid"]:
        return {
            "file": file_path, "status": "invalid",
            "detail": "前置校验未通过: " + "；".join(pre["reasons"]),
            "reasons": pre["reasons"], "warnings": pre["warnings"],
            "size": pre["size"], "dpi": pre["dpi"], "ext": pre["ext"],
        }

    if ext not in ALLOWED_EXTS:
        return {"file": file_path, "status": "skipped", "detail": f"不支持的扩展名 {ext}（支持: {sorted(ALLOWED_EXTS)}）"}

    md5 = file_md5(file_path)
    known = _load_manifest_hashes()
    if md5 in known:
        return {"file": file_path, "status": "skipped", "detail": f"已入库（manifest 命中: {known[md5]}）", "md5": md5}

    # 解析
    parsed = _parse_content(file_path, ocr_backend=ocr_backend)
    text = (parsed.get("text") or "").strip()
    if not text:
        return {
            "file": file_path, "status": "failed", "detail": f"解析/OCR 未得到正文（{parsed.get('ocr_error') or '内容为空'}）",
            "engine": parsed.get("engine"), "ocr_used": parsed.get("ocr_used"), "md5": md5,
        }

    file_name = os.path.basename(file_path)
    subject = ""
    doc_type = ""
    doc_id = None
    chunks = 0

    if not dry_run:
        from services import kb_service
        from services.doc_naming import apply_display_name
        from services.smart_ingest import gate_for_write

        # 质量闸门（正文全等去重 + 空/占位/乱码/二进制残留）：拦下的文件
        # **根本不建 Document 行**，所以库里不会再长出重复的一份正文 + 一整套分块。
        # 状态沿用 "failed"：调用方按 ok/failed/skipped/invalid 分桶，新状态会被漏计。
        verdict = gate_for_write(db, text, path=file_path)
        if not verdict["ok"]:
            return {
                "file": file_path, "status": "failed",
                "detail": "质量闸门拒绝入库：" + "；".join(verdict["reasons"]),
                "engine": parsed.get("engine"), "ocr_used": parsed.get("ocr_used"), "md5": md5,
            }

        subject = kb_service.classify_subject(file_name, text)
        doc_type = kb_service.classify_doc_type(file_name, ext.lstrip("."))

        # 1) 建 Document 记录
        doc = Document(
            file_name=file_name,
            file_path=file_path,
            file_type=ext.lstrip("."),
            content=text,
            subject=subject,
            doc_type=doc_type,
            index_status="indexed",
            ocr_used=bool(parsed.get("ocr_used")),
            structure_level="document",
        )
        db.add(doc)
        db.flush()
        apply_display_name(db, doc, text)
        doc_id = doc.id

        # 2) 分块入库（knowledge_chunks + FTS）
        chunks = kb_service.ingest_document(db, doc, replace=True)
        # 没长出分块就不算入库，别让 UI 报「已入库」而 RAG 搜不到
        doc.index_status = "indexed" if kb_service.has_searchable_chunks(
            db, doc.id) else "failed"
        db.commit()

        # 3) 增量向量化（只补缺向量的分块）
        if do_embeddings:
            try:
                from services import embedding_service

                result = asyncio.run(embedding_service.build_all_embeddings(db, force=False))
                embedding_note = result.get("built", 0)
            except Exception as e:
                embedding_note = f"向量化失败: {e}"
        else:
            embedding_note = "跳过向量化"

    # 4) 原件归档到 documents/<年份>/<科目>
    target_path = file_path
    if move_to_documents and not dry_run:
        year = time.strftime("%Y")
        sub = SUBJECT_DIR_MAP.get(subject, "未分类")
        dest_dir = os.path.join(DOCUMENTS_DIR, year, sub)
        os.makedirs(dest_dir, exist_ok=True)
        target_path = os.path.join(dest_dir, file_name)
        # 重名保护：目标已存在则加序号
        n = 1
        base, dot = os.path.splitext(file_name)
        while os.path.exists(target_path):
            target_path = os.path.join(dest_dir, f"{base}_{n}{dot}")
            n += 1
        try:
            shutil.move(file_path, target_path)
        except Exception as e:
            return {
                "file": file_path, "status": "partial", "detail": f"已入库但归档失败: {e}",
                "subject": subject, "chunks": chunks, "engine": parsed.get("engine"),
                "ocr_used": parsed.get("ocr_used"), "md5": md5, "target_path": file_path,
            }

    # 5) 元数据记录
    record = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file": file_name,
        "source": file_path,
        "md5": md5,
        "subject": subject,
        "doc_type": doc_type,
        "chunks": chunks,
        "engine": parsed.get("engine"),
        "ocr_used": parsed.get("ocr_used"),
        "doc_id": doc_id,
        "target": target_path,
        "embedding": embedding_note if not dry_run else "dry-run",
    }
    if not dry_run:
        _append_manifest(record)

    return {
        "file": file_name, "status": "ok" if not dry_run else "dry-run-ok",
        "subject": subject, "chunks": chunks,
        "engine": parsed.get("engine"), "ocr_used": parsed.get("ocr_used"),
        "md5": md5, "target_path": target_path, "detail": "入库成功" if not dry_run else "预演（未落库）",
    }


# --------------------------------------------------------------------------- #
# inbox 批量入库
# --------------------------------------------------------------------------- #
def scan_inbox(
    db: Session,
    *,
    ocr_backend: str = "auto",
    do_embeddings: bool = True,
    move_to_documents: bool = True,
    dry_run: bool = False,
    recursive: bool = False,
) -> Dict[str, Any]:
    """扫描 knowledge_base/inbox，批量快速入库。"""
    ensure_dirs()
    if not os.path.isdir(INBOX_DIR):
        return {"total": 0, "ok": 0, "failed": 0, "skipped": 0, "items": [], "detail": f"inbox 不存在: {INBOX_DIR}"}

    items: List[Dict[str, Any]] = []
    invalid_records: List[Dict[str, Any]] = []
    for root, dirs, files in os.walk(INBOX_DIR):
        # 非递归模式：只处理 inbox 顶层文件
        if not recursive and root != INBOX_DIR:
            dirs[:] = []
            continue
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            res = ingest_file(
                db, fp,
                ocr_backend=ocr_backend, do_embeddings=do_embeddings,
                move_to_documents=move_to_documents, dry_run=dry_run,
            )
            items.append(res)
            if res.get("status") == "invalid":
                invalid_records.append({
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "file": fp,
                    "reasons": res.get("reasons") or [res.get("detail", "")],
                    "size": res.get("size"),
                    "dpi": res.get("dpi"),
                    "ext": res.get("ext"),
                })

    # E6：不合格清单落盘 knowledge_base/meta/invalid_inbox.jsonl
    if invalid_records:
        os.makedirs(META_DIR, exist_ok=True)
        invalid_path = os.path.join(META_DIR, "invalid_inbox.jsonl")
        with open(invalid_path, "a", encoding="utf-8") as f:
            for rec in invalid_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    ok = [i for i in items if i.get("status") in ("ok", "dry-run-ok")]
    failed = [i for i in items if i.get("status") == "failed"]
    skipped = [i for i in items if i.get("status") == "skipped"]
    invalid = [i for i in items if i.get("status") == "invalid"]
    return {
        "total": len(items),
        "ok": len(ok),
        "failed": len(failed),
        "skipped": len(skipped),
        "invalid": len(invalid),
        "invalid_list": invalid,
        "items": items,
        "detail": "dry-run（未落库）" if dry_run else "入库完成",
    }
