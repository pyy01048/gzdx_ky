# -*- coding: utf-8 -*-
"""
A7 真题双引擎（services/exam_engine.py）
========================================
将 D:\\真题（公共课）\\专有答疑模型\\index.pkl（2-gram 字符倒排，2712 题）直接挂进
FastAPI 进程（lru 单例，避免 HTTP 往返），作为检索第 4 路 lane 与现有三路
（chunks/points/documents）RRF 融合。

四阶段检索（与 qa_engine.py 同口径，代码自研重写）：
  ① NFKC 归一 + 去空白 + 小写（构建与查询同口径）
  ② 2-gram 倒排累加 idf（idf = log((N-df+0.5)/(df+0.5)+1)）
  ③ BM25 变体 + 长度归一化 + 覆盖率加权 ×(0.7+0.3*coverage)
  ④ OCR 噪声惩罚（白名单外字符占比阶梯降权）+ 二次校验重排 top-60
     （中英考点映射 +6/条、年份 +8、有答案 +6/无答案 -1、乱码强降权 -60）

接口：
  get_exam_index()                —— lru 单例
  retrieve(query, k, subject)     —— [(doc_id, score, hits)]
  find_variants(doc_id, k)        —— [(doc_id, jaccard, score, hits)]
  format_question(doc_id)         —— 题目格式化文本
  search_with_exam(db, query, query_vec, limit, subject)
                                   —— 与 search_service 三路 RRF 融合（exam K=20）
"""
from __future__ import annotations

import logging
import math
import pickle
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 路径与常量（qa_engine 同口径）
# --------------------------------------------------------------------------- #
INDEX_FILE = Path(r"D:\真题（公共课）\专有答疑模型\index.pkl")

SUBJECTS = ["math2", "english1", "english2", "politics"]
SUBJECT_ALIAS = {
    "数学": "math2", "数二": "math2", "数2": "math2", "数学二": "math2",
    "数一": "math1", "数学一": "math1", "数三": "math3", "数学三": "math3",
    "英语": "english1", "英语一": "english1", "英一": "english1", "英二": "english2",
    "英语二": "english2",
    "政治": "politics", "马原": "politics", "毛中特": "politics",
    "math2": "math2", "math1": "math1", "math3": "math3",
    "english1": "english1", "english2": "english2", "politics": "politics",
}

IDF_K1 = 1.2
IDF_B = 0.75
DEFAULT_K = 5
MAX_K = 20
RRF_K_EXAM = 20          # exam lane 用 K=20：权重 1/21 ≈ 2.9 倍于 K=60
EXAM_LANE_BASE = -300000  # 负 ID 区分第 4 路

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_OCR_WEIRD_RE = re.compile(
    r"[^\u4e00-\u9fffA-Za-z0-9=+*/\-−()（）,，.。:：;；'\"_【】〖〗\[\]{}、？！？%√∞πλθμ∑∫≤≥]"
)

# 考点中英等价映射（OCR 题面常丢失中文考点词、仅保留数学符号）
_ALIAS_MAP = {
    "极限": ["lim"],
    "导数": ["derivative", "dy/dx", "y'", "f'(x)"],
    "积分": ["integral", "dx", "∫"],
    "微分方程": ["equation", "y''"],
    "矩阵": ["matrix", "rank"],
    "行列式": ["det"],
    "特征值": ["eigenvalue", "λ"],
    "级数": ["series", "∑"],
    "切线": ["tangent"],
    "极值": ["extreme", "max", "min"],
}


