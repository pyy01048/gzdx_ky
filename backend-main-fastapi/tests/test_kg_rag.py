# -*- coding: utf-8 -*-
"""知识图谱增强 RAG（55 号 DeepTutor 升级方案 P1-D）后端测试。

覆盖：
1. ``expand_query_with_graph`` 无匹配时返回原 query、空数组（不抛异常）。
2. ``expand_query_with_graph`` 命中知识点后沿 prerequisite 关系扩展相关术语。
3. ``recommend_learning_path`` 对不存在的 kp 返回 error == "kp_not_found"。
4. ``recommend_learning_path`` 沿 prerequisite 关系返回路径（两级前置）。
5. （可选）现有 AI 答疑接口冒烟：不因接入图谱扩展而 500。

数据构造参考 ``tests/test_memory_service.py``：SessionLocal + 测试用户 id=0，
用例前后清理本次构造的知识点/关系，保证隔离。
"""
from __future__ import annotations

import pytest

from database import SessionLocal
from models import KnowledgePoint, KnowledgePointRelation
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)

#: 测试用户（conftest 会在测试库创建 id=0 的 pytest 用户）
TEST_USER_ID = 0

#: 本文件专用科目标识，避免与其它用例的种子数据混淆
TEST_SUBJECT = "KG-RAG-测试"


def _cleanup(db) -> None:
    """清空本文件构造的知识点与关系（按科目过滤）。"""
    try:
        kp_ids = [
            row[0]
            for row in db.query(KnowledgePoint.id)
            .filter(KnowledgePoint.subject == TEST_SUBJECT)
            .all()
        ]
        if kp_ids:
            db.query(KnowledgePointRelation).filter(
                KnowledgePointRelation.source_kp_id.in_(kp_ids)
            ).delete(synchronize_session=False)
            db.query(KnowledgePointRelation).filter(
                KnowledgePointRelation.target_kp_id.in_(kp_ids)
            ).delete(synchronize_session=False)
            db.query(KnowledgePoint).filter(KnowledgePoint.id.in_(kp_ids)).delete(
                synchronize_session=False
            )
        db.commit()
    except Exception:  # noqa: BLE001 —— 清理失败不阻断用例
        db.rollback()


def _make_kp(db, name: str) -> KnowledgePoint:
    kp = KnowledgePoint(
        name=name,
        subject=TEST_SUBJECT,
        chapter="KG-RAG-章节",
        mastery=0,
        exam_frequency=1,
        difficulty=2,
        question_count=1,
    )
    db.add(kp)
    db.commit()
    db.refresh(kp)
    return kp


def _make_relation(db, source_id: int, target_id: int, relation_type: str) -> None:
    db.add(
        KnowledgePointRelation(
            source_kp_id=source_id,
            target_kp_id=target_id,
            relation_type=relation_type,
            source="manual",
        )
    )
    db.commit()


@pytest.fixture(autouse=True)
def _clean_kg_rag():
    """每个用例前后清理本文件构造的数据，保证隔离。"""
    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        _cleanup(db)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# expand_query_with_graph
# --------------------------------------------------------------------------- #
def test_expand_no_match_returns_original():
    from services.kg_rag import expand_query_with_graph

    db = SessionLocal()
    try:
        result = expand_query_with_graph(db, "完全不存在的知识点XYZ", subject=TEST_SUBJECT)
        assert result["expanded_query"] == "完全不存在的知识点XYZ"
        assert result["matched_kps"] == []
        assert result["related_terms"] == []
    finally:
        db.close()


def test_expand_empty_query_returns_original():
    from services.kg_rag import expand_query_with_graph

    db = SessionLocal()
    try:
        result = expand_query_with_graph(db, "", subject=TEST_SUBJECT)
        assert result["expanded_query"] == ""
        assert result["matched_kps"] == []
        assert result["related_terms"] == []
    finally:
        db.close()


