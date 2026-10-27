# -*- coding: utf-8 -*-
"""采集批次执行器：claim → fetch → extract → classify → 去重 → 写库。

一次性跑一批任务，返回可观测的统计：

``{"claimed", "fetched", "failed", "deduped", "pages_written",
   "notices_written", "notices_skipped", "errors": [...]}``

去重口径
--------
1. ``canonical_url`` 相同 → 同一页；
2. ``content_hash`` 相同 → 同一篇正文；
3. ``simhash64`` 汉明距离 ≤ 3 → 近似重复（同模板不同年份的公告）。

写库口径
--------
- ``crawl_pages``：正文 + 指纹（唯一键 ``canonical_url``）；
- ``kaoyan_notices``：命中分类的公告，幂等键 ``(school, title)``，已存在则跳过计数。

**依赖说明**：``crawl_pages`` / ``crawl_jobs`` / ``crawl_dead_letters`` 三张表由
ingest-pipeline 同事在 ``models.py`` 里定义。PostgreSQL 适配层（``queue_pg.py``）
落地前，:func:`run_once` 可以用内存 queue / 内存 page index 跑完整流程
（dry-run 与单测都走这条路），但**不会**去猜表结构自建表。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    select,
    text,
)
from sqlalchemy.orm import Session

from services.crawl.classifier import OTHER, classify_notice, to_db_notice_type
from services.crawl.extractor import Extracted, extract
from services.crawl.fetcher import PoliteFetcher
from services.crawl.queue import CrawlQueue, Job, _utcnow
from services.crawl.urls import canonicalize_url, content_hash, hamming_distance, simhash64

__all__ = [
    "PageRecord",
    "PageIndex",
    "MemoryPageIndex",
    "SqlitePageIndex",
    "PageWriter",
    "NullPageWriter",
    "SqlitePageWriter",
    "NoticeWriter",
    "MemoryNoticeWriter",
    "PgNoticeWriter",
    "run_once",
]


# --------------------------------------------------------------------------- #
# 记录结构
# --------------------------------------------------------------------------- #
@dataclass
class PageRecord:
    """一条抓取下来的页面（对应 ``crawl_pages`` 一行）。"""

    job_id: Optional[int]
    url: str
    canonical_url: str
    title: str = ""
    publish_date: Optional[date] = None
    html_path: Optional[str] = None
    text: str = ""
    content_hash: str = ""
    simhash: str = ""
    fetched_at: Optional[datetime] = None
    notice_type: str = ""
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "url": self.url,
            "canonical_url": self.canonical_url,
            "title": self.title,
            "publish_date": self.publish_date.isoformat() if self.publish_date else None,
            "html_path": self.html_path,
            "content_hash": self.content_hash,
            "simhash": self.simhash,
            "notice_type": self.notice_type,
            "confidence": self.confidence,
            "text_len": len(self.text or ""),
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


# --------------------------------------------------------------------------- #
# 页面索引（去重依据）
# --------------------------------------------------------------------------- #
class PageIndex:
    """已抓页面的索引，用于判重。"""

    def find_duplicate(
        self, canonical_url: str, content_hash_: str, simhash: str
    ) -> Optional[str]:  # pragma: no cover - 抽象
        raise NotImplementedError

    def add(self, record: PageRecord) -> None:  # pragma: no cover - 抽象
        raise NotImplementedError


class MemoryPageIndex(PageIndex):
    """内存索引（dry-run / 单测）。"""

    def __init__(self, *, simhash_threshold: int = 3) -> None:
        self.records: List[PageRecord] = []
        self.simhash_threshold = simhash_threshold

    def find_duplicate(self, canonical_url, content_hash_, simhash) -> Optional[str]:
        for rec in self.records:
            if canonical_url and rec.canonical_url == canonical_url:
                return rec.canonical_url
            if content_hash_ and rec.content_hash and rec.content_hash == content_hash_:
                return f"content_hash:{rec.content_hash[:12]}"
            if (
                simhash
                and rec.simhash
                and hamming_distance(rec.simhash, simhash) <= self.simhash_threshold
            ):
                return f"simhash:{rec.simhash}"
        return None

    def add(self, record: PageRecord) -> None:
        self.records.append(record)


_PAGE_META = MetaData()

_PAGES_TABLE = Table(
    "crawl_pages",
    _PAGE_META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", Integer, nullable=True),
    Column("url", String(1000), nullable=False),
    Column("canonical_url", String(1000), nullable=False, unique=True),
    Column("title", String(500), nullable=True),
    Column("publish_date", String(20), nullable=True),
    Column("html_path", String(1000), nullable=True),
    Column("text", Text, nullable=True),
    Column("content_hash", String(64), nullable=True, index=True),
    Column("simhash", String(32), nullable=True, index=True),
    Column("fetched_at", DateTime, nullable=True),
)


class SqlitePageIndex(PageIndex):
    """SQLite 版页面索引（单测用，自带建表）。"""

    def __init__(self, engine, *, create: bool = True, simhash_threshold: int = 3) -> None:
        self.engine = engine
        self.simhash_threshold = simhash_threshold
        if create:
            _PAGE_META.create_all(self.engine, checkfirst=True)

    def find_duplicate(self, canonical_url, content_hash_, simhash) -> Optional[str]:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(_PAGES_TABLE.c.canonical_url, _PAGES_TABLE.c.content_hash, _PAGES_TABLE.c.simhash)
                .where(_PAGES_TABLE.c.canonical_url == canonical_url)
                .limit(1)
            ).first()
            if row:
                return f"canonical_url:{row.canonical_url}"
            if content_hash_:
                row = conn.execute(
                    select(_PAGES_TABLE.c.canonical_url)
                    .where(_PAGES_TABLE.c.content_hash == content_hash_)
                    .limit(1)
                ).first()
                if row:
                    return f"content_hash:{row.canonical_url}"
            if simhash:
                rows = conn.execute(
                    select(_PAGES_TABLE.c.canonical_url, _PAGES_TABLE.c.simhash).limit(500)
                ).fetchall()
                for cand_url, cand_hash in rows:
                    if cand_hash and hamming_distance(cand_hash, simhash) <= self.simhash_threshold:
                        return f"simhash:{cand_url}"
        return None

    def add(self, record: PageRecord) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                _PAGES_TABLE.insert().values(
                    job_id=record.job_id,
                    url=record.url,
                    canonical_url=record.canonical_url,
                    title=record.title,
                    publish_date=record.publish_date.isoformat() if record.publish_date else None,
                    html_path=record.html_path,
                    text=record.text,
                    content_hash=record.content_hash,
                    simhash=record.simhash,
                    fetched_at=record.fetched_at,
                )
            )


# --------------------------------------------------------------------------- #
# 写入器
# --------------------------------------------------------------------------- #
class PageWriter:
    """``crawl_pages`` 写入接口。"""

    def write(self, record: PageRecord) -> bool:  # pragma: no cover - 抽象
        raise NotImplementedError


class NullPageWriter(PageWriter):
    """不写（dry-run）。"""

    def write(self, record: PageRecord) -> bool:
        return False


class SqlitePageWriter(PageWriter):
    """SQLite 版页面写入（单测用）。"""

    def __init__(self, engine, *, create: bool = True) -> None:
        self.engine = engine
        if create:
            _PAGE_META.create_all(self.engine, checkfirst=True)

    def write(self, record: PageRecord) -> bool:
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    _PAGES_TABLE.insert().values(
                        job_id=record.job_id,
                        url=record.url,
                        canonical_url=record.canonical_url,
                        title=record.title,
                        publish_date=record.publish_date.isoformat() if record.publish_date else None,
                        html_path=record.html_path,
                        text=record.text,
                        content_hash=record.content_hash,
                        simhash=record.simhash,
                        fetched_at=record.fetched_at,
                    )
                )
            return True
        except Exception:
            return False


class NoticeWriter:
    """公告写入接口。"""

    def write(
        self,
        *,
        job: Optional[Job],
        title: str,
        url: str,
        notice_type: str,
        publish_date: Optional[str],
        content: str,
        school_id: Optional[int] = None,
        school_name: Optional[str] = None,
    ) -> str:  # pragma: no cover - 抽象
        """返回 ``"written"`` 或 ``"skipped"``。"""
        raise NotImplementedError


class MemoryNoticeWriter(NoticeWriter):
    """内存写入器（dry-run / 单测）。"""

    def __init__(self) -> None:
        self.written: List[Dict[str, Any]] = []
        self.skipped: List[Dict[str, Any]] = []
        self._keys = set()

    def write(self, *, job=None, title, url, notice_type, publish_date, content,
              school_id=None, school_name=None) -> str:
        key = (school_name or f"id:{school_id}", title)
        if key in self._keys:
            self.skipped.append({"title": title, "url": url})
            return "skipped"
        self._keys.add(key)
        self.written.append(
            {
                "title": title,
                "url": url,
                "notice_type": notice_type,
                "publish_date": publish_date,
                "school_id": school_id,
                "school_name": school_name,
                "content_len": len(content or ""),
            }
        )
        return "written"


class PgNoticeWriter(NoticeWriter):
    """PostgreSQL 版公告写入（``kaoyan_notices``）。

    幂等键：``(school_name, title)``；``school_name`` 缺失时退回 ``(school_id, title)``。
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def _school_name(self, school_id: Optional[int], school_name: Optional[str]) -> Optional[str]:
        if school_name:
            return school_name
        if not school_id:
            return None
        try:
            row = self.db.execute(
                text("SELECT name FROM kaoyan_schools WHERE id = :sid"), {"sid": school_id}
            ).first()
        except Exception:
            return None
        return row[0] if row else None

    def write(self, *, job=None, title, url, notice_type, publish_date, content,
              school_id=None, school_name=None) -> str:
        resolved_name = self._school_name(school_id, school_name)
        params = {
            "title": title,
            "url": url,
            "school_id": school_id,
            "school_name": resolved_name,
            "publish_date": publish_date,
            "content": content,
            "notice_type": to_db_notice_type(notice_type),
            "source": "crawl_stack",
            "fetched_at": _utcnow().isoformat(timespec="seconds"),
            "classified_at": _utcnow().isoformat(timespec="seconds"),
        }
        if resolved_name:
            dup_sql = text(
                "SELECT id FROM kaoyan_notices "
                "WHERE title = :title AND school_name IS NOT DISTINCT FROM :school_name LIMIT 1"
            )
        else:
            dup_sql = text(
                "SELECT id FROM kaoyan_notices "
                "WHERE title = :title AND school_id IS NOT DISTINCT FROM :school_id LIMIT 1"
            )
        existing = self.db.execute(dup_sql, params).first()
        if existing:
            return "skipped"
        self.db.execute(
            text(
                "INSERT INTO kaoyan_notices "
                "(school_id, school_name, title, notice_type, publish_date, url, source, "
                " fetched_at, content, classified_at) "
                "VALUES (:school_id, :school_name, :title, CAST(:notice_type AS notice_type), "
                " :publish_date, :url, :source, :fetched_at, :content, :classified_at)"
            ),
            params,
        )
        try:
            self.db.commit()
        except Exception:  # pragma: no cover
            self.db.rollback()
            raise
        return "written"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _iso_date(value) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _default_page_index(db) -> PageIndex:
    """默认判重索引：有库用库里的 ``crawl_pages``，没库用内存。"""
    if db is None:
        return MemoryPageIndex()
    from services.crawl.queue_pg import PgPageIndex

    return PgPageIndex(db)


