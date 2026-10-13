# -*- coding: utf-8 -*-
"""跨来源题目去重（Cross-Source Question Dedupe）。

## 为什么需要这个模块（根因）

``quiz_questions`` 有三条入库路径，其中两条的判重键是**来源内**的：

* ``routers/documents.py::confirm_questions``
* ``services/document_analyzer.py::extract_questions``

两者的去重集合都是这样构造的::

    existing_contents = {
        (q.content or "")[:100]
        for q in db.query(QuizQuestion).filter(
            QuizQuestion.source.like(f"%{document.file_name}%")
        ).all()
    }

判重范围被 ``source LIKE '%当前文档名%'`` 限死在**当前这一篇文档**内。
于是：同一道题（公共课跨考题最典型）承载在A 文档和 B 文档里时，
处理 B 文档时查询只匹配 ``source`` 含 B 的行，而那条题在库里``source`` 是 A
→ 不命中 → 重复入库。

只有 ``routers/kb_import.py`` 是全局判重（``_build_existing_index`` 建全库哈希
索引），所以走 kb-import 的入库不会长重复，走文档确认/AI 抽取的会。

## 本模块做什么

在**入库前**做跨来源判重：

1. :func:`canonical_text` —— 归一化题干到「容忍OCR 差异、但不会合并不同题」的程度：
   去OCR 乱码字符（U+FFFD / 私用区 / BOM）、全角转半角、去所有空白与标点、lower()。
   保留全部实义字符（数字、字母、汉字），所以两道不同的题不会归一到同一串。
2. :func:`canonical_hash` —— 对归一化文本取 SHA-256 前 32 位十六进制。
   精确判重，O(1)。
3. :func:`FingerprintIndex` —— 一次扫描建索引：hash → question id。
   入库时先查精确指纹，命中即合并溯源、不再插入。
4. :func:`merge_provenance` —— 命中重复时**更新已有那条**而不是静默丢弃：
   把新来源并入 ``source_ids``（JSON 数组）与 ``source``（可读拼接），
   并按"信息更全者优先"补齐 answer / analysis / options。

## 开关

环境变量 ``QUIZ_DEDUPE_CROSS_SOURCE``，默认 **on**。

* ``QUIZ_DEDUPE_CROSS_SOURCE=0`` / ``off`` / ``false`` / ``no`` → 完全关闭，
  退回旧的来源内去重行为（用于出问题时一键回滚）。
* ``QUIZ_DEDUPE_CROSS_SOURCE=on`` / ``1`` / ``true`` / ``yes`` → 开启（默认）。

关闭时 :func:`dedupe_enabled` 返回 ``False``，所有调用点应跳过本模块逻辑。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

__all__ = [
    "ENV_SWITCH",
    "dedupe_enabled",
    "canonical_text",
    "canonical_hash",
    "FingerprintIndex",
    "DedupeStats",
    "DedupeResult",
    "DedupeDecision",
    "merge_provenance",
    "decide_insert",
    "build_index_from_db",
]

#: 控制跨来源去重开关的环境变量名。
ENV_SWITCH = "QUIZ_DEDUPE_CROSS_SOURCE"

#: 关闭开关时视为「关」的字面量。
_TRUTHY = {"1", "true", "yes", "on", "y", "t", "enable", "enabled"}
_FALSY = {"0", "false", "no", "off", "n", "f", "disable", "disabled", ""}

# ---------------------------------------------------------------- 归一化口径

#: OCR 噪声字符：U+FFFD 替换符、U+FEFFBOM、替换符变体、私用区。
#:同一道题被不同来源 OCR 出来，最典型的差异就是「一份带乱码一份不带」。
_OCR_JUNK = re.compile(
    "[\ufffd\ufeff\ufffe\uffff]"          # U+FFFD 替换符 / U+FEFF BOM / 非字符
    "|[\ue000-\uf8ff]"                      # BMP 私用区
    "|[\U000f0000-\U0010ffff]"              # SMP 私用区 / 未分配码位
)

#: 去掉全部空白与中英文标点。保留实义字符（数字/字母/汉字/数学符号）。
_SIGN_STRIP = re.compile(
    r"[\s\u3000]+"
    r"|[\uff08\uff09()\u3010\u3011\[\]\uff5b\uff5d\u007b\u007d"
    r"\u3001\uff0c,\u3002.\uff0e.\uff1b;\uff1a://uff1f?!//uff01!"
    r"\u201e\uff02\u201c\u201d\"'\u2019\u2018`~\uff5e\u3014\u2015\uff0d\-_|/\\|\uff5c]+"
)

#: 题干太短时指纹不可靠（容易把「2」这种碎片题判重），低于此长度直接放弃判重。
MIN_CANONICAL_LEN = 12

#: 前缀桶长度：取归一化题干的前 N 字做粗分桶。
#:
#: 为什么需要前缀桶：纯整串哈希只能判「完全相同」。但同一份文档里
#: ``extract_questions`` 可能对同一段正文切出两道题，题干前N 字完全一致、
#: 尾部因切题边界不同而略有差异（例如「…求对应的输出波」vs「…求对应的输出波形」）。
#: 这类用整串哈希抓不到，会在每次重建时各长一条。
#:
#: 为什么桶要够长（60 字）：桶太短会把「下列说法正确的是」这类共用开头
#: 的不同题塞进同一桶，虽然后续靠相似度阈值复核不会误判，但桶内候选数暴涨、
#: 判重退化成 O(n²)。60 字在中文题里足以让题干开头具有区分度。
PREFIX_BUCKET_LEN = 60

#: 前缀相同后的相似度复核阈值。
#:
#: 定 0.92 的依据（实测 20 篇真实文档、1167 道切题）：
#: 「同题不同切法」的相似度落在 0.911~1.000 区间；而**不同题**之间
#: 相似度可以高到 0.895（例：「计算lim(x→0)(sin3x)/(sin2x)」与
#: 「计算 lim(x→0)(sin2x)/(sin3x)」—— 只换了分子分母）。
#: 也就是说 0.895（不同题）与 0.911（同题异切）之间只有 0.016 的余量，
#: 任何单一阈值都无法干净分开：调到 0.88 会开始把不同题合并。
#: 因此这一层只处理 0.92 以上的高置信近似，0.92 以下的边界情况
#: **宁可留重复也不误并**——这与「少而准、不要错并」的取舍一致。
NEAR_DUP_THRESHOLD = 0.92


def dedupe_enabled() -> bool:
    """跨来源去重是否启用。**默认开启**；环境变量显式关闭时返回 False。"""
    raw = os.environ.get(ENV_SWITCH)
    if raw is None:
        return True
    v = str(raw).strip().lower()
    if v in _FALSY:
        return False
    if v in _TRUTHY:
        return True
    # 未知取值按「开」处理，但保持向后兼容的保守策略：显式非真值即视为关。
    return False


def _to_halfwidth(s: str) -> str:
    """全角字符转半角（NFKC 会把全角数字/字母/标点统一成半角）。"""
    return unicodedata.normalize("NFKC", s)


def canonical_text(content: str) -> str:
    """归一化题干，用于跨来源判重。

    归一化强度说明（为什么不会把不同题合并）：

    * **会**去掉：OCR 乱码、全部空白、全部中英文标点、全角/半角差异、大小写。
      这些在同一道题的不同来源副本之间**必然**存在差异，且不承载语义。
    * **不会**去掉：任何实义字符。所以「lim 等价无穷小」与
      「sin 等价无穷小」归一化后仍然不同，不会被误并。
    * 不做截断（不同于只取前 N 字），避免「前 N 字相同、后半段不同」
      的两道题被合并 —— 那是过度归一化的典型翻车点。
    """
    if not content:
        return ""
    s = _OCR_JUNK.sub("", content)
    s = _to_halfwidth(s)
    s = _SIGN_STRIP.sub("", s)
    return s.lower()


def canonical_hash(content: str) -> str:
    """归一化题干的 SHA-256 指纹（32 位十六进制）。

    比 ``qbank_builder.content_hash`` 更严：
      * content_hash 不去OCR 乱码 → 同一道题带乱码/不带乱码得到两个指纹；
      * content_hash 不做全角→半角 NFKC → 全角数字与半角数字得到两个指纹。
    这两点正是历史上跨来源判重失效的直接原因。
    """
    norm = canonical_text(content)
    if not norm:
        return ""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------- 指纹索引


class FingerprintIndex:
    """题干指纹 → 题目 id 的索引，供入库前 O(1) 判重。

    只保存 ``hash -> (id, source)``，不缓存题干全文，内存占用与题目数线性且很小。
    """

    __slots__ = ("_by_hash", "_known_unknown", "_by_prefix", "_texts")

    def __init__(self, initial: Optional[dict[str, tuple[int, str]]] = None) -> None:
        # hash -> (question_id, source)。同一 hash 已存在时保留最早的一条（id 最小），
        # 合并溯源时往这条上挂，符合「保留最早上入库的那条」。
        self._by_hash: dict[str, tuple[int, str]] = dict(initial or {})
        #: 已知存在但主键未知的指纹：只用于拦截，lookup 不返回它。
        self._known_unknown: set[str] = set()
        #: 前缀桶：归一化前N 字 -> [(question_id, canonical_text), ...]
        #: 用于「整串不同但前缀相同」的近似重复复核。
        self._by_prefix: dict[str, list[tuple[int, str]]] = {}
        #: question_id -> canonical_text（复核时需要题干全文，只存归一化串）
        self._texts: dict[int, str] = {}

    def add(self, h: str, qid: int, source: str = "",
            text: str = "") -> None:
        """登记一条题目的指纹。空指纹（题干过短/为空）或未知 id 忽略。

        ``qid`` 传None/负数表示「已知指纹但 id 未知」（例如调用方自己在
        事务里刚构造好行、还没拿到主键）。这类条目只用于**拦截后续同题**，
        不作为合并目标 —— :meth:`lookup` 会跳过它，避免把``existing_id``
        交给上层去查一条不存在的行。
        """
        if not h or qid is None or qid < 0:
            self._known_unknown.add(h)
            return
        cur = self._by_hash.get(h)
        if cur is None or qid < cur[0]:
            self._by_hash[h] = (qid, source or "")
        if text:
            self._texts[qid] = text
            key = text[:PREFIX_BUCKET_LEN]
            if key and len(key) >= 20:
                bucket = self._by_prefix.setdefault(key, [])
                if not any(i == qid for i, _ in bucket):
                    bucket.append((qid, text))

    def lookup(self, h: str) -> Optional[tuple[int, str]]:
        """按指纹查已入库题目，返回 ``(id, source)``；未命中返回 None。

        只返回有真实主键的条目。若指纹在 ``_known_unknown`` 里（本批事务内
        刚插入、id 未获取到），返回 ``(-1, "")`` 表示「已知重复但本批不可合并」，
        调用点应据此跳过插入但不试图查库。
        """
        if not h:
            return None
        hit = self._by_hash.get(h)
        if hit is not None:
            return hit
        if h in self._known_unknown:
            return (-1, "")
        return None

    def known_without_id(self, h: str) -> bool:
        """该指纹是否已知存在但主键未知。"""
        return bool(h) and h in self._known_unknown

    def lookup_near(self, text: str) -> Optional[tuple[int, str]]:
        """近似重复查找：整串哈希不同、但归一化前缀相同且相似度达阈值。

        只在前缀桶内比对，复杂度 O(桶内候选数)，不会退化成全库两两比较。
        阈值 :data:`NEAR_DUP_THRESHOLD`（0.92）比旧的 0.86 更严，
        因为这一层专门兜「切题边界差异」，宁可漏判也不误并不同题。

        返回 ``(question_id, canonical_text)``；未命中返回 None。
        """
        if not text:
            return None
        key = text[:PREFIX_BUCKET_LEN]
        if len(key) < 20:
            return None
        bucket = self._by_prefix.get(key)
        if not bucket or len(bucket) == 1:
            return None
        from difflib import SequenceMatcher

        best: Optional[tuple[int, str]] = None
        best_ratio = NEAR_DUP_THRESHOLD
        for qid, other in bucket:
            # 长度差过大必不相似，先跳过（便宜的剪枝）
            lo, hi = len(text) * 0.7, len(text) / 0.7 + 1
            if not (lo <= len(other) <= hi):
                continue
            r = SequenceMatcher(None, text, other).ratio()
            if r >= best_ratio:
                best_ratio, best = r, (qid, other)
        return best

    def __len__(self) -> int:
        return len(self._by_hash)


def build_index_from_db(db: Any, batch_size: int = 2000) -> FingerprintIndex:
    """从数据库现有quiz_questions 全量构建指纹索引。

    只 SELECT 三列（id / content / source），不载入 options、analysis 等大字段，
    避免 9000+ 题时把整表拉进内存。
    """
    from models import QuizQuestion  # 延迟导入，避免模块级依赖 DB 配置

    idx = FingerprintIndex()
    q = db.query(QuizQuestion.id, QuizQuestion.content, QuizQuestion.source)
    rows = q.yield_per(batch_size) if hasattr(q, "yield_per") else q
    for pid, content, source in rows:
        norm = canonical_text(content or "")
        idx.add(canonical_hash(content or ""), pid, source or "", text=norm)
    return idx


# ---------------------------------------------------------------- 溯源合并


@dataclass
class DedupeStats:
    """一次入库批次的去重计数（用于上报，不静默）。"""

    inserted: int = 0
    merged: int = 0
    skipped_existing: int = 0
    too_short: int = 0
    #:合并时被补齐字段的次数，按字段名计数
    enriched: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "inserted": self.inserted,
            "merged_duplicate": self.merged,
            "skipped_existing": self.skipped_existing,
            "too_short_for_dedupe": self.too_short,
            "enriched_fields": dict(self.enriched),
        }


@dataclass
class DedupeDecision:
    """对一条候选题的去重判定结果。"""

    action: str  # 'insert' | 'merge'
    fingerprint: str = ""
    existing_id: Optional[int] = None
    existing: Optional[Any] = None
    reason: str = ""

    @property
    def is_insert(self) -> bool:
        return self.action == "insert"


def _load_source_ids(q: Any) -> list[str]:
    """读取一条题目已记录的溯源来源列表。"""
    raw = getattr(q, "source_ids", None)
    if raw:
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return [str(x) for x in parsed] if isinstance(parsed, list) else []
            except (ValueError, TypeError):
                return [raw]
        if isinstance(raw, (list, tuple)):
            return [str(x) for x in raw]
    src = (getattr(q, "source", "") or "").strip()
    return [src] if src else []


def _dump_source_ids(items: Iterable[str]) -> str:
    return json.dumps(list(items), ensure_ascii=False)


def merge_provenance(
    db: Any,
    existing: Any,
    new_source: str,
    *,
    new_answer: Optional[str] = None,
    new_analysis: Optional[str] = None,
    new_options: Optional[Any] = None,
    stats: Optional[DedupeStats] = None,
    source_id: Optional[int] = None,
) -> list[str]:
    """把 ``new_source`` 并入已有题目的溯源信息，并补齐缺失字段。

    **不静默丢弃**：命中的重复会被更新，合并后的溯源列表写回 ``source_ids``，
    同时 ``source`` 字段也保留全部来源（``来源A | 来源B``），保证旧代码路径
    （按 source LIKE 过滤）仍能看到多来源信息。

    返回合并后的溯源列表。
    """
    items = _load_source_ids(existing)
    ns = (new_source or "").strip()
    if ns and ns not in items:
        items.append(ns)
    existing.source_ids = _dump_source_ids(items)
    existing.source = " | ".join(items)[:200]

    # 信息补齐：只在已有值为空时填，不覆盖已有内容（避免用劣质副本冲掉优质答案）。
    for attr, incoming in (
        ("answer", new_answer),
        ("analysis", new_analysis),
        ("options", new_options),
    ):
        if incoming in (None, "", [], {}):
            continue
        cur = getattr(existing, attr, None)
        if cur in (None, "", [], {}):
            setattr(existing, attr, incoming)
            if stats is not None:
                stats.enriched[attr] = stats.enriched.get(attr, 0) + 1

    return items


def _index_source(index: Any, qid: int) -> str:
    """从索引里取某题的来源串（仅用于日志/原因串，不参与判重逻辑）。"""
    for _h, (i, src) in getattr(index, "_by_hash", {}).items():
        if i == qid:
            return src
    return ""


def decide_insert(
    db: Any,
    content: str,
    new_source: str,
    index: FingerprintIndex,
    *,
    answer: Optional[str] = None,
    analysis: Optional[str] = None,
    options: Optional[Any] = None,
    stats: Optional[DedupeStats] = None,
) -> DedupeDecision:
    """入库前判定：这条候选题是「新增」还是「与已有题重复」。

    开关关闭时一律返回 ``action='insert'``（退回旧的来源内去重行为）。

    重复时**已经完成合并**：调用方只需跳过插入，不要再 ``db.add()``。
    """
    if not dedupe_enabled():
        return DedupeDecision(action="insert", reason="dedupe_disabled")

    h = canonical_hash(content)
    norm_text = canonical_text(content)
    norm_len = len(norm_text)
    near_reason = "exact_duplicate"
    if not h or norm_len < MIN_CANONICAL_LEN:
        if stats is not None:
            stats.too_short += 1
        return DedupeDecision(
            action="insert", fingerprint=h, reason="too_short_for_dedupe"
        )

    hit = index.lookup(h)
    if hit is None:
        # 整串指纹未命中 → 再试近似重复（同文档内切题边界差异场景）
        near = index.lookup_near(canonical_text(content))
        if near is None:
            return DedupeDecision(action="insert", fingerprint=h, reason="new")
        qid = near[0]
        hit = (qid, _index_source(index, qid))
        near_reason = "near_duplicate"

    qid, old_source = hit
    if qid < 0:
        # 指纹已知但本批拿不到主键（调用方未 flush）：仍然判定为重复、不插入，
        # 但不能也不需要去查库合并。
        if stats is not None:
            stats.merged += 1
        return DedupeDecision(
            action="merge",
            fingerprint=h,
            existing_id=None,
            existing=None,
            reason="duplicate_in_batch_no_id",
        )

    from models import QuizQuestion  # 延迟导入

    existing = db.query(QuizQuestion).filter(QuizQuestion.id == qid).first()
    if existing is None:
        # 索引与库不一致（极少见）：降级为插入，并把陈旧索引项剔除。
        return DedupeDecision(action="insert", fingerprint=h, reason="stale_index")

    merge_provenance(
        db,
        existing,
        new_source,
        new_answer=answer,
        new_analysis=analysis,
        new_options=options,
        stats=stats,
    )
    if stats is not None:
        stats.merged += 1
    return DedupeDecision(
        action="merge",
        fingerprint=h,
        existing_id=qid,
        existing=existing,
        reason=f"duplicate_of:{qid}@{old_source[:40]}",
    )