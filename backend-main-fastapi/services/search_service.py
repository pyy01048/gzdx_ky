# -*- coding: utf-8 -*-
"""混合检索服务：FTS5 (BM25) + 向量KNN + RRF融合。

移植自 D:\\学习平台 的 search_service.py，适配 kaoyan-study-platform 的
SQLAlchemy + SQLite 架构。向量后端默认 numpy brute-force（无需 vec0 扩展），
embedding 通过在线 API 生成（豆包/通义兼容接口）。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

RRF_K = 60
TOPN_PER_LANE = 30
VEC_MIN_DIST = 0.6  # cosine distance 阈值，超过则视为不相关

# ---------------------------------------------------------------------------
# 术语加权精排（移植自 D:\kaoyan_ai\04_app\chat.py 的 KBRetriever._term_boost）
# ---------------------------------------------------------------------------
# 领域核心术语表：检索时对这些词加权，帮助命中真正讲解概念的段落
CORE_TERMS = [
    "TTL", "CMOS", "MOS", "DAC", "ADC", "ROM", "RAM", "555", "74LS",
    "卡诺图", "与非门", "或非门", "触发器", "寄存器", "计数器", "译码器", "编码器",
    "选择器", "加法器", "比较器", "锁存器", "静态工作点", "共射极", "放大电路",
    "运算放大器", "虚短", "虚断", "差模", "共模", "反馈", "二极管", "三极管",
    "晶体管", "稳压", "整流", "滤波器", "振荡器", "多谐", "施密特", "逻辑函数",
    "真值表", "二进制", "格雷", "奇偶校验", "传输延迟", "扇出", "噪声容限",
]

# 同义词组：不同写法但指向同一概念（查询命中任一组内词，则对组内所有写法加权）
TERM_SYNONYMS = [
    ["DAC", "D/A转换器", "D/A 转换器", "数模转换器"],
    ["ADC", "A/D转换器", "A/D 转换器", "模数转换器"],
    ["TTL", "晶体管-晶体管逻辑", "晶体管逻辑"],
    ["CMOS", "互补金属氧化物半导体"],
    ["MOS", "金属氧化物半导体"],
    ["RAM", "随机存取存储器", "随机存储器"],
    ["运算放大器", "运放"],
]

# 封面/导航噪声词：命中即降权（教案封面、目录页等非知识点内容）
NOISE_TERMS = ["授课", "课时", "教学章", "教案", "目录", "课时安排", "授课方式", "主讲", "章节安排"]


def _term_boost(query: str, text: str) -> float:
    """核心术语加权：命中的术语越多、出现越靠前，权重越高（概念定义通常在段首）。
    与 kaoyan_ai 原始实现保持一致：术语出现 +2.0/次，前 200 字符 +3.0/次，噪声词 -8.0。"""
    up = query.upper()
    boost = 0.0
    for term in CORE_TERMS:
        if term in up:
            cnt = text.upper().count(term)
            if cnt:
                head = text[:200].upper().count(term)
                boost += cnt * 2.0 + head * 3.0
    for group in TERM_SYNONYMS:
        if any(t in up for t in group):
            for t in group:
                c = text.upper().count(t)
                if c:
                    h = text[:200].upper().count(t)
                    boost += c * 2.0 + h * 3.0
    for n in NOISE_TERMS:
        if n in text:
            boost -= 8.0
    return boost

# FTS5 查询里需要剔除的字符：
#   1) FTS5 语法字符（" ' ( ) * : ^）—— 会让查询串解析失败
#   2) 控制字符（\x00 等）—— jieba 会把 \x00 当成一个独立 token 保留下来，
#      只过滤语法字符的话 NUL 会被塞进 SQL 查询串
_CTRL = re.compile(r'["\'()*:^]|[\x00-\x1f\x7f]')


# ---------------------------------------------------------------------------
# 分词
# ---------------------------------------------------------------------------
def segment(text: str) -> str:
    """jieba search-mode 分词，空格分隔。jieba 未安装时回退到简单分词。"""
    try:
        import jieba
        return " ".join(t.strip() for t in jieba.cut_for_search(text) if t.strip())
    except ImportError:
        # 回退：中文2-gram + 英文单词
        tokens = []
        for w in re.findall(r"[a-zA-Z0-9]{2,}", text.lower()):
            tokens.append(w)
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
        for i in range(len(cjk) - 1):
            tokens.append(cjk[i:i + 2])
        return " ".join(tokens)


def _fts_query(user_query: str) -> str:
    tokens = [t for t in segment(user_query).split() if t]
    if not tokens:
        return '""'
    safe = [_CTRL.sub("", t) for t in tokens]
    return " OR ".join(f'"{t}"' for t in safe if t)


# ---------------------------------------------------------------------------
# 数据库表管理
# ---------------------------------------------------------------------------
def ensure_fts_table(conn: sqlite3.Connection) -> None:
    """确保 FTS5 全文检索表存在，并从 knowledge_chunks 同步数据。"""
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
            chunk_id UNINDEXED,
            document_id UNINDEXED,
            subject UNINDEXED,
            content,
            tokenize = 'unicode61'
        )
    """)
    # 检查是否需要同步数据
    count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks_fts").fetchone()[0]
    if count == 0:
        rows = conn.execute(
            "SELECT id, document_id, subject, text FROM knowledge_chunks WHERE text IS NOT NULL"
        ).fetchall()
        conn.executemany(
            "INSERT INTO knowledge_chunks_fts (chunk_id, document_id, subject, content) VALUES (?, ?, ?, ?)",
            [(r[0], r[1], r[2], r[3] or "") for r in rows],
        )
        conn.commit()


