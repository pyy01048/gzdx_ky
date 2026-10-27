# -*- coding: utf-8 -*-
"""题目 canonical 结构与「选项错乱」修复 + 校验门。

真实脏数据形态（全部来自 kaoyan.db 实测抽样，不是想象）
-------------------------------------------------------
``options`` 列存的是 **JSON 字符串**，无选项时存的是四字符 ``"null"``
（既不是 SQL NULL 也不是空串，所以 ``WHERE options IS NULL`` 查不出来——
这是历史体检脚本把「无选项」误报成 4710 的根因）。有值的部分形态如下：

    id=18  ["A、", "B）当成反相器使用，则", "A、B 端应__ 连接。",
            "A.A 或B 中有一个接1", "B.A 或B 中有一个接0",
            "C.A 和B 并联使用", "D.不能实现"]
            -> 题干被切碎混进选项；真正有效的选项是从第 4 项起的那组 A/B/C/D。
    id=21  ["C）＝∑m(...)，则它的最大项表达式是F＝ （ ）", "A、πM(0,1,2,6)", ...]
            -> 首项是上一题残留的题干尾巴。
    id=22  ["A、输出电压...", "B、输出电压...", "C、电路的抗干扰能力 二、填空题（每题5 分）"]
            -> 末项粘连了下一个题型大标题。
    id=58  ["D）工作时需加反向电压..."]  -> 只有 1 项且无 A，整段都是题干碎片。
    id=16  ["A、", "B、", "C、", "D），__是其最小项...", "A.\ufffd\ufffd", ...]
            -> 前 4 项空壳，后 4 项是乱码。

修复策略：**在被打散的标签序列里找回最长的 A→B→C→… 连续递增段**。
比「从第一个 A 开始取」稳健得多——id=18 如果从第一个 A 开始，会把空壳和
碎片当成选项；取最长递增段则能精确命中真正那组 A/B/C/D。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .config import MIN_CONTENT_CHARS

__all__ = [
    "MIN_OPTIONS",
    "MAX_STEM_CHARS",
    "OBJECTIVE_TYPES",
    "CanonicalQuestion",
    "parse_options_raw",
    "normalize_options",
    "validate_question",
]

MIN_OPTIONS = 2
MAX_STEM_CHARS = 2000
#: 题干最小实义字符数（与 verify MIN_CONTENT_CHARS 同源）
MIN_STEM_CHARS = MIN_CONTENT_CHARS
OBJECTIVE_TYPES = frozenset({"single", "multiple", "judge", "multi", "choice", "单选", "多选", "判断"})

# 选项标签：支持 A、 / A. / A． / A) / A） / （A） / [A] / 【A】
_OPTION_LABEL_RE = re.compile(
    r"^\s*[（(\[【]?\s*([A-F])\s*[、.．)）\]】]\s*(.*)$", re.I | re.S
)

# 选项文本尾部粘连的「下一个题型大标题」
_TRAILING_SECTION_RE = re.compile(
    r"[一二三四五六七八九十]+\s*[、.．]\s*"
    r"(?:选择题|填空题|判断题|简答题|计算题|分析题|设计题|证明题|作图题|画图题|论述题|综合题|应用题|名词解释)"
    r"\s*(?:[（(][^）)]{0,60}[）)])?\s*$"
)

_MEANINGFUL_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_MOJIBAKE_RE = re.compile(r"\ufffd")
_LETTERS = "ABCDEF"


@dataclass
class CanonicalQuestion:
    """一道理应干净的题目中间态（与具体存储引擎无关）。"""

    question_id: int | None = None
    stem: str = ""
    options: list[dict] = field(default_factory=list)      # [{key, text}]
    answer: str = ""
    analysis: str = ""
    knowledge_points: list[str] = field(default_factory=list)
    question_type: str = ""
    origin: str = "unknown"          # textbook / past_exam / exercise / mock
    origin_confidence: float = 0.0
    subject_raw: str = ""
    subject_norm: str = ""
    subject_bucket: str = "unknown"
    source: str = ""
    images: list[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "stem": self.stem,
            "options": self.options,
            "answer": self.answer,
            "analysis": self.analysis,
            "knowledge_points": self.knowledge_points,
            "question_type": self.question_type,
            "origin": self.origin,
            "origin_confidence": round(self.origin_confidence, 3),
            "subject_raw": self.subject_raw,
            "subject_norm": self.subject_norm,
            "subject_bucket": self.subject_bucket,
            "source": self.source,
            "images": self.images,
            "diagnostics": self.diagnostics,
        }


def parse_options_raw(raw: Any) -> tuple[list[str], dict]:
    """把存储里的 ``options`` 折解析成字符串列表。

    兼容四种历史形态：JSON 字符串 / Python 字典 / 已解析的 list / 字符串 ``"null"``。

    Args:
        raw: 原始 options 值。

    Returns:
        ``(items, info)``。``info`` 记录解析形态，便于留证。
    """
    info: dict = {"raw_type": type(raw).__name__}
    if raw is None:
        info.update(shape="null", n=0)
        return [], info
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
        text = text.strip()
        if not text or text.lower() == "null":
            info.update(shape="null_string", n=0)
            return [], info
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            info.update(shape="unparsable", n=1)
            return [text], info
        if isinstance(parsed, dict):
            items = [f"{k}、{v}" if str(k).strip() not in str(v)[:2] else str(v)
                     for k, v in parsed.items()]
        elif isinstance(parsed, (list, tuple)):
            items = list(parsed)
        else:
            info.update(shape=f"scalar_{type(parsed).__name__}", n=0)
            return [], info

    out: list[str] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, dict):
            # {"key": "A", "text": "..."} / {"A": "..."}
            if "text" in item:
                out.append(f"{item.get('key', '')}、{item.get('text', '')}")
            else:
                out.extend(f"{k}、{v}" for k, v in item.items())
        else:
            out.append(str(item))
    info.update(shape="list", n=len(out))
    return out, info


def _longest_abc_run(pairs: Sequence[tuple[str, str]]) -> tuple[int, int]:
    """在被打散的标签序列里找**最长**的 A→B→C→… 连续递增段。

    Args:
        pairs: ``[(key_letter, text), ...]``，按原始顺序。

    Returns:
        ``(start_index, run_len)``；无合法段时返回 ``(-1, 0)``。
    """
    best_start, best_len = -1, 0
    n = len(pairs)
    for start in range(n):
        if pairs[start][0] != "A":
            continue
        expect, length = 0, 0
        idx = start
        while idx < n and pairs[idx][0] == _LETTERS[expect]:
            length += 1
            expect += 1
            if expect >= len(_LETTERS):
                break
            idx += 1
        if length > best_len:
            best_start, best_len = start, length
    return best_start, best_len


def normalize_options(raw: Any) -> tuple[list[dict], dict]:
    """把任意脏形态的 ``options`` 归一成 ``[{key, text}]``。

    处理顺序：解析 → 逐项识别标签 → 取最长递增段 → 剔除空壳/乱码/尾部标题。

    Args:
        raw: 原始 options 值。

    Returns:
        ``(options, diagnostics)``。``diagnostics`` 含 ``stem_leaks``（应切回题干的
        碎片）、``dropped``（被丢弃项及原因）、``before/after`` 数量等证据。
    """
    items, diag = parse_options_raw(raw)
    diag.update(stem_leaks=[], dropped=[], trailing_removed=[],
                before=len(items), after=0, label_inferred=False, run_len=0)

    labeled: list[tuple[str, str, int]] = []   # (key, text, item_index)
    leaks: list[str] = []
    for i, item in enumerate(items):
        m = _OPTION_LABEL_RE.match(item)
        if m:
            labeled.append((m.group(1).upper(), (m.group(2) or "").strip(), i))
        else:
            leaks.append(item.strip())

    # 全部没有标签且数量 >= 2：按位置补编号为 A/B/C…（ tolerate 无标签历史数据）
    if not labeled and len(items) >= MIN_OPTIONS:
        labeled = [(_LETTERS[i], it.strip(), i) for i, it in enumerate(items) if i < len(_LETTERS)]
        leaks = []
        diag["label_inferred"] = True

    diag["stem_leaks"] = [x for x in leaks if x]
    if not labeled:
        return [], diag

    start, run_len = _longest_abc_run([(k, t) for k, t, _ in labeled])
    diag["run_len"] = run_len
    if start < 0 or run_len < MIN_OPTIONS:
        # 没有合法的 A→B 序列：整组都是碎片，全部回退为题干尾巴
        diag["stem_leaks"] = [it.strip() for it in items if it.strip()]
        return [], diag

    run = labeled[start: start + run_len]
    options: list[dict] = []
    for key, text, item_index in run:
        orig = items[item_index].strip()
        if not text:
            diag["dropped"].append({"item": orig, "reason": "empty_label"})
            continue
        # 尾部粘连的下一个题型大标题
        tm = _TRAILING_SECTION_RE.search(text)
        if tm:
            diag["trailing_removed"].append({"item": orig, "removed": tm.group(0)})
            text = _TRAILING_SECTION_RE.sub("", text).strip()
        if not _MEANINGFUL_RE.search(text):
            diag["dropped"].append({"item": orig, "reason": "no_meaningful_char"})
            continue
        if _MOJIBAKE_RE.search(text):
            diag["dropped"].append({"item": orig, "reason": "mojibake"})
            continue
        options.append({"key": key, "text": re.sub(r"\s{2,}", " ", text)})

    diag["after"] = len(options)
    return options, diag


_ANSWER_LETTER_RE = re.compile(r"[A-F]")


def _answer_letters(answer: str) -> list[str]:
    """从答案字段里抽出选项字母；答案非纯字母时返回空列表。"""
    if not answer:
        return []
    cleaned = re.sub(r"[^A-Fa-f]", "", answer).upper()
    return list(cleaned)


def validate_question(q: CanonicalQuestion) -> dict:
    """结构校验门：不达标的题目进待修复队列，**不允许**直接进入题库。

    硬错误（``errors``）决定 ``ok``；软提示（``warnings``）只降分。

    Args:
        q: 已归一的 canonical 题目。

    Returns:
        ``{"ok": bool, "errors": [...], "warnings": [...], "score": float}``。
    """
    errors: list[str] = []
    warnings: list[str] = []

    stem_len = len(_MEANINGFUL_RE.findall(q.stem))
    if stem_len < MIN_STEM_CHARS:
        errors.append("stem_too_short")
    if len(q.stem) > MAX_STEM_CHARS:
        errors.append("stem_too_long")
    if _MOJIBAKE_RE.search(q.stem):
        errors.append("stem_mojibake")

    keys = [o.get("key", "") for o in q.options]
    texts = [o.get("text", "") for o in q.options]

    if q.question_type in OBJECTIVE_TYPES:
        if len(q.options) < MIN_OPTIONS:
            errors.append("options_missing")
        else:
            expect = [_LETTERS[i] for i in range(len(keys))]
            if keys != expect:
                errors.append("options_key_not_contiguous")
            dupes = {t for t in texts if texts.count(t) > 1}
            if dupes:
                warnings.append("options_duplicate_text")
    elif len(q.options) > 0 and len(q.options) < MIN_OPTIONS:
        warnings.append("single_option_dropped_as_leak")

    # 答案校验：客观题的答案必须是选项里真实存在的字母
    letters = _answer_letters(q.answer)
    if not q.answer.strip():
        warnings.append("answer_missing")
    elif q.options and letters and not set(letters) <= set(keys):
        errors.append("answer_not_in_options")

    if q.origin == "unknown":
        warnings.append("origin_unclassified")

    if not q.subject_norm:
        warnings.append("subject_unmapped")

    score = 1.0 - 0.25 * len(errors) - 0.05 * len(warnings)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "score": max(0.0, round(score, 3)),
    }
