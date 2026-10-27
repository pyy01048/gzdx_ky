# -*- coding: utf-8 -*-
"""水印与版面噪声清洗器。

规则**外置**在 ``watermark_rules.json``，支持用户在不动代码的前提下增删特征词；
代码只负责加载、编译、执行与留证。

三类清洗目标
------------
1. ``span_rules``   行内片段：删掉命中片段，保留同行的正文。
                    典型：``判断反馈组态 东坡哥微信:xxx 第3页`` 只删水印。
2. ``line_rules``   整行特征：命中即整行丢弃。
                    典型：``--- 第1页(OCR) ---``、``考生注意：...``。
3. ``header_footer`` 按行频次统计的页眉页脚：跨页/跨文档重复出现的短行。

设计纪律（沿用本项目一贯教训）
------------------------------
- **宁可漏删，不可误杀正文**：只在确实移除过内容时才改写文本。
- **留证**：每次命中都记录 ``(规则 id, 原文片段, 行号)``，供用户抽查准确率。
- **快速预筛**：行内不含任何 fast marker 时跳过全部正则，避免全库扫描退化。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .config import WATERMARK_RULES_PATH

__all__ = [
    "Rule",
    "RulesBundle",
    "LineHit",
    "CleanResult",
    "LineFrequencyIndex",
    "load_rules",
    "strip_watermark",
    "find_residue",
    "meaningful_count",
]

_MEANINGFUL_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")

# 归一化：去空白与控制符，用于页眉页脚「同一行」的等价判定
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Rule:
    """一条编译后的清洗规则。"""

    rule_id: str
    desc: str
    kind: str            # span 或 line
    pattern: str
    compiled: re.Pattern[str]


@dataclass(frozen=True)
class RulesBundle:
    """一次加载得到的全部规则（不可变，便于跨进程复用同一份口径）。"""

    version: str
    fast_markers: tuple[str, ...]
    span_rules: tuple[Rule, ...]
    line_rules: tuple[Rule, ...]
    min_meaningful_chars: int
    hf_enabled: bool
    hf_max_line_chars: int
    hf_min_docs: int
    hf_min_hits: int


@dataclass(frozen=True)
class LineHit:
    """一次命中的证据。"""

    rule_id: str
    kind: str
    matched: str
    line_no: int


@dataclass
class CleanResult:
    """行级清洗结果。"""

    text: str
    hits: list[LineHit] = field(default_factory=list)

    @property
    def dropped_lines(self) -> int:
        return sum(1 for h in self.hits if h.kind == "line" or h.kind == "header_footer")

    @property
    def total_hits(self) -> int:
        return len(self.hits)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "dropped_lines": self.dropped_lines,
            "hits": [
                {"rule_id": h.rule_id, "kind": h.kind,
                 "matched": h.matched, "line_no": h.line_no}
                for h in self.hits
            ],
        }


def load_rules(path: str | Path | None = None) -> RulesBundle:
    """加载并编译规则表。

    Args:
        path: 规则 JSON 路径，默认 :data:`config.WATERMARK_RULES_PATH`。

    Returns:
        编译完成的 :class:`RulesBundle`。

    Raises:
        FileNotFoundError: 规则文件不存在。
        ValueError: JSON 非法，或某条正则无法编译（**不允许静默跳过**，
            否则该规则沦为死代码而使用者以为已生效）。
    """
    target = Path(path) if path is not None else WATERMARK_RULES_PATH
    if not target.exists():
        raise FileNotFoundError(f"水印规则文件不存在：{target}")
    with target.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)

    def _build(items: Iterable[dict], default_kind: str) -> list[Rule]:
        out: list[Rule] = []
        for item in items:
            pattern = item.get("pattern", "")
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"规则 {item.get('id', '<匿名>')} 的正则无法编译：{pattern!r} -> {exc}"
                ) from exc
            out.append(
                Rule(
                    rule_id=item.get("id", "<匿名>"),
                    desc=item.get("desc", ""),
                    kind=item.get("type", default_kind),
                    pattern=pattern,
                    compiled=compiled,
                )
            )
        return out

    span = _build(raw.get("span_rules", []), "span")
    line = _build(raw.get("line_rules", []), "line")
    # 页分隔标记允许各自声明 type，分别并入两类
    page = _build(raw.get("page_marker_rules", []), "line")
    for r in page:
        (span if r.kind == "span" else line).append(r)

    hf = raw.get("header_footer", {}) or {}
    return RulesBundle(
        version=str(raw.get("version", "0")),
        fast_markers=tuple(raw.get("fast_markers", [])),
        span_rules=tuple(span),
        line_rules=tuple(line),
        min_meaningful_chars=int(raw.get("min_meaningful_chars", 4)),
        hf_enabled=bool(hf.get("enabled", False)),
        hf_max_line_chars=int(hf.get("max_line_chars", 30)),
        hf_min_docs=int(hf.get("min_docs", 3)),
        hf_min_hits=int(hf.get("min_hits", 4)),
    )


def meaningful_count(text: str) -> int:
    """统计实义字符数（中英文 + 数字），用于判断某行是否已退化为空壳。"""
    return len(_MEANINGFUL_RE.findall(text or ""))


def _norm(line: str) -> str:
    return _WS_RE.sub("", line).strip()


class LineFrequencyIndex:
    """跨页/跨文档的短行频次索引，用于识别页眉页脚。

    用法：把每个「页面」或「文档」的文本喂进来，最后 :meth:`finalize`
    得到被判定为页眉页脚的归一化行集合。

    之所以同时要求 ``min_docs`` 与 ``min_hits``：单文档内部重复可能是正文
    反复出现的公式或固定句式，而**跨文档重复**才是页眉页脚的强证据。
    """

    def __init__(self, bundle: RulesBundle) -> None:
        self._max_chars = bundle.hf_max_line_chars
        self._min_docs = bundle.hf_min_docs
        self._min_hits = bundle.hf_min_hits
        self._enabled = bundle.hf_enabled
        self._hits: dict[str, int] = {}
        self._docs: dict[str, set[str]] = {}
        self._bad: set[str] = set()

    def add(self, doc_id: str, text: str | None) -> None:
        """喂入一篇文档/一页文本。

        Args:
            doc_id: 文档标识（同一 doc_id 内重复计多次，但只贡献 1 个「文档数」）。
            text: 文本内容。
        """
        if not self._enabled or not text:
            return
        seen: set[str] = set()
        for line in text.split("\n"):
            norm = _norm(line)
            if not norm or len(norm) > self._max_chars:
                continue
            if meaningful_count(norm) < 2:
                continue
            self._hits[norm] = self._hits.get(norm, 0) + 1
            self._docs.setdefault(norm, set()).add(str(doc_id))
            seen.add(norm)

    def finalize(self) -> frozenset[str]:
        """判定并返回页眉页脚行集合（归一化后的字面量）。"""
        bad = {
            norm
            for norm, n in self._hits.items()
            if n >= self._min_hits and len(self._docs.get(norm, ())) >= self._min_docs
        }
        self._bad = bad
        return frozenset(bad)

    @property
    def is_ready(self) -> bool:
        return bool(self._bad) and self._enabled

    def contains(self, line: str) -> bool:
        return self._enabled and _norm(line) in self._bad


def _clean_line(
    line: str,
    line_no: int,
    bundle: RulesBundle,
    hf: LineFrequencyIndex | None,
) -> tuple[str | None, list[LineHit]]:
    """清洗单行。返回 ``(新行 or None, 命中证据)``；``None`` 表示整行丢弃。"""
    hits: list[LineHit] = []
    if not line.strip():
        return line, hits

    # 页眉页脚检查必须**先于**快速预筛。
    # 反例：PPT 导航按钮（下页/返回/总目录）与裸页码这类行完全不含任何
    # fast marker，若放在预筛之后就会被整段跳过清洗，却在 find_residue 侧
    # （无预筛）被检出 —— 清洗与验收口径不一致，喷出一堆「假残留」。
    # 这里是普通分支去重后的集合查表，代价是常数级的归一化开销。
    if hf is not None and hf.contains(line):
        hits.append(LineHit("header_footer", "header_footer", line.strip()[:120], line_no))
        return None, hits

    # 快速预筛：没有任何 marker 就跳过全部正则
    if bundle.fast_markers and not any(m in line for m in bundle.fast_markers):
        return line, hits

    # 整行特征：命中即丢弃整行
    for rule in bundle.line_rules:
        m = rule.compiled.search(line)
        if m:
            hits.append(LineHit(rule.rule_id, "line", m.group(0)[:120], line_no))
            return None, hits

    # 行内片段剔除
    cur = line
    for rule in bundle.span_rules:
        m = rule.compiled.search(cur)
        if m:
            hits.append(LineHit(rule.rule_id, "span", m.group(0)[:120], line_no))
            cur = rule.compiled.sub(" ", cur)
    if hits:
        cur = re.sub(r"[ \t]{2,}", " ", cur).strip()
        if meaningful_count(cur) < bundle.min_meaningful_chars:
            return None, hits
    return cur, hits


def strip_watermark(
    text: str | None,
    bundle: RulesBundle | None = None,
    hf: LineFrequencyIndex | None = None,
) -> tuple[str, list[dict]]:
    """清洗整段文本并返回证据。

    Args:
        text: 原文。
        bundle: 规则集，默认自动加载。
        hf: 可选的页眉页脚索引（需已 ``finalize``）。

    Returns:
        ``(clean_text, removed_hits)``。``removed_hits`` 为 dict 列表，
        每项含 ``rule_id / kind / matched / line_no``，可直接落 JSONL 供抽查。
    """
    if not text:
        return (text or ""), []
    rules = bundle if bundle is not None else load_rules()
    kept: list[str] = []
    all_hits: list[LineHit] = []
    for idx, line in enumerate(text.split("\n"), start=1):
        new, hits = _clean_line(line, idx, rules, hf)
        all_hits.extend(hits)
        if new is None:
            continue
        kept.append(new)
    if not all_hits:
        # 未发生任何清洗：原样返回，避免把「单纯空白归一」伪造成已清洗
        return text, []
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return out, [h.__dict__ for h in all_hits]


def find_residue(
    text: str | None, bundle: RulesBundle | None = None
) -> list[dict]:
    """**只检测不改文本**：返回文本中仍存在的水印/噪声命中。

    用于 :mod:`verify` 的「水印残留检测」——与 :func:`strip_watermark`
    共用同一份规则，杜绝「清洗口径」与「验收口径」不一致导致的假合格/假失败。
    """
    if not text:
        return []
    rules = bundle if bundle is not None else load_rules()
    hits: list[dict] = []
    for idx, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        if rules.fast_markers and not any(m in line for m in rules.fast_markers):
            continue
        for rule in rules.span_rules:
            m = rule.compiled.search(line)
            if m:
                hits.append(
                    {"rule_id": rule.rule_id, "kind": "span",
                     "matched": m.group(0)[:120], "line_no": idx}
                )
        for rule in rules.line_rules:
            m = rule.compiled.search(line)
            if m:
                hits.append(
                    {"rule_id": rule.rule_id, "kind": "line",
                     "matched": m.group(0)[:120], "line_no": idx}
                )
    return hits
