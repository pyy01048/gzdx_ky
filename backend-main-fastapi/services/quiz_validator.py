# -*- coding: utf-8 -*-
"""题目质量门（quiz validator）—— 完善方案 11 §3.3 步骤 4。

目的：把"导入准确率 ≥99% 才放行"这条用户既定要求**固化成代码**，所有批量导入
（真题 / 教材 / 开源题库）共用同一套规则与抽样验收口径，而不是每次一次性人工运动。

两层校验：

1. **结构规则**（逐题、确定性）
   - 题干非空、长度下限；选项结构合法（[{"key","text"}]，key 唯一）
   - 客观题：选项 ≥2；答案 ∈ 选项 key 集合；多选答案全为字母且去重
   - 占位符检测（"略 / 同上 / 见解析 / ..."）——不能作为答案或选项正文
   - 真题：year 合理区间、question_no 为正
   - 解析缺失对客观题记 warn（可用，但进 warn 池）

2. **抽样验收**（批次级）
   - 每批随机 10%（≥30 题）人工核对结果（``{"total": 300, "reviewed": 30, "correct": 30}``）
   - 准确率 < 99% → **整批拒绝**（BatchRejected），不允许部分入库

与 ``services/quiz_content_gate`` 的分工：那边回答"这段文字像不像题"（垃圾过滤），
这里回答"这道题结构完不完整、能不能自动判分"（字段级契约）。两者串联使用。

用法（导入脚本）::

    from services.quiz_validator import validate_batch, BatchRejected
    report = validate_batch(rows, sample_review={"reviewed": 30, "correct": 30})
    if not report.ok:   # 结构失败率过高或抽样不达标
        ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

#: 批量入库的抽样准确率阈值（用户既定要求：99%）
ACCURACY_THRESHOLD = 0.99
#: 结构校验失败率上限（低于阈值整批拒绝）
STRUCTURAL_FAIL_RATE_MAX = 0.01
#: 客观题解析缺失的容忍比例（超过说明源文档质量差，需先修源）
MISSING_ANALYSIS_WARN_RATE = 0.60

PLACEHOLDERS = {
    "略",
    "同上",
    "见解析",
    "略。",
    "无",
    "…",
    "...",
    "……",
    "暂无",
    "待补充",
    "答案见解析",
    "略去",
    "-",
    "—",
}
YEAR_MIN, YEAR_MAX = 1980, 2100
OBJ_TYPES = {"single", "judge", "multi", "multiple"}


@dataclass
class Issue:
    code: str
    message: str
    severity: str = "fail"  # fail | warn


@dataclass
class BatchReport:
    total: int = 0
    passed: int = 0
    warned: int = 0
    failed: int = 0
    issues: list[tuple[int, Issue]] = field(default_factory=list)
    sample_pass_rate: float | None = None
    accepted_rows: list[dict] = field(default_factory=list)
    rejected_rows: list[tuple[int, list[Issue]]] = field(default_factory=list)
    reason: str = ""

    @property
    def fail_rate(self) -> float:
        return (self.failed / self.total) if self.total else 0.0

    @property
    def ok(self) -> bool:
        if not self.total:
            return False
        if self.fail_rate > STRUCTURAL_FAIL_RATE_MAX:
            return False
        # 铁律：没有抽样验收记录（reviewed/correct）不得入库
        if self.sample_pass_rate is None:
            return False
        if self.sample_pass_rate < ACCURACY_THRESHOLD:
            return False
        return True


def _norm(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _is_placeholder(text: Any) -> bool:
    t = _norm(text)
    return (not t) or t in PLACEHOLDERS or bool(re.fullmatch(r"[.…\-—_。]+", t))


def _option_key_list(options: Any) -> tuple[list[str], list[Issue]]:
    """返回 (keys, issues)。兼容 [{"key","text"}] / ["A. xxx"] / ["xxx"]。"""
    issues: list[Issue] = []
    keys: list[str] = []
    if not options:
        return keys, issues
    if not isinstance(options, list | tuple):
        return keys, [Issue("OPTIONS_TYPE", f"options 不是数组：{type(options).__name__}")]
    for idx, opt in enumerate(options):
        if isinstance(opt, Mapping):
            key = str(opt.get("key") or "").strip()
            text = opt.get("text")
        else:
            raw = str(opt or "").strip()
            m = re.match(r"^([A-Za-z])[.、:：)]\s*(.*)$", raw)
            key, text = (m.group(1), m.group(2)) if m else (chr(65 + idx), raw)
        key = key.upper()
        if not key:
            issues.append(Issue("OPTION_KEY_EMPTY", f"第 {idx + 1} 个选项缺少 key"))
            continue
        if key in keys:
            issues.append(Issue("OPTION_KEY_DUP", f"选项 key 重复：{key}"))
        keys.append(key)
        if _is_placeholder(text):
            issues.append(Issue("OPTION_PLACEHOLDER", f"选项 {key} 正文为占位符/空", "warn"))
    return keys, issues


def _answer_keys(answer: Any) -> list[str]:
    """把答案归一成大写 key 列表（'AB' / 'A,B' / 'A、B' / 'a b' 都接受）。"""
    raw = str(answer or "").strip()
    if not raw:
        return []
    letters = re.findall(r"[A-Za-z]", raw)
    return [x.upper() for x in letters]


def validate_question(q: Mapping[str, Any], *, require_analysis: bool = False) -> list[Issue]:
    """逐题结构校验。返回问题列表；空列表 = 通过。"""
    issues: list[Issue] = []

    content = str(q.get("content") or "").strip()
    if not content:
        issues.append(Issue("CONTENT_EMPTY", "题干为空"))
    elif len(_norm(content)) < 6:
        issues.append(Issue("CONTENT_TOO_SHORT", f"题干过短（{len(_norm(content))} 字）", "warn"))
    elif _is_placeholder(content):
        issues.append(Issue("CONTENT_PLACEHOLDER", "题干是占位符"))

    qtype = str(q.get("question_type") or q.get("type") or "single").lower()
    answer = q.get("answer")
    analysis = q.get("analysis")
    keys, opt_issues = _option_key_list(q.get("options"))
    issues += opt_issues

    if qtype in {"single", "multi", "multiple"}:
        if len(keys) < 2:
            issues.append(Issue("OPTIONS_TOO_FEW", f"{qtype} 题选项不足 2 个（实际 {len(keys)}）"))
        akeys = _answer_keys(answer)
        if not akeys:
            issues.append(Issue("ANSWER_EMPTY", "客观题无答案"))
        else:
            unknown = [k for k in akeys if keys and k not in keys]
            if unknown:
                issues.append(Issue("ANSWER_NOT_IN_OPTIONS", f"答案 {unknown} 不在选项集合 {keys} 中"))
            if qtype == "single" and len(set(akeys)) > 1:
                issues.append(Issue("ANSWER_MULTI_FOR_SINGLE", f"单选题却给了多个答案：{akeys}"))
    elif qtype == "judge":
        if str(answer or "").strip() not in {"对", "错", "√", "×", "T", "F", "true", "false", "正确", "错误"}:
            issues.append(Issue("JUDGE_ANSWER_INVALID", f"判断题答案不合法：{answer!r}"))
    else:  # fill / calc / essay / draw
        if _is_placeholder(answer):
            issues.append(Issue("ANSWER_EMPTY_SUBJECTIVE", f"{qtype} 题参考答案为空"))
        if require_analysis and _is_placeholder(analysis):
            issues.append(Issue("ANALYSIS_EMPTY_SUBJECTIVE", "主观题缺少解析/评分细则"))

    if qtype in {"single", "multi", "judge"} and _is_placeholder(analysis):
        issues.append(Issue("ANALYSIS_MISSING", "客观题缺少解析", "warn"))

    if q.get("is_past_exam") or str(q.get("source_kind") or "") == "past_exam":
        year = q.get("year")
        if year in (None, ""):
            issues.append(Issue("PAST_EXAM_YEAR_MISSING", "真题缺少年份"))
        else:
            try:
                y = int(year)
                if not (YEAR_MIN <= y <= YEAR_MAX):
                    issues.append(Issue("PAST_EXAM_YEAR_INVALID", f"真题年份不合理：{y}"))
            except (TypeError, ValueError):
                issues.append(Issue("PAST_EXAM_YEAR_INVALID", f"真题年份不是整数：{year!r}"))
        qno = q.get("question_no")
        if qno is not None:
            try:
                if int(qno) <= 0:
                    issues.append(Issue("QUESTION_NO_INVALID", f"题号应 >0：{qno}"))
            except (TypeError, ValueError):
                issues.append(Issue("QUESTION_NO_INVALID", f"题号不是整数：{qno!r}"))

    return issues


def classify(issues: Sequence[Issue]) -> str:
    if any(i.severity == "fail" for i in issues):
        return "fail"
    if issues:
        return "warn"
    return "pass"


def dedup_key(q: Mapping[str, Any]) -> str:
    """跨源判重键：归一化题干 + 科目 + 章节；跨年同题豁免在调用侧叠加 year。

    与 ``services.quiz_content_gate.stem_signature`` 的差别：这里不做相似度，
    只做确定性判重（展示层 DISTINCT ON / 存储层合并共用同一个键）。
    """
    from services.quiz_content_gate import normalize_dedup

    parts = [
        normalize_dedup(q.get("content")),
        _norm(q.get("subject")),
        _norm(q.get("chapter")),
    ]
    return "|".join(parts)


def validate_batch(
    rows: Iterable[Mapping[str, Any]],
    *,
    sample_review: Mapping[str, Any] | None = None,
    accuracy_threshold: float = ACCURACY_THRESHOLD,
    structural_fail_rate_max: float = STRUCTURAL_FAIL_RATE_MAX,
    require_analysis: bool = False,
) -> BatchReport:
    """批量校验 + 抽样验收。

    ``sample_review`` 形如 ``{"reviewed": 30, "correct": 30}``；人工核对结果由导入人提供
    （脚本会把它写进报告留痕）。低于阈值 → report.ok=False，调用方必须整批拒绝。
    """
    report = BatchReport()
    for idx, q in enumerate(rows):
        row = dict(q)
        issues = validate_question(row, require_analysis=require_analysis)
        status = classify(issues)
        report.total += 1
        if status == "fail":
            report.failed += 1
            report.rejected_rows.append((idx, issues))
            report.issues += [(idx, i) for i in issues if i.severity == "fail"]
        elif status == "warn":
            report.warned += 1
            report.accepted_rows.append(row)
            report.issues += [(idx, i) for i in issues if i.severity == "warn"]
        else:
            report.passed += 1
            report.accepted_rows.append(row)

    if sample_review:
        reviewed = int(sample_review.get("reviewed") or 0)
        correct = int(sample_review.get("correct") or 0)
        if reviewed > 0:
            report.sample_pass_rate = correct / reviewed

    reasons = []
    if report.total == 0:
        reasons.append("批次为空")
    if report.fail_rate > structural_fail_rate_max:
        reasons.append(f"结构失败率 {report.fail_rate:.2%} > {structural_fail_rate_max:.0%}")
    if report.sample_pass_rate is not None and report.sample_pass_rate < accuracy_threshold:
        reasons.append(f"抽样准确率 {report.sample_pass_rate:.2%} < {accuracy_threshold:.0%}（整批打回重抽）")
    if not reasons and report.sample_pass_rate is None:
        reasons.append("缺少抽样验收记录（reviewed/correct），按铁律不得入库")
    report.reason = "；".join(reasons)
    return report


class BatchRejected(RuntimeError):
    """批次未通过质量门——调用方必须整批回滚，不做部分入库。"""

    def __init__(self, report: BatchReport):
        self.report = report
        super().__init__(f"[质量门拒绝] {report.reason}（total={report.total} fail={report.failed}）")


def assert_batch_ok(report: BatchReport) -> None:
    if not report.ok:
        raise BatchRejected(report)
