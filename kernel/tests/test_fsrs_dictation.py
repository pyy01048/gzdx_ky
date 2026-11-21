# -*- coding: utf-8 -*-
"""fsrs_adapter / dictation_selector：SM-2 迁移估算、rating 映射、召回公式、
队列排序与配额、轮内重现、到期预测、默写选词确定性（naive UTC 红线）。"""
import datetime

import pytest
from fsrs import Rating

from kernel.dictation_selector import select
from kernel.fsrs_adapter import (
    CardState, due_forecast, from_legacy, queue, recall_prob, reinsert_positions,
    rating_from_quality, rating_from_ui, review,
)


def _dt(day=20, hour=8):
    return datetime.datetime(2026, 11, day, hour, 0, 0)   # naive UTC


def _card(cid, *, S=5.0, D=5.0, due=None, reps=3, lapses=0, mastered=False,
          learning=False):
    return CardState(card_id=cid, kind="word", stability=S, difficulty=D,
                     due=due or _dt(), last_review=None, reps=reps,
                     lapses=lapses, mastered=mastered, learning=learning)


class TestFromLegacy:
    def test_s_init_formula(self):
        c = from_legacy(quality=4, repetitions=3, interval_days=10, ef=2.5,
                        now=_dt())
        assert c.stability == max(0.5, 10.0)
        assert c.difficulty == pytest.approx(min(10.0, max(1.0, 10 - (2.5 - 1.3) * 4)))
        assert c.legacy["ef"] == 2.5
        assert c.due.tzinfo is None

    def test_zero_interval_floor_half_day(self):
        c = from_legacy(0, 0, 0, 1.3, now=_dt())
        assert c.stability == 0.5
        assert c.lapses == 1                    # quality<3 → 记一次 lapse

    def test_difficulty_clamp(self):
        assert from_legacy(4, 1, 1, 9.9).difficulty == 1.0     # 高 ef → 下限 1
        assert from_legacy(4, 1, 1, 0.5).difficulty == 10.0    # 低 ef → 上限 10


class TestRatingMapping:
    def test_quality_bands(self, fsrs_cfg):
        for q in (0, 1, 2):
            assert rating_from_quality(q, fsrs_cfg) == Rating.Again
        assert rating_from_quality(3, fsrs_cfg) == Rating.Hard   # 默认 impression→Hard
        assert rating_from_quality(4, fsrs_cfg) == Rating.Good
        assert rating_from_quality(5, fsrs_cfg) == Rating.Good   # familiar_maps_to=Good

    def test_quality_out_of_range(self, fsrs_cfg):
        with pytest.raises(ValueError):
            rating_from_quality(6, fsrs_cfg)

    def test_ui_three_levels(self, fsrs_cfg):
        assert rating_from_ui("陌生", fsrs_cfg) == Rating.Again
        assert rating_from_ui("有印象", fsrs_cfg) == Rating.Hard
        assert rating_from_ui("熟悉", fsrs_cfg) == Rating.Good
        with pytest.raises(ValueError):
            rating_from_ui("还行", fsrs_cfg)


class TestRecallProb:
    def test_formula_anchor(self):
        # t=0 → R=1；t=S → (1+19/81)^-0.5
        assert recall_prob(0, 5) == 1.0
        assert recall_prob(5, 5) == pytest.approx((1 + 19 / 81) ** -0.5)
        # desired_retention=0.9 时 t≈S 的 R 高于 0.9，t=10S 显著低于
        assert recall_prob(50, 5) < 0.9

    def test_bad_stability(self):
        with pytest.raises(ValueError):
            recall_prob(1, 0)


