"""KB 健康检查面板接口测试（GET /api/health 扩展段）。

隔离说明
--------
全部请求走 conftest 改写的临时库（DATABASE_PATH 指向 tempfile 下的 qa_test.db），
绝不触碰 ``D:\\平台\\database\\kaoyan.db`` 真实数据。

覆盖
----
1. /api/health 仍返回 200，且原有字段（status/service/version/timestamp）不回归；
2. 新增 kb 段结构完整：database / vector_store / fts5 / tables；
3. 关键表行数为整数或 None（表不存在时如实报 None，不编造 0）；
4. sample_data 落库后 documents 等表行数 > 0；
5. 探测逻辑自身不抛异常（库缺 FTS/vec 表时降级为 missing，而不是 500）。
"""
from __future__ import annotations

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


def test_health_keeps_legacy_fields(client):
    """原有字段不能因扩展而回归——前端探活依赖它们。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "kaoyan-backend"
    assert body["version"] == "3.0.0"
    # timestamp 按项目时间约定统一为 UTC+Z（前端不消费该字段，只做格式守护）
    assert body["timestamp"].endswith("Z")
    assert body["status"] in ("ok", "degraded")


def test_health_kb_section_shape(client):
    """kb 段必须一次说清：数据库 / 向量库 / FTS5 / 关键表行数。"""
    body = client.get("/api/health").json()
    kb = body["kb"]

    assert kb["status"] in ("ok", "degraded")
    assert kb["database"]["status"] in ("healthy", "unhealthy")

    vec = kb["vector_store"]
    # backend 随方言变化：SQLite 侧是 numpy 暴力检索（BLOB 表），
    # PostgreSQL 侧是 pgvector + HNSW（chunk_vectors.embedding_f32）。
    # 原先写死 numpy-brute-force → 切到 PG 后必挂（实测）。
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


def test_health_tables_count_real_rows(client, sample_data):  # noqa: ARG001
    """sample_data 落库后，行数探测必须读到真实数据（不是恒 0 的假探针）。"""
    body = client.get("/api/health").json()
    tables = body["kb"]["tables"]

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
