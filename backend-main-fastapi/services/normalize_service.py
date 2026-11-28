# -*- coding: utf-8 -*-
"""在线归一化层（C-NORMALIZE@1）。

把任意格式文档归一化为统一 Markdown 中间态（``normalized_md`` + ``blocks[]``
+ ``meta`` + ``sanitize_audit``），落旁路 JSON
``knowledge_base/_normalized/{doc_id}.json``，供导出/检索复用。

蓝图：``pipeline/document_normalizer.py``（复用其编码级联/分派/OCR 阈值）。
本模块在其之上叠加：异步签名、结构化 ``blocks[]``、清洗审计、原子旁路落盘、
``content_kind`` 分流。不直接 import 迁移期 ETL。

红线（C-NORMALIZE@1 failure semantics）：
  * 归一化失败时 ``meta.warnings`` 记录原因，``normalized_md`` 回落为清洗后纯文本；
  * 不抛异常阻断入库；
  * 幂等：同输入同输出；
  * 旁路 JSON 写入用 ``tempfile + os.replace`` 原子替换；
  * 不写 ``documents.content``（由 ingest_service 负责）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile

from pydantic import BaseModel, Field

from models import ContentKind
from services.kb_service import resolve_kb_root

logger = logging.getLogger(__name__)

#: 旁路 JSON 落盘子目录（与既有 ``_md/{id}.md`` 同范式）
_NORMALIZED_SUBDIR = "_normalized"

#: 归一化产物版本号（结构变更时升）
_NORMALIZE_VERSION = 1

#: LFS 指针前缀（C-INGEST@1）
_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"

#: 工程产物扩展名（非学习资料，不进知识库主链路）
_ENGINEERING_EXTS: frozenset[str] = frozenset(
    {
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".go",
        ".rs",
        ".rb",
        ".sh",
        ".bat",
        ".ps1",
        ".xml",
        ".svg",
        ".lock",
        ".log",
    }
)

#: 结构化数据扩展名
_STRUCTURED_EXTS: frozenset[str] = frozenset(
    {
        ".csv",
        ".xlsx",
        ".xls",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".tsv",
    }
)

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# 蓝图同款实义字符正则（用于置信度估算）
_MEANINGFUL_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


class NormalizeResult(BaseModel):
    """归一化产物（C-NORMALIZE@1）。"""

    normalized_md: str
    blocks: list[dict] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    sanitize_audit: list[dict] = Field(default_factory=list)
    version: int = _NORMALIZE_VERSION
    content_kind: ContentKind = ContentKind.lecture


def _normalized_dir() -> str:
    """旁路 JSON 落盘目录绝对路径。"""
    return os.path.join(resolve_kb_root(), _NORMALIZED_SUBDIR)


def _normalized_path(doc_id: int) -> str:
    """某文档旁路 JSON 的绝对路径。"""
    return os.path.join(_normalized_dir(), f"{doc_id}.json")


def is_lfs_pointer_bytes(raw_content: bytes) -> bool:
    """字节级 LFS 指针判定（匹配 ``version https://git-lfs.github.com/spec/v1`` 前缀）。"""
    return bool(raw_content) and _LFS_POINTER_PREFIX in raw_content[:256]


def classify_content_kind(
    file_path: str,
    raw_content: bytes | None = None,
) -> ContentKind:
    """按扩展名 + 内容启发式分流为四类（C-MODELS@1 ContentKind）。

    LFS 指针优先（auto_reject），其次工程产物，再次结构化数据，默认学习资料。
    """
    if raw_content and is_lfs_pointer_bytes(raw_content):
        return ContentKind.lfs_pointer
    ext = os.path.splitext(file_path or "")[1].lower()
    if ext in _ENGINEERING_EXTS:
        return ContentKind.engineering_artifact
    if ext in _STRUCTURED_EXTS:
        return ContentKind.structured_data
    return ContentKind.lecture


def _split_blocks(md: str) -> list[dict]:
    """按二级标题切 ``blocks[]``（结构化分块，供导出/检索复用）。"""
    if not md:
        return []
    blocks: list[dict] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in md.split("\n"):
        if line.startswith("## "):
            if current_lines or current_heading:
                blocks.append(
                    {
                        "heading": current_heading,
                        "text": "\n".join(current_lines).strip(),
                    }
                )
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines or current_heading:
        blocks.append(
            {
                "heading": current_heading,
                "text": "\n".join(current_lines).strip(),
            }
        )
    return [b for b in blocks if b["text"]]


