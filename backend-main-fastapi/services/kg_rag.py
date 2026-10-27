# -*- coding: utf-8 -*-
"""知识图谱增强 RAG（55 号 DeepTutor 升级方案 P1-D）。

基于 ``knowledge_points`` 与 ``knowledge_point_relations`` 两表：
1. :func:`expand_query_with_graph` —— 检索前把用户查询中命中的知识点，
   沿 prerequisite / parallel 关系扩展出相关术语，提升 FTS 召回。
2. :func:`recommend_learning_path` —— 沿 prerequisite 关系向上递归，
   生成「先学前置、再学当前」的学习路径。

设计约束（与项目现有风格一致）：
- 全程 try/except 旁路容错：任何异常都不向外抛，调用方无需感知。
- 只读操作，不修改任何业务数据。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from models import KnowledgePoint, KnowledgePointRelation

logger = logging.getLogger(__name__)

#: 单次扩展最多匹配的知识点数量（数据量 5000+，遍历可接受）
MAX_MATCHED_KPS = 5


def expand_query_with_graph(
    db, query: str, subject: str | None = None, max_expansions: int = 3
) -> Dict[str, Any]:
    """基于知识图谱扩展检索查询词。

    匹配策略：
    - 按 ``subject`` 过滤知识点（subject 为空则查全部）；
    - 知识点名长度 >= 2，且 ``kp.name`` 出现在 ``query`` 中（子串匹配）；
    - 最多取 :data:`MAX_MATCHED_KPS` 个匹配点。

    对每个命中的知识点，沿关系表扩展：
    - ``prerequisite`` 且 ``target_kp_id == kp.id`` → 取其 ``source_kp``（前置知识点）；
    - ``parallel`` 且（source 或 target 是 kp）→ 取另一端的知识点。

    返回：
        ``{"expanded_query": str, "matched_kps": [...], "related_terms": [...]}``。
        ``expanded_query`` = 原 query + 去重后的相关知识点名（最多 ``max_expansions`` 个）。
        无匹配时 ``expanded_query`` 原样返回、``related_terms`` 为空。
    任何异常均旁路返回原 query，不向外抛。
    """
    try:
        matched_kps = _match_knowledge_points(db, query, subject)
        related_terms = _collect_related_terms(db, matched_kps)

        # 去重（保留首次出现顺序），并截断到 max_expansions
        seen: set[str] = set()
        deduped: List[str] = []
        for term in related_terms:
            term = (term or "").strip()
            if not term:
                continue
            if term in seen:
                continue
            seen.add(term)
            deduped.append(term)
            if len(deduped) >= max_expansions:
                break

        if not deduped:
            return {
                "expanded_query": query,
                "matched_kps": matched_kps,
                "related_terms": [],
            }

        expanded = f"{query} {' '.join(deduped)}".strip()
        return {
            "expanded_query": expanded,
            "matched_kps": matched_kps,
            "related_terms": deduped,
        }
    except Exception as exc:  # noqa: BLE001 —— 旁路容错：图谱扩展失败不影响原检索
        logger.warning("expand_query_with_graph 旁路失败：%s", exc)
        return {
            "expanded_query": query,
            "matched_kps": [],
            "related_terms": [],
        }


def recommend_learning_path(db, kp_id: int, depth: int = 3) -> Dict[str, Any]:
    """基于 prerequisite 关系推荐学习路径。

    从 ``kp_id`` 出发，沿 ``relation_type='prerequisite'`` 且
    ``target_kp_id == 当前 kp`` 的关系向上递归收集前置知识点，最多 ``depth`` 层。

    返回：
        ``{"kp_id": int, "kp_name": str, "path": [{"kp_id", "name", "relation_type"}]}``。
        ``path`` 顺序 = 从最底层前置到当前知识点（先学前置，再学当前）。
        知识点不存在时返回 ``{"error": "kp_not_found"}``。
    任何异常返回 ``{"error": str}``，不向外抛。
    """
    try:
        kp = db.query(KnowledgePoint).filter(KnowledgePoint.id == kp_id).first()
        if kp is None:
            return {"error": "kp_not_found"}

        path: List[Dict[str, Any]] = []
        visited: set[int] = set()
        _collect_prerequisites(db, kp_id, depth, visited, path)

        return {
            "kp_id": kp.id,
            "kp_name": kp.name or "",
            "path": path,
        }
    except Exception as exc:  # noqa: BLE001 —— 旁路容错：返回错误信息而非抛异常
        logger.warning("recommend_learning_path 失败 kp_id=%s：%s", kp_id, exc)
        return {"error": str(exc)}


# --------------------------------------------------------------------------- #
# 内部辅助
# --------------------------------------------------------------------------- #
def _match_knowledge_points(db, query: str, subject: str | None) -> List[Dict[str, Any]]:
    """在知识点表中模糊匹配查询文本里出现的知识点名。

    匹配规则（与规格一致）：
    - ``name`` 长度 >= 2；
    - ``kp.name in query``（知识点名是查询文本的子串）。
    先按 ``subject`` 过滤缩小遍历范围，数据量 5000+ 可接受。
    """
    if not query:
        return []

    kp_q = db.query(KnowledgePoint).filter(KnowledgePoint.name.isnot(None))
    if subject:
        kp_q = kp_q.filter(KnowledgePoint.subject == subject)

    matched: List[Dict[str, Any]] = []
    for kp in kp_q.limit(5000).all():
        name = (kp.name or "").strip()
        if len(name) < 2:
            continue
        if name in query:
            matched.append({"kp_id": kp.id, "name": name})
            if len(matched) >= MAX_MATCHED_KPS:
                break
    return matched


def _collect_related_terms(db, matched_kps: List[Dict[str, Any]]) -> List[str]:
    """对每个命中知识点，收集 prerequisite 前置与 parallel 并列知识点的名称。"""
    related: List[str] = []
    for m in matched_kps:
        kp_id = m["kp_id"]
        # prerequisite：target 是当前 kp → source 是前置知识点
        prereq_rows = (
            db.query(KnowledgePointRelation)
            .filter(
                KnowledgePointRelation.relation_type == "prerequisite",
                KnowledgePointRelation.target_kp_id == kp_id,
            )
            .all()
        )
        for row in prereq_rows:
            if row.source_kp is not None and (row.source_kp.name or "").strip():
                related.append(row.source_kp.name.strip())

        # parallel：source 或 target 是当前 kp → 取另一端
        parallel_rows = (
            db.query(KnowledgePointRelation)
            .filter(
                KnowledgePointRelation.relation_type == "parallel",
                KnowledgePointRelation.source_kp_id == kp_id,
            )
            .all()
        )
        parallel_rows += (
            db.query(KnowledgePointRelation)
            .filter(
                KnowledgePointRelation.relation_type == "parallel",
                KnowledgePointRelation.target_kp_id == kp_id,
            )
            .all()
        )
        for row in parallel_rows:
            other = row.target_kp if row.source_kp_id == kp_id else row.source_kp
            if other is not None and (other.name or "").strip():
                related.append(other.name.strip())
    return related


def _collect_prerequisites(
    db, kp_id: int, depth: int, visited: set[int], path: List[Dict[str, Any]]
) -> None:
    """递归收集前置知识点（自底向上）。

    - 防环：``visited`` 记录已访问的 kp_id，重复即停止。
    - 每一跳把 ``source_kp`` 的名称/id 加入 ``path``。
    - ``depth <= 0`` 时不再向下递归。
    """
    if depth <= 0 or kp_id in visited:
        return
    visited.add(kp_id)

    rows = (
        db.query(KnowledgePointRelation)
        .filter(
            KnowledgePointRelation.relation_type == "prerequisite",
            KnowledgePointRelation.target_kp_id == kp_id,
        )
        .all()
    )
    for row in rows:
        if row.source_kp is None:
            continue
        source_id = row.source_kp.id
        if source_id in visited:
            continue
        # 先递归收集更底层的前置，保证 path 顺序 = 从最底层到当前
        _collect_prerequisites(db, source_id, depth - 1, visited, path)
        path.append(
            {
                "kp_id": source_id,
                "name": row.source_kp.name or "",
                "relation_type": "prerequisite",
            }
        )