# -*- coding: utf-8 -*-
"""学习目标的数值阈值（全站单一出处）：目标分数上限 + 每日配额上限。

## 为什么要有这个模块

用户实测可以把「目标总分」存成 **2000 分**（`PUT /api/goals` 原本一个上限都没校验），
也可以把「每日新词」存成 2000 词。这些数一旦落库，就会被仪表盘的进度环、
今日航线、正确率分母原样读出来，变成"今天该做 2000 项"的恐慌数字 —— 而恐慌
数字的源头是**入口没有闸门**，不是展示层不够克制。

所以把"什么数才算合理"集中写在这里，三处共用：

1. ``schemas.GoalBase`` —— Pydantic 字段硬边界（越界即 422 错误壳）；
2. ``routers/study/goals.py`` —— 跨字段自洽校验（四分项之和 / 总分），
   用 :class:`utils.exceptions.BusinessException` 返回统一错误壳；
3. ``services.daily_load`` —— 「今日推荐量」的钳制上限，保证即使库里存了
   荒谬的历史值，供数层也只会给出合理量。

## 考研满分的客观依据（不是拍脑袋）

| 科目 | 满分 | 说明 |
|------|------|------|
| 思想政治理论（101）/ 英语（201/202/204） | **100** | 全国统一命题 |
| 数学（301/302/303）等业务课一 | **150**；管理类联考综合能力（199）为 **200** | 上限取 200 容纳 199 |
| 业务课二（各校自命题） | **150**；311 教育学基础综合 / 306 临床中医综合等为 **300** | 上限取 300 容纳 3xx 综合 |
| 初试总分 | **500**（多数学术/专业硕士）；管理类联考 **300**（200+100） | 上限取 500 |

也就是说：单科上限刻意**放宽到该科目族的最大值**，总分上限取**所有专业里
初试总分的最大值 500**。这样既不挡真实的报考组合，又杜绝 2000 分。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = [
    "SCORE_TOTAL_MAX",
    "SCORE_PART_MAX",
    "SCORE_PART_LABEL",
    "DAILY_QUOTA_LIMITS",
    "score_limit_error",
    "daily_limit_error",
]

#: 目标分数下限：0 分没有意义（负数更不可能），但**允许不填**（NULL = 未设目标）。
SCORE_MIN = 0

#: 初试总分目标上限（见模块 docstring 的满分表）。
SCORE_TOTAL_MAX = 500

#: 各分项目标 → 该科目族允许的最大满分。
SCORE_PART_MAX: Dict[str, int] = {
    "politics_target": 100,  # 101 政治 / 199 管综里的数学不构成单独目标列
    "english_target": 100,  # 201 英语一 / 204 英语二
    "math_target": 200,  # 业务课一：数学 150；199 管理类综合能力 200
    "major_target": 300,  # 业务课二：自命题 150；3xx 专业基础综合 300
}

#: 校验文案用的中文名（错误信息必须说清"哪一科、上限多少、为什么"）。
SCORE_PART_LABEL: Dict[str, str] = {
    "total_score_target": "总分目标",
    "politics_target": "政治",
    "english_target": "英语",
    "math_target": "数学/业务课一",
    "major_target": "专业课/业务课二",
}

#: 每日配额：``min`` / ``max`` / ``default``（default 仅用于"用户没设目标时的系统建议量"）
#:
#: 上限取值理由（对齐主流 app 的可选区间，再往上就不是"每日目标"而是"总库量"）：
#: - 专注 600 分钟 = 一天 10 小时，再多是把"次日"排进了"今天"；
#: - 新词 200 / 复习 500：扇贝、墨墨这类产品的每日上限区间，
#:   超过 200 新词/天的记忆负荷在间隔重复理论下并不划算；
#: - 刷题 200 道：冲刺期成套训练也不会超过这个量。
DAILY_QUOTA_LIMITS: Dict[str, Dict[str, Any]] = {
    "daily_focus_minutes": {"min": 1, "max": 600, "default": 120, "label": "每日专注时长", "unit": "分钟"},
    "daily_new_words": {"min": 1, "max": 200, "default": 20, "label": "每日新词", "unit": "词"},
    "daily_review_words": {"min": 1, "max": 500, "default": 100, "label": "每日复习词量", "unit": "词"},
    "daily_questions": {"min": 1, "max": 200, "default": 15, "label": "每日刷题", "unit": "道"},
}

#: 「今日推荐量」里非目标驱动轨道的硬上限（卡片 / 错题 / 待办）。
#: 这三类没有对应的 goals 列，上限纯粹为了防止"把整库到期一坨当今日任务"。
TODAY_TRACK_CAPS: Dict[str, Dict[str, Any]] = {
    "cards": {"max": 200, "default": 50, "label": "记忆卡片", "unit": "张"},
    "errors": {"max": 200, "default": 30, "label": "错题复习", "unit": "道"},
    "tasks": {"max": 50, "default": 10, "label": "今日待办", "unit": "项"},
}


def score_limit_error(field: str, value: Any) -> Optional[str]:
    """单个分数字段的越界说明；合法返回 ``None``。

    返回**可直接展示给用户**的中文句子：说清是哪一项、传了多少、上限多少、
    上限的依据是什么。错误壳里还要带结构化的 ``field`` / ``limit``，
    见 :func:`score_limits_detail`。
    """
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return f"{SCORE_PART_LABEL.get(field, field)} 必须是整数"

    label = SCORE_PART_LABEL.get(field, field)
    if n < SCORE_MIN:
        return f"{label}不能为负数（当前 {n}）"
    limit = SCORE_TOTAL_MAX if field == "total_score_target" else SCORE_PART_MAX.get(field)
    if limit is None:
        return None
    if n > limit:
        return f"{label}目标 {n} 分超过初试满分上限 {limit} 分"
    return None


def score_limits_detail() -> Dict[str, Any]:
    """结构化上限，放进错误响应的 ``detail`` 供前端渲染表单校验。"""
    return {
        "total_max": SCORE_TOTAL_MAX,
        "part_max": dict(SCORE_PART_MAX),
        "min": SCORE_MIN,
        "rule": "考研初试总分最高 500 分（政治100+英语100+业务课一150+业务课二150；"
        "199 管理类综合能力 200 计入业务课一，3xx 专业基础综合 300 计入业务课二）",
    }


def daily_limit_error(field: str, value: Any) -> Optional[str]:
    """每日配额字段越界说明；合法返回 ``None``。"""
    spec = DAILY_QUOTA_LIMITS.get(field)
    if spec is None or value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return f"{spec['label']} 必须是整数"
    if n < spec["min"]:
        return f"{spec['label']}至少为 {spec['min']}（当前 {n}），不想设目标就留空"
    if n > spec["max"]:
        return f"{spec['label']}不能超过 {spec['max']}（当前 {n}）：那是全库总量级别，不是每日任务量"
    return None
