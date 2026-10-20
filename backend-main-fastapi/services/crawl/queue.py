# -*- coding: utf-8 -*-
"""采集任务队列：状态机 + 退避重排 + 死信。

状态机
------
``pending``（新建） → ``running``（被领取） → ``done``（成功）
                                        ↘ ``failed``（失败，按 attempts 退避重排）
``failed`` 累计到 ``attempts >= max_attempts`` → ``dead``，并写死信表。

退避规则：``next_run_at = now + 2 ** attempts 分钟``（attempts 为已尝试次数）。

持久化
------
``crawl_jobs`` / ``crawl_dead_letters`` 两张表由 **ingest-pipeline 同事在
``models.py`` 里定义**，本模块**不重复定义模型**：

- :class:`MemoryJobStore` —— 纯内存，测试与 dry-run 用；
- :class:`SqliteJobStore` —— 自带建表（仅 SQLite），单测用；
- PostgreSQL 适配层（``queue_pg.py``）等模型落地后再补，在此之前
  :func:`open_store` 会抛 :class:`_ModelsUnavailable` 并说明原因。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    select,
    update,
)
from sqlalchemy.engine import Engine

__all__ = [
    "Job",
    "JobStore",
    "MemoryJobStore",
    "SqliteJobStore",
    "CrawlQueue",
    "open_store",
    "_ModelsUnavailable",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_DEAD",
]

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_DEAD = "dead"

#: 全部状态（含死信），stats() 固定按这套 key 输出
ALL_STATUSES = (
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_DEAD,
)


class _ModelsUnavailable(RuntimeError):
    """``models.CrawlJob`` / ``CrawlPage`` / ``CrawlDeadLetter`` 尚未就绪。"""


def _utcnow() -> datetime:
    """naive UTC now（与 ``models._utcnow`` 口径一致）。"""
    return datetime.utcnow()


@dataclass
class Job:
    """一条采集任务。"""

    id: int
    source_key: str
    school_id: Optional[int]
    url: str
    job_type: str
    status: str
    attempts: int
    next_run_at: datetime
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_key": self.source_key,
            "school_id": self.school_id,
            "url": self.url,
            "job_type": self.job_type,
            "status": self.status,
            "attempts": self.attempts,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# --------------------------------------------------------------------------- #
# Store 抽象
# --------------------------------------------------------------------------- #
class JobStore:
    """队列持久化接口（可替换）。"""

    def add(
        self,
        *,
        source_key: str,
        url: str,
        school_id: Optional[int],
        job_type: str,
        now: datetime,
    ) -> Job:  # pragma: no cover - 抽象
        raise NotImplementedError

    def find_active(self, source_key: str, url: str) -> Optional[Job]:  # pragma: no cover
        raise NotImplementedError

    def claim(self, limit: int, now: datetime) -> List[Job]:  # pragma: no cover
        raise NotImplementedError

    def get(self, job_id: int) -> Optional[Job]:  # pragma: no cover
        raise NotImplementedError

    def update(self, job_id: int, **fields) -> Optional[Job]:  # pragma: no cover
        raise NotImplementedError

    def add_dead_letter(self, job: Job, error: str, payload: Optional[dict] = None) -> None:
        raise NotImplementedError  # pragma: no cover

    def dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def counts(self) -> Dict[str, int]:  # pragma: no cover
        raise NotImplementedError


class MemoryJobStore(JobStore):
    """纯内存实现（测试 / dry-run）。线程安全。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[int, Job] = {}
        self._dead: List[Dict[str, Any]] = []
        self._seq = 0

    def add(self, *, source_key, url, school_id, job_type, now) -> Job:
        with self._lock:
            self._seq += 1
            job = Job(
                id=self._seq,
                source_key=source_key,
                school_id=school_id,
                url=url,
                job_type=job_type,
                status=STATUS_PENDING,
                attempts=0,
                next_run_at=now,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
            self._jobs[job.id] = job
            return job

    def find_active(self, source_key: str, url: str) -> Optional[Job]:
        with self._lock:
            for job in self._jobs.values():
                if job.source_key == source_key and job.url == url and job.status in (
                    STATUS_PENDING,
                    STATUS_FAILED,
                    STATUS_RUNNING,
                ):
                    return job
        return None

    def claim(self, limit: int, now: datetime) -> List[Job]:
        with self._lock:
            candidates = [
                job
                for job in self._jobs.values()
                if job.status in (STATUS_PENDING, STATUS_FAILED)
                and job.next_run_at is not None
                and job.next_run_at <= now
            ]
            candidates.sort(key=lambda j: (j.next_run_at, j.id))
            claimed = []
            for job in candidates[: max(0, int(limit))]:
                job.status = STATUS_RUNNING
                job.attempts += 1
                job.updated_at = now
                claimed.append(job)
            return claimed

    def get(self, job_id: int) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: int, **fields) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in fields.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = _utcnow()
            return job

    def add_dead_letter(self, job: Job, error: str, payload: Optional[dict] = None) -> None:
        with self._lock:
            self._dead.append(
                {
                    "job_id": job.id,
                    "url": job.url,
                    "source_key": job.source_key,
                    "error": error,
                    "attempts": job.attempts,
                    "payload": payload or {},
                    "created_at": _utcnow().isoformat(),
                }
            )

    def dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._dead[-limit:])

    def counts(self) -> Dict[str, int]:
        with self._lock:
            result = {status: 0 for status in ALL_STATUSES}
            for job in self._jobs.values():
                result[job.status] = result.get(job.status, 0) + 1
            result["total"] = len(self._jobs)
            return result