def _sanitize(md: str) -> tuple[str, list[dict]]:
    """轻量清洗：去零宽字符/控制字符，记录审计。"""
    audit: list[dict] = []
    if not md:
        return "", audit
    n_zw = len(_ZERO_WIDTH_RE.findall(md))
    n_ctrl = len(_CTRL_RE.findall(md))
    if n_zw:
        audit.append({"rule": "strip_zero_width", "count": n_zw})
    if n_ctrl:
        audit.append({"rule": "strip_control", "count": n_ctrl})
    out = _ZERO_WIDTH_RE.sub("", md)
    out = _CTRL_RE.sub("", out)
    return out, audit


def _write_sidecar(doc_id: int, result: NormalizeResult) -> None:
    """旁路 JSON 原子写入：``tempfile + os.replace``。失败仅记日志，不阻断。"""
    try:
        target_dir = _normalized_dir()
        os.makedirs(target_dir, exist_ok=True)
        target = _normalized_path(doc_id)
        payload = result.model_dump(mode="json")
        # tempfile 在同目录，保证 os.replace 是原子 rename（同 filesystem）
        fd, tmp = tempfile.mkstemp(prefix=f"{doc_id}.", suffix=".tmp", dir=target_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, target)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("旁路 JSON 写入失败 doc_id=%s: %s", doc_id, exc)


def _build_meta() -> dict:
    """初始化 meta 字典（统一口径，避免散落字面量）。"""
    return {
        "engine": "",
        "confidence": 0.0,
        "warnings": [],
        "encoding": "",
        "page_count": 0,
        "format": "",
    }


def _normalize_via_pipeline(file_path: str, meta: dict) -> str:
    """调蓝图 ``pipeline.document_normalizer.normalize_document`` 抽取正文。

    成功时把蓝图返回的 specific 字典合并进 meta；失败抛出由调用方兜底。
    """
    from pipeline.document_normalizer import normalize_document as _normalize

    text, specific = _normalize(file_path)
    normalized_md = text or ""
    meta.update(specific or {})
    meta.setdefault("engine", meta.get("engine") or "pipeline")
    meta["format"] = meta.get("file_type", "") or os.path.splitext(file_path or "")[1].lstrip(".").lower()
    meta.setdefault("warnings", [])
    if "pages" in meta:
        meta["page_count"] = meta["pages"]
    chars = meta.get("chars") or len(_MEANINGFUL_RE.findall(normalized_md))
    if normalized_md:
        meta["confidence"] = round(min(1.0, float(chars) / max(1, len(normalized_md))), 4)
    if "encoding" not in meta and specific:
        # 蓝图 read_text_auto 返回编码写在 engine 字段里，尽力提取
        eng = str(specific.get("engine", ""))
        if ":" in eng:
            meta["encoding"] = eng.split(":", 1)[1]
    return normalized_md


async def normalize_document(
    file_path: str,
    doc_id: int,
    raw_content: bytes,
) -> NormalizeResult:
    """归一化文档 → 统一 Markdown 中间态，落旁路 JSON。

    幂等：同输入同输出。失败时 ``meta.warnings`` 记录原因，``normalized_md``
    回落为清洗后纯文本，不抛异常阻断入库（C-NORMALIZE@1 failure semantics）。
    """
    content_kind = classify_content_kind(file_path, raw_content)
    meta = _build_meta()
    normalized_md = ""

    # LFS 指针：不归一化，直接标记并落旁路
    if content_kind == ContentKind.lfs_pointer:
        meta.update(engine="none", format="lfs_pointer", warnings=["lfs_pointer_auto_reject"])
        result = NormalizeResult(
            normalized_md="",
            blocks=[],
            meta=meta,
            sanitize_audit=[],
            content_kind=content_kind,
        )
        _write_sidecar(doc_id, result)
        return result

    # 复用 pipeline/document_normalizer.py 蓝图（编码级联/分派/OCR 阈值）
    try:
        normalized_md = _normalize_via_pipeline(file_path, meta)
    except Exception as exc:  # noqa: BLE001
        meta.setdefault("warnings", []).append(f"normalize_failed:{type(exc).__name__}:{exc}")
        # 回落：按字节解码为纯文本
        try:
            normalized_md = (raw_content or b"").decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            normalized_md = ""

    # 清洗
    normalized_md, sanitize_audit = _sanitize(normalized_md)
    if not normalized_md.strip():
        meta.setdefault("warnings", []).append("empty_normalized_md")

    blocks = _split_blocks(normalized_md)

    result = NormalizeResult(
        normalized_md=normalized_md,
        blocks=blocks,
        meta=meta,
        sanitize_audit=sanitize_audit,
        content_kind=content_kind,
    )
    # 旁路落盘（原子替换）
    _write_sidecar(doc_id, result)
    return result


async def read_normalized(doc_id: int) -> NormalizeResult | None:
    """读旁路 JSON，缺失返回 None（C-NORMALIZE@1）。"""
    path = _normalized_path(doc_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return NormalizeResult(**data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("旁路 JSON 读取失败 doc_id=%s: %s", doc_id, exc)
        return None
