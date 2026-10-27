# -*- coding: utf-8 -*-
"""来源分类（教材 / 真题 / 习题 / 模拟）与科目归一。

为什么要做优先级裁决
--------------------
``quiz_questions.source`` 现存两个前缀 ``知识库:`` / ``真题:``，但它们**不可信**：
实测发现大量错配（数据来自用户导入时在 UI 上选错分类）：

- ``知识库:贵大16-25真题.pdf``   405 题：文件名明确是真题，却落成知识库 → **提升**为 past_exam。
- ``真题:数字电子技术基础章节题库.pdf`` 817 题：文件名明确是章习题，却落成真题 → **降级**为 exercise。

因此判据优先级定为：**文件名 > 正文 > source 前缀**。
文件名是作者命名的原始意图，正文是卷面客观证据，而 source 前缀只是当时的一次
下拉框选择，最容易错。三者冲突时显式留证（`evidence` 里写明提升/降级），
不做静默覆盖。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import SUBJECT_ALIASES_PATH

__all__ = [
    "ORIGINS",
    "load_subject_aliases",
    "normalize_subject",
    "classify_origin",
    "split_source_prefix",
]

ORIGINS = ("textbook", "past_exam", "exercise", "mock")

# ---- 文件名 / 正文 强特征（按置信度从强到弱） ----------------------------- #
_FILENAME_PAST_EXAM_RE = re.compile(
    r"(真题|历年真题|考研真题|招生考试试题|入学考试|初试试题|复试试题|回忆版真题|真\s*题)"
)
_FILENAME_EXERCISE_RE = re.compile(
    r"(题库|章习题|章节题库|习题解答|课后题|课后习题|习题集|自测题|同步练习|练习册|作业题)"
)
_FILENAME_MOCK_RE = re.compile(
    r"(?:全真模拟|模拟[卷题]|模拟考试|模拟测验|模拟预测|模拟训练|"
    r"押题|预测[卷题]|冲刺卷|密押|模考)"
)
_FILENAME_TEXTBOOK_RE = re.compile(
    r"(教材|讲义|课件|教案|笔记|教程|教科书|考点精讲|知识点总结|学习指导|复习全书|复习资料|讲义稿)"
)
_CONTENT_PAST_EXAM_RE = re.compile(
    r"(考生注意|全部答案必须写在答题纸|本试题纸|考试科目代码|考试科目：|"
    r"硕士研究生招生考试试题|招生考试试题|考试时间\s*[:：]|满分\s*[:：]\s*\d{2,3})"
)
_CONTENT_EXAM_HEADER_RE = re.compile(r"(?:^|\n)\s*(?:一|二|三|四|五)、?\s*(?:选择题|填空题|判断题|简答题|计算题)")

# 科目名中的「模拟」字样必须与「模拟卷/模拟题」语义区分开：
# 「模拟电子技术基础 第6版」是**教材**（4981 题都是这门课），而
# 「2023年6月模拟电子技术模拟考试」里第二个「模拟」才是「模拟考」。
# 因此判定时先把「模拟电子/模拟电路/模拟部分」这些科目词掩掉再匹配。
_SUBJECT_MONI_TOKEN_RE = re.compile(r"模拟(?:电子|电路|部分)")

# source 前缀（形如 ``真题:xxx.pdf``）
_SOURCE_PREFIX_RE = re.compile(r"^\s*([^:：]{1,10})\s*[:：]\s*(.*)$", re.S)

_SUBJECT_CACHE: dict | None = None


def load_subject_aliases(path: str | Path | None = None) -> tuple[list[tuple[str, str, str]], dict, str]:
    """加载科目别名表。

    Args:
        path: JSON 路径，默认 :data:`config.SUBJECT_ALIASES_PATH`。

    Returns:
        ``(entries, buckets, unknown_bucket)``。``entries`` 已按别名长度降序，
        保证「数字电子技术」优先于「电子技术」被命中。

    Raises:
        FileNotFoundError: 别名表不存在。
        ValueError: JSON 非法。
    """
    global _SUBJECT_CACHE
    if _SUBJECT_CACHE is not None:
        return _SUBJECT_CACHE  # type: ignore[return-value]

    target = Path(path) if path is not None else SUBJECT_ALIASES_PATH
    if not target.exists():
        raise FileNotFoundError(f"科目别名表不存在：{target}")
    with target.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)

    entries: list[tuple[str, str, str]] = []
    for canonical, meta in (raw.get("canonical") or {}).items():
        bucket = meta.get("bucket", raw.get("unknown_bucket", "unknown"))
        for alias in meta.get("aliases") or [canonical]:
            entries.append((str(alias).strip(), canonical, bucket))
    # 长别名优先，避免「电子技术」抢先命中「数字电子技术」
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    buckets = raw.get("buckets", {})
    unknown = raw.get("unknown_bucket", "unknown")
    _SUBJECT_CACHE = (entries, buckets, unknown)
    return _SUBJECT_CACHE


def _strip_ext(name: str) -> str:
    return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", (name or "").strip())


def split_source_prefix(source: str | None) -> tuple[str, str]:
    """拆分 ``source`` 的前缀与文件名部分。

    Args:
        source: 形如 ``真题:xxx.pdf`` 或纯文件名。

    Returns:
        ``(prefix, rest)``；无前缀时 ``prefix`` 为空串。
    """
    if not source:
        return "", ""
    m = _SOURCE_PREFIX_RE.match(source)
    if not m:
        return "", source.strip()
    return m.group(1).strip(), m.group(2).strip()


def normalize_subject(
    subject: str | None = None,
    source: str | None = None,
    file_name: str | None = None,
) -> tuple[str, str, str | None]:
    """科目归一。

    优先匹配显式的 ``subject`` 列；缺失或判定为 unknown 时，回退到 source /
    file_name（IMA 导入的资料常有文件名带科目而无 subject 列的情况）。

    Args:
        subject: 科目列原值。
        source: source 列原值（形如 ``知识库:xxx``）。
        file_name: 文件名。

    Returns:
        ``(canonical, bucket, matched_alias)``；未命中时 canonical 为空串、
        bucket 为 ``unknown``。
    """
    entries, _buckets, unknown = load_subject_aliases()
    candidates: list[str] = []
    for raw in (subject, source, _strip_ext(file_name or "")):
        if raw and str(raw).strip():
            candidates.append(str(raw).strip())
    if source:
        prefix, rest = split_source_prefix(source)
        if rest:
            candidates.append(_strip_ext(rest))

    for probe in candidates:
        lowered = probe.lower()
        for alias, canonical, bucket in entries:
            if alias.lower() in lowered:
                return canonical, bucket, alias
    return "", unknown, None


def classify_origin(
    source: str | None = None,
    file_name: str | None = None,
    content: str | None = None,
) -> tuple[str, float, list[str]]:
    """判定题目/文档的来源类型。

    Args:
        source: source 列原值（可能带 ``真题:`` / ``知识库:`` 前缀）。
        file_name: 文件名。
        content: 正文片段（可为空）。

    Returns:
        ``(origin, confidence, evidence)``。``origin`` 取 :data:`ORIGINS` 之一，
        无法确定时为 ``unknown``；``evidence`` 说明每条判据，冲突时写明提升/降级。
    """
    evidence: list[str] = []
    prefix, source_name = split_source_prefix(source)
    name = _strip_ext(file_name or source_name or "")
    window = (content or "")[:1200]

    # 1) 文件名优先（作者原始意图最强）
    if _FILENAME_PAST_EXAM_RE.search(name):
        evidence.append("filename=真题特征")
        return "past_exam", 0.90, evidence
    # 掩掉科目名里的「模拟」再判模拟卷/押题，避免 4981 道模电题被误判
    moni_probe = _SUBJECT_MONI_TOKEN_RE.sub("", name)
    if _FILENAME_MOCK_RE.search(moni_probe):
        evidence.append("filename=模拟/押题特征")
        return "mock", 0.90, evidence
    if _FILENAME_EXERCISE_RE.search(name):
        evidence.append("filename=题库/习题特征")
        return "exercise", 0.85, evidence
    if _FILENAME_TEXTBOOK_RE.search(name):
        evidence.append("filename=教材/讲义特征")
        return "textbook", 0.85, evidence

    # 2) 正文客观证据（卷面抬头）
    if window and _CONTENT_PAST_EXAM_RE.search(window):
        hits = _CONTENT_PAST_EXAM_RE.findall(window)
        strong = len(set(hits)) >= 2
        evidence.append(f"content=卷面抬头({hits[0][:20]})")
        return "past_exam", (0.88 if strong else 0.72), evidence
    if window and _CONTENT_EXAM_HEADER_RE.search(window):
        evidence.append("content=题型大标题谱系")
        return "exercise", 0.60, evidence

    # 3) source 前缀兜底。能走到这里说明文件名与正文都没有更强信号，
    #    此时前缀是可用的（弱）证据，不存在冲突需要裁决。
    if prefix == "真题":
        evidence.append("source_prefix=真题(弱)")
        return "past_exam", 0.60, evidence
    if prefix in {"模拟", "押题"}:
        evidence.append("source_prefix=模拟(弱)")
        return "mock", 0.70, evidence
    if prefix == "知识库":
        evidence.append("source_prefix=知识库(弱)")
        return "textbook", 0.55, evidence

    return "unknown", 0.0, evidence or ["无可用判据"]
