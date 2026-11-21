# -*- coding: utf-8 -*-
"""规则引擎 R1–R10（落地方案 §4.4，纯函数）。

仲裁优先级（总方案 §4.3）：R2 > R5 > R8 > R3/R4 > R1 > R10 > R6 > R9 > R7；
同一晚最多 1 份合并提案；恢复模式期间 R1 静默。
G1：basis 数字全部由本模块脚本填充；G3：replan/reflow 绝不改动 done 任务。
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from kernel.config_loader import RulesConfig
from kernel.drift_detector import (
    STATUS_MICRO_ADJUST,
    STATUS_RECOVERY,
    DriftResult,
)

MISSING_LABEL = "无记录"   # basis 无数据字段显式写"无记录"，不省略（硬标准 2.2-6）


@dataclass(frozen=True)
class TaskDTO:
    task_id: str
    title: str
    kind: str                      # new_learn | review | repair | verify
    subject: str
    est_minutes: int
    core: bool = True
    planned_date: Optional[str] = None
    status: str = "pending"        # pending | done | partial | missed | expired
    depends_on: Tuple[str, ...] = ()
    exam_weight: str = "B"         # A | B | C
    overdue_days: int = 0


@dataclass(frozen=True)
class DailySignal:
    """单日消费信号（rule_engine.evaluate 输入）。"""

    date: str
    drift: DriftResult
    core_debt_hours: float = 0.0
    review_backlog: int = 0
    zero_report_streak: int = 0            # 连续零汇报天数
    feel: Optional[str] = None             # too_hard | too_easy | None
    accuracy: Optional[float] = None       # 当日正确率 0-1，None=无答题记录
    too_easy_streak: int = 0
    misc_counts: Mapping[Tuple[str, str], int] = field(default_factory=dict)  # (kp_id,error_type)->次数
    milestone_delay_days: int = 0
    window_completion_rate: Optional[float] = None
    subject_debt_hours: Mapping[str, float] = field(default_factory=dict)
    mode: str = "normal"                   # normal | recovery（当前生效模式）


@dataclass(frozen=True)
class RuleHit:
    rule: str                # R1..R10
    action: str
    payload: Dict = field(default_factory=dict)
    priority: int = 99


@dataclass(frozen=True)
class PlanOption:
    name: str                # A | B
    label: str
    tasks: Tuple[TaskDTO, ...]
    assumption: str
    tradeoff: str


@dataclass(frozen=True)
class PlanOptions:
    options: Tuple[PlanOption, ...]
    basis: Dict
    trigger_rules: Tuple[str, ...]
    floor_card: bool = False   # 预算不足时的"今日仅复习"保底卡（空方案不允许）


# --------------------------------------------------------------------------- #
# evaluate：R1–R10 触发判定 + 仲裁
# --------------------------------------------------------------------------- #
def _priority(cfg: RulesConfig, rule: str) -> int:
    try:
        return cfg.priority_order.index(rule)
    except ValueError:  # pragma: no cover - 配置缺项时排最后
        return 99


def evaluate(sig: DailySignal, mode: str, cfg: RulesConfig) -> List[RuleHit]:
    """返回按仲裁优先级排序后的命中列表（同晚只取第一份合并提案由调用方决定）。

    mode: "normal" | "recovery"。恢复模式期间 R1 静默（硬标准）。
    """
    hits: List[RuleHit] = []
    band = sig.drift.status

    # R2 恢复模式：drift 进入 recovery 带
    if band == STATUS_RECOVERY:
        hits.append(RuleHit("R2", "propose_recovery",
                            {"drift": sig.drift.drift}))
    # R5 复习闸门：积压 > 日配额 × ratio
    if sig.review_backlog > cfg.quota_review * cfg.review_backlog_ratio:
        hits.append(RuleHit("R5", "halve_new_learn_quota",
                            {"backlog": sig.review_backlog}))
    # R8 强制修复：同 (kp, error_type) >= 3 次
    for (kp_id, err_type), n in sorted(sig.misc_counts.items()):
        if n >= 3:
            hits.append(RuleHit("R8", "force_repair",
                                {"kp_id": kp_id, "error_type": err_type,
                                 "occurrences": n}))
    # R3 难度下调：too_hard（MVP 单信号触发追问；正确率可用时须低于阈值）
    if sig.feel == "too_hard" and (
        sig.accuracy is None or sig.accuracy < cfg.too_hard_accuracy
    ):
        hits.append(RuleHit("R3", "diagnose_then_downgrade",
                            {"accuracy": sig.accuracy}))
    # R4 提速选项：too_easy 且正确率 > 阈值连续 N 天
    if sig.feel == "too_easy" and sig.accuracy is not None \
            and sig.accuracy > cfg.too_easy_accuracy \
            and sig.too_easy_streak >= cfg.too_easy_streak:
        hits.append(RuleHit("R4", "offer_accelerate",
                            {"streak": sig.too_easy_streak}))
    # R1 节奏微调：micro_adjust 带；恢复模式静默
    if band == STATUS_MICRO_ADJUST and mode != "recovery":
        hits.append(RuleHit("R1", "micro_adjust_tomorrow",
                            {"drift": sig.drift.drift,
                             "scale": round(1 - abs(sig.drift.drift or 0.0), 3)}))
    # R10 无负罪错过：用户标记 missed（payload 由 shell 传当日重塑需求）
    if sig.zero_report_streak == 0 and band in (STATUS_MICRO_ADJUST, STATUS_RECOVERY):
        pass  # R10 是事件驱动端点 reflow_today，不在夜间扫描里凭空触发
    # R6 低压唤回：连续 N 天零汇报
    if sig.zero_report_streak >= cfg.zero_report_days:
        hits.append(RuleHit("R6", "gentle_recheck_budget",
                            {"streak": sig.zero_report_streak}))
    # R9 阶段重排：里程碑延迟 > 7 天
    if sig.milestone_delay_days > cfg.milestone_delay_days:
        hits.append(RuleHit("R9", "stage_replan",
                            {"delay_days": sig.milestone_delay_days}))
    # R7 周日复盘：date 是周日
    try:
        dow = datetime.date.fromisoformat(sig.date).weekday()
        if dow == 6:
            hits.append(RuleHit("R7", "weekly_retro", {}))
    except ValueError:  # pragma: no cover - 非法日期由 shell 校验
        pass

    hits.sort(key=lambda h: _priority(cfg, h.rule))
    return hits


# --------------------------------------------------------------------------- #
# replan_missed：A/B 时间预算重排（G3 已完成不可变）
# --------------------------------------------------------------------------- #
_WEIGHT_RANK = {"A": 0, "B": 1, "C": 2}


def _sort_key(t: TaskDTO, strategy: str) -> Tuple:
    # 高权重优先；稳健策略把长任务往后放（先保短平快），追赶策略反之
    length_bias = t.est_minutes if strategy == "conservative" else -t.est_minutes
    return (_WEIGHT_RANK.get(t.exam_weight, 1), 0 if t.core else 1,
            -t.overdue_days, length_bias, t.task_id)


def _fill_budget(missed: Sequence[TaskDTO], budget_min: int, cfg: RulesConfig,
                 strategy: str, done_ids: frozenset) -> List[TaskDTO]:
    """带 depends_on 约束的优先级装填：前置未完成（且不在本次装填集合内已就位）
    的任务不得越过前置装填。装填结果绝不包含 done 任务（G3）。"""
    ordered = sorted(missed, key=lambda t: _sort_key(t, strategy))
    selected: List[TaskDTO] = []
    selected_ids = set()
    remaining = budget_min
    # 两遍装填保证依赖先行：第一遍挑依赖满足的，第二遍补被依赖阻塞后新解锁的
    pool = list(ordered)
    while True:
        progressed = False
        for t in list(pool):
            if t.est_minutes > remaining:
                continue
            blocked = [d for d in t.depends_on
                       if d not in selected_ids and d not in done_ids]
            if blocked:
                continue
            selected.append(t)
            selected_ids.add(t.task_id)
            pool.remove(t)
            remaining -= t.est_minutes
            progressed = True
        if not progressed or not pool:
            break
    if strategy == "conservative":
        # 稳健：按依赖拓扑顺序输出，完整保留任务原时长
        pos = {t.task_id: i for i, t in enumerate(selected)}
        ordered_out: List[TaskDTO] = []
        pending = list(selected)
        while pending:
            placed = {o.task_id for o in ordered_out}
            progressed = False
            for t in list(pending):
                if all(d in placed or d not in pos for d in t.depends_on):
                    ordered_out.append(t)
                    pending.remove(t)
                    progressed = True
            if not progressed:  # pragma: no cover - 循环依赖兜底
                ordered_out.extend(pending)
                break
        return ordered_out
    # 追赶压缩：装不下的任务压缩到最短块继续覆盖（单项最低 25 分钟块），
    # 与稳健方案形成方向性差异；预算耗尽即停
    out2: List[TaskDTO] = list(selected)
    covered = {t.task_id for t in out2}
    for t in sorted(pool, key=lambda x: _sort_key(x, strategy)):
        if remaining <= 0:
            break
        minutes = max(1, min(t.est_minutes, 25, remaining))
        out2.append(TaskDTO(
            task_id=t.task_id, title=t.title, kind=t.kind,
            subject=t.subject, est_minutes=minutes,
            core=t.core, planned_date=t.planned_date, status=t.status,
            depends_on=t.depends_on, exam_weight=t.exam_weight,
            overdue_days=t.overdue_days))
        covered.add(t.task_id)
        remaining -= minutes
    return out2


def build_basis(sig: DailySignal, hits: Sequence[RuleHit]) -> Dict:
    """basis 五字段（G1：全部脚本输出；无数据写"无记录"，不省略）。"""
    rate = sig.window_completion_rate
    subj = {k: v for k, v in sorted(sig.subject_debt_hours.items())}
    return {
        "window_completion_rate": f"{rate:.0%}" if rate is not None else MISSING_LABEL,
        "drift": sig.drift.drift if sig.drift.drift is not None else MISSING_LABEL,
        "drift_status": sig.drift.status,
        "subject_debt_hours": subj if subj else MISSING_LABEL,
        "feel_signal": sig.feel or MISSING_LABEL,
        "review_backlog": sig.review_backlog,
        "triggered_rules": [h.rule for h in hits],
    }


def replan_missed(done: List[TaskDTO], missed: List[TaskDTO], budget_min: int,
                  cfg: RulesConfig, *, sig: Optional[DailySignal] = None,
                  hits: Optional[Sequence[RuleHit]] = None) -> PlanOptions:
    """A 稳健 / B 追赶 双方案。

    G3 不变式：done 集合作为只读输入，不出现在任何方案任务列表、其状态不被
    本函数以任何形式改写；装填时用于解开 depends_on 依赖判定。
    空方案不允许：预算连一个最短任务都装不下 → 输出"今日仅复习"保底卡。
    """
    done_ids = frozenset(t.task_id for t in done)
    plan_a = _fill_budget(missed, budget_min, cfg, "conservative", done_ids)
    plan_b = _fill_budget(missed, budget_min, cfg, "aggressive", done_ids)
    # 保底卡判定以**完整任务**（未压缩）为准：稳健方案装不下任何整任务即触发；
    # 追赶方案的压缩覆盖不豁免保底卡（G3/验收：空整任务方案不允许，须给保底卡）
    floor = not plan_a
    basis = build_basis(sig, hits or []) if sig is not None else {}
    opts = (
        PlanOption("A", "稳健降载", tuple(plan_a),
                   "优先保证高权重科目", "低优先级任务继续顺延"),
        PlanOption("B", "追赶压缩", tuple(plan_b),
                   "压缩单项时长以覆盖更多", "单项深度可能不足"),
    )
    if floor:
        opts = tuple(
            PlanOption(o.name, o.label, (), o.assumption, o.tradeoff)
            for o in opts)
    return PlanOptions(options=opts, basis=basis,
                       trigger_rules=tuple(h.rule for h in (hits or [])),
                       floor_card=floor)


# --------------------------------------------------------------------------- #
# reflow_today：R10 无负罪错过（余量回 backlog 不惩罚）
# --------------------------------------------------------------------------- #
def reflow_today(missed: List[TaskDTO], available_min: int,
                 cfg: RulesConfig) -> List[TaskDTO]:
    """把错过的任务按 25/45min 块重塑进今日剩余预算。

    守恒断言（硬标准 2.2-5）：输出任务 est_minutes 总和 <= available_min；
    余量任务原样返回给调用方回 backlog（不摊派未来七天、不惩罚）。
    """
    blocks = sorted(cfg.reflow_block_minutes)
    small = blocks[0]
    out: List[TaskDTO] = []
    remaining = available_min
    for t in sorted(missed, key=lambda x: _sort_key(x, "conservative")):
        if remaining < small:
            break
        fit = max((b for b in blocks if b <= remaining), default=None)
        if fit is None:
            break
        minutes = min(t.est_minutes, fit)
        out.append(TaskDTO(
            task_id=t.task_id, title=t.title, kind=t.kind, subject=t.subject,
            est_minutes=minutes, core=t.core, planned_date=t.planned_date,
            status="pending", depends_on=t.depends_on,
            exam_weight=t.exam_weight, overdue_days=t.overdue_days))
        remaining -= minutes
    return out


# --------------------------------------------------------------------------- #
# 非核心消解 / 恢复退出（供 shell nightly scan 消费）
# --------------------------------------------------------------------------- #
def expire_noncore(tasks: Sequence[TaskDTO], today: str,
                   cfg: RulesConfig) -> List[str]:
    """core=false 且积压超过 expire_after_days 的 pending 任务转 expired，
    返回应转 expired 的 task_id 列表（不再出现在欠账合计）。"""
    d0 = datetime.date.fromisoformat(today)
    out = []
    for t in tasks:
        if t.core or t.status != "pending" or not t.planned_date:
            continue
        age = (d0 - datetime.date.fromisoformat(t.planned_date)).days
        if age > cfg.expire_after_days:
            out.append(t.task_id)
    return out


def recovery_exit(days: Sequence[Tuple[float, float]],
                  cfg: RulesConfig) -> bool:
    """恢复退出条件：欠账 < debt_exit_hours 且 drift >= -on_track_band
    连续 recovery_exit_days 天。days: [(debt_hours, drift), ...] 按日排列。"""
    need = cfg.recovery_exit_days
    if len(days) < need:
        return False
    for debt, drift in days[-need:]:
        if debt >= cfg.debt_exit_hours or drift < -cfg.drift.on_track_band:
            return False
    return True


def apply_soft_gate(new_learn_quota: int, core_debt_hours: float,
                    cfg: RulesConfig) -> Tuple[int, bool]:
    """R2' 软闸门：欠账 > 10h → 新学配额封顶 50%，返回 (配额, 是否触发)。
    只封顶＋提示，不改变模式标签。"""
    if core_debt_hours > cfg.debt_soft_gate_hours:
        return int(new_learn_quota * cfg.new_learn_cap_on_debt), True
    return new_learn_quota, False