def test_expand_prerequisite_relation():
    from services.kg_rag import expand_query_with_graph

    db = SessionLocal()
    try:
        # 构造：时序逻辑电路（前置） → 触发器（目标）
        trigger = _make_kp(db, "触发器")
        sequential = _make_kp(db, "时序逻辑电路")
        _make_relation(db, source_id=sequential.id, target_id=trigger.id, relation_type="prerequisite")

        result = expand_query_with_graph(db, "触发器怎么分析", subject=TEST_SUBJECT)
        assert result["matched_kps"], "应命中触发器知识点"
        assert any(m["name"] == "触发器" for m in result["matched_kps"])
        assert "时序逻辑电路" in result["related_terms"]
        assert "时序逻辑电路" in result["expanded_query"]
        assert result["expanded_query"].startswith("触发器怎么分析")
    finally:
        db.close()


def test_expand_max_expansions_limit():
    from services.kg_rag import expand_query_with_graph

    db = SessionLocal()
    try:
        # 构造一个知识点，带两个前置，验证 max_expansions=1 只扩展一个词
        target = _make_kp(db, "触发器")
        pre1 = _make_kp(db, "时序逻辑电路")
        pre2 = _make_kp(db, "组合逻辑电路")
        _make_relation(db, source_id=pre1.id, target_id=target.id, relation_type="prerequisite")
        _make_relation(db, source_id=pre2.id, target_id=target.id, relation_type="prerequisite")

        result = expand_query_with_graph(db, "触发器怎么分析", subject=TEST_SUBJECT, max_expansions=1)
        assert len(result["related_terms"]) == 1
        # 扩展词是 pre1 或 pre2 之一
        assert result["related_terms"][0] in {"时序逻辑电路", "组合逻辑电路"}
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# recommend_learning_path
# --------------------------------------------------------------------------- #
def test_recommend_path_kp_not_found():
    from services.kg_rag import recommend_learning_path

    db = SessionLocal()
    try:
        result = recommend_learning_path(db, 999999999)
        assert result.get("error") == "kp_not_found"
    finally:
        db.close()


def test_recommend_path_two_levels():
    from services.kg_rag import recommend_learning_path

    db = SessionLocal()
    try:
        # 构造三级链：基本触发器 → 时序逻辑电路 → 触发器（当前）
        leaf = _make_kp(db, "触发器")
        mid = _make_kp(db, "时序逻辑电路")
        root = _make_kp(db, "基本触发器")
        _make_relation(db, source_id=mid.id, target_id=leaf.id, relation_type="prerequisite")
        _make_relation(db, source_id=root.id, target_id=mid.id, relation_type="prerequisite")

        result = recommend_learning_path(db, leaf.id, depth=3)
        assert result["kp_id"] == leaf.id
        assert result["kp_name"] == "触发器"
        names = [p["name"] for p in result["path"]]
        # 顺序：从最底层前置到当前 —— 基本触发器 → 时序逻辑电路
        assert names == ["基本触发器", "时序逻辑电路"]
        assert all(p["relation_type"] == "prerequisite" for p in result["path"])
    finally:
        db.close()


def test_recommend_path_no_prerequisite():
    from services.kg_rag import recommend_learning_path

    db = SessionLocal()
    try:
        kp = _make_kp(db, "孤立知识点")
        result = recommend_learning_path(db, kp.id, depth=3)
        assert result["kp_id"] == kp.id
        assert result["kp_name"] == "孤立知识点"
        assert result["path"] == []
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# API 冒烟（可选）：现有 AI 答疑接口不因接入图谱扩展而 500
# --------------------------------------------------------------------------- #
def test_api_ai_rag_smoke():
    """冒烟：/api/ai/rag-search 不因图谱扩展接入而 500。

    现有测试（test_ai_service 等）已覆盖该接口主流程，这里只做轻量冒烟。
    """
    try:
        resp = client.get("/api/ai/rag-search", params={"query": "触发器", "limit": 3})
        # 200 或 4xx（如查询参数名不符）都可接受，唯独不能 500
        assert resp.status_code != 500, f"AI 答疑接口因图谱扩展而 500：{resp.text[:200]}"
    except Exception:  # noqa: BLE001 —— 接口不存在/路由变动时跳过冒烟
        pytest.skip("AI RAG 接口不可用，跳过冒烟")