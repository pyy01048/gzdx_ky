# -*- coding: utf-8 -*-
"""多格式文档 → 统一 Markdown 中间态。

支持的 11 种格式（与库中 ``documents.file_type`` 实测分布一一对应）：

===========  =====  ==========================================
格式          引擎    兜底
===========  =====  ==========================================
pdf           pdfplumber（无文本层时自动转 OCR）
docx          python-docx                       DocumentParser
doc / word    python-docx 试读 → mammoth         DocumentParser
pptx / ppt    python-pptx                        DocumentParser
txt / md      编码级联探测
image/jpg/png services.ocr_service.OCRService
===========  =====  ==========================================

两条工程纪律
------------
1. **依赖不存在不等于可以崩**：可选依赖（mammoth 等）在函数内惰性导入，
   缺失时按优先级降级到下一个引擎，并把失败原因写进 ``meta.warnings``。
   绝不静默返回空串——空串会让下游误判「文档原本就是空的」。
2. **源文件只归档不删除**：:func:`archive_source` 用 ``copy2`` 而非 ``move``；
   转换失败也不能丢原件。
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable

from .config import ARCHIVE_DIR

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "EXT_TO_TYPE",
    "normalize_document",
    "archive_source",
    "read_text_auto",
]

EXT_TO_TYPE = {
    ".pdf": "pdf", ".txt": "txt", ".md": "md",
    ".doc": "doc", ".docx": "docx",
    ".ppt": "ppt", ".pptx": "pptx",
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".bmp": "image",
    ".word": "word",
}
SUPPORTED_EXTENSIONS = frozenset(EXT_TO_TYPE)

# OCR 触发阈值：PDF 平均每页实义字符少于该值时判定为扫描件
_MIN_CHARS_PER_PAGE = 40
_MEANINGFUL_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")

Encoding = str


def read_text_auto(path: str | Path) -> tuple[str, Encoding]:
    """按编码级联读取文本，返回 ``(文本, 实际可用编码)``。

    顺序：utf-8-sig → utf-8 → gb18030 → big5 → 忽略错误兜底。
    早期导入的大量 .txt 是 GBK 编码，直接按 utf-8 读会产出满屏 U+FFFD 乱码，
    这类乱码后续任何清洗都救不回来，必须在入口就解对。
    """
    target = Path(path)
    raw = target.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore"), "utf-8/ignore"


def _md_heading(text: str, level: int = 1) -> str:
    text = (text or "").strip()
    return f"{'#' * level} {text}\n\n" if text else ""


def _normalize_plain(path: Path) -> tuple[str, dict]:
    text, enc = read_text_auto(path)
    return text, {"engine": f"read_text_auto:{enc}"}


def _normalize_md(path: Path) -> tuple[str, dict]:
    text, enc = read_text_auto(path)
    return text, {"engine": f"passthrough:{enc}"}


def _normalize_pdf(path: Path, use_ocr_fallback: bool = True) -> tuple[str, dict]:
    """PDF → Markdown。优先 pdfplumber 抽文本层，疑似扫描件时降级 OCR。"""
    import pdfplumber

    pages: list[str] = []
    meta: dict = {"engine": "pdfplumber", "pages": 0, "warnings": []}
    with pdfplumber.open(str(path)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:  # 单页失败不该炸掉整份文件
                pages.append("")
                meta["warnings"].append(f"page{idx}_extract_failed:{type(exc).__name__}")
        total_pages = len(pdf.pages)
    meta["pages"] = total_pages

    body = "\n\n".join(p.strip() for p in pages if p.strip())
    chars = len(_MEANINGFUL_RE.findall(body))
    avg = chars / max(1, total_pages)
    meta["chars"] = chars
    meta["chars_per_page"] = round(avg, 1)

    # 扫描件判定：文本层几乎为空
    if use_ocr_fallback and avg < _MIN_CHARS_PER_PAGE:
        try:
            from services.document_parser import DocumentParser

            text = DocumentParser().parse(str(path))
            if text and not text.startswith("[解析失败"):
                meta["engine"] = "pdfplumber+OCR"
                meta["ocr_used"] = True
                return text, meta
            meta["warnings"].append(f"ocr_fallback:{text[:80]}")
        except Exception as exc:
            meta["warnings"].append(f"ocr_unavailable:{type(exc).__name__}:{exc}")
    meta["ocr_used"] = False
    return body, meta


def _normalize_docx(path: Path) -> tuple[str, dict]:
    """DOCX → Markdown：段落 + 标题层级 + 表格。"""
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []
    n_tables = 0
    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name or "").lower()
        if style.startswith("heading"):
            try:
                level = max(1, min(6, int(style.replace("heading", "").strip() or 1)))
            except ValueError:
                level = 2
            parts.append(_md_heading(text, level).strip())
        else:
            parts.append(text)
    for table in doc.tables:
        n_tables += 1
        rows = []
        for row in table.rows:
            rows.append("| " + " | ".join(c.text.strip() for c in row.cells) + " |")
        if len(rows) >= 2:
            sep = "| " + " | ".join("---" for _ in rows[0].split("|")[1:-1]) + " |"
            rows.insert(1, sep)
        if rows:
            parts.append("\n".join(rows))
    return "\n\n".join(parts), {"engine": "python-docx", "tables": n_tables}


def _normalize_pptx(path: Path) -> tuple[str, dict]:
    """PPT(X) → Markdown：每页一个二级标题 + 文本框列表。"""
    from pptx import Presentation

    prs = Presentation(str(path))
    parts: list[str] = []
    n_shapes = 0
    for idx, slide in enumerate(prs.slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                text = "".join(r.text for r in para.runs).strip()
                if text:
                    lines.append(text)
                    n_shapes += 1
        if lines:
            parts.append(_md_heading(f"第 {idx} 页", 2).strip() + "\n" + "\n".join(lines))
    return "\n\n".join(parts), {"engine": "python-pptx", "slides": len(prs.slides), "text_frames": n_shapes}


def _normalize_doc(path: Path) -> tuple[str, dict]:
    """旧式 .doc / word 的尽力解析：docx 试读 → mammoth → DocumentParser。"""
    # 1) 不少 .doc 实际上是伪装扩展名的 docx
    try:
        text, meta = _normalize_docx(path)
        if text.strip():
            meta["engine"] = "python-docx(as .doc)"
            return text, meta
    except Exception:
        pass
    # 2) mammoth：把 .doc 转成语义 HTML/Markdown 的最可靠选择
    try:
        import mammoth  # type: ignore

        with path.open("rb") as fp:
            result = mammoth.convert_to_markdown(fp)
        text = result.value or ""
        warns = [str(m.message) for m in getattr(result, "messages", [])][:5]
        if text.strip():
            return text, {"engine": "mammoth", "warnings": warns}
    except ImportError:
        meta_doc_hint = "mammoth_not_installed"
    except Exception as exc:
        meta_doc_hint = f"mammoth_failed:{type(exc).__name__}"
    else:
        meta_doc_hint = "mammoth_no_output"
    # 3) 项目既有解析器兜底
    try:
        from services.document_parser import DocumentParser

        text = DocumentParser().parse(str(path))
        if text and not text.startswith("[解析失败"):
            return text, {"engine": "DocumentParser", "warnings": [meta_doc_hint]}
        return "", {"engine": "DocumentParser", "warnings": [meta_doc_hint, f"unsupported_doc:{text[:80]}"]}
    except Exception as exc:
        return "", {"engine": "none", "warnings": [meta_doc_hint, f"doc_unreadable:{type(exc).__name__}:{exc}"]}


def _normalize_image(path: Path) -> tuple[str, dict]:
    """图片 → 文本：复用项目既有 OCRService（本地 RapidOCR，数据不出网）。"""
    from services.ocr_service import OCRService

    svc = OCRService(device="cpu")
    text = svc.recognize(str(path)) or ""
    meta = {"engine": "OCRService", "ocr_used": True, "chars": len(text)}
    if not text.strip():
        meta["warnings"] = [f"ocr_empty:{svc.last_error or '未识别到文字'}"]
    return text, meta


_NORMALIZERS: dict[str, Callable[[Path], tuple[str, dict]]] = {
    "txt": _normalize_plain,
    "md": _normalize_md,
    "pdf": _normalize_pdf,
    "docx": _normalize_docx,
    "doc": _normalize_doc,
    "word": _normalize_doc,
    "pptx": _normalize_pptx,
    "ppt": _normalize_pptx,
    "image": _normalize_image,
    "jpg": _normalize_image,
    "jpeg": _normalize_image,
    "png": _normalize_image,
    "bmp": _normalize_image,
}


def normalize_document(file_path: str | Path, file_type: str | None = None) -> tuple[str, dict]:
    """把任意受支持格式转成 Markdown 文本 + 元信息。

    Args:
        file_path: 源文件绝对路径。
        file_type: 显式类型（如库里的 ``documents.file_type``）；为空则按扩展名推断。

    Returns:
        ``(markdown_text, meta)``。``meta`` 至少含 ``engine`` / ``file_type``，
        失败时含 ``error`` 与 ``warnings``，**空正文一定伴随说明**，不静默返回空。
    """
    target = Path(file_path)
    if file_type and file_type.strip():
        ftype = file_type.strip().lower()
    else:
        ftype = EXT_TO_TYPE.get(target.suffix.lower(), "")

    meta: dict = {"file_type": ftype, "source": target.name}
    if not target.exists():
        meta.update(engine="none", error="file_missing", chars=0)
        return "", meta
    if ftype not in _NORMALIZERS:
        meta.update(engine="none", error=f"unsupported_type:{ftype or 'unknown'}", chars=0)
        return "", meta

    try:
        text, specific = _NORMALIZERS[ftype](target)
    except ImportError as exc:
        meta.update(engine="none", error=f"missing_dependency:{exc}", chars=0)
        return "", meta
    except Exception as exc:
        meta.update(engine="none", error=f"{type(exc).__name__}:{exc}", chars=0)
        return "", meta

    meta.update(specific)
    meta.setdefault("chars", len(_MEANINGFUL_RE.findall(text)))
    if not text.strip():
        meta.setdefault("warnings", []).append("empty_result")
    return text, meta


def archive_source(file_path: str | Path, dest_root: str | Path | None = None) -> dict:
    """把源文件复制到归档目录（**复制，绝不移动/删除**）。

    Args:
        file_path: 源文件。
        dest_root: 归档根目录，默认 :data:`config.ARCHIVE_DIR`。

    Returns:
        含 ``archived`` / ``archive_path`` / ``reason`` 的结果字典。
    """
    src = Path(file_path)
    root = Path(dest_root) if dest_root is not None else ARCHIVE_DIR
    if not src.exists():
        return {"archived": False, "archive_path": "", "reason": "file_missing"}
    dest = root / src.name
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size == src.stat().st_size:
            return {"archived": True, "archive_path": str(dest), "reason": "already_archived"}
        shutil.copy2(src, dest)
        return {"archived": True, "archive_path": str(dest), "reason": "copied"}
    except OSError as exc:
        return {"archived": False, "archive_path": "", "reason": f"{type(exc).__name__}:{exc}"}