def _default_page_writer(db, write_pages: bool) -> PageWriter:
    """默认页面写入器：dry-run / 无库 → 不写；有库 → 写 ``crawl_pages``。"""
    if not write_pages or db is None:
        return NullPageWriter()
    from services.crawl.queue_pg import PgPageWriter

    return PgPageWriter(db)


def run_once(
    db=None,
    *,
    limit: int = 5,
    respect_robots: bool = True,
    write_pages: bool = True,
    queue: Optional[CrawlQueue] = None,
    page_index: Optional[PageIndex] = None,
    page_writer: Optional[PageWriter] = None,
    notice_writer: Optional[NoticeWriter] = None,
    attachment_pipeline=None,
    download_attachments: bool = True,
    fetcher: Optional[PoliteFetcher] = None,
    extract_fn: Callable[[str, str], Extracted] = extract,
    classify_fn: Callable[..., Any] = classify_notice,
) -> Dict[str, Any]:
    """跑一批采集任务。

    :param db: SQLAlchemy ``Session``/``Engine``；为 ``None`` 且未传 ``queue`` 时用内存队列
    :param limit: 本批最多领取多少条
    :param respect_robots: 是否遵守 robots.txt
    :param write_pages: 是否写 ``crawl_pages``
    :param attachment_pipeline: 附件下载/解析管线（见
        :class:`services.crawl.attachments.AttachmentPipeline`）；为 ``None`` 且有库时
        自动建一个（无库时不落盘）
    :param download_attachments: 是否下载附件（默认开）
    """
    the_queue = queue if queue is not None else CrawlQueue(db)
    the_fetcher = fetcher if fetcher is not None else PoliteFetcher()
    the_index = page_index if page_index is not None else _default_page_index(db)
    the_page_writer = page_writer if page_writer is not None else _default_page_writer(db, write_pages)
    the_notice_writer = notice_writer
    the_attachments = attachment_pipeline
    if the_attachments is None and db is not None and write_pages and download_attachments:
        from services.crawl.attachments import AttachmentPipeline

        the_attachments = AttachmentPipeline(
            db=db,
            fetcher=the_fetcher,
            respect_robots=respect_robots,
        )

    def _dead_letter(job, error: str, payload: Dict[str, Any]) -> None:
        """附件级失败 → 写死信（不打断整批）。"""
        try:
            the_queue.store.add_dead_letter(job, error, payload)
        except Exception as exc:  # pragma: no cover
            stats["errors"].append(f"dead_letter_error: {exc}")

    stats: Dict[str, Any] = {
        "claimed": 0,
        "fetched": 0,
        "failed": 0,
        "deduped": 0,
        "pages_written": 0,
        "notices_written": 0,
        "notices_skipped": 0,
        "attachments_downloaded": 0,
        "attachments_parsed": 0,
        "errors": [],
    }

    jobs = the_queue.claim(limit)
    stats["claimed"] = len(jobs)

    for job in jobs:
        try:
            result = the_fetcher.fetch(job.url, respect_robots=respect_robots)
        except Exception as exc:  # 抓取器自身异常也算失败
            stats["failed"] += 1
            stats["errors"].append(f"{job.url}: fetch_error: {exc}")
            the_queue.fail(job.id, f"fetch_error: {exc}")
            continue

        if result.error and result.error != "too_large":
            stats["failed"] += 1
            stats["errors"].append(f"{job.url}: {result.error}")
            the_queue.fail(job.id, result.error)
            continue

        stats["fetched"] += 1
        if result.error == "too_large":
            stats["errors"].append(f"{job.url}: too_large（已截断）")

        final_url = result.final_url or job.url
        extracted = extract_fn(result.html or "", final_url)
        title = (extracted.title or "").strip() or job.url
        notice_type, confidence = classify_fn(title, extracted.text or "")

        canonical = canonicalize_url(final_url)
        chash = content_hash(extracted.text or "")
        shash = simhash64(extracted.text or "")

        duplicate = the_index.find_duplicate(canonical, chash, shash)
        if duplicate:
            stats["deduped"] += 1
            the_queue.complete(job.id)
            continue

        record = PageRecord(
            job_id=job.id,
            url=final_url,
            canonical_url=canonical,
            title=title,
            publish_date=extracted.publish_date,
            text=extracted.text or "",
            content_hash=chash,
            simhash=shash,
            fetched_at=_utcnow(),
            notice_type=notice_type,
            confidence=float(confidence or 0.0),
        )

        # 附件：落盘 + （PDF）解析入库；附件级失败写死信，不打断整批
        if the_attachments is not None and extracted.attachments:
            try:
                artifacts = the_attachments.process(
                    html=result.html or "",
                    url=final_url,
                    attachments=extracted.attachments,
                    job=job,
                    on_error=_dead_letter,
                )
            except Exception as exc:
                artifacts = None
                stats["errors"].append(f"{final_url}: attachment_error: {exc}")
            if artifacts is not None:
                if artifacts.html_rel_path:
                    record.html_path = artifacts.html_rel_path
                for att in artifacts.attachments:
                    if att.status in ("stored", "parsed"):
                        stats["attachments_downloaded"] += 1
                    if att.status == "parsed":
                        stats["attachments_parsed"] += 1

        if write_pages and the_page_writer is not None:
            try:
                if the_page_writer.write(record):
                    stats["pages_written"] += 1
            except Exception as exc:
                stats["errors"].append(f"{final_url}: page_write_error: {exc}")

        try:
            the_index.add(record)
        except Exception as exc:
            stats["errors"].append(f"{final_url}: index_error: {exc}")

        if the_notice_writer is not None and notice_type and notice_type != OTHER:
            try:
                outcome = the_notice_writer.write(
                    job=job,
                    title=title,
                    url=final_url,
                    notice_type=notice_type,
                    publish_date=_iso_date(record.publish_date),
                    content=record.text,
                    school_id=job.school_id,
                    school_name=None,
                )
                if outcome == "written":
                    stats["notices_written"] += 1
                else:
                    stats["notices_skipped"] += 1
            except Exception as exc:
                stats["errors"].append(f"{final_url}: notice_write_error: {exc}")

        the_queue.complete(job.id)

    return stats
