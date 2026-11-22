# -*- coding: utf-8 -*-
"""W1 数据真实性底座 · 纯逻辑回归（不依赖数据库）。

覆盖两个"制造恐慌"的根因闸门：

1. **目标分数阈值**（``services.study_limits`` + ``schemas.GoalBase`` +
   ``routers/study/goals.py::_check_scores``）：2000 分总分、120 分政治这类
   荒谬值必须在入口被挡掉，且错误走统一错误壳；
2. **今日推荐量钳制**（``services.daily_load._track``）：整库到期 5712 词
   只能给出"今日 ≤ 配额/上限"的合理量，差额转入复习债而不是加回今日量。

跑法（本机 PG 不可用时也能跑）::

    python -m pytest tests/test_study_limits_w1.py -q -p no:langsmith_plugin --noconftest

需要真库的接口级回归见 ``tests/test_daily_load_w1.py``。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


# --------------------------------------------------------------------------- #
# 1. 分数阈值
# --------------------------------------------------------------------------- #
def test_total_score_over_500_is_rejected_by_message():
    from services import study_limits

    # 用户实测：目标总分可以存到 2000
    assert study_limits.score_limit_error("total_score_target", 2000)
    assert study_limits.score_limit_error("total_score_target", 500) is None
    assert study_limits.score_limit_error("total_score_target", None) is None  # 未设目标不算越界
    assert study_limits.score_limit_error("total_score_target", -1)


def test_each_subject_capped_by_its_own_full_mark():
    from services import study_limits

    L = study_limits
    assert L.SCORE_PART_MAX == {
        "politics_target": 100,
        "english_target": 100,
        "math_target": 200,  # 199 管理类综合能力满分 200
        "major_target": 300,  # 311/306 等专业基础综合满分 300
    }
    assert L.score_limit_error("politics_target", 120)
    assert L.score_limit_error("politics_target", 100) is None
    assert L.score_limit_error("english_target", 101)
    assert L.score_limit_error("math_target", 200) is None
    assert L.score_limit_error("major_target", 301)


def test_pydantic_layer_blocks_the_same_values():
    """PUT /api/goals 走 GoalUpdate：越界在 Pydantic 层就 422，不用等到路由。"""
    import schemas
    from pydantic import ValidationError

    for bad in (
        {"total_score_target": 2000},
        {"politics_target": 120},
        {"daily_new_words": 2000},  # 旧边界 le=2000 正是"一天 2000 新词"的合法入口
        {"daily_review_words": 5000},
        {"daily_focus_minutes": 1440},
    ):
        with pytest.raises(ValidationError, match="less than or equal"):
            schemas.GoalUpdate(**bad)

    # 合理值照常通过；None（未设）也必须通过
    schemas.GoalUpdate(total_score_target=350, politics_target=70, daily_new_words=40)
    schemas.GoalUpdate()


def test_cross_field_sum_and_contradiction():
    from routers.study.goals import _check_scores
    from utils.exceptions import BusinessException

    goal = SimpleNamespace(
        politics_target=65,
        english_target=65,
        math_target=120,
        major_target=150,
        total_score_target=400,
    )
    # 合法更新不抛
    _check_scores(goal, {"total_score_target": 400})
    _check_scores(goal, {"remark": "改备注不该被分数校验挡住"})

    # 四科都填 → 之和 630 > 500 必须挡
    with pytest.raises(BusinessException) as ei:
        _check_scores(goal, {"math_target": 200, "major_target": 300})
    assert ei.value.code == "INVALID_PARAMETER"
    assert ei.value.status_code == 422
    assert "500" in ei.value.message
    assert ei.value.detail["total_max"] == 500

    # 总分低于任一单科 → 自相矛盾
    contradict = SimpleNamespace(
        politics_target=60,
        english_target=60,
        math_target=150,
        major_target=150,
        total_score_target=120,
    )
    with pytest.raises(BusinessException) as ei2:
        _check_scores(contradict, {"total_score_target": 120})
    assert "矛盾" in ei2.value.message

    # 分项没填全时不做求和判断（新号只填了政治，不该被"之和"规则挡下）
    _check_scores(
        SimpleNamespace(
            politics_target=None,
            english_target=None,
            math_target=None,
            major_target=None,
            total_score_target=None,
        ),
        {"politics_target": 80},
    )


def test_score_limits_detail_is_machine_readable():
    """错误壳里的 detail 要能让前端直接渲染表单上限。"""
    from services import study_limits

    d = study_limits.score_limits_detail()
    assert d["total_max"] == 500
    assert d["part_max"]["politics_target"] == 100
    assert d["min"] == 0
    assert "500" in d["rule"]


# --------------------------------------------------------------------------- #
# 2. 今日推荐量钳制
# --------------------------------------------------------------------------- #
def test_track_clamps_whole_library_debt_to_a_daily_amount():
    """整库 5712 词到期 → 今日推荐只能是配额/上限内的合理量，差额进复习债。"""
    from services.daily_load import _track

    t = _track("review_words", "单词复习", "词", available=5712, quota=None, cap=500, default=100)
    assert t["value"] == 100
    assert t["basis"] == "system_default"
    assert t["over_quota"] == 5612
    assert "复习债" in t["note"]


def test_track_respects_user_goal_quota():
    from services.daily_load import _track

    t = _track("review_words", "单词复习", "词", available=300, quota=50, cap=500, default=100)
    assert t["value"] == 50
    assert t["basis"] == "goal"
    assert t["over_quota"] == 250


def test_track_caps_absurd_legacy_goal():
    """库里存量的历史脏值（每日 2000 词）也必须被上限压住，并说明原因。"""
    from services.daily_load import _track

    t = _track("new_words", "今日新词", "词", available=5712, quota=2000, cap=200, default=20)
    assert t["value"] == 200
    assert t["basis"] == "goal_capped"
    assert "上限" in t["note"]


def test_track_honest_zero_when_nothing_available():
    """零数据新号：库存 0 → 今日推荐 0，绝不能拿配额或系统建议量冒充任务。"""
    from services.daily_load import _track

    t = _track("new_words", "今日新词", "词", available=0, quota=20, cap=200, default=20)
    assert t["value"] == 0
    assert t["basis"] == "stock_limited"
    assert t["over_quota"] == 0


def test_track_stock_limited_below_quota():
    from services.daily_load import _track

    t = _track("questions", "刷题", "道", available=7, quota=15, cap=200, default=15)
    assert t["value"] == 7
    assert t["basis"] == "stock_limited"


def test_limits_and_track_share_one_source_of_numbers():
    """闸门与钳制必须读同一份常量：改一处不会出现"校验放宽了、推荐量没跟"。"""
    from services import daily_load, study_limits

    caps = {
        t["key"]: study_limits.DAILY_QUOTA_LIMITS[t["quota_field"]]["max"]
        for t in daily_load.TRACK_QUOTA_MAP
        if t.get("quota_field")
    }
    assert caps["new_words"] == 200
    assert caps["review_words"] == 500
    assert caps["questions"] == 200
    assert caps["focus"] == 600


def test_plan_by_key_tolerates_missing_plan():
    from services.daily_load import plan_by_key

    assert plan_by_key(None) == {}
    assert plan_by_key({"tracks": None}) == {}
    got = plan_by_key({"tracks": [{"key": "cards", "value": 30}]})
    assert got["cards"]["value"] == 30
