# -*- coding: utf-8 -*-
"""准确率验证器：管线产物的抽样验收与硬门禁。

为什么要独立一层验证
--------------------
清洗器自己宣称「我清干净了」不算证据。本模块**独立于清洗流程**再跑一遍
检测：用同一份规则表扫描**转换后的产物**，检查水印是否真的没了、结构是否真的
达标。两者共用规则但不是同一段代码，避免「清洗器写错了自己也测不出来」。

四项硬检查
----------
1. ``content_not_empty``  正文实义字符达标，杜绝「空文档」「空题干」。
2. ``no_watermark_residue`` 用 :func:`watermark.find_residue` 复查残留。
3. ``no_mojibake``        无 U+FFFD 乱码（转码/OCR 失败的直接证据）。
4. ``structure_complete`` 题目通过 :func:`question_schema.validate_question`。

三项对外指标（用户要的「99%」就量在这里）
----------------------------------------
- ``watermark_residue_rate`` 水印残留率 = 残留命中数 / 抽样数
- ``option_fix_rate``       选项修复率 = 修复成功数 / 原本错乱数
- ``structure_pass_rate``   结构达标率 = 通过的结构数 / 抽样数

抽样用**固定种子**，保证同一批数据两次跑出的数字完全一致，便于用户复核和
回归对比；否则「这次 99.2% 上次 98.7%」根本无法归因。
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from . import watermark as wm
from .config import (
    DEFAULT_ACCURACY_THRESHOLD,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    ETL_OUT_DIR,
    MIN_CONTENT_CHARS,
)
from .question_schema import CanonicalQuestion, validate_question

__all__ = [
    "MIN_CONTENT_CHARS",
    "count_meaningful",
    "CheckResult",
    "VerificationReport",
    "GateRejected",
    "sample_records",
    "verify_record",
    "verify_batch",
    "enforce_gate",
]

_MOJIBAKE_RE = re.compile(r"\ufffd")
_MEANINGFUL_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


@dataclass(frozen=True)
class CheckResult:
    """单项检查结果。"""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class VerificationReport:
    """一次验收的完整报告。"""

    total: int = 0
    passed: int = 0
    failed: int = 0
    threshold: float = DEFAULT_ACCURACY_THRESHOLD
    metrics: dict = field(default_factory=dict)
    check_summary: dict = field(default_factory=dict)
    failed_samples: list[dict] = field(default_factory=list)
    seed: int = DEFAULT_SEED
    sampled: bool = False

    @property
    def accuracy(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    @property
    def gate_passed(self) -> bool:
        return self.accuracy >= self.threshold

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "accuracy": round(self.accuracy, 4),
            "threshold": self.threshold,
            "gate_passed": self.gate_passed,
            "metrics": self.metrics,
            "check_summary": self.check_summary,
            "failed_samples": self.failed_samples,
            "seed": self.seed,
            "sampled": self.sampled,
        }


class GateRejected(RuntimeError):
    """验收未达阈值，拒绝进入下一阶段（入库 / 上线）。"""

    def __init__(self, report: VerificationReport) -> None:
        self.report = report
        super().__init__(
            f"验收未通过：准确率 {report.accuracy:.2%} < 阈值 {report.threshold:.2%}"
            f"（{report.passed}/{report.total}）。拒绝入库。"
        )


def count_meaningful(text: str) -> int:
    """统计实义字符数（中英文与数字）。

    与白带空白的 len() 不同：标点、OCR 装饰符号不计入，避免「一行全是破折号」
    被当成有内容。
    """
    return len(_MEANINGFUL_RE.findall(text or ""))


def sample_records(records: Sequence[dict], n: int, seed: int = DEFAULT_SEED) -> list[dict]:
    """确定性抽样。

    Args:
        records: 全部记录。
        n: 目标抽样数，超过总量时返回全部（顺序打乱后取前 n）。
        seed: 随机种子，固定以保证可复现。

    Returns:
        抽样后的记录列表。
    """
    items = list(records)
    if n <= 0 or len(items) <= n:
        return items
    rng = random.Random(seed)
    return rng.sample(items, n)


def verify_record(
    record: dict,
    bundle: wm.RulesBundle | None = None,
    hf: wm.LineFrequencyIndex | None = None,
) -> list[CheckResult]:
    """对单条已转换记录做四项硬检查。

    Args:
        record: 转换后的记录字典。需含 ``text``（正文）；题目额外读
            ``options`` / ``answer`` / ``question_type`` 等字段。
        bundle: 规则集，默认加载。
        hf: 已 finalize 的页眉页脚索引（用于复检页眉页脚是否真的剔除干净）。

    Returns:
        :class:`CheckResult` 列表，**包含失败项与通过项**，便于统计各项通过率。
    """
    rules = bundle if bundle is not None else wm.load_rules()
    text = record.get("text") or record.get("clean_text") or ""
    results: list[CheckResult] = []

    # 1) 正文非空
    meaningful = len(_MEANINGFUL_RE.findall(text))
    results.append(
        CheckResult("content_not_empty", meaningful >= MIN_CONTENT_CHARS,
                    f"实义字符={meaningful}")
        if meaningful >= MIN_CONTENT_CHARS
        else CheckResult("content_not_empty", False, f"实义字符={meaningful} < {MIN_CONTENT_CHARS}")
    )

    # 2) 水印残留：与清洗共用同一份规则的**独立检测**
    residue = wm.find_residue(text, rules)
    if hf is not None and hf.is_ready:
        for line in text.split("\n"):
            if hf.contains(line):
                residue.append(
                    {"rule_id": "header_footer", "kind": "header_footer",
                     "matched": line.strip()[:120], "line_no": -1}
                )
    results.append(
        CheckResult("no_watermark_residue", not residue,
                    f"残留 {len(residue)} 处")
        if residue
        else CheckResult("no_watermark_residue", True, "")
    )

    # 3) 乱码
    bad = len(_MOJIBAKE_RE.findall(text))
    results.append(
        CheckResult("no_mojibake", bad == 0, f"U+FFFD x{bad}")
        if bad
        else CheckResult("no_mojibake", True, "")
    )

    # 4) 结构完整性：题目走 validate_question，文档走 meta 检查
    if record.get("kind") == "question":
        q = CanonicalQuestion(
            question_id=record.get("question_id"),
            stem=record.get("stem") or text,
            options=record.get("options") or [],
            answer=record.get("answer") or "",
            analysis=record.get("analysis") or "",
            question_type=record.get("question_type") or "",
            origin=record.get("origin") or "unknown",
            subject_norm=record.get("subject_norm") or "",
        )
        verdict = validate_question(q)
        detail = ";".join(verdict["errors"]) or ";".join(verdict["warnings"])
        results.append(CheckResult("structure_complete", bool(verdict["ok"]), detail))
    else:
        meta = record.get("meta") or {}
        ok = not meta.get("error") and bool(text.strip())
        results.append(
            CheckResult("structure_complete", bool(ok), meta.get("error") or "ok")
        )
    return results


def verify_batch(
    records: Iterable[dict],
    *,
    threshold: float = DEFAULT_ACCURACY_THRESHOLD,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: int = DEFAULT_SEED,
    bundle: wm.RulesBundle | None = None,
    hf: wm.LineFrequencyIndex | None = None,
) -> VerificationReport:
    """对一批已转换记录做抽样验收。

    Args:
        records: 已转换的记录。
        threshold: 准确率门禁阈值。
        sample_size: 抽样数；``<=0`` 表示全量。
        seed: 随机种子。
        bundle: 规则集。
        hf: 页眉页脚索引。

    Returns:
        :class:`VerificationReport`。
    """
    rules = bundle if bundle is not None else wm.load_rules()
    items = list(records)
    did_sample = sample_size > 0 and len(items) > sample_size
    subset = sample_records(items, sample_size, seed) if did_sample else items

    report = VerificationReport(threshold=threshold, seed=seed, sampled=did_sample)
    report.total = len(subset)

    check_tally: dict[str, int] = {}
    wm_residue = 0
    opt_broken = 0
    opt_fixed = 0
    struct_pass = 0

    for rec in subset:
        results = verify_record(rec, rules, hf)
        failed = [r for r in results if not r.passed]
        for r in results:
            if r.passed:
                check_tally[r.name] = check_tally.get(r.name, 0) + 1
        if failed:
            report.failed += 1
            if len(report.failed_samples) < 20:
                report.failed_samples.append({
                    "id": rec.get("question_id") or rec.get("id") or rec.get("doc_id"),
                    "kind": rec.get("kind", ""),
                    "failed_checks": [
                        {"name": f.name, "detail": f.detail} for f in failed
                    ],
                    "preview": (rec.get("text") or rec.get("stem") or "")[:160],
                })
        else:
            report.passed += 1

        # 三项对外指标
        if any(r.name == "no_watermark_residue" and not r.passed for r in results):
            wm_residue += 1
        diag = rec.get("diagnostics") or {}
        if rec.get("kind") == "question":
            before = diag.get("before")
            after = diag.get("after")
            if before is not None and before > 0 and before != after:
                opt_broken += 1
                if (after or 0) >= 2:
                    opt_fixed += 1
            if any(r.name == "structure_complete" and r.passed for r in results):
                struct_pass += 1

    n = report.total or 1
    q_total = sum(1 for r in subset if r.get("kind") == "question") or 1
    report.check_summary = {k: round(v / n, 4) for k, v in check_tally.items()}
    report.metrics = {
        "watermark_residue_rate": round(wm_residue / n, 4),
        "option_fix_rate": round(opt_fixed / opt_broken, 4) if opt_broken else None,
        "option_broken_count": opt_broken,
        "option_fixed_count": opt_fixed,
        "structure_pass_rate": round(struct_pass / q_total, 4),
        "question_count": q_total,
    }
    return report


def enforce_gate(report: VerificationReport) -> VerificationReport:
    """硬门禁：准确率不达标直接抛 :class:`GateRejected`。

    Args:
        report: 验收报告。

    Returns:
        原报告（通过时方便链式调用）。

    Raises:
        GateRejected: 准确率低于阈值。
    """
    if not report.gate_passed:
        raise GateRejected(report)
    return report
