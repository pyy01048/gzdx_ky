"""V11 模块 6：answer_cache 单测。

覆盖：
* 精确命中（含大小写/空白/全半角归一）
* 未命中返回 None
* 相似命中（Jaccard > 0.9）
* TTL 过期视为未命中
* 多线程并发写入不炸
* 库文件损坏/不可写时 get/set 静默降级
"""
from __future__ import annotations

import importlib
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def ac(tmp_path, monkeypatch):
    """每个用例一个独立的临时缓存库，并 reload 模块以读取新路径。"""
    db_path = tmp_path / "test_answer_cache.db"
    monkeypatch.setenv("ANSWER_CACHE_DB_PATH", str(db_path))

    import services.answer_cache as module_under_test
    importlib.reload(module_under_test)
    yield module_under_test

    # 清理：删除临时库文件（best-effort）
    try:
        module_under_test.clear_cache()
    except Exception:
        pass


def test_exact_hit_returns_answer(ac):
    ac.set_cached("什么是导数？", "导数是瞬时变化率。", subject="数学", ttl_hours=24)
    hit = ac.get_cached("什么是导数？", subject="数学")

    assert hit is not None
    assert hit["answer"] == "导数是瞬时变化率。"
    assert hit["source"] == "exact"
    assert hit["query_hash"]
    assert hit["hit_at"]


def test_normalization_exact_hit(ac):
    """大小写归一 + 去首尾空白 + 全半角归一 后应判为精确命中。"""
    ac.set_cached("Hello World", "英文答案 A", subject="英语")
    # 全角空格 + 前后空白 + 大小写混合
    hit = ac.get_cached("　  hello WORLD  ", subject="英语")
    assert hit is not None
    assert hit["source"] == "exact"
    assert hit["answer"] == "英文答案 A"


def test_miss_returns_none(ac):
    ac.set_cached("已存在的问题", "答案 X")
    assert ac.get_cached("完全不存在的问题") is None
    assert ac.get_cached("") is None
    assert ac.get_cached("   ") is None


def test_similar_hit(ac):
    """仅差一个标点/字符，Jaccard > 0.9 → source=similar。"""
    original = "考研数学高等数学极限的计算方法总结与常见题型"
    similar = "考研数学高等数学极限的计算方法总结与常见题型？"  # 多一个全角问号
    ac.set_cached(original, "相似答案：极限四则运算与洛必达。", subject="数学")

    hit = ac.get_cached(similar, subject="数学")
    assert hit is not None
    assert hit["source"] == "similar"
    assert hit["answer"] == "相似答案：极限四则运算与洛必达。"


def test_ttl_expired_treated_as_miss(ac):
    ac.set_cached("临时问题", "临时答案", ttl_hours=24)
    # 直接把 expires_at 改到过去
    conn = sqlite3.connect(ac._DB_PATH)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE answer_cache SET expires_at = ?;", (past,))
    conn.commit()
    conn.close()

    assert ac.get_cached("临时问题") is None
    # 过期条目应被惰性清理掉
    stats = ac.cache_stats()
    assert stats["record_count"] == 0


def test_overwrite_same_key_updates_answer(ac):
    ac.set_cached("同一问题", "旧答案")
    ac.set_cached("同一问题", "新答案")
    hit = ac.get_cached("同一问题")
    assert hit is not None
    assert hit["answer"] == "新答案"
    # 覆盖后仍只有一条
    assert ac.cache_stats()["record_count"] == 1


def test_concurrent_writes_no_crash(ac):
    """多线程并发写 N 条不同问题，最终全部落库且无异常。"""
    N = 50

    def worker(worker_id: int):
        for i in range(N):
            q = f"并发问题-{worker_id}-{i}"
            ac.set_cached(q, f"答案 {worker_id}-{i}", subject="数学")

    threads = [threading.Thread(target=worker, args=(wid,)) for wid in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    for t in threads:
        assert not t.is_alive(), "线程未在 30s 内结束"

    stats = ac.cache_stats()
    assert stats["record_count"] == 8 * N
    assert stats["write_count"] == 8 * N

    # 抽查一条可读
    hit = ac.get_cached("并发问题-3-10", subject="数学")
    assert hit is not None
    assert hit["source"] == "exact"


def test_corrupt_db_silent_degradation(ac, tmp_path, monkeypatch):
    """库路径指向一个目录（SQLite 无法打开）时，get/set 都不抛异常。"""
    bad_dir = tmp_path / "is_a_directory"
    bad_dir.mkdir()
    monkeypatch.setenv("ANSWER_CACHE_DB_PATH", str(bad_dir))
    importlib.reload(ac)

    # 不应抛异常
    assert ac.get_cached("任意问题") is None
    ac.set_cached("任意问题", "答案")
    stats = ac.cache_stats()
    assert stats["record_count"] == 0
    assert stats["db_path"] == str(bad_dir)


def test_cache_stats_and_clear(ac):
    ac.set_cached("问题 A", "答案 A")
    ac.set_cached("问题 B", "答案 B")
    ac.get_cached("问题 A")  # 命中一次
    ac.get_cached("问题 ???")  # 未命中一次

    stats = ac.cache_stats()
    assert stats["record_count"] == 2
    assert stats["hit_count"] >= 1
    assert stats["write_count"] == 2
    assert stats["db_path"].endswith("test_answer_cache.db")

    ac.clear_cache()
    assert ac.cache_stats()["record_count"] == 0
