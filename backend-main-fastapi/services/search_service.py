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
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from services.dbapi_compat import wrap_conn  # noqa: E402  PG/SQLite 双底座连接适配

logger = logging.getLogger(__name__)

RRF_K: int = 60
TOPN_PER_LANE: int = 30
VEC_MIN_DIST: float = 0.6  # cosine distance 阈值，超过则视为不相关

# ---------------------------------------------------------------------------
# 术语加权精排（移植自 D:\kaoyan_ai\04_app\chat.py 的 KBRetriever._term_boost）
# ---------------------------------------------------------------------------
# 领域核心术语表：检索时对这些词加权，帮助命中真正讲解概念的段落
CORE_TERMS: list[str] = [
    "TTL",
    "CMOS",
    "MOS",
    "DAC",
    "ADC",
    "ROM",
    "RAM",
    "555",
    "74LS",
    "卡诺图",
    "与非门",
    "或非门",
    "触发器",
    "寄存器",
    "计数器",
    "译码器",
    "编码器",
    "选择器",
    "加法器",
    "比较器",
    "锁存器",
    "静态工作点",
    "共射极",
    "放大电路",
    "运算放大器",
    "虚短",
    "虚断",
    "差模",
    "共模",
    "反馈",
    "二极管",
    "三极管",
    "晶体管",
    "稳压",
    "整流",
    "滤波器",
    "振荡器",
    "多谐",
    "施密特",
    "逻辑函数",
    "真值表",
    "二进制",
    "格雷",
    "奇偶校验",
    "传输延迟",
    "扇出",
    "噪声容限",
]

# 同义词组：不同写法但指向同一概念（查询命中任一组内词，则对组内所有写法加权）
TERM_SYNONYMS: list[list[str]] = [
    ["DAC", "D/A转换器", "D/A 转换器", "数模转换器"],
    ["ADC", "A/D转换器", "A/D 转换器", "模数转换器"],
    ["TTL", "晶体管-晶体管逻辑", "晶体管逻辑"],
    ["CMOS", "互补金属氧化物半导体"],
    ["MOS", "金属氧化物半导体"],
    ["RAM", "随机存取存储器", "随机存储器"],
    ["运算放大器", "运放"],
]

# 封面/导航噪声词：命中即降权（教案封面、目录页等非知识点内容）
NOISE_TERMS: list[str] = [
    "授课",
    "课时",
    "教学章",
    "教案",
    "目录",
    "课时安排",
    "授课方式",
    "主讲",
    "章节安排",
]


def _term_boost(query: str, text: str) -> float:
    """核心术语加权：命中的术语越多、出现越靠前，权重越高（概念定义通常在段首）。

    与 kaoyan_ai 原始实现保持一致：术语出现 +2.0/次，前 200 字符 +3.0/次，噪声词 -8.0。
    """
    up = query.upper()
    text_up = text.upper()
    head_up = text[:200].upper()
    boost = 0.0
    for term in CORE_TERMS:
        if term in up:
            cnt = text_up.count(term)
            if cnt:
                boost += cnt * 2.0 + head_up.count(term) * 3.0
    for group in TERM_SYNONYMS:
        if any(t in up for t in group):
            for t in group:
                c = text_up.count(t)
                if c:
                    boost += c * 2.0 + head_up.count(t) * 3.0
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
        tokens: list[str] = list(re.findall(r"[a-zA-Z0-9]{2,}", text.lower()))
        cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
        for i in range(len(cjk) - 1):
            tokens.append(cjk[i : i + 2])
        return " ".join(tokens)


def _fts_query(user_query: str) -> str:
    """构造 FTS5 MATCH 表达式：分词后用 OR 连接带引号词元。"""
    tokens = [t for t in segment(user_query).split() if t]
    if not tokens:
        return '""'
    safe = [_CTRL.sub("", t) for t in tokens]
    return " OR ".join(f'"{t}"' for t in safe if t)


# 停用词：中文疑问句里的高频虚词，进 LIKE/tsquery 只会拖慢召回质量。
_STOPWORDS: frozenset[str] = frozenset(
    {
        "的",
        "了",
        "是",
        "有",
        "和",
        "与",
        "及",
        "在",
        "对",
        "把",
        "被",
        "什么",
        "怎么",
        "怎样",
        "为什么",
        "如何",
        "哪些",
        "哪个",
        "这个",
        "那个",
        "一下",
        "请问",
        "请",
        "问",
        "用",
        "作用",
        "时候",
    }
)

