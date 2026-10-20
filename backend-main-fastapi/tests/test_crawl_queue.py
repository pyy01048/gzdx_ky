# -*- coding: utf-8 -*-
"""``services/crawl/queue.py`` 单测：内存队列 + SQLite 内存库（不碰 PostgreSQL）。"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from services.crawl.queue import (  # noqa: E402
    STATUS_DEAD,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    CrawlQueue,
    MemoryJobStore,
    SqliteJobStore,
    _ModelsUnavailable,
    open_store,
)


def sqlite_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture(params=["memory", "sqlite"])
def queue(request):
    if request.param == "memory":
        return CrawlQueue(store=MemoryJobStore(), max_attempts=3)
    return CrawlQueue(sqlite_engine(), max_attempts=3)


def _force_due(queue, job_id):
    """把退避时间提前，模拟"到点重试"。"""
    queue.store.update(job_id, next_run_at=datetime.utcnow() - timedelta(minutes=1))


# --------------------------------------------------------------------------- #
# 正常流程
# --------------------------------------------------------------------------- #
def test_enqueue_claim_complete_full_flow(queue):
    job_id = queue.enqueue(source_key="school:1", url="https://example.edu.cn/a.html", school_id=1)
    assert isinstance(job_id, int)

    stats = queue.stats()
    assert stats[STATUS_PENDING] == 1
    assert stats["total"] == 1

    jobs = queue.claim(1)
    assert len(jobs) == 1
    assert jobs[0].id == job_id
    assert jobs[0].status == STATUS_RUNNING
    assert jobs[0].attempts == 1
    assert jobs[0].school_id == 1
    assert jobs[0].job_type == "notice"

    assert queue.complete(job_id) is True
    stats = queue.stats()
    assert stats[STATUS_DONE] == 1
    assert stats[STATUS_RUNNING] == 0


def test_claim_does_not_return_same_job_twice(queue):
    queue.enqueue(source_key="school:1", url="https://example.edu.cn/a.html")
    first = queue.claim(1)
    second = queue.claim(1)
    assert len(first) == 1
    assert second == [], "running 的任务不该被重复领取"


def test_enqueue_is_idempotent_for_same_source_and_url(queue):
    a = queue.enqueue(source_key="school:1", url="https://example.edu.cn/a.html")
    b = queue.enqueue(source_key="school:1", url="https://example.edu.cn/a.html")
    assert a == b
    assert queue.stats()["total"] == 1


def test_claim_respects_limit(queue):
    for i in range(5):
        queue.enqueue(source_key="school:1", url=f"https://example.edu.cn/{i}.html")
    assert len(queue.claim(2)) == 2
    assert len(queue.claim(2)) == 2


# --------------------------------------------------------------------------- #
# 失败 / 退避 / 死信
# --------------------------------------------------------------------------- #
def test_fail_requeues_with_exponential_backoff(queue):
    job_id = queue.enqueue(source_key="school:1", url="https://example.edu.cn/a.html")
    jobs = queue.claim(1)
    status = queue.fail(jobs[0].id, "http_500")
    assert status == STATUS_FAILED
    job = queue.store.get(job_id)
    assert job.status == STATUS_FAILED
    assert job.last_error == "http_500"
    # 第一次失败：next_run_at = now + 2 ** attempts(=1) 分钟
    delay_minutes = (job.next_run_at - datetime.utcnow()).total_seconds() / 60
    assert 1.5 < delay_minutes <= 2.1, f"退避应约 2 分钟，实际 {delay_minutes}"


def test_failed_job_is_not_claimed_before_next_run_at(queue):
    queue.enqueue(source_key="school:1", url="https://example.edu.cn/a.html")
    jobs = queue.claim(1)
    queue.fail(jobs[0].id, "http_500")
    assert queue.claim(1) == [], "退避时间未到的任务不该被领取"


def test_three_failures_land_in_dead_letters(queue):
    job_id = queue.enqueue(source_key="school:1", url="https://example.edu.cn/a.html")
    for i in range(3):
        jobs = queue.claim(1)
        assert len(jobs) == 1, f"第 {i + 1} 次重试应能领到任务"
        status = queue.fail(jobs[0].id, f"boom-{i}")
        _force_due(queue, job_id)  # 跳过退避等待，模拟"到点重试"
    assert status == STATUS_DEAD

    stats = queue.stats()
    assert stats[STATUS_DEAD] == 1
    assert stats[STATUS_FAILED] == 0

    letters = queue.dead_letters()
    assert len(letters) == 1
    assert letters[0]["error"] == "boom-2"
    assert letters[0]["url"] == "https://example.edu.cn/a.html"
    assert letters[0]["source_key"] == "school:1"
    assert letters[0]["attempts"] == 3
    assert queue.claim(1) == [], "死信不该再被领取"


def test_dead_letter_appears_after_retry_schedule(queue):
    """走完整重试周期（手动把退避时间提前）后进死信，attempts 累加到 3。"""
    job_id = queue.enqueue(source_key="school:1", url="https://example.edu.cn/a.html")
    for _ in range(3):
        jobs = queue.claim(1)
        queue.fail(jobs[0].id, "boom")
        _force_due(queue, job_id)
    assert queue.store.get(job_id).status == STATUS_DEAD
    assert queue.store.get(job_id).attempts == 3
    assert len(queue.dead_letters()) == 1


def test_fail_on_unknown_job(queue):
    assert queue.fail(999999, "boom") == "missing"
    assert queue.complete(999999) is False


# --------------------------------------------------------------------------- #
# store 选择
# --------------------------------------------------------------------------- #
def test_open_store_memory_when_db_is_none():
    assert isinstance(open_store(None), MemoryJobStore)


def test_open_store_sqlite_creates_tables():
    engine = sqlite_engine()
    store = open_store(engine)
    assert isinstance(store, SqliteJobStore)
    assert "crawl_jobs" in engine.dialect.get_table_names(engine.connect())
    assert "crawl_dead_letters" in engine.dialect.get_table_names(engine.connect())


def test_open_store_postgres_uses_pg_adapter():
    """PostgreSQL 分支接 ORM 适配层（models.CrawlJob 等已落地）。"""
    from services.crawl.queue_pg import PgJobStore

    engine = create_engine("postgresql+psycopg://user@127.0.0.1:5432/kaoyan")
    store = open_store(engine)
    assert isinstance(store, PgJobStore)


def test_pg_adapter_raises_when_models_missing(monkeypatch):
    """模型没落地时必须明确报错，不许猜表结构。"""
    from services.crawl import queue_pg

    def _boom():
        raise _ModelsUnavailable("models.CrawlJob 尚未落地")

    monkeypatch.setattr(queue_pg, "load_models", _boom)
    engine = create_engine("postgresql+psycopg://user@127.0.0.1:5432/kaoyan")
    with pytest.raises(_ModelsUnavailable):
        open_store(engine)
