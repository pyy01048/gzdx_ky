# -*- coding: utf-8 -*-
"""rule_engine：R1–R10 触发/仲裁、A/B 方向性、预算守恒、basis 完整、
G1 数字一致性、G3 已完成不可变属性测试（规范 §2.2/§2.3）。"""
import random
from dataclasses import replace

import pytest

from kernel.drift_detector import (
    STATUS_INSUFFICIENT, STATUS_MICRO_ADJUST, STATUS_NO_PLAN, STATUS_ON_TRACK,
    STATUS_RECOVERY, DayLedger, DriftResult, compute_drift,
)
from kernel.rule_engine import (
    MISSING_LABEL, DailySignal, PlanOptions, TaskDTO, apply_soft_gate,
    build_basis, evaluate, expire_noncore, reflow_today, replan_missed,
    recovery_exit,
)


def _drift(status, value=None):
    return DriftResult(drift=value, status=status, window_days=7,
                       planned_avg=100.0, completed_avg=100.0)


def _sig(**kw):
    base = dict(date="2026-11-20", drift=_drift(STATUS_ON_TRACK, 0.0))
    base.update(kw)
    return DailySignal(**base)


def _task(tid, *, kind="new_learn", est=45, core=True, weight="B",
          status="pending", depends=(), planned=None, overdue=0, subject="ds"):
    return TaskDTO(task_id=tid, title=f"任务{tid}", kind=kind, subject=subject,
                   est_minutes=est, core=core, planned_date=planned,
                   status=status, depends_on=tuple(depends),
                   exam_weight=weight, overdue_days=overdue)


