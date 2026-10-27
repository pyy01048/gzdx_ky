# -*- coding: utf-8 -*-
"""PostgreSQL 适配层：把 :mod:`services.crawl.queue` 的 store 接口接到 ORM 模型上。

依赖 ``models.CrawlJob`` / ``models.CrawlPage`` / ``models.CrawlDeadLetter``
（ingest-pipeline 同事定义）。模型没落地时导入本模块会抛
:class:`services.crawl.queue._ModelsUnavailable`，**不猜表结构、不自己建表**。

与 SQLite 版的差别
------------------
- 领取任务用 ``SELECT ... FOR UPDATE SKIP LOCKED``（PG 专有），多进程并发跑批
  时同一批任务不会被两个 worker 同时领走；
- ``crawl_pages.canonical_url`` 上有唯一约束，写入撞车时按"已存在"处理（判重）；
- ``crawl_pages.publish_date`` 是 ``Date`` 类型，写入前从 ISO 字符串转回 date。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.crawl.queue import (
    ALL_STATUSES,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Job,
    JobStore,
    _ModelsUnavailable,
    _utcnow,
)
from utils.timeutil import to_aware_utc, to_naive_utc

__all__ = ["PgJobStore", "PgPageIndex", "PgPageWriter", "load_models"]


def load_models():
    """取三个 ORM 模型；缺失时抛 :class:`_ModelsUnavailable`。"""
    try:
        from models import CrawlDeadLetter, CrawlJob, CrawlPage
    except Exception as exc:  # models 里还没有这三个类
        raise _ModelsUnavailable(
            "models.CrawlJob / CrawlPage / CrawlDeadLetter 尚未落地，"
            f"无法启用 PostgreSQL 适配层（{type(exc).__name__}: {exc}）"
        ) from exc
    return CrawlJob, CrawlPage, CrawlDeadLetter


def _as_date(value) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _as_session(db):
    """把 Session / Engine 都归一成 Session。返回 (session, 是否自建)。"""
    if isinstance(db, Session):
        return db, False
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db)(), True


class PgJobStore(JobStore):
    """``crawl_jobs`` / ``crawl_dead_letters`` 的 PostgreSQL 实现。"""

    def __init__(self, db) -> None:
        self.db, self._owns_session = _as_session(db)
        self.CrawlJob, self.CrawlPage, self.CrawlDeadLetter = load_models()
        try:
            self._is_pg = self.db.get_bind().dialect.name == "postgresql"
        except Exception:  # pragma: no cover - 极端环境
            self._is_pg = False

    # -- 内部工具 -------------------------------------------------------- #
    @staticmethod
    def _to_job(row) -> Job:
        # crawl_* 已改为 timestamptz，psycopg 读回的是 aware；Job/内存 store
        # 仍按 naive UTC 比较，边界处统一折算，避免 naive/aware TypeError。
        return Job(
            id=int(row.id),
            source_key=row.source_key,
            school_id=row.school_id,
            url=row.url or "",
            job_type=row.job_type or "notice",
            status=row.status,
            attempts=int(row.attempts or 0),
            next_run_at=to_naive_utc(row.next_run_at),
            last_error=row.last_error,
            created_at=to_naive_utc(row.created_at),
            updated_at=to_naive_utc(row.updated_at),
        )

    def _commit(self) -> None:
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    # -- 接口实现 -------------------------------------------------------- #
    def add(self, *, source_key, url, school_id, job_type, now) -> Job:
        row = self.CrawlJob(
            source_key=source_key,
            url=url,
            school_id=school_id,
            job_type=job_type,
            status=STATUS_PENDING,
            attempts=0,
            next_run_at=to_aware_utc(now),
            created_at=to_aware_utc(now),
            updated_at=to_aware_utc(now),
        )
        self.db.add(row)
        self._commit()
        self.db.refresh(row)
        return self._to_job(row)

    def find_active(self, source_key: str, url: str) -> Optional[Job]:
        stmt = (
            select(self.CrawlJob)
            .where(
                self.CrawlJob.source_key == source_key,
                self.CrawlJob.url == url,
                self.CrawlJob.status.in_([STATUS_PENDING, STATUS_FAILED, STATUS_RUNNING]),
            )
            .limit(1)
        )
        row = self.db.execute(stmt).scalars().first()
        return self._to_job(row) if row else None

    def claim(self, limit: int, now: datetime) -> List[Job]:
        stmt = (
            select(self.CrawlJob)
            .where(
                self.CrawlJob.status.in_([STATUS_PENDING, STATUS_FAILED]),
                self.CrawlJob.next_run_at <= to_aware_utc(now),
            )
            .order_by(self.CrawlJob.next_run_at.asc(), self.CrawlJob.id.asc())
            .limit(max(0, int(limit)))
        )
        if self._is_pg:
            # 多 worker 并发时跳过已被别人锁住的行
            stmt = stmt.with_for_update(skip_locked=True)
        rows = self.db.execute(stmt).scalars().all()
        claimed: List[Job] = []
        for row in rows:
            row.status = STATUS_RUNNING
            row.attempts = int(row.attempts or 0) + 1
            row.updated_at = to_aware_utc(now)
            claimed.append(self._to_job(row))
        if claimed:
            self._commit()
        return claimed

    def get(self, job_id: int) -> Optional[Job]:
        row = self.db.get(self.CrawlJob, job_id)
        return self._to_job(row) if row else None

    def update(self, job_id: int, **fields) -> Optional[Job]:
        row = self.db.get(self.CrawlJob, job_id)
        if row is None:
            return None
        for key, value in fields.items():
            if hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = to_aware_utc(_utcnow())
        self._commit()
        return self._to_job(row)

    def add_dead_letter(self, job: Job, error: str, payload: Optional[dict] = None) -> None:
        row = self.CrawlDeadLetter(
            job_id=job.id,
            url=job.url,
            source_key=job.source_key,
            error=error,
            attempts=int(job.attempts or 0),
            payload=payload or {},
            created_at=to_aware_utc(_utcnow()),
        )
        self.db.add(row)
        self._commit()

    def dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = (
            self.db.execute(
                select(self.CrawlDeadLetter)
                .order_by(self.CrawlDeadLetter.id.desc())
                .limit(max(0, int(limit)))
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": row.id,
                "job_id": row.job_id,
                "url": row.url,
                "source_key": row.source_key,
                "error": row.error,
                "attempts": row.attempts,
                "payload": row.payload or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    def counts(self) -> Dict[str, int]:
        result = {status: 0 for status in ALL_STATUSES}
        rows = self.db.execute(
            select(self.CrawlJob.status).select_from(self.CrawlJob)
        ).fetchall()
        for row in rows:
            result[row.status] = result.get(row.status, 0) + 1
        result["total"] = sum(result.get(status, 0) for status in ALL_STATUSES)
        return result


class PgPageIndex:
    """``crawl_pages`` 判重索引（PostgreSQL）。"""

    def __init__(self, db, *, simhash_threshold: int = 3) -> None:
        self.db, self._owns_session = _as_session(db)
        self.simhash_threshold = simhash_threshold
        self.CrawlJob, self.CrawlPage, self.CrawlDeadLetter = load_models()

    def find_duplicate(self, canonical_url, content_hash_, simhash) -> Optional[str]:
        model = self.CrawlPage
        if canonical_url:
            row = self.db.execute(
                select(model.canonical_url)
                .where(model.canonical_url == canonical_url)
                .limit(1)
            ).first()
            if row:
                return f"canonical_url:{row.canonical_url}"
        if content_hash_:
            row = self.db.execute(
                select(model.canonical_url)
                .where(model.content_hash == content_hash_)
                .limit(1)
            ).first()
            if row:
                return f"content_hash:{row.canonical_url}"
        if simhash:
            from services.crawl.urls import hamming_distance

            rows = self.db.execute(
                select(model.canonical_url, model.simhash).limit(500)
            ).fetchall()
            for cand_url, cand_hash in rows:
                if cand_hash and hamming_distance(cand_hash, simhash) <= self.simhash_threshold:
                    return f"simhash:{cand_url}"
        return None

    def add(self, record) -> None:
        """索引本身不做写入（写库由 :class:`PgPageWriter` 负责）。"""
        return None


class PgPageWriter:
    """``crawl_pages`` 写入（PostgreSQL）。"""

    def __init__(self, db) -> None:
        self.db, self._owns_session = _as_session(db)
        self.CrawlJob, self.CrawlPage, self.CrawlDeadLetter = load_models()

    def write(self, record) -> bool:
        model = self.CrawlPage
        row = model(
            job_id=record.job_id,
            url=record.url,
            canonical_url=record.canonical_url,
            title=(record.title or None) and record.title[:512],
            publish_date=_as_date(record.publish_date),
            html_path=record.html_path,
            text=record.text,
            content_hash=record.content_hash,
            simhash=record.simhash,
            fetched_at=to_aware_utc(record.fetched_at),
        )
        self.db.add(row)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            return False
        return True