def ensure_vec_table(conn: sqlite3.Connection) -> None:
    """确保向量表存在（numpy brute-force 后端，存储 BLOB）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_chunks_vec (
            chunk_id INTEGER PRIMARY KEY,
            document_id INTEGER,
            subject TEXT,
            embedding BLOB,
            dim INTEGER,
            FOREIGN KEY (chunk_id) REFERENCES knowledge_chunks(id)
        )
    """)
    conn.commit()


def ensure_tables(db: Session) -> None:
    """对外入口：确保 FTS 和向量表都存在。"""
    conn = db.connection().connection
    ensure_fts_table(conn)
    ensure_vec_table(conn)


# ---------------------------------------------------------------------------
# FTS5 检索
# ---------------------------------------------------------------------------
def fts_search(
    conn: sqlite3.Connection,
    query: str,
    topn: int = TOPN_PER_LANE,
    subject: Optional[str] = None,
) -> List[Tuple[int, int]]:
    """FTS5 BM25 检索，返回 [(chunk_id, rank)]，rank 从 1 开始。"""
    q_seg = _fts_query(query)
    if q_seg == '""':
        return []
    sql = (
        "SELECT chunk_id, bm25(knowledge_chunks_fts) AS s "
        "FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH ?"
    )
    params: list[Any] = [q_seg]
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    sql += " ORDER BY s LIMIT ?"
    params.append(topn)
    rows = conn.execute(sql, params).fetchall()
    return [(r[0], i + 1) for i, r in enumerate(rows)]


# ---------------------------------------------------------------------------
# 向量检索（numpy brute-force）
# ---------------------------------------------------------------------------
def vec_search(
    conn: sqlite3.Connection,
    query_vec: np.ndarray,
    topn: int = TOPN_PER_LANE,
    subject: Optional[str] = None,
) -> List[Tuple[int, int]]:
    """向量 KNN 检索（numpy brute-force），返回 [(chunk_id, rank)]。"""
    q = np.asarray(query_vec, dtype=np.float32)
    if q.ndim != 1:
        return []
    sql = "SELECT chunk_id, embedding FROM knowledge_chunks_vec WHERE embedding IS NOT NULL"
    params: list[Any] = []
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return []
    # 过滤维度匹配的向量
    valid = []
    for r in rows:
        try:
            v = np.frombuffer(r[1], dtype=np.float32)
            if v.shape[0] == q.shape[0]:
                valid.append((r[0], v))
        except Exception:
            continue
    if not valid:
        return []
    mat = np.stack([v for _, v in valid])
    # cosine similarity（假设向量已归一化，bge 系列默认归一化）
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    mat_norm = mat / norms
    q_norm = q / (np.linalg.norm(q) or 1)
    sims = mat_norm @ q_norm
    # cosine distance = 1 - similarity
    candidates = [
        (valid[i][0], float(1.0 - sims[i]))
        for i in range(len(valid))
        if (1.0 - sims[i]) < VEC_MIN_DIST
    ]
    candidates.sort(key=lambda x: x[1])
    return [(c, i + 1) for i, (c, _d) in enumerate(candidates[:topn])]