class TestReview:
    def test_naive_utc_guard(self, fsrs_cfg):
        aware = datetime.datetime(2026, 11, 20, tzinfo=datetime.timezone.utc)
        with pytest.raises(ValueError):
            review(_card("c1"), Rating.Good, aware, 3000, fsrs_cfg)

    def test_full_log_fields_and_good_grows(self, fsrs_cfg):
        st, log = review(_card("c1", due=_dt(18)), Rating.Good, _dt(), 4200, fsrs_cfg)
        assert st.due > _dt() and st.last_review == _dt()
        assert st.due.tzinfo is None and log.review_ts.tzinfo is None
        assert log.review_duration_ms == 4200
        assert log.card_id == "c1" and log.rating == int(Rating.Good)
        assert log.stability > 0 and 1 <= log.difficulty <= 10
        for f in ("state", "elapsed_days", "scheduled_days"):
            assert getattr(log, f) is not None
        assert st.stability >= 5.0              # Good 不降稳定度

    def test_again_lowers_interval_first_day_min(self, fsrs_cfg):
        newc = _card("n1", reps=0, due=_dt(), learning=True)
        st, _log = review(newc, Rating.Again, _dt(), 1000, fsrs_cfg)
        assert (st.due - _dt()).total_seconds() >= 86400   # V12：首间隔 ≥1 天


class TestQueue:
    def test_risk_order_and_quota(self, fsrs_cfg):
        now = _dt()
        cards = [
            _card("safe", S=30, due=now),           # 刚到期，R 高
            _card("danger", S=1, due=now - datetime.timedelta(days=5)),
            _card("mid", S=5, due=now - datetime.timedelta(days=1)),
            _card("done", S=5, due=now, mastered=True),
            _card("future", S=5, due=now + datetime.timedelta(days=3)),
        ]
        out = queue(cards, now, fsrs_cfg)
        ids = [c.card_id for c in out]
        assert "done" not in ids and "future" not in ids
        assert ids == ["danger", "mid", "safe"]     # R 升序＝最危险优先

    def test_quota_trims_not_drops(self, fsrs_cfg):
        now = _dt()
        cards = [_card(f"c{i}", due=now) for i in range(10)]
        out = queue(cards, now, fsrs_cfg, quota_review=3, quota_new=0)
        assert len(out) == 3

    def test_aware_now_rejected(self, fsrs_cfg):
        with pytest.raises(ValueError):
            queue([], datetime.datetime.now(datetime.timezone.utc), fsrs_cfg)


class TestReinsertForecast:
    def test_reinsert_plus4(self):
        q = ["a", "b", "c", "d", "e", "f", "g"]
        out = reinsert_positions(q, ["a"], offset=4)
        assert out[0] == "b" and out[4] == "a"      # 队首后第 4 位重现
        assert sorted(out) == sorted(q)             # 不增删元素

    def test_reinsert_deterministic(self):
        q = ["x", "y", "z", "w", "v", "u"]
        a = reinsert_positions(q, ["x", "y"])
        b = reinsert_positions(q, ["x", "y"])
        assert a == b

    def test_due_forecast_buckets(self):
        now = _dt()
        cards = [_card("a", due=now), _card("b", due=now),
                 _card("c", due=now + datetime.timedelta(days=2)),
                 _card("d", due=now, mastered=True)]
        fc = due_forecast(cards, now, days=7)
        assert len(fc) == 7
        assert fc[now.date().isoformat()] == 2
        assert fc[(now + datetime.timedelta(days=2)).date().isoformat()] == 1


class TestDictation:
    def test_topn_union_yesterday_errors(self):
        now = _dt()
        cards = [_card(f"w{i}", S=1 + i, due=now) for i in range(10)]
        chosen = select(cards, ["w9"], now, n=3)
        assert set(chosen[:3]) == {"w0", "w1", "w2"}   # R 最低（S 最小）Top-3
        assert "w9" in chosen                          # 昨日错词必选

    def test_mastered_excluded(self):
        now = _dt()
        cards = [_card("m", S=1, due=now, mastered=True), _card("o", S=9, due=now)]
        assert select(cards, ["m"], now, n=5) == ["o"]

    def test_deterministic_same_state(self):
        now = _dt()
        cards = [_card(f"k{i}", S=(i % 3) + 1, due=now) for i in range(20)]
        assert select(cards, [], now, n=7) == select(cards, [], now, n=7)

    def test_bad_inputs(self):
        with pytest.raises(ValueError):
            select([], [], _dt(), n=0)
        with pytest.raises(ValueError):
            select([], [], datetime.datetime.now(datetime.timezone.utc))
