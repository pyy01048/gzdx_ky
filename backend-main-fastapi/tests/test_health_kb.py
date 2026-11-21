"""健康检查接口契约测试（V3.12 评审 B-01/B-06 整改后的新契约）。

隔离说明
--------
全部请求走 conftest 改写的测试库（PG_DATABASE=kaoyan_test / 临时 SQLite），
绝不触碰生产库 ``kaoyan`` / ``D:\\平台\\database\\kaoyan.db``。

新契约（docs/reports/v312-review-remediation-20261121.md §1/§2）
--------------------------------------------------------------
1. 公开 ``GET /api/health``：零 DB、常数时间，只回 ``{"status","version"}``——
   不得泄露 git_sha / kb 段 / 表名行数 / 向量维度（旧实现 async def 里同步跑
   全表 count 探测 ~10s，占死事件循环，是评审「后端挂起」的根因之一）；
2. 重探测移到 ``GET /api/health/detail``：匿名 401、管理员 200，
   payload 含 service/version/git_sha/built_at/timestamp/kb；
3. kb 段结构完整：database / vector_store / fts5 / tables，关键表行数为
   真实计数（表不存在时如实报 None，不编造 0）；
4. 探测逻辑自身不抛异常（库缺 FTS/vec 表时降级为 missing，而不是 500）。
"""

from __future__ import annotations

import pytest

KEY_TABLES = (
    "documents",
    "knowledge_chunks",
    "quiz_questions",
    "error_records",
    "knowledge_points",
    "words",
    "tasks",
    "papers",
    "kaoyan_schools",
)


@pytest.fixture()
def real_auth(app_module):
    """临时弹出 conftest 的鉴权旁路，让真实访问策略跑（匿名请求用）。

    与 tests/test_guest_access.py 的 _real_auth 同款写法：结束原样恢复，
    不影响其他模块的管理员身份替身。
    """
    from utils.access_policy import enforce_access
    from utils.security import current_user

    saved = {dep: app_module.dependency_overrides.pop(dep, None) for dep in (enforce_access, current_user)}
    yield
    for dep, fn in saved.items():
        if fn is not None:
            app_module.dependency_overrides[dep] = fn


@pytest.fixture()
def fresh_detail_cache(monkeypatch):
    """清掉 /api/health/detail 的 30s TTL 进程内缓存，强制读真实计数。"""
    import main as main_mod

    monkeypatch.setattr(main_mod, "_health_detail_cache", {"at": 0.0, "payload": None})


def test_public_health_is_minimal_and_leaks_nothing(client):
    """公开探活只回 status/version——kb/git_sha/表行数等运维信息一律不得出现。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "version": "3.0.0"}
    # 显式锁死零泄露（评审 B-06：/health 曾泄露 git_sha + 库表行数）
    for key in ("kb", "git_sha", "service", "timestamp", "built_at", "tables"):
        assert key not in body


def test_health_detail_anonymous_is_401(client, real_auth):  # noqa: ARG001
    """诊断快照仅管理员可见：匿名必须 401（而不是 200 带 kb 段）。"""
    assert client.get("/api/health/detail").status_code == 401


def test_health_detail_admin_kb_shape_and_real_rows(client, sample_data, fresh_detail_cache):  # noqa: ARG001
    """管理员 200：kb 段结构完整，且 sample_data 落库后行数是真实计数。"""
    resp = client.get("/api/health/detail")
    assert resp.status_code == 200
    body = resp.json()
    # 运维标识只在 detail 里出现
    assert body["service"] == "kaoyan-backend"
    assert body["version"] == "3.0.0"
    assert "git_sha" in body
    assert body["timestamp"].endswith("+00:00") or body["timestamp"].endswith("Z")

    kb = body["kb"]
    assert kb["status"] in ("ok", "degraded")
    assert kb["database"]["status"] in ("healthy", "unhealthy")

    vec = kb["vector_store"]
    # backend 随方言变化：SQLite 侧是 numpy 暴力检索（BLOB 表），
    # PostgreSQL 侧是 pgvector + HNSW（chunk_vectors.embedding_f32）。
    assert vec["backend"] in ("numpy-brute-force", "pgvector-hnsw", "pgvector")
    assert vec["status"] in ("ok", "empty", "partial", "missing", "unknown")
    assert isinstance(vec["rows"], int)

    fts = kb["fts5"]
    assert fts["status"] in ("ok", "partial", "missing", "unknown")
    assert isinstance(fts["rows"], int)

    tables = kb["tables"]
    for name in KEY_TABLES:
        assert name in tables, f"关键表 {name} 未纳入健康检查"
        entry = tables[name]
        assert entry["exists"] in (True, False)
        # 表存在 → 行数必须是 int；不存在 → 如实报 None（不编造 0）
        if entry["exists"]:
            assert isinstance(entry["rows"], int)
        else:
            assert entry["rows"] is None

    # sample_data 已落库：行数探测必须读到真实数据（不是恒 0 的假探针）
    assert tables["documents"]["exists"] is True
    assert tables["documents"]["rows"] >= 1
    assert tables["quiz_questions"]["rows"] >= 2
    assert tables["tasks"]["rows"] >= 2


def test_health_snapshot_degrades_not_crashes(client):  # noqa: ARG001
    """临时库没有 FTS5/vec 表时，探测降级为 missing，接口本身仍 200。"""
    from services.health_service import kb_health_snapshot

    snap = kb_health_snapshot()
    # 临时库里 search_service 的索引表大概率未建 → missing 且整体 degraded
    if snap["fts5"]["status"] == "missing":
        assert snap["status"] == "degraded"
    assert snap["database"]["status"] == "healthy"
