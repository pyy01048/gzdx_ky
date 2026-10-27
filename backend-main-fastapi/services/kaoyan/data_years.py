# -*- coding: utf-8 -*-
"""择校分析的「年度」唯一出口。

为什么要单独一个模块（而不是各端点各写各的）：
以前 heatmap / scatter / recommend 都把默认年份写成 ``Query(2026)``，AI 问答话术里
还直接印死「2026 年招生人数较多的院校参考」。用户导入的是 2025 或 2027 的数据时，
页面默认值与文案都还停在 2026 —— 年份于是变成一个会过期的常量，而不是数据的属性。

口径：年份只能从已入库的 ``kaoyan_scorelines.year`` / ``kaoyan_admissions.year`` 派生。
库里没有数据时返回空列表 / None，由上层显示空态；**绝不回落到某个写死的年份**。
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func

from core.models import KaoyanAdmission, KaoyanScoreline

#: 参与年度派生的表（表名, 模型）。新增按年组织的数据源时只改这里。
_YEAR_SOURCES = (("分数线", KaoyanScoreline), ("招生", KaoyanAdmission))


def available_years(db) -> List[int]:
    """库里真实存在数据的年份，倒序（最新在前）。

    各表分别 DISTINCT 再并集：某校只有招生表有 2024、只有分数线表有 2025 时，
    两个年份都应当出现在下拉里，否则用户切过去看不到任何内容还以为坏了。
    """
    years: set[int] = set()
    for _label, model in _YEAR_SOURCES:
        rows = db.query(model.year).distinct().all()
        years.update(int(r[0]) for r in rows if r[0] is not None)
    return sorted(years, reverse=True)


def resolve_year(db, year: Optional[int] = None) -> Optional[int]:
    """确定本次查询使用的年份。

    - 调用方显式传了年份 → 原样使用（即使库里没有该年数据，也只是查出来为空，
      这是用户的选择，不做「智能改写」）。
    - 没传 → 用库里最新的年份。
    - 库里没有任何年份数据 → None，调用方必须走空态分支，不能猜。
    """
    if year is not None:
        return int(year)
    years = available_years(db)
    return years[0] if years else None


def year_range(db, fallback: Optional[int] = None) -> List[int]:
    """下拉候选年份：库里有数据的那些。

    空库时返回 ``fallback`` 对应的单元素列表（如果给了），否则返回空列表 ——
    前端据此决定是渲染选择器还是渲染空态。
    """
    years = available_years(db)
    if years:
        return years
    return [fallback] if fallback is not None else []
