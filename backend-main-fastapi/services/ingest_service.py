# -*- coding: utf-8 -*-
"""单一入库入口（C-INGEST@1）。

流程：``classify_content_kind → DocumentParser.parse → normalize_document
      → gate_for_write → 写 documents.content → 写旁路 JSON → 分块``。

* LFS 指针 ``auto_reject``，不写 content；
* ``engineering_artifact`` / ``lfs_pointer`` 不进知识库主链路（不切块）；
* ``gate_for_write`` 拒绝时不覆盖旧 content（保持现有行为）；
* 幂等：同文件重复入库产生相同 content + 旁路。

红线（C-INGEST@1 interaction semantics）：``gate_for_write(...)`` 直调形态保留
（``tests/test_ingest_gate.py`` AST 守卫认「函数内有 gate_for_write(...) 直调」）。
"""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel, Field

from models import ContentKind
from services.smart_ingest import gate_for_write

logger = logging.getLogger(__name__)

#: LFS 指针前缀（C-INGEST@1）
_LFS_POINTER_PREFIX = "version https://git-lfs.github.com/spec/v1"


class IngestResult(BaseModel):
    """入库结果（C-INGEST@1）。"""

    ok: bool
    doc_id: int
    content_kind: ContentKind = ContentKind.lecture
    normalized: bool = False
    warnings: list[str] = Field(default_factory=list)


def is_lfs_pointer(text: str) -> bool:
    """匹配 LFS 指针前缀 ``version https://git-lfs.github.com/spec/v1``（C-INGEST@1）。"""
    return bool(text) and text.lstrip().startswith(_LFS_POINTER_PREFIX)


def classify_content_kind(
    file_path: str,
    raw_content: bytes | None = None,
    text: str | None = None,
) -> ContentKind:
    """按内容/扩展名分流为四类（C-MODELS@1 ContentKind）。

    LFS 指针优先（auto_reject），其次工程产物，再次结构化数据，默认学习资料。
    """
    # LFS 指针：text 前缀或 raw_content 前缀
    if text and is_lfs_pointer(text):
        return ContentKind.lfs_pointer
    if raw_content and raw_content[:256].lstrip().startswith(_LFS_POINTER_PREFIX.encode("utf-8")):
        return ContentKind.lfs_pointer
    # 复用 normalize_service 的扩展名分流（单一源）
    from services.normalize_service import classify_content_kind as _classify

    return _classify(file_path, raw_content)


def _set_content_kind(doc, content_kind: ContentKind) -> None:
    """写 ``documents.content_kind`` 列（T5 提供，存量兼容默认 lecture）。"""
    try:
        doc.content_kind = content_kind.value
    except Exception:  # noqa: BLE001 —— 列未上线（T5 未合并）时静默跳过，不阻断入库
        pass


