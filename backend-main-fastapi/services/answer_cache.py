"""V11 模块 6：问答语义缓存（answer cache）。

设计要点
--------
* 独立 SQLite 文件 ``data/answer_cache.db``，**绝不**触碰主库 ``kaoyan.db``。
* 缓存键 = 规范化查询文本的 sha256：
  大小写归一（casefold）+ 去首尾空白 + Unicode NFKC 全半角归一。
  规范化后文本相同即精确命中（``source="exact"``）。
* 相似复用：字符集合 Jaccard 相似度 > 0.9 视为相似命中（``source="similar"``），
  不调用 LLM，零额外推理成本。
* TTL 默认 24 小时；查询时惰性删除过期条目并视为未命中。
* 线程安全：WAL 模式 + 模块级可重入锁 + 短事务；任何读写异常都静默降级
  （get 返回 None，set 直接吞掉异常），绝不把缓存故障冒泡到主链路。

对外接口（冻结，后续 Agentic 升级按此接线，签名不可改）::

    get_cached(query, subject=None) -> Optional[Dict[str, Any]]
    set_cached(query, answer, subject=None, ttl_hours=24) -> None
    cache_stats() -> Dict[str, Any]
    clear_cache() -> None
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

# --------------------------------------------------------------------------- #
# 路径与常量
# --------------------------------------------------------------------------- #
# 本文件位于 <backend>/services/answer_cache.py，根目录再上一级。
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB_PATH = os.path.join(_BACKEND_ROOT, "data", "answer_cache.db")

# 允许测试/运维通过环境变量覆盖库文件路径；默认走 data/answer_cache.db。
_DB_PATH: str = os.environ.get("ANSWER_CACHE_DB_PATH", _DEFAULT_DB_PATH)

# 相似命中阈值（字符集合 Jaccard）。
_SIMILAR_THRESHOLD = 0.9
# 相似候选扫描上限，避免库膨胀后全表扫拖累主链路。
_SIMILAR_SCAN_LIMIT = 500

_LOCK = threading.RLock()

# 运行期计数（内存态，重启归零；记录数实时查库）。
_HIT_COUNT = 0
_MISS_COUNT = 0
_WRITE_COUNT = 0

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS answer_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash       TEXT NOT NULL UNIQUE,
    normalized_query TEXT NOT NULL,
    subject          TEXT,
    answer           TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT 'exact',
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_answer_cache_hash    ON answer_cache(query_hash);
CREATE INDEX IF NOT EXISTS idx_answer_cache_expires  ON answer_cache(expires_at);
"""


# --------------------------------------------------------------------------- #
# 规范化 / 相似度
# --------------------------------------------------------------------------- #
def _normalize(query: str) -> str:
    """大小写归一 + 全半角归一 + 去首尾空白。"""
    if not query:
        return ""
    text = unicodedata.normalize("NFKC", query)
    return text.strip().casefold()


def _hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _jaccard(a: str, b: str) -> float:
    """字符集合 Jaccard 相似度（中文场景下对单字扰动/标点差异较稳）。"""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    union = len(sa | sb)
    if union == 0:
        return 0.0
    return len(sa & sb) / union


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# SQLite 连接管理
# --------------------------------------------------------------------------- #
def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path,
        timeout=5.0,
        isolation_level=None,  # 自动提交模式，手动 BEGIN IMMEDIATE 控制事务
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    # WAL 提升并发读写性能；busy_timeout 处理抢锁。
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except sqlite3.Error:
        pass
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


# --------------------------------------------------------------------------- #
# 惰性过期清理
# --------------------------------------------------------------------------- #
def _purge_expired(conn: sqlite3.Connection, now_iso: str) -> None:
    try:
        conn.execute("DELETE FROM answer_cache WHERE expires_at < ?;", (now_iso,))
    except sqlite3.Error:
        pass