# --------------------------------------------------------------------------- #
# 文本归一化与 n-gram（构建与查询同口径）
# --------------------------------------------------------------------------- #
def norm_text(text: Any) -> str:
    """全角转半角 + 去除空白 + 小写。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = re.sub(r"\s+", "", text)
    return text.lower()


def char_ngrams(text: Any, n: int = 2) -> set:
    """字符级 n-gram 集合（默认 2-gram）。"""
    text = norm_text(text)
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def ocr_noise_ratio(stem: Any) -> float:
    """估算题面 OCR 噪声比例：异常字符占题面字符比例。0 表示干净，越大越可疑。"""
    s = re.sub(r"\s", "", stem or "")
    if not s:
        return 1.0
    weird = _OCR_WEIRD_RE.findall(s)
    return len(weird) / len(s)


def detect_subject(query: str) -> Optional[str]:
    """从查询中识别科目；长别名优先（英语二 > 英语）。"""
    q = norm_text(query)
    hits = [(len(k), k, v) for k, v in SUBJECT_ALIAS.items() if k in q]
    if not hits:
        return None
    hits.sort(key=lambda x: -x[0])
    return hits[0][2]


# --------------------------------------------------------------------------- #
# 真题索引
# --------------------------------------------------------------------------- #
class ExamIndex:
    """2-gram 真题索引（直接加载 index.pkl，零第三方依赖）。"""

    def __init__(self, index_file: Path = INDEX_FILE):
        self.index_file = index_file
        idx = pickle.loads(index_file.read_bytes())
        self.docs: List[Dict[str, Any]] = idx["docs"]
        self.doc_grams: List[set] = idx["doc_grams"]
        self.postings: Dict[str, list] = idx["postings"]
        self.total: int = idx.get("total", len(self.docs))
        self.n_docs = len(self.docs)
        # 预计算 idf
        self.idf: Dict[str, float] = {}
        for gram, plist in self.postings.items():
            df = len(plist)
            self.idf[gram] = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)
        # doc 长度（BM25 长度归一化）
        self.doc_len = [len(g) for g in self.doc_grams]
        self.avg_doc_len = sum(self.doc_len) / max(1, self.n_docs)
        logger.info("真题索引加载完成：%d 题，postings %d 项", self.n_docs, len(self.postings))

    # ---- 工具 ----
    def _q(self, doc_id: int) -> Dict[str, Any]:
        q = self.docs[doc_id].get("q")
        if isinstance(q, str):
            try:
                import ast
                q = ast.literal_eval(q)
            except Exception:
                q = {}
        return q or {}

    def _stem_text(self, doc_id: int) -> str:
        q = self._q(doc_id)
        stem = q.get("stem") or ""
        options = q.get("options") or {}
        answer = q.get("answer") or ""
        analysis = q.get("analysis") or ""
        return norm_text(stem + "".join(str(v) for v in options.values()) + answer + analysis)

    # ---- 二次校验重排（重写版：直接用 index.pkl 的 q 字段，不再依赖分科目 JSON）----
    def _extract_keywords(self, query: str) -> set:
        q = norm_text(query)
        kws = set()
        for seg in re.findall(r"[\u4e00-\u9fff]{2,}", q):
            if seg not in ("考研", "真题", "数学", "英语", "政治", "解答", "选择题", "大题"):
                kws.add(seg)
        for w in re.findall(r"[a-z]{3,}", q):
            kws.add(w)
        for cn, en_terms in _ALIAS_MAP.items():
            if cn in q:
                kws.update(en_terms)
        return kws

    def _rerank_by_keywords(
        self,
        candidates: List[Tuple[int, float, int]],
        query: str,
        year: Optional[int] = None,
        subject: Optional[str] = None,
    ) -> List[Tuple[int, float, int, int]]:
        kws = self._extract_keywords(query)
        if not kws and year is None:
            return [(d, s, h, 0) for d, s, h in candidates]
        cn_re = re.compile(r"[\u4e00-\u9fff]+")
        scored = []
        for doc_id, base, hits in candidates:
            bonus = 0.0
            kw_hits = 0
            if kws:
                text = self._stem_text(doc_id)
                for kw in kws:
                    if cn_re.fullmatch(kw):
                        if kw in text:
                            kw_hits += 1
                    else:
                        if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text):
                            kw_hits += 1
                bonus += kw_hits * 6.0
            qd = self._q(doc_id)
            if year is not None and qd.get("year") == year:
                bonus += 8.0
            noise = ocr_noise_ratio(qd.get("stem") or "")
            if noise > 0.25 and kw_hits < 2:
                bonus -= 60.0
            if kw_hits == 0 and year is None:
                bonus -= 20.0
            if (qd.get("answer") or "").strip():
                bonus += 6.0
            else:
                bonus -= 1.0
            scored.append((doc_id, base + bonus, hits, kw_hits))
        scored.sort(key=lambda x: (-x[1], -x[2], -x[3]))
        return scored

    # ---- 检索 ----
    def retrieve(
        self,
        query: str,
        k: int = DEFAULT_K,
        subject: Optional[str] = None,
    ) -> List[Tuple[int, float, int]]:
        """BM25 变体检索：返回 [(doc_id, score, gram_hits)] 按得分降序。"""
        q_grams = char_ngrams(query)
        if not q_grams:
            return []
        k = max(1, min(int(k), MAX_K))
        year_m = _YEAR_RE.search(norm_text(query))
        year = int(year_m.group()) if year_m else None

        scores: Dict[int, float] = defaultdict(float)
        hit_grams: Dict[int, set] = defaultdict(set)
        for gram in q_grams:
            plist = self.postings.get(gram)
            if not plist:
                continue
            idf = self.idf[gram]
            for doc_id in plist:
                scores[doc_id] += idf
                hit_grams[doc_id].add(gram)
        if not scores:
            return []

        if subject is not None:
            subj_set = {i for i in range(self.n_docs) if self._q(i).get("subject") == subject}
            scores = {i: s for i, s in scores.items() if i in subj_set}
            if not scores:
                return []

        results = []
        for doc_id, raw in scores.items():
            hits = len(hit_grams[doc_id])
            coverage = hits / max(1.0, float(len(q_grams)))
            dl = self.doc_len[doc_id]
            norm = IDF_K1 * (1 - IDF_B + IDF_B * dl / self.avg_doc_len)
            score = raw * (IDF_K1 + 1) / (norm + IDF_K1) * (0.7 + 0.3 * coverage)
            noise = ocr_noise_ratio(self._q(doc_id).get("stem") or "")
            if noise > 0.35:
                score *= 0.30
            elif noise > 0.25:
                score *= 0.50
            elif noise > 0.15:
                score *= 0.70
            elif noise > 0.10:
                score *= 0.85
            results.append((doc_id, score, hits))

        results.sort(key=lambda x: (-x[1], -x[2]))
        top = results[:60]
        reranked = self._rerank_by_keywords(top, query, year=year, subject=subject)
        return [(d, s, h) for d, s, h, _ in reranked][:k]

    # ---- 变式题 ----
    def find_variants(self, doc_id: int, k: int = 3, min_sim: float = 0.08) -> List[Tuple[int, float, float, int]]:
        """以指定题目的题干 2-gram 为查询，返回相似题（变式题）。"""
        base_grams = self.doc_grams[doc_id]
        if not base_grams:
            return []
        scores: Dict[int, float] = defaultdict(float)
        hit_grams: Dict[int, set] = defaultdict(set)
        for gram in base_grams:
            plist = self.postings.get(gram)
            if not plist:
                continue
            idf = self.idf[gram]
            for did in plist:
                scores[did] += idf
                hit_grams[did].add(gram)
        results = []
        for did, raw in scores.items():
            if did == doc_id:
                continue
            hits = len(hit_grams[did])
            union = len(base_grams | self.doc_grams[did])
            jac = hits / max(1.0, union)
            if jac < min_sim:
                continue
            dl = self.doc_len[did]
            norm = IDF_K1 * (1 - IDF_B + IDF_B * dl / self.avg_doc_len)
            score = raw * (IDF_K1 + 1) / (norm + IDF_K1)
            results.append((did, jac, score, hits))
        results.sort(key=lambda x: (-x[1], -x[2]))
        return results[:k]

    # ---- 格式化 ----
    def format_question(self, doc_id: int, with_answer: bool = True) -> str:
        q = self._q(doc_id)
        lines = [f"【{q.get('subject_name', '')}｜{q.get('year', '')}年｜{q.get('section', '')}｜{q.get('type', '')}】"]
        stem = (q.get("stem") or "").strip()
        if stem:
            lines.append(f"题目：{stem}")
        options = q.get("options") or {}
        opts = []
        for letter in ("A", "B", "C", "D"):
            if letter in options and options[letter]:
                opts.append(f"{letter}.{options[letter]}")
        if opts:
            lines.append("选项：" + "　".join(opts))
        if with_answer and (q.get("answer") or "").strip():
            lines.append(f"答案：{q.get('answer')}")
        if with_answer and (q.get("analysis") or "").strip():
            lines.append(f"解析：{q.get('analysis')}")
        return "\n".join(lines)

    def question_detail(self, doc_id: int) -> Dict[str, Any]:
        """结构化详情（供 search_service 第 4 路返回）。"""
        q = self._q(doc_id)
        variants = []
        try:
            vlist = self.find_variants(doc_id, k=3)
            for did, jac, score, hits_n in vlist:
                variants.append({
                    "doc_id": did,
                    "similarity": round(jac, 4),
                    "question": self.format_question(did, with_answer=True),
                    "subject": self._q(did).get("subject"),
                    "year": self._q(did).get("year"),
                })
        except Exception as e:  # 变式题失败不影响主结果
            logger.warning("find_variants(%s) 失败: %s", doc_id, e)
        return {
            "source_type": "exam_question",
            "doc_id": doc_id,
            "subject": q.get("subject"),
            "subject_name": q.get("subject_name"),
            "year": q.get("year"),
            "section": q.get("section"),
            "type": q.get("type"),
            "quality": q.get("quality"),
            "question": self.format_question(doc_id, with_answer=True),
            "answer": q.get("answer") or "",
            "analysis": q.get("analysis") or "",
            "variants": variants,
        }


# --------------------------------------------------------------------------- #
# lru 单例
# --------------------------------------------------------------------------- #
_lru: Optional[ExamIndex] = None


def get_exam_index() -> ExamIndex:
    global _lru
    if _lru is None:
        _lru = ExamIndex()
    return _lru


def retrieve(query: str, k: int = DEFAULT_K, subject: Optional[str] = None):
    """便捷入口：真题检索。"""
    return get_exam_index().retrieve(query, k=k, subject=subject)


def find_variants(doc_id: int, k: int = 3):
    """便捷入口：变式题。"""
    return get_exam_index().find_variants(doc_id, k=k)


# --------------------------------------------------------------------------- #
# 第 4 路融合：与 search_service 三路 RRF 融合（现有三路行为不变，仅新增）
# --------------------------------------------------------------------------- #
def search_with_exam(
    db,
    query: str,
    query_vec=None,
    limit: int = 6,
    subject: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """三路（chunks/points/documents）+ 第 4 路（exam_question）RRF 融合检索。

    现有 hybrid_search_with_rerank 结果不动；exam lane 用负 ID -300000-doc_id，
    RRF K=20（权重约 2.9 倍于 K=60）。返回结果含 source_type='exam_question'。
    """
    from services.search_service import hybrid_search_with_rerank

    base = hybrid_search_with_rerank(db, query, query_vec=query_vec, limit=limit, subject=subject) or []
    exam = get_exam_index().retrieve(query, k=min(limit * 3, MAX_K), subject=subject)
    if not exam:
        return base

    # 现有三路融合结果整体作为一路 lane（保持其内部顺序与精排不变），exam 作为第 4 路
    lanes = []
    if base:
        lanes.append([(i + 1, i + 1) for i in range(len(base))])
    exam_lane = [(EXAM_LANE_BASE - d, i + 1) for i, (d, _s, _h) in enumerate(exam)]
    lanes.append(exam_lane)

    # RRF 融合：现有三路（base 已按 K=60 融合精排）保持 K=60 语义，
    # exam 第 4 路用 K=20（1/21 ≈ 2.9 倍权重），避免并列时 base 恒占前位
    from services.search_service import RRF_K

    fused_scores: Dict[int, float] = {}
    if base:
        for cid, rank in lanes[0]:
            fused_scores[cid] = fused_scores.get(cid, 0) + 1.0 / (RRF_K + rank)
    for cid, rank in lanes[-1]:
        fused_scores[cid] = fused_scores.get(cid, 0) + 1.0 / (RRF_K_EXAM + rank)
    fused_sorted = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

    # 取详情（base 结果直接映射；exam 用负 ID 区分）
    base_by_id = {i + 1: r for i, r in enumerate(base)}
    results: List[Dict[str, Any]] = []
    for cid, _score in fused_sorted[:limit * 2]:
        if cid <= 0:  # exam lane（负 ID，cid = EXAM_LANE_BASE - doc_id）
            doc_id = EXAM_LANE_BASE - cid
            det = get_exam_index().question_detail(doc_id)
            det["score"] = round(fused_scores.get(cid, 0), 4)
            det["chunk_id"] = cid
            results.append(det)
        else:
            base_idx = cid
            if base_idx in base_by_id:
                r = dict(base_by_id[base_idx])
                r["score"] = round(fused_scores.get(cid, 0), 4)
                results.append(r)
    return results[:limit]


if __name__ == "__main__":  # pragma: no cover
    idx = get_exam_index()
    for q in ["2019年考研数学二求极限", "英语二完形填空"]:
        print("QUERY:", q)
        for doc_id, score, hits in idx.retrieve(q, k=3):
            print(" -", doc_id, round(score, 4), hits, idx._q(doc_id).get("year"), idx._q(doc_id).get("subject"))