#: tsquery 词元字面量里必须剔除的字符：`'` 结束引号、`\\` 是 tsquery 转义符。
_TS_UNSAFE = re.compile(r"['\\]")


def query_terms(query: str, max_terms: int = 5) -> tuple[str, list[str]]:
    """抽取检索词：返回 ``(整句 core, 关键词列表)``。

    整句 core 用作「短语命中」这一最高权重信号；关键词按长度降序取 ``max_terms``
    个（长词区分度高）。PG 全文路与 PG 文档路共用这一份口径，避免两处漂移。
    """
    core = _CTRL.sub("", (query or "").strip())[:60]
    if not core:
        return "", []
    terms: list[str] = []
    for t in segment(core).split():
        t = _CTRL.sub("", t).strip()
        if len(t) >= 2 and t not in _STOPWORDS and t not in terms:
            terms.append(t)
    return core, sorted(terms, key=len, reverse=True)[:max_terms]


def _tsquery_or(terms: list[str]) -> str:
    """把关键词拼成 `to_tsquery('simple', ...)` 的 OR 查询串（带引号转义）。"""
    parts: list[str] = []
    for t in terms:
        safe = _TS_UNSAFE.sub("", t)
        if safe:
            parts.append(f"'{safe}'")
    return " | ".join(parts)


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
            conn.execute("SELECT 1 FROM knowledge_chunks WHERE search_vector IS NOT NULL LIMIT 1")
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
def _pg_tsvector_candidates(
    conn,
    core: str,
    terms: list[str],
    want: int,
    subject: str | None,
) -> list[tuple[Any, ...]]:
    """PG 全文主查：GIN(`search_vector`) 索引路，返回 [(chunk_id, text, doc_name)]。

    为什么不再用 ILIKE 子串扫（2026-11-23 实测，81348 块）：

    * `text ILIKE '%词%'` 的 OR 组合让优化器放弃 GIN trgm 走全表扫描，且为了
      `ORDER BY length(text)` 把全部命中行的正文拖进排序元组 —— 单条 0.86~1.7 秒，
      是 /api/ai/rag-search 冷启动 2.8 秒里的最大头；
    * `search_vector` 是 020 分片的 GENERATED 列，输入正是**入库时 jieba 预分词**
      的 `search_tokens`，与查询侧 :func:`segment` 同一套分词，因此词元级 `@@`
      匹配覆盖得住原来的子串召回：同一批查询实测命中 3831 vs 3875（差 1.1%）、
      6335 vs 6335、7067 vs 7068，而耗时 4 ms vs 1900 ms。

    排序仍走「窄列排序 + 宽列回取」两段：内层只对 id 排 ts_rank，外层按选中的 id
    取正文，避免上万行 TOAST 正文进排序元组。
    """
    tsq = _tsquery_or(terms) or _tsquery_or([core])
    if not tsq:
        return []
    sql = (
        "SELECT kc.id, kc.text, kc.doc_name FROM knowledge_chunks kc JOIN ("
        " SELECT k2.id AS cid FROM knowledge_chunks k2"
        "  WHERE k2.search_vector @@ to_tsquery('simple', %(q)s) "
    )
    params: dict[str, Any] = {"q": tsq, "n": want}
    if subject:
        sql += " AND k2.subject = %(subject)s"
        params["subject"] = subject
    sql += "  ORDER BY ts_rank(k2.search_vector, to_tsquery('simple', %(q)s)) DESC LIMIT %(n)s) s ON s.cid = kc.id"
    try:
        return conn.execute(sql, params).fetchall()
    except Exception as exc:  # noqa: BLE001 —— 语法/扩展异常一律降级到 ILIKE 兜底路
        logger.warning("PG tsvector 全文路异常，改用 ILIKE 兜底：%s", exc)
        return []


