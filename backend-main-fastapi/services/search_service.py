# -*- coding: utf-8 -*-
"""混合检索服务：FTS5 (BM25) + 向量KNN + RRF融合。

移植自 D:\\学习平台 的 search_service.py，适配 kaoyan-study-platform 的
SQLAlchemy + SQLite 架构。向量后端默认 numpy brute-force（无需 vec0 扩展），
embedding 通过在线 API 生成（豆包/通义兼容接口）。
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session
from services.dbapi_compat import wrap_conn  # noqa: E402  PG/SQLite 双底座连接适配

logger = logging.getLogger(__name__)

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


def _is_pg(conn) -> bool:
    """连接是否为 PostgreSQL（用于检索层双后端分流）。

    用 dbapi_compat.is_postgres（按模块名判定），不依赖全局配置，
    避免"测试连 PG 但配置说 SQLite"的错配。
    """
    from services.dbapi_compat import is_postgres
    return is_postgres(conn)


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
def ensure_fts_table(conn) -> None:
    """确保全文检索可用。

    PostgreSQL 迁移（2026-10-14）：PG 侧**不需要建表**——`knowledge_chunks`
    自带 `search_vector tsvector`（生成列）与 GIN 索引 `idx_chunks_search`，
    实测 61041 行全部已填充。SQLite 侧保留原有 FTS5 虚表逻辑。
    """
    if _is_pg(conn):
        # PG：确认生成列与索引就位即可，无需同步数据
        try:
            conn.execute(
                "SELECT 1 FROM knowledge_chunks WHERE search_vector IS NOT NULL LIMIT 1"
            )
        except Exception:  # noqa: BLE001
            logger.warning("PG 侧 knowledge_chunks.search_vector 不可用，全文检索将降级")
        return

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


def ensure_vec_table(conn) -> None:
    """确保向量表存在。

    PostgreSQL 迁移（2026-10-14）：PG 侧向量表是 `chunk_vectors`
    （pgvector 的 `embedding_f32` 列 + HNSW 索引 `idx_chunk_vectors_hnsw`），
    由 core/sql/020 分片建好，**无需运行时建表**。SQLite 侧保留原 BLOB 表。
    """
    if _is_pg(conn):
        return

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
    conn = wrap_conn(db.connection().connection)
    ensure_fts_table(conn)
    ensure_vec_table(conn)


# ---------------------------------------------------------------------------
# 全文检索（双后端）
# ---------------------------------------------------------------------------
def fts_search(
    conn,
    query: str,
    topn: int = TOPN_PER_LANE,
    subject: Optional[str] = None,
) -> List[Tuple[int, int]]:
    """全文检索，返回 [(chunk_id, rank)]，rank 从 1 开始。

    PostgreSQL 迁移（2026-10-14）：SQLite 侧走 FTS5 + bm25()；
    PG 侧走原生 `search_vector @@ plainto_tsquery` + ts_rank。
    原先只支持 SQLite，PG 下因 `knowledge_chunks_fts` 表不存在直接抛错，
    导致 hybrid 检索必然失败、退化为 Python 词集 Jaccard 全表扫描。
    """
    if _is_pg(conn):
        # 全文检索策略（2026-10-14 建立，2026-10-20 修正召回）
        # ------------------------------------------------
        # 实测 `knowledge_chunks.search_vector` 的词元**并非全部按中文词切分**：
        #   有的块切成 '卡诺图'（正确），有的整句存成 '用卡诺图化简下列逻辑函数。'（未切）。
        # 因此单纯 `to_tsquery('simple', '傅里叶 & 变换')` 会大量漏召回。
        #
        # 现行策略（两段式，ILIKE + trgm 索引）：
        #   第一段 主查：把 query 分词成关键词后 OR 做 ILIKE，取 limit*4 条候选
        #                （中文无分词依赖；整句原样作为最高权重信号，防误召回）；
        #   第二段 精排：只对这批候选按「整句命中/命中词数/密度/位置」打分排序。
        # 2026-10-20 之前主查用的是**整句** ILIKE（`%译码器的使能端有什么用%`），
        # 自然语言提问几乎不可能原样出现在某个 chunk 里，全文一路长期召回 0 条，
        # 混合检索实际只剩向量一路 —— 这是本次修正的直接原因。
        # 性能上仍只扫候选池，不把排序范围放大到全表（历史版本曾因此 13.1 秒）。
        text_q = (query or "").strip()
        if not text_q:
            return []
        core = _CTRL.sub("", text_q)[:60]
        if not core:
            return []

        # 性能关键（2026-10-14 实测校准）：
        # 上一版把 ILIKE / tsvector / similarity() 混在一个 SELECT 里加权排序，
        # 优化器因此放弃索引走全表扫描，6 万行耗时 13.1 秒。
        # 实测 `ILIKE '%x%'` 单独用是能走 GIN trgm 索引的
        # （EXPLAIN 显示 Bitmap Index Scan on idx_chunks_text_trgm）。
        #
        # 改为**两段式**：
        #   第一段 主查：ILIKE + trgm 索引，取 limit*4 条候选（毫秒级）
        #   第二段 精排：只对这批候选算 ts_rank/similarity 加权排序
        # 这样既保留了三段式的召回质量，又把排序范围从 6 万行压到几十行。
        # 召回策略修正（2026-10-20）：
        # 旧实现把**整句**当子串 `ILIKE '%译码器的使能端有什么用%'`，自然语言提问
        # 几乎不可能原样出现在某个 chunk 里 → 全文这一路长期返回空，混合检索实际
        # 只剩向量一路（向量一挂就完全无召回）。这里改为按分词后的关键词 OR 召回，
        # 再用命中词数/密度精排，保留"整句子串"作为最高权重信号。
        stop = {"的", "了", "是", "有", "和", "与", "及", "在", "对", "把", "被",
                "什么", "怎么", "怎样", "为什么", "如何", "哪些", "哪个", "这个",
                "那个", "一下", "请问", "请", "问", "用", "作用", "时候"}
        terms = []
        for t in segment(core).split():
            t = _CTRL.sub("", t).strip()
            if len(t) >= 2 and t not in stop and t not in terms:
                terms.append(t)
        # 长词区分度高：最多取 5 个
        terms = sorted(terms, key=len, reverse=True)[:5]

        candidate_n = max(topn * 4, 40)
        if terms:
            ors = []
            params: dict[str, Any] = {}
            for i, t in enumerate(terms):
                ors.append(f"kc.text ILIKE %(like{i})s")
                params[f"like{i}"] = f"%{t}%"
            sql = (
                "SELECT kc.id, kc.text, kc.doc_name FROM knowledge_chunks kc "
                f"WHERE ({' OR '.join(ors)})"
            )
        else:
            sql = (
                "SELECT kc.id, kc.text, kc.doc_name FROM knowledge_chunks kc "
                "WHERE kc.text ILIKE %(like)s"
            )
            params = {"like": f"%{core}%"}
        if subject:
            # subject 用子查询换算成 subject_id，与 030 分片的外键设计一致
            sql += " AND kc.subject = %(subject)s"
            params["subject"] = subject
        sql += " ORDER BY length(kc.text) ASC LIMIT %(n)s"
        params["n"] = candidate_n
        rows = conn.execute(sql, params).fetchall()
        if not rows:
            # 兜底：关键词未命中时退到向量/tsvector 已无意义，如实返回空
            return []

        # 精排：整句命中 > 命中词多 > 密度高 > 位置靠前；长度短者优先
        match_terms = terms or [core]
        scored: list[tuple[int, float]] = []
        for cid, txt, _doc in rows:
            t = txt or ""
            phrase_hit = t.count(core)
            hit_n = sum(1 for term in match_terms if term in t)
            total_hits = sum(t.count(term) for term in match_terms)
            density = total_hits / max(1, len(t))
            first_pos = min((t.find(term) for term in match_terms if term in t), default=-1)
            pos_bonus = 1.0 if 0 <= first_pos < 120 else 0.0
            score = phrase_hit * 3.0 + hit_n * 2.0 + density * 800 + pos_bonus
            scored.append((cid, score))
        scored.sort(key=lambda x: -x[1])
        return [(cid, i + 1) for i, (cid, _s) in enumerate(scored[:topn])]

    q_seg = _fts_query(query)
    if q_seg == '""':
        return []
    sql = (
        "SELECT chunk_id, bm25(knowledge_chunks_fts) AS s "
        "FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH ?"
    )
    params = [q_seg]
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    sql += " ORDER BY s LIMIT ?"
    params.append(topn)
    rows = conn.execute(sql, params).fetchall()
    return [(r[0], i + 1) for i, r in enumerate(rows)]


# ---------------------------------------------------------------------------
# 向量检索（双后端）
# ---------------------------------------------------------------------------
def vec_search(
    conn,
    query_vec: np.ndarray,
    topn: int = TOPN_PER_LANE,
    subject: Optional[str] = None,
    query_dim: Optional[int] = None,
) -> List[Tuple[int, int]]:
    """向量 KNN 检索，返回 [(chunk_id, rank)]。

    PostgreSQL 迁移（2026-10-14）：SQLite 侧保留 numpy 暴力检索（BLOB 存储）；
    PG 侧改用 pgvector 的 `<=>` 余弦距离操作符，走 HNSW 索引
    `idx_chunk_vectors_hnsw`，避免原先把全表向量读进内存做 matmul。
    """
    if _is_pg(conn):
        return _pg_vec_search(conn, query_vec, topn, subject, query_dim)

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


def _pg_vec_search(
    conn,
    query_vec: np.ndarray,
    topn: int,
    subject: Optional[str],
    query_dim: Optional[int],
) -> List[Tuple[int, int]]:
    """PG 侧向量检索：pgvector `<=>` 余弦距离 + HNSW 索引 `idx_chunk_vectors_hnsw`。

    列名澄清（实测踩坑）：`chunk_vectors` 有两个向量承载列 —
      * `embedding`     bytea（退化方案，Python 侧检索引用）
      * `embedding_f32` vector(512)（**pgvector 列，HNSW 索引建在这一列上**）
    早期实现误用了 `embedding`（bytea 列无法用 `<=>` 运算符），且报错被 debug 吞掉，
    表现为"静默返回空"。现在显式指向 `embedding_f32`。
    """
    try:
        vec = np.asarray(query_vec, dtype=np.float32)
        if vec.ndim != 1:
            return []
        lit = "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"
        # 红线 3：违禁文档（非 0854 学科）的分块不参与语义召回
        sql = (
            "SELECT chunk_id FROM chunk_vectors cv "
            "WHERE cv.embedding_f32 IS NOT NULL "
            "  AND NOT EXISTS (SELECT 1 FROM documents d "
            "                  WHERE d.id = cv.document_id AND d.is_junk IS TRUE)"
        )
        params: list[Any] = []
        if subject:
            sql += " AND subject_id IN (SELECT id FROM subjects WHERE name = %s)"
            params.append(subject)
        # 查询向量出现两次（一次供 ORDER BY 走 HNSW，一次用于 SELECT 距离列可省）
        sql += " ORDER BY embedding_f32 <=> %s::vector LIMIT %s"
        params.extend([lit, topn])
        rows = conn.execute(sql, params).fetchall()
        return [(r[0], i + 1) for i, r in enumerate(rows)]
    except Exception as exc:  # noqa: BLE001
        # 向量未灌库（历史上 chunk_vectors 为 0 行）或 pgvector 不可用：
        # 如实返回空，让 hybrid 融合降级为纯全文检索，而不是中断整条问答链。
        # 用 warning 而非 debug：这类问题必须能在日志里看见，否则又会"静默失效"。
        logger.warning("PG 向量检索失败（向量未灌库或 pgvector 异常）：%s", exc)
        return []


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
    conn = wrap_conn(db.connection().connection)
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
            f"SELECT kc.id, kc.document_id, kc.subject, kc.text, "
            f"       COALESCE(kc.doc_name, kd.file_name) AS doc_name, "
            f"       kc.page_start, kc.page_end, kc.chunk_index "
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
                    # 引用溯源（2026-10-20）：答疑回答必须能标到「哪份文档、第几页」。
                    # page_start 由解析阶段写入；历史 docx 资料可能为 NULL，
                    # 此时前端/回答退化为「第 N 段」（chunk_index）。
                    "doc_name": r[4] or "",
                    "page_start": r[5],
                    "page_end": r[6],
                    "chunk_index": r[7],
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
                    "doc_name": "",
                    "page_start": None,
                    "page_end": None,
                    "chunk_index": None,
                    "score": fused_scores.get(-100000 - r[0], 0),
                    "source_type": "knowledge_point",
                    "point_name": r[1],
                })

    # 取 documents 详情
    #
    # PostgreSQL 迁移修正（2026-10-14）：原写法有两处 PG 不兼容
    #   1. `documents.file_type` 在 PG canonical schema 里已改名 `source_format`
    #      （ADR-002 格式归一：source_format 记录原始格式、canonical_content 存中间态）；
    #   2. `?` 占位符在 psycopg 下非法（只认 %s）。
    # 经 dbapi_compat 适配后两处都可执行，业务侧无需区分后端。
    if doc_id_list:
        from services.dbapi_compat import adapt_sql, is_postgres

        _pg = is_postgres(conn)
        _fmt_col = "source_format" if _pg else "file_type"
        placeholders = ",".join("?" * len(doc_id_list))
        _sql = (
            f"SELECT id, file_name, subject, content, {_fmt_col} "
            f"FROM documents WHERE id IN ({placeholders}) AND is_junk IS NOT TRUE"
        )
        rows = conn.execute(adapt_sql(_sql, conn), doc_id_list).fetchall()
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
                    "doc_name": r[1] or "",
                    "page_start": None,
                    "page_end": None,
                    "chunk_index": None,
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
    # 红线 3：违禁/废弃文档（非 0854 学科）不参与检索
    sql += " AND is_junk IS NOT TRUE"
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
    """获取检索索引统计信息。

    两条路径（务必分清，曾因此 /api/ai/search-status 恒 500）：

      * **PostgreSQL**：FTS 是 `knowledge_chunks.search_vector` 原生列
        （GIN 索引），向量是 `chunk_vectors.embedding_f32`（pgvector + HNSW）。
        镜像表 `knowledge_chunks_fts/_vec` **在 PG 侧不存在**
        （`ensure_fts_table` / `ensure_vec_table` 对 PG 直接 return）。
      * **SQLite**：FTS5 虚表 + BLOB 向量表，即那两个镜像表。
    """
    conn = wrap_conn(db.connection().connection)

    if _is_pg(conn):
        total_chunks = conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks"
        ).fetchone()[0]
        fts_count = conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE search_vector IS NOT NULL"
        ).fetchone()[0]
        vec_count = conn.execute(
            "SELECT COUNT(*) FROM chunk_vectors WHERE embedding_f32 IS NOT NULL"
        ).fetchone()[0]
        return {
            "total_chunks": total_chunks,
            "fts_indexed": fts_count,
            "vec_indexed": vec_count,
            "fts_ready": fts_count > 0,
            "vec_ready": vec_count > 0,
            # 明示口径：前端「索引状态」卡片按这个字段显示表名
            "backend": "postgresql",
            "fts_table": "knowledge_chunks.search_vector",
            "vec_table": "chunk_vectors.embedding_f32",
        }

    ensure_fts_table(conn)
    ensure_vec_table(conn)
    total_chunks = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
    fts_count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks_fts").fetchone()[0]
    vec_count = conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks_vec WHERE embedding IS NOT NULL"
    ).fetchone()[0]
    return {
        "total_chunks": total_chunks,
        "fts_indexed": fts_count,
        "vec_indexed": vec_count,
        "fts_ready": fts_count > 0,
        "vec_ready": vec_count > 0,
        "backend": "sqlite",
        "fts_table": "knowledge_chunks_fts",
        "vec_table": "knowledge_chunks_vec",
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