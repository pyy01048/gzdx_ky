# -*- coding: utf-8 -*-
"""题库导入高精分类器（v2，置信闸门版）。

设计目标
--------
把「识别度/准确率冲到 99%」拆成两条可独立保证的性质：

1. **分类质量**：科目 = 关键词加权 + 向量质心 softmax 相似度 + LLM 受控兜底
   （只在两路分歧 / 双低置信时触发，避免小模型乱猜污染）。每个字段输出 0~1
   置信度，且 *约束* 输出必须落在已知科目/题型集合内（不允许幻觉标签）。
2. **可信闸门**：只有高置信判定才「自动入库」（可信集）；低置信判定打
   ``needs_review`` 进人工复核队列，绝不静默错标、也不丢弃。于是
   **自动入库那一批的精度由阈值保证**，可量化逼近 99%，而覆盖率由质量决定。

这是与 v1（``quiz_autoclassify``）的本质区别：v1 一律落库只标 verified=False，
低置信结果混在「已入库」里拉低整体识别度；v2 把「可信」与「待核」显式分离。

入口
----
- ``classify_batch_v2(questions, db)``：批量（一次 embedding），返回每题决策字典。
- ``autoclassify_v2(questions, db, use_llm)``：就地补全字段 + 返回统计，供导入入口调用。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 阈值（可调，评测脚本会扫这些值定位 99% 落点）
# --------------------------------------------------------------------------- #
SUBJECT_AUTO_THRESH = 0.90   # 科目置信 ≥ 此值才自动入库（主判据；实测自动集精度 ~98%，
                             # 残差主要为库内标签噪声——详见 scripts/_diag_real_sweep.py）
TYPE_AUTO_THRESH = 0.80      # 题型置信 ≥ 此值才自动入库
LLM_TRIGGER_CONF = 0.60      # 两路都低于此值或分歧时，触发 LLM 兜底
LLM_BUDGET_S = 45.0          # LLM 兜底单批时间预算（超时静默降级）

# 合法题型集合（约束 LLM 输出，禁止幻觉）
VALID_TYPES = {"single", "multiple", "judge", "fill", "calc", "essay", "draw"}

# --------------------------------------------------------------------------- #
# 数据复用：v1 的关键词规则（科目/知识点映射），直接复用其词表避免漂移
# --------------------------------------------------------------------------- #
from services.quiz_autoclassify import (  # noqa: E402
    _SUBJECT_RULES, _KP_RULES, _llm_chat_with_budget,
)

# 题型结构特征（复用 v1 的正则思路，但带置信度）
_FILL_RE = re.compile(r"_{3,}|＿{3,}")
_CHOICE_OPT_RE = re.compile(r"^[A-D][\.、．\)]", re.M)


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class FieldDecision:
    """单个字段的分类决策。"""
    value: str = ""
    confidence: float = 0.0
    source: str = "none"   # none/keyword/vector/fusion/llm/disagree


@dataclass
class QuestionDecision:
    """单题的完整分类决策。"""
    subject: FieldDecision = field(default_factory=FieldDecision)
    question_type: FieldDecision = field(default_factory=FieldDecision)
    knowledge_point: FieldDecision = field(default_factory=FieldDecision)
    classify_confidence: float = 0.0
    auto_accept: bool = False
    needs_review: bool = False
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject.value,
            "subject_conf": round(self.subject.confidence, 4),
            "subject_source": self.subject.source,
            "question_type": self.question_type.value,
            "type_conf": round(self.question_type.confidence, 4),
            "type_source": self.question_type.source,
            "knowledge_point": self.knowledge_point.value,
            "kp_conf": round(self.knowledge_point.confidence, 4),
            "classify_confidence": round(self.classify_confidence, 4),
            "classify_source": self.subject.source,
            "auto_accept": self.auto_accept,
            "needs_review": self.needs_review,
            "classify_reason": self.reason,
        }


# --------------------------------------------------------------------------- #
# 路1：关键词加权评分（比 v1 的"计数取最大"更稳：引入支配度 + 最小命中数）
# --------------------------------------------------------------------------- #
def _keyword_subject_scores(text: str) -> Dict[str, int]:
    """每科命中 *不同* 关键词的数量（去重计数，避免同一词重复命中刷分）。"""
    scores: Dict[str, int] = {}
    for subject, kws in _SUBJECT_RULES:
        hits = sum(1 for kw in kws if kw in text)
        if hits:
            scores[subject] = hits
    return scores


def _keyword_decision(text: str) -> FieldDecision:
    """关键词路决策：用「支配度」换算置信度，1 个命中只给低置信。"""
    scores = _keyword_subject_scores(text)
    if not scores:
        return FieldDecision("", 0.0, "keyword")
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_subj, best_hits = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    dominance = (best_hits - second) / best_hits if best_hits else 0.0
    if best_hits >= 2:
        conf = round(0.50 + 0.45 * dominance, 4)   # 2 命中且压倒 → 0.95
    else:
        conf = 0.35                                  # 单命中，弱信号
    return FieldDecision(best_subj, conf, "keyword")


# --------------------------------------------------------------------------- #
# 路2：向量质心 softmax 相似度（复用 chunk_classifier 的质心与编码）
# --------------------------------------------------------------------------- #
def _load_vector_assets(db):
    """返回 (embed_func, centroids) 或 (None, None)。

    不依赖历史 ``subject_prototypes`` 表（其 ORM 与库结构对不上、向量信号长期静默失效），
    改读自建的 ``quiz_subject_centroids``（原始 SQL 管理，bytea 向量）。
    """
    try:
        from services.chunk_classifier import encode_texts, vector_scores
        if db is None:
            return None, None
        centroids = _load_quiz_centroids(db)
        if not centroids:
            return None, None
        return (lambda texts: encode_texts(list(texts))), centroids
    except Exception as e:  # noqa: BLE001
        logger.info("[quiz_cls_v2] 向量路不可用，降级为关键词+LLM: %s", e)
        return None, None


def _load_quiz_centroids(db) -> Dict[str, "np.ndarray"]:
    """从 quiz_subject_centroids 读取各科目质心（缓存于进程内）。

    注意：返回的字典**只含** subject->向量，绝不可混入加载标记等杂项键，
    否则 vector_scores 会对非向量值做余弦而抛错（历史坑：曾把 __loaded__ 布尔
    一并传入，导致向量路整批静默失效、小科目全判空）。
    """
    from sqlalchemy import text
    global _QUIZ_CENTROID_LOADED
    if _QUIZ_CENTROID_LOADED:
        return {k: v for k, v in _QUIZ_CENTROID_CACHE.items()}
    rows = db.execute(text(
        "SELECT subject, dim, vector FROM quiz_subject_centroids")).fetchall()
    import numpy as _np
    for subject, dim, vec in rows:
        if vec is None:
            continue
        arr = _np.frombuffer(vec, dtype=_np.float32)
        if dim and arr.size != dim:
            continue
        _QUIZ_CENTROID_CACHE[subject] = arr
    _QUIZ_CENTROID_LOADED = True
    return {k: v for k, v in _QUIZ_CENTROID_CACHE.items()}


_QUIZ_CENTROID_CACHE: Dict[str, Any] = {}
_QUIZ_CENTROID_LOADED = False


# 兄弟科对：余弦空间里贴身肉搏、共享 EE 词表，单靠余弦/单关键词极易互判。
_SIB_PAIR = {"数字电子技术", "模拟电子技术"}
# 兄弟科余弦间隙阈值：小于此值视为"贴身肉搏"，压低置信强制进复核（防互判错标）。
_SIB_GAP_MIN = 0.06


def _cosine_scores(emb, centroids) -> Dict[str, float]:
    """逐科目原始余弦相似度（L2 归一后点积）。"""
    import numpy as _np
    q = emb / max(float(_np.linalg.norm(emb)), 1e-9)
    out: Dict[str, float] = {}
    for s, c in centroids.items():
        c = c / max(float(_np.linalg.norm(c)), 1e-9)
        out[s] = float(_np.dot(q, c))
    return out


def _vector_decision(text: str, embed_func, centroids) -> FieldDecision:
    if embed_func is None or not centroids:
        return FieldDecision("", 0.0, "vector")
    try:
        emb = embed_func([text])
        if emb is None or len(emb) == 0:
            return FieldDecision("", 0.0, "vector")
        cos = _cosine_scores(emb[0], centroids)
        if not cos:
            return FieldDecision("", 0.0, "vector")
        ranked = sorted(cos.items(), key=lambda kv: -kv[1])
        best_subj, best_c = ranked[0]
        second_subj, second_c = ranked[1] if len(ranked) > 1 else (None, 0.0)
        margin = best_c - second_c
        # 校准置信：高 cosine + 大边距 → 高；平局/低 cosine → 低。
        # （softmax 概率最大仅 ~0.4，无法直接做闸门，故改用原始余弦+边距校准。）
        conf = round(float(min(0.98, max(0.0, 0.30 + 1.0 * (best_c - 0.60) + 2.5 * margin))), 4)
        # 兄弟科贴身肉搏：第二恰为其兄弟科且间隙小 → 压低置信，强制进复核
        if (best_subj in _SIB_PAIR and second_subj in _SIB_PAIR
                and (best_c - second_c) < _SIB_GAP_MIN):
            conf = min(conf, 0.60)
        return FieldDecision(best_subj, conf, "vector")
    except Exception as e:  # noqa: BLE001
        logger.info("[quiz_cls_v2] 向量编码失败，降级: %s", e)
        return FieldDecision("", 0.0, "vector")


# --------------------------------------------------------------------------- #
# 路3：LLM 受控兜底（只在两路分歧 / 双低置信时触发；约束输出到候选集）
# --------------------------------------------------------------------------- #
_LLM_SUBJECT_PROMPT = """你是考研题库的科目分类器。只从候选科目中选一个，不要编造。
候选科目：{subjects}
输出严格 JSON（不要其他文字）：{{"subject":"<科目>","confidence":<0~1>}}
题目：{text}"""


def _llm_subject_decision(text: str, candidates: List[str]) -> Optional[FieldDecision]:
    items = (text or "")[:300]
    prompt = _LLM_SUBJECT_PROMPT.format(subjects="|".join(candidates), text=items)
    try:
        raw = _llm_chat_with_budget(prompt)
        raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S)
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return None
        obj = json.loads(m.group(0))
        subj = str(obj.get("subject", "")).strip()
        if subj not in candidates:
            return None
        try:
            conf = float(obj.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        return FieldDecision(subj, round(conf, 4), "llm")
    except Exception as e:  # noqa: BLE001
        logger.debug("[quiz_cls_v2] LLM 兜底失败: %s", e)
        return None


# --------------------------------------------------------------------------- #
# 科目融合：关键词 × 向量（+ 必要时 LLM）
# --------------------------------------------------------------------------- #
def _subject_candidates_list() -> List[str]:
    try:
        from services.chunk_classifier import subject_candidates
        return list(subject_candidates())
    except Exception:  # noqa: BLE001
        return [s for s, _ in _SUBJECT_RULES]


def classify_subject_v2(
    text: str,
    *,
    embed_func=None,
    protos=None,
    db=None,
    use_llm: bool = True,
) -> FieldDecision:
    kw = _keyword_decision(text)
    vec = _vector_decision(text, embed_func, protos)
    cands = _subject_candidates_list()

    # 两路一致且都有信号 → 融合
    if kw.value and vec.value and kw.value == vec.value:
        # 兄弟科（数字/模拟）共享 EE 词表，单靠强关键词可能互判；这里仍允许强
        # 关键词/清晰向量自动入库，但兄弟科分歧与弱一致统一交 LLM 受控裁决，
        # 由 LLM 在候选集内定夺，既保覆盖又保精度（见下方分歧分支）。
        if kw.confidence >= 0.50 or vec.confidence >= 0.75:
            conf = min(0.99, 0.92 + 0.07 * min(kw.confidence, vec.confidence))
        else:
            conf = 0.80
        return FieldDecision(kw.value, conf, "fusion")

    # 仅一路有信号：直接采用该路（保留其校准置信，不再额外惩罚）
    if vec.value and not kw.value:
        return FieldDecision(vec.value, vec.confidence, "vector")
    if kw.value and not vec.value:
        return FieldDecision(kw.value, kw.confidence, "keyword")

    # 两路都有信号但方向不同 → 分歧：LLM 受控裁决（约束到候选集）
    if kw.value and vec.value and kw.value != vec.value:
        if use_llm:
            llm = _llm_subject_decision(text, cands)
            if llm is not None and llm.value:
                if llm.value in (kw.value, vec.value):
                    # LLM 站队到某一路 → 采信该路并适度提信
                    base = kw.confidence if llm.value == kw.value else vec.confidence
                    return FieldDecision(llm.value, min(0.95, max(base, llm.confidence) + 0.05), "llm")
                return FieldDecision(llm.value, min(0.85, llm.confidence), "llm")
        # LLM 不可用/无果 → 取较高一路并压低置信（标记分歧，进复核）
        better = kw if kw.confidence >= vec.confidence else vec
        return FieldDecision(better.value, round(better.confidence * 0.7, 4), "disagree")

    # 两路皆无信号
    return FieldDecision("", 0.0, "none")


# --------------------------------------------------------------------------- #
# 题型分类（结构优先，带置信度）
# --------------------------------------------------------------------------- #
def classify_type_v2(content: str, options: Optional[List[str]]) -> FieldDecision:
    text = (content or "").strip()
    opts = [o for o in (options or []) if o and str(o).strip()]
    # 1) 选项/选择结构 → 单选（最高优先，结构最硬）
    if len(opts) >= 2:
        return FieldDecision("single", 0.97, "rule")
    if len(_CHOICE_OPT_RE.findall(text)) >= 2:
        return FieldDecision("single", 0.92, "rule")
    # 2) 填空占位符（下划线）→ 填空
    if _FILL_RE.search(text) or "填空" in text:
        return FieldDecision("fill", 0.90, "rule")
    # 3) 显式判断词 → 判断
    if re.search(r"判断|对错|打[√×]|是否正确|正确与否|说法正确", text):
        return FieldDecision("judge", 0.88, "rule")
    # 4) 作图
    if re.search(r"画出|作[出]?图|画[出]?图|波形图|电路图|真值表|状态图|画出波形", text):
        return FieldDecision("draw", 0.85, "rule")
    # 5) 计算
    if re.search(r"计算|化简|求[出解值该其]|试求|求解|等于多少|是多少|最简", text):
        return FieldDecision("calc", 0.84, "rule")
    # 6) 显式简答/论述词
    if re.search(r"简述|简答|论述|分析|为什么|说明理由|试说明|叙述|证明|阐述|试述|举例说明|比较.*与", text):
        return FieldDecision("essay", 0.82, "rule")
    # 7) 疑问句 / 疑问代词（无选项、无空）→ 简答
    if re.search(r"[?？]", text) or re.search(r"哪些|什么|如何|怎样|为何|有何区别|有何作用|包括", text):
        return FieldDecision("essay", 0.74, "rule")
    # 8) 陈述句（无？、无空、无选项）→ 判断题（判断题多为陈述性断言）
    if re.search(r"[。.！!]$", text) or len(text) <= 80:
        return FieldDecision("judge", 0.72, "rule")
    return FieldDecision("single", 0.4, "rule")  # 兜底：单选但低置信


# --------------------------------------------------------------------------- #
# 知识点分类（科目内高频无歧义关键词映射；低置信不阻塞自动入库）
# --------------------------------------------------------------------------- #
def classify_kp_v2(subject: Optional[str], content: str) -> FieldDecision:
    if not subject:
        return FieldDecision("", 0.0, "none")
    text = content or ""
    best_kw, best_pos = None, -1
    for kw in _KP_RULES.get(subject, {}):
        pos = text.find(kw)
        if pos != -1 and (best_pos == -1 or pos < best_pos):
            best_kw, best_pos = kw, pos
    if best_kw:
        return FieldDecision(_KP_RULES[subject][best_kw], 0.75, "rule")
    return FieldDecision("", 0.0, "none")


# --------------------------------------------------------------------------- #
# 单题决策
# --------------------------------------------------------------------------- #
def decide_question(
    content: str,
    options: Optional[List[str]] = None,
    *,
    embed_func=None,
    protos=None,
    db=None,
    use_llm: bool = True,
) -> QuestionDecision:
    d = QuestionDecision()
    d.subject = classify_subject_v2(
        content or "", embed_func=embed_func, protos=protos, db=db, use_llm=use_llm)
    d.question_type = classify_type_v2(content, options)
    d.knowledge_point = classify_kp_v2(d.subject.value, content or "")

    # 自动入库闸门：科目 + 题型都必须高置信
    subj_ok = bool(d.subject.value) and d.subject.confidence >= SUBJECT_AUTO_THRESH
    type_ok = d.question_type.confidence >= TYPE_AUTO_THRESH
    d.auto_accept = subj_ok and type_ok
    d.needs_review = not d.auto_accept

    # 整体置信度：取科目与题型置信的调和下限（任一低都拉低）
    if d.subject.confidence and d.question_type.confidence:
        d.classify_confidence = round(
            min(d.subject.confidence, d.question_type.confidence), 4)
    else:
        d.classify_confidence = round(
            max(d.subject.confidence, d.question_type.confidence), 4)

    if d.needs_review:
        d.reason = (
            f"科目({d.subject.source}={d.subject.confidence:.2f})"
            f"/题型({d.question_type.source}={d.question_type.confidence:.2f}) 未达自动入库阈值"
        )
    return d


# --------------------------------------------------------------------------- #
# 批量入口（一次 embedding，供导入调用）
# --------------------------------------------------------------------------- #
def classify_batch_v2(
    questions: List[Dict[str, Any]],
    db=None,
    use_llm: bool = True,
) -> List[QuestionDecision]:
    """批量分类。复用向量路一次编码全部题干。"""
    embed_func, protos = _load_vector_assets(db)
    # 若向量可用，批量编码（单题编码太慢）
    if embed_func is not None and protos:
        try:
            texts = [(q.get("content") or "") for q in questions]
            embs = embed_func(texts)
            # 用逐题向量决策替换批量占位（保持与单题同口径）
            decisions: List[QuestionDecision] = []
            for i, q in enumerate(questions):
                d = decide_question(
                    q.get("content") or "", q.get("options"),
                    embed_func=None, protos=None, db=db, use_llm=use_llm)
                # 用批量向量结果覆盖（避免 decide 内部再编一次）
                if embs is not None and len(embs) > i:
                    vec = _vector_decision_from_embedding(embs[i], protos)
                    # 重新融合科目（用向量结果 + 关键词）
                    kw = _keyword_decision(q.get("content") or "")
                    d.subject = _fuse_subject(kw, vec, use_llm=use_llm,
                                             text=q.get("content") or "", db=db)
                d.question_type = classify_type_v2(q.get("content"), q.get("options"))
                d.knowledge_point = classify_kp_v2(d.subject.value, q.get("content") or "")
                _finalize(d)
                decisions.append(d)
            return decisions
        except Exception as e:  # noqa: BLE001
            logger.info("[quiz_cls_v2] 批量向量失败，退回逐题: %s", e)

    return [
        decide_question(q.get("content") or "", q.get("options"),
                       embed_func=embed_func, protos=protos, db=db, use_llm=use_llm)
        for q in questions
    ]


def _vector_decision_from_embedding(emb, protos) -> FieldDecision:
    try:
        cos = _cosine_scores(emb, protos)
        if not cos:
            return FieldDecision("", 0.0, "vector")
        ranked = sorted(cos.items(), key=lambda kv: -kv[1])
        best_subj, best_c = ranked[0]
        second_subj, second_c = ranked[1] if len(ranked) > 1 else (None, 0.0)
        margin = best_c - second_c
        conf = round(float(min(0.98, max(0.0, 0.30 + 1.0 * (best_c - 0.60) + 2.5 * margin))), 4)
        if (best_subj in _SIB_PAIR and second_subj in _SIB_PAIR
                and (best_c - second_c) < _SIB_GAP_MIN):
            conf = min(conf, 0.60)
        return FieldDecision(best_subj, conf, "vector")
    except Exception:  # noqa: BLE001
        return FieldDecision("", 0.0, "vector")


def _fuse_subject(kw: FieldDecision, vec: FieldDecision, *, use_llm: bool, text: str, db=None) -> FieldDecision:
    """与 classify_subject_v2 同口径的融合（供批量路径复用）。"""
    cands = _subject_candidates_list()
    if kw.value and vec.value and kw.value == vec.value:
        if kw.confidence >= 0.50 or vec.confidence >= 0.75:
            return FieldDecision(kw.value, min(0.99, 0.92 + 0.07 * min(kw.confidence, vec.confidence)), "fusion")
        return FieldDecision(kw.value, 0.80, "fusion")
    # 仅一路有信号：直接采用该路（保留校准置信）
    if vec.value and not kw.value:
        return FieldDecision(vec.value, vec.confidence, "vector")
    if kw.value and not vec.value:
        return FieldDecision(kw.value, kw.confidence, "keyword")
    # 两路方向不同 → 分歧：LLM 受控裁决
    if kw.value and vec.value and kw.value != vec.value:
        if use_llm:
            llm = _llm_subject_decision(text, cands)
            if llm is not None and llm.value:
                if llm.value in (kw.value, vec.value):
                    base = kw.confidence if llm.value == kw.value else vec.confidence
                    return FieldDecision(llm.value, min(0.95, max(base, llm.confidence) + 0.05), "llm")
                return FieldDecision(llm.value, min(0.85, llm.confidence), "llm")
        better = kw if kw.confidence >= vec.confidence else vec
        return FieldDecision(better.value, round(better.confidence * 0.7, 4), "disagree")
    return FieldDecision("", 0.0, "none")


def _finalize(d: QuestionDecision) -> None:
    subj_ok = bool(d.subject.value) and d.subject.confidence >= SUBJECT_AUTO_THRESH
    type_ok = d.question_type.confidence >= TYPE_AUTO_THRESH
    d.auto_accept = subj_ok and type_ok
    d.needs_review = not d.auto_accept
    if d.subject.confidence and d.question_type.confidence:
        d.classify_confidence = round(min(d.subject.confidence, d.question_type.confidence), 4)
    else:
        d.classify_confidence = round(max(d.subject.confidence, d.question_type.confidence), 4)
    if d.needs_review:
        d.reason = (f"科目({d.subject.source}={d.subject.confidence:.2f})"
                    f"/题型({d.question_type.source}={d.question_type.confidence:.2f}) 未达自动入库阈值")


# --------------------------------------------------------------------------- #
# 导入入口（就地补全字段 + 返回统计）
# --------------------------------------------------------------------------- #
def autoclassify_v2(
    questions: List[Dict[str, Any]],
    db=None,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """v2 自动分类主入口。

    就地补全每题的 subject/question_type/knowledge_point，并写入分类置信与复核标记：
      - auto_accept 的题：needs_review=False（可信自动入库）
      - 其余：needs_review=True（进复核队列，不静默错标）

    返回统计：classified / auto_accepted / needs_review / by_source。
    """
    decisions = classify_batch_v2(questions, db=db, use_llm=use_llm)
    auto = review = 0
    by_source: Dict[str, int] = {}
    for q, dec in zip(questions, decisions):
        # 仅补全 *缺* 字段：若调用方已显式给了科目/题型，尊重其输入（人工/来源已知）
        if not q.get("subject") and dec.subject.value:
            q["subject"] = dec.subject.value
        if not q.get("question_type") or q.get("question_type") in ("", None):
            q["question_type"] = dec.question_type.value
        if not q.get("knowledge_point") and dec.knowledge_point.value:
            q["knowledge_point"] = dec.knowledge_point.value
        q["classify_confidence"] = dec.classify_confidence
        q["classify_source"] = dec.subject.source
        q["needs_review"] = dec.needs_review
        by_source[dec.subject.source] = by_source.get(dec.subject.source, 0) + 1
        if dec.auto_accept:
            auto += 1
        else:
            review += 1
    return {
        "classified": len(questions),
        "auto_accepted": auto,
        "needs_review": review,
        "by_source": by_source,
    }


# --------------------------------------------------------------------------- #
# 幂等加列（与 chunk_classifier.ensure_chunk_label_columns 同模式）
# --------------------------------------------------------------------------- #
_QUIZ_CLASSIFY_COLUMNS = [
    ("classify_confidence", "ALTER TABLE quiz_questions ADD COLUMN IF NOT EXISTS classify_confidence FLOAT"),
    ("classify_source", "ALTER TABLE quiz_questions ADD COLUMN IF NOT EXISTS classify_source VARCHAR(30)"),
    ("needs_review", "ALTER TABLE quiz_questions ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT FALSE"),
]


def ensure_quiz_classify_columns(db) -> List[str]:
    """确保 quiz_questions 的分类闸门列存在（幂等，生产/测试库首次导入时调用）。"""
    from sqlalchemy import text

    added: List[str] = []
    for name, ddl in _QUIZ_CLASSIFY_COLUMNS:
        try:
            db.execute(text(ddl))
            db.commit()
            added.append(name)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            # DuplicateColumnError / 已存在 / 方言差异都视为"已就绪"，不阻断导入
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                continue
            logger.warning("[quiz_cls_v2] 加列 %s 跳过: %s", name, e)
    return added
