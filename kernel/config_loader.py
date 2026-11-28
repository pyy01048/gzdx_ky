# -*- coding: utf-8 -*-
"""kernel 配置加载器：kernel/config/*.yaml → 冻结 dataclass。

设计要点：
- 零第三方 YAML 依赖：内置一个最小子集解析器（缩进映射/标量/行内列表），
  配置文件由本模块自己维护，格式受控；改配置不改代码。
- 加载结果全部 frozen dataclass（含 tuple 字段），杜绝运行期被篡改。
- 任何解析错误显式抛出 ConfigError，绝不静默给默认值掩盖问题。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

CONFIG_DIR = Path(__file__).resolve().parent / "config"


class ConfigError(ValueError):
    """配置文件缺失/格式非法。"""


# --------------------------------------------------------------------------- #
# 最小 YAML 子集解析（映射 + 标量 + 行内列表 + 注释）
# --------------------------------------------------------------------------- #
_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")


def _parse_scalar(tok: str) -> Any:
    tok = tok.strip()
    if tok == "" or tok in ("~", "null"):
        return None
    low = tok.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if _INT_RE.match(tok):
        return int(tok)
    if _FLOAT_RE.match(tok):
        return float(tok)
    if tok.startswith("[") and tok.endswith("]"):
        inner = tok[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(p) for p in inner.split(",")]
    if (tok.startswith('"') and tok.endswith('"')) or (tok.startswith("'") and tok.endswith("'")):
        return tok[1:-1]
    return tok


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    """解析受控子集 YAML：两层以内缩进映射、标量、行内列表。"""
    root: Dict[str, Any] = {}
    # stack of (indent, mapping)
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_no_eol in text.splitlines():
        line = raw_no_eol.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            raise ConfigError(f"无法解析的行（缺少冒号）: {stripped!r}")
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ConfigError(f"缩进异常: {stripped!r}")
        parent = stack[-1][1]
        if val == "":
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(val)
    return root


def load_yaml(name: str, *, base: Path | None = None) -> Dict[str, Any]:
    path = (base or CONFIG_DIR) / name
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    return parse_simple_yaml(path.read_text(encoding="utf-8"))


def _req(data: Mapping[str, Any], key: str, ctx: str) -> Any:
    if key not in data:
        raise ConfigError(f"{ctx}: 缺少必填项 {key!r}")
    return data[key]


# --------------------------------------------------------------------------- #
# 冻结配置 dataclass
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DriftConfig:
    window_days: int
    min_days: int
    on_track_band: float  # drift >= -on_track_band → on_track
    recovery_band: float  # drift < -recovery_band → recovery
    micro_adjust_pct: float  # R1 明日任务量下调比例上限


@dataclass(frozen=True)
class RulesConfig:
    drift: DriftConfig
    debt_soft_gate_hours: float  # R2' 欠账软闸门
    debt_exit_hours: float  # 恢复退出条件：欠账 < 3h
    recovery_exit_days: int  # 连续 3 天
    review_backlog_ratio: float  # R5：积压 > 日配额 × 1.5
    zero_report_days: int  # R6：连续 3 天零汇报
    expire_after_days: int  # 非核心消解 14d
    quota_new: int
    quota_review: int
    new_learn_cap_on_debt: float  # 软闸门封顶 50%
    too_hard_accuracy: float  # R3：<60%
    too_easy_accuracy: float  # R4：>90%
    too_easy_streak: int  # R4：连续 5 天
    milestone_delay_days: int  # R9：>7 天
    priority_order: Tuple[str, ...]  # 仲裁优先级
    reflow_block_minutes: Tuple[int, ...]  # R10：25/45min 块


@dataclass(frozen=True)
class ComplianceConfig:
    c_whitelist_headers: Tuple[str, ...]
    cpp_subset_headers: Tuple[str, ...]
    banned_functions: Tuple[str, ...]
    file_io_functions: Tuple[str, ...]
    allowed_streams: Tuple[str, ...]


@dataclass(frozen=True)
class AuditConfig:
    tuimian_cum_pp: float  # 推免挤压三年累计 ≥10pp
    shrink_pct: float  # 缩招同比 ≥20%
    heat_rise_pct: float  # 爆热报录比上升 ≥30%
    heat_abs_ratio: float  # 且绝对值 >8
    retest_ratio_high: float  # 复录比高判定
    stale_seasons: int  # access_date 超 N 个招生季 → 待复核


@dataclass(frozen=True)
class FsrsConfig:
    desired_retention: float
    familiar_maps_to: str  # Good（默认）| Easy
    impression_maps_to: str  # Hard（默认）| Good
    optimizer_gate: int  # ≥1000 条日志才启用
    optimizer_gate_min: int  # 可配下限 512
    queue_quota_new: int
    queue_quota_review: int
    first_interval_min_days: int  # V12 口径：新卡首间隔 ≥1 天
    reinsert_offset: int  # 轮内 +4 重现


@dataclass(frozen=True)
class KernelConfig:
    rules: RulesConfig
    compliance: ComplianceConfig
    audit: AuditConfig
    fsrs: FsrsConfig
    source_dir: str = ""


def _load_drift(data: Mapping[str, Any]) -> DriftConfig:
    d = _req(data, "drift", "rules.yaml")
    return DriftConfig(
        window_days=int(_req(d, "window_days", "drift")),
        min_days=int(_req(d, "min_days", "drift")),
        on_track_band=float(_req(d, "on_track_band", "drift")),
        recovery_band=float(_req(d, "recovery_band", "drift")),
        micro_adjust_pct=float(d.get("micro_adjust_pct", 0.25)),
    )


def load_rules_config(base: Path | None = None) -> RulesConfig:
    data = load_yaml("rules.yaml", base=base)
    drift = _load_drift(data)
    return RulesConfig(
        drift=drift,
        debt_soft_gate_hours=float(_req(data, "debt_soft_gate_hours", "rules.yaml")),
        debt_exit_hours=float(data.get("debt_exit_hours", 3.0)),
        recovery_exit_days=int(data.get("recovery_exit_days", 3)),
        review_backlog_ratio=float(data.get("review_backlog_ratio", 1.5)),
        zero_report_days=int(data.get("zero_report_days", 3)),
        expire_after_days=int(data.get("expire_after_days", 14)),
        quota_new=int(data.get("quota_new", 50)),
        quota_review=int(data.get("quota_review", 200)),
        new_learn_cap_on_debt=float(data.get("new_learn_cap_on_debt", 0.5)),
        too_hard_accuracy=float(data.get("too_hard_accuracy", 0.6)),
        too_easy_accuracy=float(data.get("too_easy_accuracy", 0.9)),
        too_easy_streak=int(data.get("too_easy_streak", 5)),
        milestone_delay_days=int(data.get("milestone_delay_days", 7)),
        priority_order=tuple(str(x) for x in _req(data, "priority_order", "rules.yaml")),
        reflow_block_minutes=tuple(int(x) for x in data.get("reflow_block_minutes", [25, 45])),
    )


def load_compliance_config(base: Path | None = None) -> ComplianceConfig:
    data = load_yaml("compliance.yaml", base=base)
    return ComplianceConfig(
        c_whitelist_headers=tuple(_req(data, "c_whitelist_headers", "compliance.yaml")),
        cpp_subset_headers=tuple(data.get("cpp_subset_headers", [])),
        banned_functions=tuple(_req(data, "banned_functions", "compliance.yaml")),
        file_io_functions=tuple(data.get("file_io_functions", [])),
        allowed_streams=tuple(data.get("allowed_streams", ["stdin", "stdout", "stderr"])),
    )


def load_audit_config(base: Path | None = None) -> AuditConfig:
    data = load_yaml("audit.yaml", base=base)
    return AuditConfig(
        tuimian_cum_pp=float(_req(data, "tuimian_cum_pp", "audit.yaml")),
        shrink_pct=float(_req(data, "shrink_pct", "audit.yaml")),
        heat_rise_pct=float(_req(data, "heat_rise_pct", "audit.yaml")),
        heat_abs_ratio=float(_req(data, "heat_abs_ratio", "audit.yaml")),
        retest_ratio_high=float(data.get("retest_ratio_high", 1.5)),
        stale_seasons=int(data.get("stale_seasons", 1)),
    )


def load_fsrs_config(base: Path | None = None) -> FsrsConfig:
    data = load_yaml("fsrs.yaml", base=base)
    return FsrsConfig(
        desired_retention=float(_req(data, "desired_retention", "fsrs.yaml")),
        familiar_maps_to=str(data.get("familiar_maps_to", "Good")),
        impression_maps_to=str(data.get("impression_maps_to", "Hard")),
        optimizer_gate=int(data.get("optimizer_gate", 1000)),
        optimizer_gate_min=int(data.get("optimizer_gate_min", 512)),
        queue_quota_new=int(data.get("queue_quota_new", 50)),
        queue_quota_review=int(data.get("queue_quota_review", 200)),
        first_interval_min_days=int(data.get("first_interval_min_days", 1)),
        reinsert_offset=int(data.get("reinsert_offset", 4)),
    )


def load_config(base: Path | None = None) -> KernelConfig:
    """一次性加载全部配置为冻结 dataclass。"""
    return KernelConfig(
        rules=load_rules_config(base),
        compliance=load_compliance_config(base),
        audit=load_audit_config(base),
        fsrs=load_fsrs_config(base),
        source_dir=str(base or CONFIG_DIR),
    )