# --------------------------------------------------------------------------- #
# 对外接口
# --------------------------------------------------------------------------- #
def get_cached(
    query: str, subject: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """命中返回缓存结构，未命中/过期/异常返回 None。"""
    global _HIT_COUNT, _MISS_COUNT

    if not query or not query.strip():
        return None

    norm = _normalize(query)
    if not norm:
        return None
    qhash = _hash(norm)

    with _LOCK:
        try:
            conn = _connect(_DB_PATH)
        except sqlite3.Error:
            _MISS_COUNT += 1
            return None
        try:
            try:
                _ensure_schema(conn)
                now_iso = _iso(_now())
                _purge_expired(conn, now_iso)

                # 1) 精确命中
                row = conn.execute(
                    "SELECT answer, source, created_at, query_hash "
                    "FROM answer_cache WHERE query_hash = ? LIMIT 1;",
                    (qhash,),
                ).fetchone()
                if row is not None:
                    _HIT_COUNT += 1
                    return {
                        "answer": row["answer"],
                        "hit_at": now_iso,
                        "query_hash": row["query_hash"],
                        "source": "exact",
                    }

                # 2) 相似命中（Jaccard > 0.9）
                sim_row = _find_similar(conn, norm, subject, now_iso)
                if sim_row is not None:
                    _HIT_COUNT += 1
                    return {
                        "answer": sim_row["answer"],
                        "hit_at": now_iso,
                        "query_hash": sim_row["query_hash"],
                        "source": "similar",
                    }

                _MISS_COUNT += 1
                return None
            except sqlite3.Error:
                _MISS_COUNT += 1
                return None
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def _find_similar(
    conn: sqlite3.Connection,
    norm_query: str,
    subject: Optional[str],
    now_iso: str,
) -> Optional[sqlite3.Row]:
    """在未过期条目中找 Jaccard 最高且 > 阈值的一条。"""
    try:
        if subject:
            rows = conn.execute(
                "SELECT normalized_query, answer, query_hash "
                "FROM answer_cache "
                "WHERE expires_at >= ? AND subject = ? "
                "ORDER BY id DESC LIMIT ?;",
                (now_iso, subject, _SIMILAR_SCAN_LIMIT),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT normalized_query, answer, query_hash "
                "FROM answer_cache "
                "WHERE expires_at >= ? "
                "ORDER BY id DESC LIMIT ?;",
                (now_iso, _SIMILAR_SCAN_LIMIT),
            ).fetchall()
    except sqlite3.Error:
        return None

    best: Optional[sqlite3.Row] = None
    best_score = 0.0
    for r in rows:
        score = _jaccard(norm_query, r["normalized_query"] or "")
        if score > best_score:
            best_score = score
            best = r
    if best is not None and best_score > _SIMILAR_THRESHOLD:
        return best
    return None


def set_cached(
    query: str,
    answer: str,
    subject: Optional[str] = None,
    ttl_hours: int = 24,
) -> None:
    """写入/覆盖缓存；任何失败静默忽略。"""
    global _WRITE_COUNT

    if not query or not query.strip() or answer is None:
        return

    norm = _normalize(query)
    if not norm:
        return
    qhash = _hash(norm)

    try:
        ttl = int(ttl_hours)
    except (TypeError, ValueError):
        ttl = 24
    if ttl <= 0:
        ttl = 24

    now = _now()
    created_iso = _iso(now)
    expires_iso = _iso(now + timedelta(hours=ttl))

    with _LOCK:
        try:
            conn = _connect(_DB_PATH)
        except sqlite3.Error:
            return
        try:
            try:
                _ensure_schema(conn)
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    """
                    INSERT INTO answer_cache
                        (query_hash, normalized_query, subject, answer,
                         source, created_at, expires_at)
                    VALUES (?, ?, ?, ?, 'exact', ?, ?)
                    ON CONFLICT(query_hash) DO UPDATE SET
                        normalized_query = excluded.normalized_query,
                        subject          = excluded.subject,
                        answer           = excluded.answer,
                        source           = 'exact',
                        created_at       = excluded.created_at,
                        expires_at       = excluded.expires_at;
                    """,
                    (qhash, norm, subject, answer, created_iso, expires_iso),
                )
                conn.execute("COMMIT;")
                _WRITE_COUNT += 1
            except sqlite3.Error:
                try:
                    conn.execute("ROLLBACK;")
                except sqlite3.Error:
                    pass
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def cache_stats() -> Dict[str, Any]:
    """返回缓存统计：记录数 / 命中数 / 写入数 / 库文件路径。"""
    with _LOCK:
        record_count = 0
        try:
            conn = _connect(_DB_PATH)
            try:
                _ensure_schema(conn)
                cur = conn.execute("SELECT COUNT(*) AS n FROM answer_cache;")
                row = cur.fetchone()
                if row is not None:
                    record_count = row[0] or 0
            finally:
                conn.close()
        except sqlite3.Error:
            record_count = 0

        return {
            "record_count": record_count,
            "hit_count": _HIT_COUNT,
            "write_count": _WRITE_COUNT,
            "db_path": _DB_PATH,
        }


def clear_cache() -> None:
    """清空全部缓存条目（测试与运维用）。"""
    with _LOCK:
        try:
            conn = _connect(_DB_PATH)
            try:
                _ensure_schema(conn)
                conn.execute("DELETE FROM answer_cache;")
            finally:
                conn.close()
        except sqlite3.Error:
            pass


__all__ = [
    "get_cached",
    "set_cached",
    "cache_stats",
    "clear_cache",
]
