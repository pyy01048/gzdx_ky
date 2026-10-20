# -*- coding: utf-8 -*-
"""数学公式 OCR 损坏检测（数学扫描件的主防线）。

背景（2026-10-20 实测，team-lead 提供）
--------------------------------------
数学类 PDF **全部是纯扫描件**（`27张宇数学公式手册.pdf` 190 页、
`同济大学高等数学第七版上册.pdf` 442 页，前 10 页文字层字符数全为 0，
每页 1 张图），所以 scanned → RapidOCR 是数学科目的**主路径**，不是边缘情况。

而 RapidOCR 在数学公式上会**读错**（不是读漏）：

======================================  ==========================
原文                                     RapidOCR 识别结果
======================================  ==========================
``x``                                     ``α`` / ``r``
``-``（减号）                             汉字「一」
``f(x)``                                  ``fLg(）`` / ``f()``
``f(-x)=f(x)``                            ``f（一）=f()``
======================================  ==========================

于是同一句原文能被读成：

    设函数y=f(r)…恒有f（一）=f()，则称f(α)为…偶函数

**单条正则判不了**（``f(α)`` 在正常数学书里也合法），必须看**结构信号**。

实测命中率（2026-10-20，`27张宇数学公式手册.pdf` 前 12 页，RapidOCR 真跑）
--------------------------------------------------------------------------
* 含公式字符的行 **60 条 → 命中 26 条**（43%），命中样本例如::

      为y=f().                                  → empty_call（原文 y=f(x)）
      恒有f（一r）=f（x)，则称                   → mixed_width_paren（原文 f(-x)=f(x)）
      f()为区间I内的偶函数；如果恒有f(一α)=一f(）   → empty_call + mixed_width_paren
      意的rEI,必有r士TEI,并且f(r十T)=f(),则称      → empty_call + cjk_as_operator（"士"是"+"）

* 纯中文正文行 **272 条 → 误报 0 条**（误报会白白丢掉可用内容，比漏报更贵，
  所以强信号只取「结构已坏」那种一眼可判的形态，形近字类归为弱信号）。

本模块的产出
------------
``detect_math_corruption(text) -> MathGuardResult``

* ``corrupted``（强信号命中）：这段文字里的公式**结构已经坏了**，必须重解析。
  强信号 = 括号不配对 / 半全角括号混用 / 函数调用出现空括号 / 括号里出现汉字数字
  （减号被读成「一」）。
* ``suspect``（仅弱信号命中）：**可能是**损坏（例如函数实参是希腊字母，
  原文多半是 x），但也可能是正常数学记号 → 只提示复核，不当成损坏。
* ``reasons``：命中了哪些信号，便于人工核对。

调用方（``services/parsers/rapidocr_parser.py``）把结果写进
``ParsedBlock.extra['math_corrupted']`` / ``['math_suspect']``，
下游质检（``services/ingest_pipeline.py``）据此把题降级并留痕。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

#: 希腊字母（当实参出现时是弱信号）
_GREEK = r"α-ωΑ-Ω"

#: 强信号：函数调用后紧跟空括号 —— 原文必有实参（f() / f（））
_RE_EMPTY_CALL = re.compile(r"[A-Za-z]\s*[（(]\s*[）)]")

#: 强信号：函数调用括号里是汉字数字 —— 减号被读成「一」「二」等（f（一））
#: 必须要求前面有「字母+左括号」，否则中文的「（一）单项选择题」这种**正常小节号**
#: 会被误判成损坏。
_RE_CJK_NUM_IN_PAREN = re.compile(r"[A-Za-z]\s*[（(]\s*[一二三四五六七八九十]\s*[）)]")

#: 强信号：半角开括号配全角闭括号（fLg(））/ 全角开配半角闭（f（x)）
_RE_MIXED_OPEN_HALF = re.compile(r"（[^（），,()]{0,60}?\)")
_RE_MIXED_OPEN_FULL = re.compile(r"\([^（）()]{0,60}?）")

#: 弱信号：函数实参是希腊字母（f(α)）
_RE_GREEK_ARG = re.compile(rf"[A-Za-z]{{1,4}}\s*[（(]\s*[{_GREEK}]\s*[）)]")

#: 弱信号：函数名被读成大小写混排（fLg(）—— l 被当成 1）
_RE_GARBLED_NAME = re.compile(r"[a-z][A-Z][a-z]\s*[（(]")

#: 弱信号：等号右侧出现单个孤立小写字母被当成实参（y=f(r)）
_RE_LONE_ARG = re.compile(rf"[=＝]\s*[A-Za-z]\s*\(\s*[{_GREEK}r]\s*[）)]")

#: 弱信号：形近字顶替数学运算符（RapidOCR 经典错法）
#:   "+"→士  "-"→一  "="→二  "∈"→于  "x"→工  "/"→刀
#: 判据：这些汉字**夹在字母/数字/数学符号之间**（中文散文里它们不会这样出现，
#: 例如「土地」「干净」「工程师」前后都是汉字，不会命中）。
_RE_CJK_AS_OPERATOR = re.compile(r"[A-Za-z0-9（(]\s*[士土干于工刀千]\s*[,，=＝<＞>）)0-9A-Za-z]")

#: 弱信号：右括号后跟汉字数字再跟数字（"=0" 被读成 "二0"）
_RE_CJK_NUM_AS_OPERATOR = re.compile(r"[)）]\s*[一二三四五六七八九十]\s*\d")


@dataclass
class MathGuardResult:
    """一段 OCR 文本的公式损坏判定结果。"""

    corrupted: bool = False
    suspect: bool = False
    reasons: List[str] = field(default_factory=list)

    @property
    def hit(self) -> bool:
        """有没有任何信号命中（损坏或可疑）。"""
        return self.corrupted or self.suspect

    def to_extra(self) -> Dict[str, Any]:
        """转成 ``ParsedBlock.extra`` 片段（无信号时返回空 dict）。"""
        if not self.hit:
            return {}
        extra: Dict[str, Any] = {}
        if self.corrupted:
            extra["math_corrupted"] = True
        if self.suspect:
            extra["math_suspect"] = True
        if self.reasons:
            extra["math_corrupt_reasons"] = list(self.reasons)
        return extra


def _unbalanced(text: str) -> bool:
    """括号不配对（半角与全角分别计数）。"""
    return (
        text.count("(") != text.count(")")
        or text.count("（") != text.count("）")
    )


def detect_math_corruption(text: str) -> MathGuardResult:
    """检测一段 OCR 文本里的公式损坏。

    参数
    ----
    text: OCR 出来的原文（可能夹杂中文正文）。

    返回
    ----
    :class:`MathGuardResult`：
    * ``corrupted=True`` —— 强信号命中，公式结构已坏，必须重解析；
    * ``suspect=True`` —— 只有弱信号命中，建议复核；
    * ``reasons`` —— 命中的信号名列表。
    """
    result = MathGuardResult()
    if not text or not text.strip():
        return result

    strong: List[str] = []
    weak: List[str] = []

    if _RE_EMPTY_CALL.search(text):
        strong.append("empty_call")
    if _RE_CJK_NUM_IN_PAREN.search(text):
        strong.append("cjk_num_in_paren")
    if _RE_MIXED_OPEN_HALF.search(text) or _RE_MIXED_OPEN_FULL.search(text):
        strong.append("mixed_width_paren")

    if _unbalanced(text):
        # 弱信号：行级 OCR 常把跨行公式拆开，半边括号很常见
        weak.append("unbalanced_paren")
    if _RE_GREEK_ARG.search(text):
        weak.append("greek_argument")
    if _RE_GARBLED_NAME.search(text):
        weak.append("garbled_function_name")
    if _RE_LONE_ARG.search(text):
        weak.append("lone_latin_argument")
    if _RE_CJK_AS_OPERATOR.search(text):
        weak.append("cjk_as_operator")
    if _RE_CJK_NUM_AS_OPERATOR.search(text):
        weak.append("cjk_numeral_as_operator")

    result.reasons = strong + weak
    result.corrupted = bool(strong)
    # 弱信号单独命中 → 只算「可疑」；与强信号共存时也算损坏
    result.suspect = bool(weak) and not strong
    return result


def is_math_corrupted(text: str) -> bool:
    """便捷入口：这段文本里的公式是否已损坏（强信号）。"""
    return detect_math_corruption(text).corrupted


def summarize_blocks(blocks: Any) -> Dict[str, Any]:
    """给一批块汇总损坏情况（供 pipeline 统计用）。

    返回 ``{"corrupted": n, "suspect": n, "block_ids": [...]}``。
    """
    corrupted = 0
    suspect = 0
    block_ids: List[str] = []
    for block in blocks or []:
        extra = getattr(block, "extra", None)
        if not isinstance(extra, dict):
            continue
        if extra.get("math_corrupted"):
            corrupted += 1
            block_ids.append(str(getattr(block, "block_id", "") or ""))
        elif extra.get("math_suspect"):
            suspect += 1
    return {"corrupted": corrupted, "suspect": suspect, "block_ids": block_ids}