class TestRuleTriggers:
    def test_r2_recovery_band(self, rules_cfg):
        hits = evaluate(_sig(drift=_drift(STATUS_RECOVERY, -0.5)), "normal", rules_cfg)
        assert any(h.rule == "R2" for h in hits)

    def test_r1_micro_band(self, rules_cfg):
        hits = evaluate(_sig(drift=_drift(STATUS_MICRO_ADJUST, -0.2)), "normal", rules_cfg)
        assert any(h.rule == "R1" for h in hits)

    def test_r1_silent_in_recovery_mode(self, rules_cfg):
        hits = evaluate(_sig(drift=_drift(STATUS_MICRO_ADJUST, -0.2)), "recovery", rules_cfg)
        assert not any(h.rule == "R1" for h in hits)

    def test_on_track_zero_disturbance(self, rules_cfg):
        """带宽内零打扰：on_track 不产生任何提案规则（R7 周日复盘除外——非调整类）。"""
        # 2026-11-20 是周五
        hits = evaluate(_sig(), "normal", rules_cfg)
        assert [h.rule for h in hits] == []

    def test_insufficient_data_zero_trigger(self, rules_cfg):
        hits = evaluate(_sig(drift=_drift(STATUS_INSUFFICIENT)), "normal", rules_cfg)
        assert [h.rule for h in hits] == []

    def test_no_plan_zero_trigger(self, rules_cfg):
        hits = evaluate(_sig(drift=_drift(STATUS_NO_PLAN, 0.0)), "normal", rules_cfg)
        assert [h.rule for h in hits] == []

    def test_r5_backlog_gate(self, rules_cfg):
        sig = _sig(review_backlog=int(rules_cfg.quota_review * 1.5) + 1)
        hits = evaluate(sig, "normal", rules_cfg)
        assert any(h.rule == "R5" for h in hits)

    def test_r5_boundary_not_triggered(self, rules_cfg):
        sig = _sig(review_backlog=int(rules_cfg.quota_review * 1.5))  # 恰好等于不触发（>）
        hits = evaluate(sig, "normal", rules_cfg)
        assert not any(h.rule == "R5" for h in hits)

    def test_r2prime_soft_gate_boundary(self, rules_cfg):
        q, gated = apply_soft_gate(50, 10.0, rules_cfg)   # =10h 不触发（>）
        assert (q, gated) == (50, False)
        q, gated = apply_soft_gate(50, 10.01, rules_cfg)  # >10h 封顶 50%
        assert (q, gated) == (25, True)

    def test_r8_misconception_ge3(self, rules_cfg):
        sig = _sig(misc_counts={("kp_ds_1", "概念混淆"): 3})
        hits = evaluate(sig, "normal", rules_cfg)
        r8 = [h for h in hits if h.rule == "R8"]
        assert len(r8) == 1 and r8[0].payload["occurrences"] == 3

    def test_r3_too_hard_single_signal(self, rules_cfg):
        sig = _sig(feel="too_hard", accuracy=None)   # MVP：feel 单信号即追问
        hits = evaluate(sig, "normal", rules_cfg)
        assert any(h.rule == "R3" for h in hits)

    def test_r3_suppressed_when_accuracy_high(self, rules_cfg):
        sig = _sig(feel="too_hard", accuracy=0.8)
        hits = evaluate(sig, "normal", rules_cfg)
        assert not any(h.rule == "R3" for h in hits)

    def test_r4_too_easy_streak(self, rules_cfg):
        sig = _sig(feel="too_easy", accuracy=0.95,
                   too_easy_streak=rules_cfg.too_easy_streak)
        hits = evaluate(sig, "normal", rules_cfg)
        assert any(h.rule == "R4" for h in hits)

    def test_r6_zero_report_streak(self, rules_cfg):
        sig = _sig(zero_report_streak=rules_cfg.zero_report_days)
        hits = evaluate(sig, "normal", rules_cfg)
        assert any(h.rule == "R6" for h in hits)

    def test_r9_milestone_delay(self, rules_cfg):
        sig = _sig(milestone_delay_days=rules_cfg.milestone_delay_days + 1)
        hits = evaluate(sig, "normal", rules_cfg)
        assert any(h.rule == "R9" for h in hits)
        sig2 = _sig(milestone_delay_days=rules_cfg.milestone_delay_days)  # 等号不触发（>）
        assert not any(h.rule == "R9" for h in evaluate(sig2, "normal", rules_cfg))

    def test_r7_sunday_only(self, rules_cfg):
        assert any(h.rule == "R7" for h in evaluate(_sig(date="2026-11-22"), "normal", rules_cfg))  # 周日
        assert not any(h.rule == "R7" for h in evaluate(_sig(date="2026-11-21"), "normal", rules_cfg))  # 周六

    def test_arbitration_priority_order(self, rules_cfg):
        """R2 > R5 > R8 > R3 > R1：多规则同时命中时按配置优先级排序。"""
        sig = _sig(drift=_drift(STATUS_RECOVERY, -0.5),
                   review_backlog=1000,
                   misc_counts={("k", "t"): 5}, feel="too_hard", accuracy=0.1)
        hits = evaluate(sig, "normal", rules_cfg)
        order = [h.rule for h in hits]
        assert order.index("R2") < order.index("R5") < order.index("R8") < order.index("R3")


class TestReplan:
    def test_ab_directions_differ(self, rules_cfg):
        done = [_task("d1", status="done")]
        missed = [_task(f"m{i}", est=30, weight="ABC"[i % 3]) for i in range(6)]
        po = replan_missed(done, missed, 100, rules_cfg)
        a_ids = {t.task_id for t in po.options[0].tasks}
        b_ids = {t.task_id for t in po.options[1].tasks}
        assert a_ids != b_ids or po.options[0].tasks != po.options[1].tasks
        for o in po.options:
            assert o.assumption and o.tradeoff

    def test_done_immutable_never_in_options(self, rules_cfg):
        done = [_task("d1", status="done"), _task("d2", status="done")]
        missed = [_task("m1", est=40)]
        po = replan_missed(done, missed, 200, rules_cfg)
        all_ids = {t.task_id for o in po.options for t in o.tasks}
        assert "d1" not in all_ids and "d2" not in all_ids

    def test_empty_budget_floor_card(self, rules_cfg):
        po = replan_missed([], [_task("m1", est=60)], 10, rules_cfg)
        assert po.floor_card is True   # 空方案不允许 → 保底卡标记

    def test_depends_on_respected(self, rules_cfg):
        missed = [_task("b", est=30, depends=["a"]), _task("a", est=30)]
        po = replan_missed([], missed, 40, rules_cfg)
        a_opt = po.options[0]
        ids = [t.task_id for t in a_opt.tasks]
        if "b" in ids:
            assert "a" in ids and ids.index("a") < ids.index("b")

    def test_basis_five_fields(self, rules_cfg):
        sig = _sig(window_completion_rate=0.62,
                   subject_debt_hours={"math": 3.5})
        hits = evaluate(sig, "normal", rules_cfg)
        basis = build_basis(sig, hits)
        for k in ("window_completion_rate", "drift", "subject_debt_hours",
                  "feel_signal", "review_backlog"):
            assert k in basis
        assert basis["feel_signal"] == MISSING_LABEL   # 无数据显式"无记录"

    def test_g1_basis_numbers_equal_engine_output(self, rules_cfg):
        """G1 属性：basis 各字段 == rule_engine 输出，逐字段断言。"""
        led = [DayLedger(f"2026-11-{10+i:02d}", 120, 90) for i in range(7)]
        d = compute_drift(led, rules_cfg.drift)
        sig = _sig(drift=d, window_completion_rate=0.75)
        basis = build_basis(sig, [])
        assert basis["drift"] == d.drift              # 数字直接来自脚本
        assert basis["drift_status"] == d.status
        assert basis["window_completion_rate"] == "75%"