# --------------------------------------------------------------------------- #
# SQLite 实现（单测用；自带建表）
# --------------------------------------------------------------------------- #
_SQLITE_META = MetaData()

_JOBS_TABLE = Table(
    "crawl_jobs",
    _SQLITE_META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_key", String(100), nullable=False, index=True),
    Column("school_id", Integer, nullable=True),
    Column("url", String(1000), nullable=False),
    Column("job_type", String(50), nullable=False, default="notice"),
    Column("status", String(20), nullable=False, default=STATUS_PENDING, index=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("next_run_at", DateTime, nullable=True, index=True),
    Column("last_error", Text, nullable=True),
    Column("created_at", DateTime, nullable=True),
    Column("updated_at", DateTime, nullable=True),
)

_DEAD_TABLE = Table(
    "crawl_dead_letters",
    _SQLITE_META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("job_id", Integer, nullable=True, index=True),
    Column("url", String(1000), nullable=True),
    Column("source_key", String(100), nullable=True),
    Column("error", Text, nullable=True),
    Column("attempts", Integer, nullable=True),
    Column("payload", Text, nullable=True),
    Column("created_at", DateTime, nullable=True),
)


class SqliteJobStore(JobStore):
    """SQLite 版 store：自建 ``crawl_jobs`` / ``crawl_dead_letters`` 两张表。

    只用于本地单测与离线试跑；生产是 PostgreSQL，适配层见 ``queue_pg.py``。
    """

    def __init__(self, engine: Engine, *, create: bool = True) -> None:
        self.engine = engine
        if create:
            _SQLITE_META.create_all(self.engine, checkfirst=True)

    # -- 内部工具 -------------------------------------------------------- #
    def _row_to_job(self, row) -> Job:
        return Job(
            id=int(row.id),
            source_key=row.source_key,
            school_id=row.school_id,
            url=row.url,
            job_type=row.job_type,
            status=row.status,
            attempts=int(row.attempts or 0),
            next_run_at=row.next_run_at,
            last_error=row.last_error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # -- 接口实现 -------------------------------------------------------- #
    def add(self, *, source_key, url, school_id, job_type, now) -> Job:
        with self.engine.begin() as conn:
            result = conn.execute(
                _JOBS_TABLE.insert().values(
                    source_key=source_key,
                    url=url,
                    school_id=school_id,
                    job_type=job_type,
                    status=STATUS_PENDING,
                    attempts=0,
                    next_run_at=now,
                    last_error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            job_id = int(result.inserted_primary_key[0])
        return Job(
            id=job_id,
            source_key=source_key,
            school_id=school_id,
            url=url,
            job_type=job_type,
            status=STATUS_PENDING,
            attempts=0,
            next_run_at=now,
            last_error=None,
            created_at=now,
            updated_at=now,
        )

    def find_active(self, source_key: str, url: str) -> Optional[Job]:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(_JOBS_TABLE)
                .where(
                    _JOBS_TABLE.c.source_key == source_key,
                    _JOBS_TABLE.c.url == url,
                    _JOBS_TABLE.c.status.in_([STATUS_PENDING, STATUS_FAILED, STATUS_RUNNING]),
                )
                .limit(1)
            ).first()
        return self._row_to_job(row) if row else None

    def claim(self, limit: int, now: datetime) -> List[Job]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(_JOBS_TABLE)
                .where(
                    _JOBS_TABLE.c.status.in_([STATUS_PENDING, STATUS_FAILED]),
                    _JOBS_TABLE.c.next_run_at <= now,
                )
                .order_by(_JOBS_TABLE.c.next_run_at.asc(), _JOBS_TABLE.c.id.asc())
                .limit(max(0, int(limit)))
            ).fetchall()
            claimed: List[Job] = []
            for row in rows:
                conn.execute(
                    update(_JOBS_TABLE)
                    .where(_JOBS_TABLE.c.id == row.id)
                    .values(
                        status=STATUS_RUNNING,
                        attempts=_JOBS_TABLE.c.attempts + 1,
                        updated_at=now,
                    )
                )
                job = self._row_to_job(row)
                job.status = STATUS_RUNNING
                job.attempts = int(row.attempts or 0) + 1
                job.updated_at = now
                claimed.append(job)
        return claimed

    def get(self, job_id: int) -> Optional[Job]:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(_JOBS_TABLE).where(_JOBS_TABLE.c.id == job_id)
            ).first()
        return self._row_to_job(row) if row else None

    def update(self, job_id: int, **fields) -> Optional[Job]:
        fields = {k: v for k, v in fields.items() if v is not None or k == "last_error"}
        if not fields:
            return self.get(job_id)
        fields.setdefault("updated_at", _utcnow())
        with self.engine.begin() as conn:
            conn.execute(update(_JOBS_TABLE).where(_JOBS_TABLE.c.id == job_id).values(**fields))
        return self.get(job_id)

    def add_dead_letter(self, job: Job, error: str, payload: Optional[dict] = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                _DEAD_TABLE.insert().values(
                    job_id=job.id,
                    url=job.url,
                    source_key=job.source_key,
                    error=error,
                    attempts=job.attempts,
                    payload=json.dumps(payload or {}, ensure_ascii=False),
                    created_at=_utcnow(),
                )
            )

    def dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(_DEAD_TABLE)
                .order_by(_DEAD_TABLE.c.id.desc())
                .limit(max(0, int(limit)))
            ).fetchall()
        out = []
        for row in rows:
            try:
                payload = json.loads(row.payload or "{}")
            except Exception:
                payload = {}
            out.append(
                {
                    "id": row.id,
                    "job_id": row.job_id,
                    "url": row.url,
                    "source_key": row.source_key,
                    "error": row.error,
                    "attempts": row.attempts,
                    "payload": payload,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        return out

    def counts(self) -> Dict[str, int]:
        result = {status: 0 for status in ALL_STATUSES}
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(_JOBS_TABLE.c.status, _JOBS_TABLE.c.id).select_from(_JOBS_TABLE)
            ).fetchall()
            for row in rows:
                result[row.status] = result.get(row.status, 0) + 1
        result["total"] = sum(result.get(status, 0) for status in ALL_STATUSES)
        return result


# --------------------------------------------------------------------------- #
# 队列
# --------------------------------------------------------------------------- #
class CrawlQueue:
    """采集任务队列（状态机 + 退避重排 + 死信）。

    :param db: SQLAlchemy ``Session`` / ``Engine``；``None`` 表示纯内存
    :param max_attempts: 超过该尝试次数即判定死信
    :param store: 直接指定 store 实现（测试用）
    """

    def __init__(self, db=None, *, max_attempts: int = 3, store: Optional[JobStore] = None) -> None:
        self.max_attempts = int(max_attempts)
        self.store = store if store is not None else open_store(db)

    # ------------------------------------------------------------------ #
    def enqueue(
        self,
        *,
        source_key: str,
        url: str,
        school_id: Optional[int] = None,
        job_type: str = "notice",
    ) -> int:
        """入队一条任务。

        同一 ``(source_key, url)`` 若已有未完成任务（pending/failed/running），
        直接返回既有任务 id，不重复排队。
        """
        existing = self.store.find_active(source_key, url)
        if existing is not None:
            return existing.id
        job = self.store.add(
            source_key=source_key,
            url=url,
            school_id=school_id,
            job_type=job_type,
            now=_utcnow(),
        )
        return job.id

    def claim(self, limit: int = 1) -> List[Job]:
        """领取到期任务（``next_run_at <= now``），置为 running 并累加 attempts。"""
        return self.store.claim(limit, _utcnow())

    def complete(self, job_id: int) -> bool:
        """标记任务完成。"""
        job = self.store.get(job_id)
        if job is None:
            return False
        self.store.update(job_id, status=STATUS_DONE, last_error=None)
        return True

    def fail(self, job_id: int, error: str) -> str:
        """标记任务失败。

        未超次数 → 置 ``failed`` 并按 ``2 ** attempts`` 分钟重排；
        超次数 → 置 ``dead`` 并写死信。返回最终状态。
        """
        job = self.store.get(job_id)
        if job is None:
            return "missing"
        attempts = int(job.attempts or 0)
        if attempts >= self.max_attempts:
            self.store.update(job_id, status=STATUS_DEAD, last_error=error)
            self.store.add_dead_letter(job, error, payload=job.to_dict())
            return STATUS_DEAD
        delay_minutes = 2 ** attempts
        self.store.update(
            job_id,
            status=STATUS_FAILED,
            last_error=error,
            next_run_at=_utcnow() + timedelta(minutes=delay_minutes),
        )
        return STATUS_FAILED

    def stats(self) -> Dict[str, int]:
        """各状态计数。"""
        return self.store.counts()

    def dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:
        """死信列表。"""
        return self.store.dead_letters(limit)


# --------------------------------------------------------------------------- #
# store 选择
# --------------------------------------------------------------------------- #
def _models_available() -> bool:
    """探测 ``models.CrawlJob`` / ``CrawlPage`` / ``CrawlDeadLetter`` 是否已就绪。"""
    try:
        from models import CrawlDeadLetter, CrawlJob, CrawlPage  # noqa: F401

        return True
    except Exception:
        return False


def _engine_of(db) -> Engine:
    """从 Session / Engine 里取 engine。"""
    if isinstance(db, Engine):
        return db
    bind = getattr(db, "bind", None)
    if bind is not None:
        return bind
    get_bind = getattr(db, "get_bind", None)
    if callable(get_bind):
        return get_bind()
    raise TypeError(f"无法从 {type(db).__name__} 解析出 SQLAlchemy engine")


def open_store(db=None, *, store: Optional[JobStore] = None) -> JobStore:
    """按 ``db`` 选一个 store。

    - ``None`` → :class:`MemoryJobStore`
    - SQLite → :class:`SqliteJobStore`（自动建表）
    - PostgreSQL → :class:`services.crawl.queue_pg.PgJobStore`（依赖
      ``models.CrawlJob`` 等模型；模型未就绪时抛 :class:`_ModelsUnavailable`）
    """
    if store is not None:
        return store
    if db is None:
        return MemoryJobStore()
    if isinstance(db, JobStore):
        return db
    engine = _engine_of(db)
    dialect = engine.dialect.name
    if dialect == "sqlite":
        return SqliteJobStore(engine)
    if dialect == "postgresql":
        if not _models_available():
            raise _ModelsUnavailable(
                "models.CrawlJob / CrawlPage / CrawlDeadLetter 尚未落地，"
                "PostgreSQL 适配层 queue_pg.py 无法启用；"
                "请先等 ingest-pipeline 同事合入模型。"
            )
        from services.crawl.queue_pg import PgJobStore

        return PgJobStore(db)
    raise _ModelsUnavailable(f"暂不支持的数据库方言：{dialect}")