def _pg_ilike_candidates(
    conn,
    core: str,
    terms: list[str],
    want: int,
    subject: str | None,
    exclude: set,
    tsq: str,
) -> list[tuple[Any, ...]]:
    """PG 全文兜底路：子串 ILIKE，只在索引路召回不足 ``topn`` 时才跑。

    保留它是因为历史数据里混有**未经 jieba 分词**的块（词元表里没有它们的中文词），
    纯 tsvector 会漏。与旧版的关键差别：加了 `LIMIT` 屏障的候选池 CTE，排序只在
    池内做（实测同一查询：全命中集 top-N 排序 1.6 秒 → 池内排序 0.2 秒）。
    """
    if not core and not terms:
        return []
    params: dict[str, Any] = {}
    if terms:
        ors = []
        for i, t in enumerate(terms):
            ors.append(f"kc.text ILIKE %(like{i})s")
            params[f"like{i}"] = f"%{t}%"
        pred = " OR ".join(ors)
    else:
        pred = "kc.text ILIKE %(like)s"
        params["like"] = f"%{core}%"

    sql = f"WITH pool AS MATERIALIZED (SELECT kc.id FROM knowledge_chunks kc WHERE ({pred})"
    if tsq:
        sql += " AND NOT (kc.search_vector @@ to_tsquery('simple', %(q)s))"
        params["q"] = tsq
    if exclude:
        sql += " AND kc.id <> ALL(%(ex)s)"
        params["ex"] = list(exclude)
    if subject:
        sql += " AND kc.subject = %(subject)s"
        params["subject"] = subject
    sql += (
        " LIMIT %(scan)s) SELECT kc.id, kc.text, kc.doc_name FROM knowledge_chunks kc"
        " JOIN pool ON pool.id = kc.id ORDER BY length(kc.text) ASC LIMIT %(n)s"
    )
    params["scan"] = max(want * 6, 200)
    params["n"] = want
    try:
        return conn.execute(sql, params).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PG ILIKE 兜底全文路异常：%s", exc)
        return []


def fts_search(
    conn,
    query: str,
    topn: int = TOPN_PER_LANE,
    subject: str | None = None,
) -> list[tuple[int, int]]:
    """全文检索，返回 [(chunk_id, rank)]，rank 从 1 开始。

    PostgreSQL 迁移（2026-10-14）：SQLite 侧走 FTS5 + bm25()；
    PG 侧走原生 `search_vector @@ plainto_tsquery` + ts_rank。
    原先只支持 SQLite，PG 下因 `knowledge_chunks_fts` 表不存在直接抛错，
    导致 hybrid 检索必然失败、退化为 Python 词集 Jaccard 全表扫描。
    """
    if _is_pg(conn):
        return _pg_fts_search(conn, query, topn, subject)

    q_seg = _fts_query(query)
    if q_seg == '""':
        return []
    sql = (
        "SELECT chunk_id, bm25(knowledge_chunks_fts) AS s FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH ?"
    )
    params: list[Any] = [q_seg]
    if subject:
        sql += " AND subject = ?"
        params.append(subject)
    sql += " ORDER BY s LIMIT ?"
    params.append(topn)
    rows = conn.execute(sql, params).fetchall()
    return [(r[0], i + 1) for i, r in enumerate(rows)]


def _pg_fts_search(
    conn,
    query: str,
    topn: int,
    subject: str | None,
) -> list[tuple[int, int]]:
    """PG 全文检索：两段式（候选 + 精排）。

    第一段 候选：GIN 索引路取 candidate_n 条（召回不足才补 ILIKE 池）
    第二段 精排：只对这批候选按「整句命中/命中词数/密度/位置」打分排序
    """
    core, terms = query_terms(query)
    if not core:
        return []
    candidate_n = max(topn * 4, 40)

    rows = _pg_tsvector_candidates(conn, core, terms, candidate_n, subject)
    if len(rows) < topn:
        seen = {r[0] for r in rows}
        rows += _pg_ilike_candidates(conn, core, terms, candidate_n - len(rows), subject, seen, _tsquery_or(terms))
    if not rows:
        # 兜底：关键词未命中时退到向量已无意义，如实返回空
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


# ---------------------------------------------------------------------------
# 向量检索（双后端）
# ---------------------------------------------------------------------------
def vec_search(
    conn,
    query_vec: np.ndarray,
    topn: int = TOPN_PER_LANE,
    subject: str | None = None,
    query_dim: int | None = None,
) -> list[tuple[int, int]]:
    """向量 KNN 检索，返回 [(chunk_id, rank)]。

    PostgreSQL 迁移（2026-10-14）：SQLite 侧保留 numpy 暴力检索（BLOB 存储）；
    PG 侧改用 pgvector 的 `<=>` 余弦距离操作符，走 HNSW 索引
    `idx_chunk_vectors_hnsw`，避免原先把全表向量读进内存做 matmul。
    """
    if _is_pg(conn):
        return _pg_vec_search(conn, query_vec, topn, subject, query_dim)
    return _sqlite_vec_search(conn, query_vec, topn, subject)


