# -*- coding: utf-8 -*-
"""附件管线：下载 → 存盘 → 解析（PDF）→ 落 ``document_pages`` / ``document_blocks``。

院校公告的价值往往在附件里（招生简章 PDF、专业目录、复试细则、名单表）。
本模块负责把 ``<a href>`` 里的附件真正带回来：

1. **下载**：复用 :class:`services.crawl.fetcher.PoliteFetcher`（robots 合规、
   同域串行、指数退避、20MB 上限），二进制模式取原始字节；
2. **存盘**：落到 ``<storage_root>/attachments/<sha1[:2]>/<sha1>/``，
   并写一份 ``manifest.json`` 记录来源 URL、相对路径、sha256、解析状态；
   存储根目录来自环境变量 ``KAOYAN_CRAWL_ROOT``，默认取仓库内的 ``data/crawl``
   （**不写死本机绝对路径**）；
3. **解析**：PDF 走知识库同一条管线
   ``services.parsers.router.route_parse(pdf_path, *, prefer, max_pages, out_dir)``，
   落库复用 ``services.ingest_pipeline.ingest_pdf``（它会建 ``documents`` 行并写
   ``document_pages`` / ``document_blocks``）；
4. **降级**：``route_parse`` / ``ingest_pipeline`` 导入失败（缺 OCR 依赖）时
   **不崩**——附件照常存盘，解析标记为 ``parse_skipped``，并写一条死信说明原因。

非 PDF 附件（doc/docx/xls/xlsx/zip）只存盘，解析留给后续文档管线。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

from services.crawl.fetcher import PoliteFetcher

logger = logging.getLogger(__name__)

__all__ = [
    "AttachmentRecord",
    "PageArtifacts",
    "AttachmentPipeline",
    "storage_root",
    "STORAGE_ROOT_ENV",
]

#: 存储根目录环境变量（可覆盖默认的 ``data/crawl``）
STORAGE_ROOT_ENV = "KAOYAN_CRAWL_ROOT"

#: 单页附件数量上限（礼貌抓取：别把人家站点当 CDN 用）
DEFAULT_MAX_FILES = 10

#: 单附件体积上限 20MB
DEFAULT_MAX_BYTES = 20 * 1024 * 1024

#: 会走 PDF 解析的扩展名
PARSEABLE_EXT = frozenset({"pdf"})

#: 附件状态
STATUS_STORED = "stored"          # 已存盘，未解析（非 PDF 或未启用解析）
STATUS_PARSED = "parsed"          # 已解析并落库
STATUS_PARSE_SKIPPED = "parse_skipped"  # 解析器不可用 / 未启用
STATUS_PARSE_FAILED = "parse_failed"    # 解析报错
STATUS_FAILED = "failed"          # 下载失败


def storage_root(root: Optional[str] = None) -> str:
    """附件存储根目录：显式入参 > 环境变量 > ``data/crawl``。"""
    if root:
        return os.path.abspath(root)
    env = os.environ.get(STORAGE_ROOT_ENV, "").strip()
    if env:
        return os.path.abspath(env)
    try:
        from core.db_session import DATA_DIR

        return os.path.join(DATA_DIR, "crawl")
    except Exception:  # pragma: no cover - core 不可用时的兜底
        return os.path.abspath(os.path.join("data", "crawl"))


@dataclass
class AttachmentRecord:
    """一个附件的处理结果。"""

    url: str
    filename: str
    ext: str
    status: str = STATUS_STORED
    path: str = ""          # 落盘绝对路径
    rel_path: str = ""      # 相对 storage root 的路径
    size: int = 0
    sha256: str = ""
    document_id: Optional[int] = None
    pages: int = 0
    blocks: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "filename": self.filename,
            "ext": self.ext,
            "status": self.status,
            "path": self.path,
            "rel_path": self.rel_path,
            "size": self.size,
            "sha256": self.sha256,
            "document_id": self.document_id,
            "pages": self.pages,
            "blocks": self.blocks,
            "error": self.error,
        }


@dataclass
class PageArtifacts:
    """一页抓取产物落盘后的位置信息。"""

    html_rel_path: str = ""
    html_path: str = ""
    manifest_rel_path: str = ""
    attachments: List[AttachmentRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "html_rel_path": self.html_rel_path,
            "manifest_rel_path": self.manifest_rel_path,
            "attachments": [a.to_dict() for a in self.attachments],
        }


#: 文件名里允许保留的字符
_ALLOWED_NAME_CHARS = set("._- ()[]（）")
#: 文件名里必须替换掉的字符（Windows 非法字符 + 路径分隔符）
_FORBIDDEN_NAME_CHARS = set('\\/:*?"<>|')


def _safe_filename(name: str, fallback: str = "attachment") -> str:
    """把远端文件名洗成安全的本地文件名（去路径、替换非法字符）。"""
    raw = (name or "").replace("\\", "/").strip()
    raw = raw.split("/")[-1]
    out = []
    for ch in raw:
        out.append(ch if (ch.isalnum() or ch in _ALLOWED_NAME_CHARS) else "_")
    cleaned = "".join(out).strip() or fallback
    return cleaned[:180]


class AttachmentPipeline:
    """公告附件的下载 / 存盘 / 解析管线。"""

    def __init__(
        self,
        *,
        root: Optional[str] = None,
        fetcher: Optional[PoliteFetcher] = None,
        db=None,
        respect_robots: bool = True,
        max_files: int = DEFAULT_MAX_FILES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        parse_pdfs: bool = True,
        max_pages: Optional[int] = None,
        parse_fn: Optional[Callable[..., Any]] = None,
        ingest_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.root = storage_root(root)
        self.fetcher = fetcher if fetcher is not None else PoliteFetcher()
        self.db = db
        self.respect_robots = respect_robots
        self.max_files = int(max_files)
        self.max_bytes = int(max_bytes)
        self.parse_pdfs = bool(parse_pdfs)
        self.max_pages = max_pages
        # 注入点（测试用假实现，避免真跑 OCR）
        self._parse_fn = parse_fn
        self._ingest_fn = ingest_fn

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    def _rel(self, path: str) -> str:
        try:
            return os.path.relpath(path, self.root).replace(os.sep, "/")
        except ValueError:  # pragma: no cover - 跨盘符
            return path

    def _page_dir(self, url: str) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return os.path.join(self.root, "pages", digest[:2], digest)

    def _attachment_dir(self, url: str) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return os.path.join(self.root, "attachments", digest[:2], digest)

    # ------------------------------------------------------------------ #
    # HTML 存盘
    # ------------------------------------------------------------------ #
    def save_html(self, html: str, url: str) -> PageArtifacts:
        """把原始 HTML 存盘，返回相对路径（供 ``crawl_pages.html_path``）。"""
        page_dir = self._page_dir(url)
        os.makedirs(page_dir, exist_ok=True)
        path = os.path.join(page_dir, "page.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html or "")
        return PageArtifacts(html_rel_path=self._rel(path), html_path=path)

    # ------------------------------------------------------------------ #
    # 主流程
    # ------------------------------------------------------------------ #
    def process(
        self,
        *,
        html: str = "",
        url: str = "",
        attachments: Optional[List[Dict[str, Any]]] = None,
        job=None,
        on_error: Optional[Callable[..., None]] = None,
    ) -> PageArtifacts:
        """处理一页：存 HTML → 下载附件 → 解析 PDF → 写清单。

        :param on_error: ``on_error(job, error, payload)``，用于把附件级失败
            记成死信（由 runner 注入队列的 ``add_dead_letter``）
        """
        artifacts = self.save_html(html, url) if html else PageArtifacts()
        targets = list(attachments or [])[: self.max_files]
        if not targets:
            return artifacts

        attach_dir = self._attachment_dir(url)
        os.makedirs(attach_dir, exist_ok=True)

        for item in targets:
            record = self._handle_one(item, attach_dir)
            artifacts.attachments.append(record)
            if record.status in (STATUS_FAILED, STATUS_PARSE_FAILED, STATUS_PARSE_SKIPPED):
                self._report(on_error, job, record, url)

        manifest_path = os.path.join(attach_dir, "manifest.json")
        payload = {
            "page_url": url,
            "created_at": _now_iso(),
            "attachments": [a.to_dict() for a in artifacts.attachments],
        }
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        artifacts.manifest_rel_path = self._rel(manifest_path)
        return artifacts

    # ------------------------------------------------------------------ #
    def _handle_one(self, item: Dict[str, Any], attach_dir: str) -> AttachmentRecord:
        url = (item or {}).get("url") or ""
        filename = _safe_filename((item or {}).get("filename") or "")
        ext = ((item or {}).get("ext") or "").lower()
        record = AttachmentRecord(url=url, filename=filename, ext=ext)
        if not url:
            record.status = STATUS_FAILED
            record.error = "empty_url"
            return record

        result = self.fetcher.fetch(url, respect_robots=self.respect_robots, binary=True)
        if result.error and result.error != "too_large":
            record.status = STATUS_FAILED
            record.error = result.error
            return record
        if not result.content:
            record.status = STATUS_FAILED
            record.error = result.error or "empty_body"
            return record

        digest = hashlib.sha256(result.content).hexdigest()
        record.sha256 = digest
        record.size = len(result.content)
        if not filename:
            filename = f"{digest[:16]}.{ext or 'bin'}"
            record.filename = filename

        path = os.path.join(attach_dir, filename)
        with open(path, "wb") as fh:
            fh.write(result.content)
        record.path = path
        record.rel_path = self._rel(path)
        record.status = STATUS_STORED
        if result.error == "too_large":
            record.error = "too_large"

        if self.parse_pdfs and ext in PARSEABLE_EXT:
            self._parse_pdf(record, url)
        return record

    def _parse_pdf(self, record: AttachmentRecord, page_url: str) -> None:
        """解析 PDF 并落 ``document_pages`` / ``document_blocks``。"""
        parse_fn = self._parse_fn
        ingest_fn = self._ingest_fn
        if parse_fn is None or ingest_fn is None:
            try:
                from services.parsers.router import route_parse

                parse_fn = parse_fn or route_parse
            except Exception as exc:
                record.status = STATUS_PARSE_SKIPPED
                record.error = f"parser_unavailable: {type(exc).__name__}: {exc}"
                return
            try:
                from services.ingest_pipeline import ingest_pdf

                ingest_fn = ingest_fn or ingest_pdf
            except Exception as exc:
                record.status = STATUS_PARSE_SKIPPED
                record.error = f"ingest_unavailable: {type(exc).__name__}: {exc}"
                return

        try:
            outcome = ingest_fn(
                self.db,
                record.path,
                max_pages=self.max_pages,
                parse_fn=parse_fn,
                write=True,
                cut_questions=False,
            )
        except ImportError as exc:
            # 解析依赖缺失（没装 OCR 引擎 / 解析模块未落地）→ 跳过解析，不崩
            record.status = STATUS_PARSE_SKIPPED
            record.error = f"parser_unavailable: {type(exc).__name__}: {exc}"
            return
        except Exception as exc:
            record.status = STATUS_PARSE_FAILED
            record.error = f"parse_error: {type(exc).__name__}: {exc}"
            logger.warning("附件解析失败 %s: %s", record.filename, exc)
            return

        record.document_id = outcome.get("document_id") if isinstance(outcome, dict) else None
        record.pages = int(outcome.get("pages") or 0) if isinstance(outcome, dict) else 0
        record.blocks = int(outcome.get("blocks") or 0) if isinstance(outcome, dict) else 0
        record.status = STATUS_PARSED
        self._mark_document_source(record)

    def _mark_document_source(self, record: AttachmentRecord) -> None:
        """给 documents 行打上"来自采集"的来源标记（便于后续清理/统计）。"""
        if not record.document_id or self.db is None:
            return
        try:
            from models import Document

            row = self.db.get(Document, record.document_id)
            if row is not None and not row.subject_source:
                row.subject_source = "crawl"
                self.db.commit()
        except Exception as exc:  # pragma: no cover - 标记失败不影响主流程
            logger.debug("打 documents.subject_source 失败: %s", exc)

    def _report(self, on_error, job, record: AttachmentRecord, page_url: str) -> None:
        if on_error is None or job is None:
            return
        try:
            on_error(
                job,
                record.error or record.status,
                {
                    "kind": "attachment",
                    "page_url": page_url,
                    "attachment_url": record.url,
                    "filename": record.filename,
                    "status": record.status,
                    "rel_path": record.rel_path,
                },
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("写附件死信失败: %s", exc)


def _now_iso() -> str:
    from utils.timeutil import naive_utc_iso

    return naive_utc_iso()


def attachment_domain(url: str) -> str:
    """附件所属域（调试用）。"""
    return urlsplit(url).netloc