class TestG3Property:
    def test_completed_immutable_random50(self, rules_cfg):
        """属性测试：随机 50 组 done/pending，跑全部调整规则，done 集合逐字节不变。"""
        rng = random.Random(20261121)
        for _ in range(50):
            n_done = rng.randint(0, 6)
            n_todo = rng.randint(1, 8)
            done = [_task(f"d{i}", est=rng.choice([25, 45, 60]),
                          status="done") for i in range(n_done)]
            todo = [_task(f"t{i}", est=rng.choice([25, 45, 60]),
                          depends=[f"d{rng.randint(0, max(0, n_done - 1))}"]
                          if n_done and rng.random() < 0.2 else [])
                    for i in range(n_todo)]
            snap = tuple(done)
            budget = rng.randint(0, 300)
            po = replan_missed(done, todo, budget, rules_cfg, sig=_sig())
            reflow_today(todo, budget, rules_cfg)
            assert tuple(done) == snap                 # G3：done 不被改写
            assert all(t.status == "done" for t in done)
            for o in po.options:
                assert all(t.status != "done" for t in o.tasks)


class TestReflowBudget:
    def test_conservation_random100(self, rules_cfg):
        """预算守恒：100 组随机 available × 任务池，总时长 ≤ 申报预算。"""
        rng = random.Random(7)
        for _ in range(100):
            pool = [_task(f"p{i}", est=rng.choice([15, 25, 45, 60, 90]))
                    for i in range(rng.randint(1, 10))]
            avail = rng.randint(0, 240)
            out = reflow_today(pool, avail, rules_cfg)
            assert sum(t.est_minutes for t in out) <= avail

    def test_no_penalty_leftover_returned(self, rules_cfg):
        pool = [_task("x", est=30), _task("y", est=30)]
        out = reflow_today(pool, 30, rules_cfg)
        assert sum(t.est_minutes for t in out) <= 30   # 余量不摊派


class TestExpireAndExit:
    def test_noncore_expire_after_14d(self, rules_cfg):
        tasks = [_task("a", core=False, planned="2026-10-01"),
                 _task("b", core=True, planned="2026-10-01"),
                 _task("c", core=False, planned="2026-11-15")]
        out = expire_noncore(tasks, "2026-11-20", rules_cfg)
        assert out == ["a"]

    def test_recovery_exit_requires_3_clean_days(self, rules_cfg):
        days = [(2.0, -0.10)] * 3
        assert recovery_exit(days, rules_cfg) is True
        assert recovery_exit([(2.0, -0.10)] * 2, rules_cfg) is False
        assert recovery_exit([(2.0, -0.10), (5.0, -0.10), (2.0, -0.10)], rules_cfg) is False
        assert recovery_exit([(2.0, -0.10)] * 2 + [(2.0, -0.20)], rules_cfg) is False
