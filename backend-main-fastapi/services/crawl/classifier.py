# -*- coding: utf-8 -*-
"""公告类型分类（规则优先，LLM 兜底）。

规则表来自 ``docx/34-OCR与数据采集开源方案-20261020.md`` §5.4，
在原表基础上做了三处工程化补强（**原表关键词全部保留**）：

1. 补了同义写法（如"复试线"同时覆盖"复试分数线/复试基本分数线/校线/院线"）；
2. 关键词按长度加权——"推免占比"（报录比）比"推免"（推免）更长更具体，
   标题命中长词时压过短词；
3. 标题权重远高于正文，避免正文里顺带提一句"复试"就把类型带偏。

LLM 兜底
---------
规则全部落空时才考虑调 LLM。当前**不接 LLM**，但接口留好了：
调用方传 ``llm_fallback=lambda title, text: (类型, 置信度)`` 或 ``None``。
TODO(ingest-pipeline): 接入 LLM 时需遵守"类型必须落在 :data:`NOTICE_TYPES`
或 '其他' 之内"的约束，避免脏类型写进 ``kaoyan_notices.notice_type`` 枚举。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

__all__ = [
    "NOTICE_TYPES",
    "OTHER",
    "classify_notice",
    "to_db_notice_type",
    "LLMClassifier",
]

OTHER = "其他"

#: 类型 → 关键词（顺序即优先级，命中分相同时先到先得）
NOTICE_TYPES: Dict[str, List[str]] = {
    "招生简章": ["招生简章", "招生章程", "报考条件", "报考要求", "招生办法"],
    "专业目录": ["招生专业目录", "专业目录", "考试科目", "招生专业一览"],
    "复试线": ["复试分数线", "复试基本分数线", "复试线", "校线", "院线", "国家线"],
    "报录比": ["报录比", "报考人数", "录取人数", "推免占比", "报录情况"],
    "复试细则": ["复试录取实施细则", "复试细则", "复试办法", "复试科目", "复试安排", "复试工作方案"],
    "调剂": ["调剂公告", "调剂缺额", "调剂系统", "调剂志愿", "调剂"],
    "推免": ["推免", "推荐免试", "夏令营", "推免生"],
    "录取": ["拟录取名单", "拟录取", "录取公示", "录取名单", "录取结果"],
    "初试": ["初试成绩", "初试考生", "成绩查询", "成绩复核", "复核申请", "复核", "初试"],
    "报名": ["预报名", "正式报名", "网上确认", "报名须知", "报名"],
    "大纲": ["考试大纲", "参考书目", "大纲"],
}

#: 与 ``kaoyan_notices.notice_type`` 枚举（公告/简章/复试/调剂/录取/初试/报名/大纲/目录）对齐
_DB_TYPE_BY_NAME: Dict[str, str] = {
    "招生简章": "简章",
    "专业目录": "目录",
    "复试线": "复试",
    "报录比": "公告",
    "复试细则": "复试",
    "调剂": "调剂",
    "推免": "公告",
    "录取": "录取",
    "初试": "初试",
    "报名": "报名",
    "大纲": "大纲",
    OTHER: "公告",
}

#: LLM 兜底签名：(title, text) -> (类型, 置信度) 或 None
LLMClassifier = Callable[[str, str], Optional[Tuple[str, float]]]

_TITLE_WEIGHT = 3.0
_BODY_WEIGHT = 1.0
#: 正文里关键词的命中次数上限，防止长正文里"报名"刷屏
_BODY_MAX_HITS = 3


def _keyword_weight(keyword: str) -> float:
    """关键词长度加权：越长越具体。"""
    return 1.0 + len(keyword) / 4.0


def _count_hits(haystack: str, needle: str) -> int:
    if not haystack or not needle:
        return 0
    return haystack.count(needle)


def _score_types(title: str, text: str) -> Dict[str, float]:
    title = title or ""
    text = text or ""
    scores: Dict[str, float] = {}
    for name, keywords in NOTICE_TYPES.items():
        score = 0.0
        for kw in keywords:
            hits_title = _count_hits(title, kw)
            if hits_title:
                score += _TITLE_WEIGHT * _keyword_weight(kw) * min(hits_title, 2)
            if text:
                hits_body = min(_count_hits(text, kw), _BODY_MAX_HITS)
                if hits_body:
                    score += _BODY_WEIGHT * _keyword_weight(kw) * hits_body
        if score > 0:
            scores[name] = score
    return scores


def _confidence(top: float, second: float) -> float:
    """置信度：绝对分越高越可信；若与次优类型接近则打折。"""
    if top <= 0:
        return 0.0
    conf = 0.45 + 0.08 * top
    if second > 0:
        conf *= top / (top + second)
    return round(min(conf, 0.99), 4)


def classify_notice(
    title: str,
    text: str = "",
    *,
    llm_fallback: Optional[LLMClassifier] = None,
) -> Tuple[str, float]:
    """判定公告类型。

    :param title: 公告标题（权重最高）
    :param text: 正文（可选，权重低）
    :param llm_fallback: 规则全落空时的 LLM 兜底回调；当前默认不接
    :return: ``(类型, 置信度)``；全不命中返回 ``("其他", 0.0)``

    >>> classify_notice("2025年硕士研究生招生简章")[0]
    '招生简章'
    >>> classify_notice("随便一条通知")[0]
    '其他'
    """
    scores = _score_types(title, text)
    if not scores:
        if llm_fallback is not None:
            guess = llm_fallback(title or "", text or "")
            if guess:
                name, conf = guess
                if name in NOTICE_TYPES or name == OTHER:
                    return name, float(conf)
        return OTHER, 0.0

    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], list(NOTICE_TYPES).index(kv[0])))
    top_name, top_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0
    return top_name, _confidence(top_score, second_score)


def to_db_notice_type(name: str) -> str:
    """把内部类型名映射到 ``kaoyan_notices.notice_type`` 枚举标签。"""
    return _DB_TYPE_BY_NAME.get(name or OTHER, "公告")