def _sqlite_vec_search(
    conn,
    query_vec: np.ndarray,
    topn: int,
    subject: str | None,
) -> list[tuple[int, int]]:
    """SQLite 侧向量检索：numpy 暴力 cosine。"""
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
    valid: list[tuple[int, np.ndarray]] = []
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
    candidates = [(valid[i][0], float(1.0 - sims[i])) for i in range(len(valid)) if (1.0 - sims[i]) < VEC_MIN_DIST]
    candidates.sort(key=lambda x: x[1])
    return [(c, i + 1) for i, (c, _d) in enumerate(candidates[:topn])]


def _pg_vec_search(
    conn,
    query_vec: np.ndarray,
    topn: int,
    subject: str | None,
    query_dim: int | None,
) -> list[tuple[int, int]]:
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
def rrf_fuse(*lanes: list[tuple[int, int]], k: int = RRF_K) -> list[int]:
    """Reciprocal Rank Fusion，返回融合后的 chunk_id 列表（按分数降序）。"""
    scores: dict[int, float] = {}
    for lane in lanes:
        for chunk_id, rank in lane:
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return [cid for cid, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


# ---------------------------------------------------------------------------
# 对外主接口
# ---------------------------------------------------------------------------
_SUBJECT_FILTER_SENTINELS: frozenset[str] = frozenset(
    {
        "",
        "全部科目",
        "全部",
        "所有科目",
        "all",
        "All",
        "*",
    }
)


def normalize_subject_filter(subject: str | None) -> str | None:
    """学科过滤参数归一（2026-11-21 审计 P1-11 修复）。

    前端「全部科目」哨兵值此前被当字面学科名去匹配，必然空结果。
    哨兵值一律归一为 None（不过滤）；其余仅做 strip。
    """
    if subject is None:
        return None
    s = str(subject).strip()
    return None if s in _SUBJECT_FILTER_SENTINELS else s


# 知识点 / 文档用负 ID 区分，避免与 chunk_id 冲突
_POINT_ID_OFFSET = 100000
_DOC_ID_OFFSET = 200000


def _encode_point_id(pid: int) -> int:
    """知识点 ID → 负 ID（与 chunk_id 区分）。"""
    return -_POINT_ID_OFFSET - pid


def _encode_doc_id(did: int) -> int:
    """文档 ID → 负 ID（与 chunk_id 区分）。"""
    return -_DOC_ID_OFFSET - did


def _decode_fused_id(cid: int) -> tuple[str, int]:
    """融合 ID → (类型, 原始 ID)。类型 ∈ {'chunk', 'point', 'doc'}。"""
    if cid > 0:
        return "chunk", cid
    if -_DOC_ID_OFFSET < cid <= -_POINT_ID_OFFSET:
        return "point", abs(cid) - _POINT_ID_OFFSET
    return "doc", abs(cid) - _DOC_ID_OFFSET


def hybrid_search(
    db: Session,
    query: str,
    query_vec: np.ndarray | None = None,
    limit: int = 6,
    subject: str | None = None,
) -> list[dict]:
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
    subject = normalize_subject_filter(subject)

    # ---- 第一路：knowledge_chunks（FTS + 向量）----
    fts_lane = fts_search(conn, query, topn=TOPN_PER_LANE, subject=subject)
    vec_lane: list[tuple[int, int]] = []
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
    all_lanes: list[list[tuple[int, int]]] = []
    if chunk_ids:
        all_lanes.append([(cid, i + 1) for i, cid in enumerate(chunk_ids)])
    if point_ids:
        all_lanes.append([(_encode_point_id(pid), i + 1) for i, pid in enumerate(point_ids)])
    if doc_ids:
        all_lanes.append([(_encode_doc_id(did), i + 1) for i, did in enumerate(doc_ids)])

    if not all_lanes:
        return []

    # 多路 RRF 融合
    fused_scores: dict[int, float] = {}
    for lane in all_lanes:
        for cid, rank in lane:
            fused_scores[cid] = fused_scores.get(cid, 0) + 1.0 / (RRF_K + rank)

    # 按分数排序
    fused_sorted = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
    fused_ids = [cid for cid, _ in fused_sorted[: limit * 2]]  # 多取一些，后面过滤

    if not fused_ids:
        return []

    # ---- 取详情（按类型分桶，批量查询避免 N+1）----
    results = _fetch_fused_details(conn, fused_ids, fused_scores)

    # ---- RRF 后精排：kaoyan_ai 术语加权（CORE_TERMS/TERM_SYNONYMS/NOISE_TERMS + 前200字符加权）----
    for r in results:
        tb = _term_boost(query, r.get("content") or "")
        r["term_boost"] = tb
        r["score"] = (r.get("score") or 0) + tb

    # 按精排后分数排序，取 limit
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def _fetch_fused_details(
    conn,
    fused_ids: list[int],
    fused_scores: dict[int, float],
) -> list[dict]:
    """按融合 ID 分桶批量取详情，返回结果列表（未排序）。"""
    chunk_id_list = [cid for cid in fused_ids if cid > 0]
    point_id_list = [abs(cid) - _POINT_ID_OFFSET for cid in fused_ids if -_DOC_ID_OFFSET < cid <= -_POINT_ID_OFFSET]
    doc_id_list = [abs(cid) - _DOC_ID_OFFSET for cid in fused_ids if cid <= -_DOC_ID_OFFSET]

    results: list[dict] = []
    if chunk_id_list:
        results.extend(_fetch_chunk_details(conn, chunk_id_list, fused_scores))
    if point_id_list:
        results.extend(_fetch_point_details(conn, point_id_list, fused_scores))
    if doc_id_list:
        results.extend(_fetch_doc_details(conn, doc_id_list, fused_scores))
    return results


def _fetch_chunk_details(
    conn,
    chunk_id_list: list[int],
    fused_scores: dict[int, float],
) -> list[dict]:
    """批量取 knowledge_chunks 详情。"""
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
    out: list[dict] = []
    for cid in chunk_id_list:
        if cid not in id_to_row:
            continue
        r = id_to_row[cid]
        out.append(
            {
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
            }
        )
    return out


def _fetch_point_details(
    conn,
    point_id_list: list[int],
    fused_scores: dict[int, float],
) -> list[dict]:
    """批量取 knowledge_points 详情。"""
    placeholders = ",".join("?" * len(point_id_list))
    rows = conn.execute(
        f"SELECT id, name, description, subject, document_id FROM knowledge_points WHERE id IN ({placeholders})",
        point_id_list,
    ).fetchall()
    id_to_row = {r[0]: r for r in rows}
    out: list[dict] = []
    for pid in point_id_list:
        if pid not in id_to_row:
            continue
        r = id_to_row[pid]
        out.append(
            {
                "chunk_id": _encode_point_id(r[0]),
                "document_id": r[4] or 0,
                "subject": r[3] or "",
                "content": f"【知识点】{r[1]}\n{r[2] or ''}",
                "document_title": "",
                "doc_name": "",
                "page_start": None,
                "page_end": None,
                "chunk_index": None,
                "score": fused_scores.get(_encode_point_id(r[0]), 0),
                "source_type": "knowledge_point",
                "point_name": r[1],
            }
        )
    return out


def _fetch_doc_details(
    conn,
    doc_id_list: list[int],
    fused_scores: dict[int, float],
) -> list[dict]:
    """批量取 documents 详情。

    PostgreSQL 迁移修正（2026-10-14）：原写法有两处 PG 不兼容
      1. `documents.file_type` 在 PG canonical schema 里已改名 `source_format`
         （ADR-002 格式归一：source_format 记录原始格式、canonical_content 存中间态）；
      2. `?` 占位符在 psycopg 下非法（只认 %s）。
    经 dbapi_compat 适配后两处都可执行，业务侧无需区分后端。
    """
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
    out: list[dict] = []
    for did in doc_id_list:
        if did not in id_to_row:
            continue
        r = id_to_row[did]
        # 文档内容取前500字符作为摘要
        doc_content = (r[3] or "")[:500]
        out.append(
            {
                "chunk_id": _encode_doc_id(r[0]),
                "document_id": r[0],
                "subject": r[2] or "",
                "content": f"【文档】{r[1]}\n{doc_content}",
                "document_title": r[1] or "",
                "doc_name": r[1] or "",
                "page_start": None,
                "page_end": None,
                "chunk_index": None,
                "score": fused_scores.get(_encode_doc_id(r[0]), 0),
                "source_type": "document",
                "file_type": r[4] or "",
            }
        )
    return out


def _search_knowledge_points(
    conn: sqlite3.Connection,
    query: str,
    topn: int = 30,
    subject: str | None = None,
) -> list[int]:
    """检索 knowledge_points（知识点），返回 ID 列表。"""
    tokens = [t for t in segment(query).split() if t]
    if not tokens:
        return []

    # 用 LIKE 匹配 name 和 description（简单但有效）
    conditions: list[str] = []
    params: list[Any] = []
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


def _pg_doc_ids_for_term(conn, term: str, subject: str | None) -> set:
    """单个关键词命中的文档集合：标题（GIN trgm，列小）∪ 分块正文（GIN tsvector）。

    分块就是文档正文切出来的（实测 2666 篇里 2600 篇已切块），所以"正文含该词"
    这一判据在 GIN 索引上算，而不是在 64 MB 的 `documents.content` 上扫。
    """
    tsq = _tsquery_or([term])
    ids: set = set()
    if tsq:
        sql = (
            "SELECT kc.document_id FROM knowledge_chunks kc"
            " WHERE kc.search_vector @@ to_tsquery('simple', %(q)s) AND kc.document_id IS NOT NULL"
        )
        params: dict[str, Any] = {"q": tsq}
        if subject:
            sql += " AND kc.subject = %(subject)s"
            params["subject"] = subject
        ids.update(r[0] for r in conn.execute(sql, params).fetchall())
    tsql = "SELECT d.id FROM documents d WHERE d.is_junk IS NOT TRUE AND d.file_name ILIKE %(t)s"
    tparams: dict[str, Any] = {"t": f"%{term}%"}
    if subject:
        tsql += " AND d.subject = %(subject)s"
        tparams["subject"] = subject
    ids.update(r[0] for r in conn.execute(tsql, tparams).fetchall())
    return ids


def _pg_unindexed_doc_ids(conn, terms: list[str], subject: str | None, want: int) -> list[int]:
    """尚未切块的文档（实测 66/2666）没有索引可走，只能回落到原始 content 蒙词。

    用 `NOT EXISTS(分块)` 先把扫描面压到那几十行，再对 content 做 ILIKE，
    这样"无索引全表扫 64 MB"就只剩历史欠账的那一小截。
    """
    if not terms:
        return []
    conds = " AND ".join(f"(u.file_name ILIKE %(t{i})s OR u.content ILIKE %(t{i})s)" for i in range(len(terms)))
    params: dict[str, Any] = {f"t{i}": f"%{t}%" for i, t in enumerate(terms)}
    # AS MATERIALIZED 是必需的屏障：直接写 WHERE ... AND (content ILIKE ...) 时
    # 优化器按自身的低成本估计把 content 蒙词排到 NOT EXISTS 之前，实测仍要
    # 500~630 ms（64 MB TOAST 全表求值）；先物化"未切块"那几十行再判正文 = 11~22 ms。
    sql = (
        "WITH u AS MATERIALIZED ("
        " SELECT d.id, d.file_name, d.content FROM documents d"
        "  WHERE d.is_junk IS NOT TRUE"
        "   AND NOT EXISTS (SELECT 1 FROM knowledge_chunks kc WHERE kc.document_id = d.id)"
        " )"
        f" SELECT u.id FROM u WHERE ({conds})"
    )
    if subject:
        sql += " AND EXISTS (SELECT 1 FROM documents d2 WHERE d2.id = u.id AND d2.subject = %(subject)s)"
        params["subject"] = subject
    sql += " ORDER BY length(u.file_name) ASC LIMIT %(n)s"
    params["n"] = want
    try:
        return [r[0] for r in conn.execute(sql, params).fetchall()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("PG 未切块文档兜底检索异常：%s", exc)
        return []


def _pg_search_documents(conn, query: str, topn: int, subject: str | None) -> list[int]:
    """PG 文档路：跨词取交集（= 旧版 AND 语义），排序按标题长度升序（口径不变）。

    旧实现是一条 `AND (file_name LIKE ? OR content LIKE ?)` ×5 蒙词，PG 下对
    documents.content（64 MB TOAST）全表求值，实测 0.4~1.0 秒/次，占 rag-search
    剩余耗时的大头；补 pg_trgm GIN 也救不了（实测常见中文词命中七成文档，
    走位图索引后 recheck 仍要把正文读出来：0.72 秒 vs 全表 0.66 秒）。
    """
    core, terms = query_terms(query)
    if not terms:
        terms = [core] if core else []
    if not terms:
        return []
    try:
        sets = [_pg_doc_ids_for_term(conn, t, subject) for t in terms]
        hits = set.intersection(*[s for s in sets]) if sets else set()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PG 文档路（索引交集）异常：%s", exc)
        hits = set()
    # 排序口径与旧版一致：短文件名（通常是主题文档）优先
    out: list[int] = []
    if hits:
        try:
            rows = conn.execute(
                "SELECT d.id FROM documents d WHERE d.id = ANY(%(ids)s) AND d.is_junk IS NOT TRUE"
                " ORDER BY length(d.file_name) ASC LIMIT %(n)s",
                {"ids": list(hits), "n": topn},
            ).fetchall()
            out = [r[0] for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("PG 文档路排序异常：%s", exc)
            out = list(hits)[:topn]
    if len(out) < topn:
        out += _pg_unindexed_doc_ids(conn, terms, subject, topn - len(out))
    return out


def _search_documents(
    conn: sqlite3.Connection,
    query: str,
    topn: int = 30,
    subject: str | None = None,
) -> list[int]:
    """检索 documents（文档标题/内容），返回 ID 列表。

    PG 走 :func:`_pg_search_documents`（GIN 索引路）；SQLite 保留原 LIKE 蒙词
    （FTS5 影子表只覆盖分块，文档级标题匹配数据量小，实测毫秒级）。
    """
    if _is_pg(conn):
        return _pg_search_documents(conn, query, topn, subject)

    tokens = [t for t in segment(query).split() if t]
    if not tokens:
        return []

    conditions: list[str] = []
    params: list[Any] = []
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
        total_chunks = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE search_vector IS NOT NULL").fetchone()[0]
        vec_count = conn.execute("SELECT COUNT(*) FROM chunk_vectors WHERE embedding_f32 IS NOT NULL").fetchone()[0]
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
    vec_count = conn.execute("SELECT COUNT(*) FROM knowledge_chunks_vec WHERE embedding IS NOT NULL").fetchone()[0]
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
# 来源类型权重（知识点 > 分块 > 文档）
_SOURCE_WEIGHTS: dict[str, float] = {
    "knowledge_point": 1.3,
    "chunk": 1.0,
    "document": 0.8,
}


def _length_weight(content_len: int) -> float:
    """按内容长度给长度权重：中等长度（200~800）最优。"""
    if 200 <= content_len <= 800:
        return 1.2
    if 100 <= content_len < 200 or 800 < content_len <= 1500:
        return 1.0
    return 0.8


def _title_match_bonus(source_type: str, r: dict, query_tokens: set[str]) -> float:
    """标题命中加分：知识点名命中 +0.5/词，文档标题命中 +0.3/词。"""
    bonus = 0.0
    if source_type == "knowledge_point":
        point_name = (r.get("point_name", "") or "").lower()
        for token in query_tokens:
            if token.lower() in point_name:
                bonus += 0.5
    elif source_type == "document":
        doc_title = (r.get("document_title", "") or "").lower()
        for token in query_tokens:
            if token.lower() in doc_title:
                bonus += 0.3
    return bonus


def rerank_results(results, query, limit=6):
    """对检索结果进行重排，提升相关性。"""
    if not results:
        return []

    query_tokens = {t for t in segment(query).split() if len(t) >= 2}
    if not query_tokens:
        return results[:limit]

    reranked: list[dict] = []
    for r in results:
        content = r.get("content", "") or ""
        source_type = r.get("source_type", "chunk")
        original_score = r.get("score", 0)

        content_lower = content.lower()
        match_count = 0
        match_positions: list[int] = []
        for token in query_tokens:
            pos = content_lower.find(token.lower())
            if pos >= 0:
                match_count += 1
                match_positions.append(pos)

        coverage = match_count / len(query_tokens)

        source_weight = _SOURCE_WEIGHTS.get(source_type, 1.0)
        length_weight = _length_weight(len(content))
        title_match = _title_match_bonus(source_type, r, query_tokens)

        early_match = sum(0.2 for pos in match_positions if pos < 100)

        final_score = (
            (original_score * 0.4 + coverage * 0.3 + title_match * 0.15 + early_match * 0.15)
            * source_weight
            * length_weight
        )

        # 术语加权精排（移植 kaoyan_ai）：核心术语命中数加权 + 噪声词降权
        final_score += _term_boost(query, content)

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
    return search_with_exam(db, query, query_vec=query_vec, limit=limit, subject=subject)