async def ingest_document(
    doc_id: int,
    file_path: str,
    raw_content: bytes,
    source_format: str,
) -> IngestResult:
    """单一入库入口（C-INGEST@1）。

    流程：classify → parse → normalize → gate → 写 content → 写旁路 → 分块。
    内部使用独立 DB 会话（``SessionLocal``），与调用方会话隔离；调用方在调用后
    应 ``db.expire_all()`` 或重新查询以看到写入结果。
    """
    from database import SessionLocal
    from starlette.concurrency import run_in_threadpool

    from models import Document
    from services.doc_naming import apply_display_name
    from services.kb_service import (
        has_searchable_chunks,
        preclean_watermarks,
    )
    from services.kb_service import (
        ingest_document as _kb_ingest,
    )

    warnings: list[str] = []
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            return IngestResult(ok=False, doc_id=doc_id, warnings=["document_not_found"])

        # 1. classify
        content_kind = classify_content_kind(file_path, raw_content)

        # LFS 指针：auto_reject，不写 content
        if content_kind == ContentKind.lfs_pointer:
            doc.index_status = "failed"
            doc.parse_error = "lfs_pointer_auto_reject"
            db.commit()
            return IngestResult(
                ok=False,
                doc_id=doc_id,
                content_kind=content_kind,
                warnings=["lfs_pointer_auto_reject"],
            )

        # engineering_artifact / structured_data：归一化落旁路，但不进主链路
        if content_kind in (ContentKind.engineering_artifact, ContentKind.structured_data):
            normalized = await _normalize_safely(
                file_path,
                doc_id,
                raw_content,
                warnings,
            )
            _set_content_kind(doc, content_kind)
            doc.index_status = "indexed"
            doc.parse_progress = 1.0
            db.commit()
            return IngestResult(
                ok=True,
                doc_id=doc_id,
                content_kind=content_kind,
                normalized=normalized,
                warnings=warnings,
            )

        # 2. parse（lecture 主链路）
        content_text = await _parse_content_text(file_path, raw_content, warnings)

        if not content_text or not content_text.strip():
            content_text = (
                f"[{source_format or 'unknown'} 文件，未能提取到文本内容] 文件名：{os.path.basename(file_path or '')}"
            )

        # 预清洗水印（与既有 /parse 同源）
        content_text, _wm_dropped, _wm_mixed = preclean_watermarks(content_text)

        # 3. normalize（旁路落盘）
        normalized = await _normalize_safely(file_path, doc_id, raw_content, warnings)

        # 4. gate_for_write（AST 守卫：必须直调在写 content 的同一函数体内）
        def _run_gate(_text=content_text, _path=file_path or "", _doc_id=doc_id):
            return gate_for_write(db, _text, path=_path, doc_id=_doc_id)

        verdict = await run_in_threadpool(_run_gate)
        if not verdict["ok"]:
            # gate 拒绝：不覆盖旧 content（保持现有行为）
            doc.index_status = "failed"
            doc.parse_error = "；".join(verdict["reasons"])
            db.commit()
            return IngestResult(
                ok=False,
                doc_id=doc_id,
                content_kind=content_kind,
                normalized=normalized,
                warnings=warnings + verdict["reasons"],
            )

        # 5. 写 documents.content
        doc.content = content_text
        _set_content_kind(doc, content_kind)
        doc.parse_progress = 0.5
        apply_display_name(db, doc, content_text)
        db.commit()

        # 6. 分块入库（写 knowledge_chunks + FTS，RAG 可检索）
        chunk_count = 0
        try:
            chunk_count = _kb_ingest(db, doc, replace=True)
            doc.chunk_count = chunk_count
            doc.parse_progress = 0.8
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"chunk_failed:{type(exc).__name__}:{exc}")

        # indexed 口径 = 库里真有可检索分块
        doc.index_status = "indexed" if has_searchable_chunks(db, doc.id) else "failed"
        doc.parse_progress = 1.0
        db.commit()

        return IngestResult(
            ok=True,
            doc_id=doc_id,
            content_kind=content_kind,
            normalized=normalized,
            warnings=warnings,
        )
    finally:
        db.close()


async def _normalize_safely(
    file_path: str,
    doc_id: int,
    raw_content: bytes,
    warnings: list[str],
) -> bool:
    """调 normalize_document 落旁路；失败仅记 warning，不阻断入库。"""
    from services.normalize_service import normalize_document

    try:
        await normalize_document(file_path, doc_id, raw_content)
        return True
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"normalize_failed:{type(exc).__name__}")
        return False


async def _parse_content_text(
    file_path: str,
    raw_content: bytes,
    warnings: list[str],
) -> str:
    """解析正文：有文件走 DocumentParser，无文件从 raw_content 解码。"""
    from starlette.concurrency import run_in_threadpool

    if file_path and os.path.exists(file_path):
        try:
            from services.document_parser import DocumentParser

            parser = DocumentParser()
            return await run_in_threadpool(parser.parse, file_path)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"parse_failed:{type(exc).__name__}:{exc}")
            return ""

    try:
        return (raw_content or b"").decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""