# ---------------------------------------------------------------------------
# RRF 融合
# ---------------------------------------------------------------------------
def rrf_fuse(*lanes: List[Tuple[int, int]], k: int = RRF_K) -> List[int]:
    """Reciprocal Rank Fusion，返回融合后的 chunk_id 列表（按分数降序）。"""
    scores: dict[int, float] = {}
    for lane in lanes:
        for chunk_id, rank in lane:
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return [cid for cid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


# ---------------------------------------------------------------------------
# 对外主接口
# ---------------------------------------------------------------------------
def hybrid_search(
    db: Session,
    query: str,
    query_vec: Optional[np.ndarray] = None,
    limit: int = 6,
    subject: Optional[str] = None,
) -> List[dict]:
    """混合检索主入口（三路召回：chunks + points + documents）。

    V2.0 修复：原版本只检索 knowledge_chunks，知识点和文档从不进入 RAG 上下文。
    现同时检索三路，RRF 融合后返回。

    Args:
        db: SQLAlchemy Session
        query: 用户查询文本
        query_vec: 查询向量（None 时仅用 FTS）
        limit: 返回结果数
        subject: 学科过滤

    Returns:
        检索结果列表，每项含 chunk_id, document_id, subject, content, score, source_type
    """
    conn = db.connection().connection
    ensure_fts_table(conn)
    ensure_vec_table(conn)

    # ---- 第一路：knowledge_chunks（FTS + 向量）----
    fts_lane = fts_search(conn, query, topn=TOPN_PER_LANE, subject=subject)
    vec_lane: List[Tuple[int, int]] = []
    if query_vec is not None:
        vec_lane = vec_search(conn, query_vec, topn=TOPN_PER_LANE, subject=subject)
    if vec_lane:
        chunk_ids = rrf_fuse(fts_lane, vec_lane)
    else:
        chunk_ids = [cid for cid, _ in fts_lane]

    # ---- 第二路：knowledge_points（知识点）----
    point_ids = _search_knowledge_points(conn, query, topn=TOPN_PER_LANE, subject=subject)

    # ---- 第三路：documents（文档标题/摘要）----
    doc_ids = _search_documents(conn, query, topn=TOPN_PER_LANE, subject=subject)

    # ---- 三路 RRF 融合 ----
    # 给每路的结果分配 rank，然后 RRF 融合
    all_lanes = []
    if chunk_ids:
        all_lanes.append([(cid, i + 1) for i, cid in enumerate(chunk_ids)])
    if point_ids:
        # 知识点用负 ID 区分（-100000 - point_id）
        all_lanes.append([(-100000 - pid, i + 1) for i, pid in enumerate(point_ids)])
    if doc_ids:
        # 文档用负 ID 区分（-200000 - doc_id）
        all_lanes.append([(-200000 - did, i + 1) for i, did in enumerate(doc_ids)])

    if not all_lanes:
        return []

    # 多路 RRF 融合
    fused_scores: Dict[int, float] = {}
    for lane in all_lanes:
        for cid, rank in lane:
            fused_scores[cid] = fused_scores.get(cid, 0) + 1.0 / (RRF_K + rank)

    # 按分数排序
    fused_sorted = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
    fused_ids = [cid for cid, _ in fused_sorted[:limit * 2]]  # 多取一些，后面过滤

    if not fused_ids:
        return []

    # ---- 取详情 ----
    results = []
    chunk_id_list = [cid for cid in fused_ids if cid > 0]
    point_id_list = [abs(cid) - 100000 for cid in fused_ids if -200000 < cid <= -100000]
    doc_id_list = [abs(cid) - 200000 for cid in fused_ids if cid <= -200000]

    # 取 chunks 详情
    if chunk_id_list:
        placeholders = ",".join("?" * len(chunk_id_list))
        rows = conn.execute(
            f"SELECT kc.id, kc.document_id, kc.subject, kc.text, kd.file_name "
            f"FROM knowledge_chunks kc LEFT JOIN documents kd ON kc.document_id = kd.id "
            f"WHERE kc.id IN ({placeholders})",
            chunk_id_list,
        ).fetchall()
        id_to_row = {r[0]: r for r in rows}
        for cid in chunk_id_list:
            if cid in id_to_row:
                r = id_to_row[cid]
                results.append({
                    "chunk_id": r[0],
                    "document_id": r[1],
                    "subject": r[2],
                    "content": r[3] or "",
                    "document_title": r[4] or "",
                    "score": fused_scores.get(cid, 0),
                    "source_type": "chunk",
                })

    # 取 points 详情
    if point_id_list:
        placeholders = ",".join("?" * len(point_id_list))
        rows = conn.execute(
            f"SELECT id, name, description, subject, document_id "
            f"FROM knowledge_points WHERE id IN ({placeholders})",
            point_id_list,
        ).fetchall()
        id_to_row = {r[0]: r for r in rows}
        for pid in point_id_list:
            if pid in id_to_row:
                r = id_to_row[pid]
                results.append({
                    "chunk_id": -100000 - r[0],
                    "document_id": r[4] or 0,
                    "subject": r[3] or "",
                    "content": f"【知识点】{r[1]}\n{r[2] or ''}",
                    "document_title": "",
                    "score": fused_scores.get(-100000 - r[0], 0),
                    "source_type": "knowledge_point",
                    "point_name": r[1],
                })

    # 取 documents 详情
    if doc_id_list:
        placeholders = ",".join("?" * len(doc_id_list))
        rows = conn.execute(
            f"SELECT id, file_name, subject, content, file_type "
            f"FROM documents WHERE id IN ({placeholders})",
            doc_id_list,
        ).fetchall()
        id_to_row = {r[0]: r for r in rows}
        for did in doc_id_list:
            if did in id_to_row:
                r = id_to_row[did]
                # 文档内容取前500字符作为摘要
                doc_content = (r[3] or "")[:500]
                results.append({
                    "chunk_id": -200000 - r[0],
                    "document_id": r[0],
                    "subject": r[2] or "",
                    "content": f"【文档】{r[1]}\n{doc_content}",
                    "document_title": r[1] or "",
                    "score": fused_scores.get(-200000 - r[0], 0),
                    "source_type": "document",
                    "file_type": r[4] or "",
                })

    # ---- RRF 后精排：kaoyan_ai 术语加权（CORE_TERMS/TERM_SYNONYMS/NOISE_TERMS + 前200字符加权）----
    for r in results:
        tb = _term_boost(query, r.get("content") or "")
        r["term_boost"] = tb
        r["score"] = (r.get("score") or 0) + tb

    # 按精排后分数排序，取 limit
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def _search_knowledge_points(
    conn: sqlite3.Connection,
    query: str,
    topn: int = 30,
    subject: Optional[str] = None,
) -> List[int]:
    """检索 knowledge_points（知识点），返回 ID 列表。"""
    tokens = [t for t in segment(query).split() if t]
    if not tokens:
        return []

    # 用 LIKE 匹配 name 和 description（简单但有效）
    conditions = []
    params = []
    for token in tokens[:5]:  # 最多5个关键词
        conditions.append("(name LIKE ? OR description LIKE ?)")
        params.extend([f"%{token}%", f"%{token}%"])

    sql = f"SELECT id FROM knowledge_points WHERE {' AND '.join(conditions)}"
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    sql += " ORDER BY LENGTH(name) LIMIT ?"
    params.append(topn)

    try:
        rows = conn.execute(sql, params).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _search_documents(
    conn: sqlite3.Connection,
    query: str,
    topn: int = 30,
    subject: Optional[str] = None,
) -> List[int]:
    """检索 documents（文档标题/内容），返回 ID 列表。"""
    tokens = [t for t in segment(query).split() if t]
    if not tokens:
        return []

    conditions = []
    params = []
    for token in tokens[:5]:
        conditions.append("(file_name LIKE ? OR content LIKE ?)")
        params.extend([f"%{token}%", f"%{token}%"])

    sql = f"SELECT id FROM documents WHERE {' AND '.join(conditions)}"
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    sql += " ORDER BY LENGTH(file_name) LIMIT ?"
    params.append(topn)

    try:
        rows = conn.execute(sql, params).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def get_index_stats(db: Session) -> dict:
    """获取检索索引统计信息。"""
    conn = db.connection().connection
    ensure_fts_table(conn)
    ensure_vec_table(conn)
    total_chunks = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
    fts_count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks_fts").fetchone()[0]
    vec_count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks_vec WHERE embedding IS NOT NULL").fetchone()[0]
    return {
        "total_chunks": total_chunks,
        "fts_indexed": fts_count,
        "vec_indexed": vec_count,
        "fts_ready": fts_count > 0,
        "vec_ready": vec_count > 0,
    }


# ---------------------------------------------------------------------------
# V3.0 重排（Rerank）：优化检索结果排序
# ---------------------------------------------------------------------------
def rerank_results(results, query, limit=6):
    """对检索结果进行重排，提升相关性。"""
    if not results:
        return []

    query_tokens = set(segment(query).split())
    query_tokens = {t for t in query_tokens if len(t) >= 2}
    if not query_tokens:
        return results[:limit]

    reranked = []
    for r in results:
        content = r.get("content", "") or ""
        source_type = r.get("source_type", "chunk")
        original_score = r.get("score", 0)

        content_lower = content.lower()
        match_count = 0
        match_positions = []
        for token in query_tokens:
            pos = content_lower.find(token.lower())
            if pos >= 0:
                match_count += 1
                match_positions.append(pos)

        coverage = match_count / len(query_tokens) if query_tokens else 0

        source_weight = {
            "knowledge_point": 1.3,
            "chunk": 1.0,
            "document": 0.8,
        }.get(source_type, 1.0)

        content_len = len(content)
        if 200 <= content_len <= 800:
            length_weight = 1.2
        elif 100 <= content_len < 200 or 800 < content_len <= 1500:
            length_weight = 1.0
        else:
            length_weight = 0.8

        title_match = 0
        if source_type == "knowledge_point":
            point_name = (r.get("point_name", "") or "").lower()
            for token in query_tokens:
                if token.lower() in point_name:
                    title_match += 0.5
        elif source_type == "document":
            doc_title = (r.get("document_title", "") or "").lower()
            for token in query_tokens:
                if token.lower() in doc_title:
                    title_match += 0.3

        early_match = 0
        for pos in match_positions:
            if pos < 100:
                early_match += 0.2

        final_score = (
            original_score * 0.4 +
            coverage * 0.3 +
            title_match * 0.15 +
            early_match * 0.15
        ) * source_weight * length_weight

        # 术语加权精排（移植 kaoyan_ai）：核心术语命中数加权 + 噪声词降权
        term_boost = _term_boost(query, content)
        final_score += term_boost

        r["rerank_score"] = final_score
        r["coverage"] = coverage
        r["match_count"] = match_count
        reranked.append(r)

    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return reranked[:limit]


def hybrid_search_with_rerank(db, query, query_vec=None, limit=6, subject=None):
    """混合检索 + 重排（V3.0 推荐使用）。"""
    raw_results = hybrid_search(db, query, query_vec, limit=limit * 3, subject=subject)
    return rerank_results(raw_results, query, limit=limit)


# ---------------------------------------------------------------------------
# V4.0 第 4 路：真题 2-gram 引擎融合（现有三路行为不变，仅新增 exam lane）
# ---------------------------------------------------------------------------
def hybrid_search_with_exam(db, query, query_vec=None, limit=6, subject=None, exam_k=20):
    """混合检索 + 真题双引擎第 4 路融合。

    内部经 services.exam_engine.search_with_exam 实现：
      - 现有三路（chunks/points/documents）RRF 精排结果保持原样
      - 真题 lane 用负 ID（-300000 - doc_id），K=20（1/21 权重约为 K=60 的 2.9 倍）
      - 返回含 source_type='exam_question' 的详情（year/answer/analysis/variants）
    红线：不修改 hybrid_search / rerank_results 任何行为。
    """
    from services.exam_engine import search_with_exam

    # search_with_exam 内部使用 RRF_K_EXAM=20；exam_k 参数保留兼容外部调用方
    return search_with_exam(
        db, query, query_vec=query_vec, limit=limit, subject=subject
    )