# -*- coding: utf-8 -*-
"""考研规划端点的「届数由数据派生」回归测试。

锁两件事：
  1. ``/plan/roadmap``、``/plan/milestones`` 不传 year 时跟随后端权威
     （``_resolve_plan_year`` → Goal 配置的届 → ``default_exam_year``），
     并把自己可选的届数一并下发 —— 前端不得再写死 ``[2026, 2027, 2028]``；
  2. ``available_years`` 是「库里真实生成过节点的届 ∪ 当前目标届」，
     生成新的一届后候选要真的多出来。

另附采集端点的参数守卫：``year`` 不能有写死的 2026 默认值，``notices`` 的
院校数上限必须是独立参数（历史上它复用 year 当 max_schools，2026 所到之处全量爬站）。
"""
from __future__ import annotations

import inspect

from routers.kaoyan.kaoyan import collection_refresh
from routers.study.plan import get_roadmap, list_milestones


def _assert_year_list_shape(years, target):
    assert isinstance(years, list) and years, "候选届不能为空（目标届至少要包含自己）"
    assert target in years, f"当前目标届 {target} 必须出现在候选里"
    assert years == sorted(set(years), reverse=True), f"候选届应去重倒序：{years}"


def test_roadmap_follows_backend_year_authority(client):
    r = client.get("/api/plan/roadmap")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["year"], int)
    _assert_year_list_shape(body["available_years"], body["year"])
    assert isinstance(body["exam_date_is_official"], bool), (
        "初试日必须带「是否官方公布」标记，未公布的届前端要显示「预估」")


def test_milestones_exposes_same_years(client):
    r = client.get("/api/plan/milestones")
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_year_list_shape(body["available_years"], body["year"])


def test_available_years_grows_after_generating_another_cohort(client):
    base = client.get("/api/plan/roadmap").json()
    extra = base["year"] + 3
    g = client.post(f"/api/plan/generate?year={extra}")
    assert g.status_code == 200, g.text

    after = client.get("/api/plan/roadmap").json()
    assert extra in after["available_years"], (
        f"已为 {extra} 届生成节点，候选里却查不到 —— available_years 又变成写死的了")
    # 不传 year 仍然回到权威推导出来的那一届，而不是列表里最大的
    assert after["year"] == base["year"]

    # 显式请求那一届时，year 字段应如实切换
    picked = client.get(f"/api/plan/roadmap?year={extra}").json()
    assert picked["year"] == extra


def test_missing_start_date_never_yields_nan_days_left(client):
    """缺 start_date 的节点必须退回初试日算天数。

    旧实现直接 `m.start_date - today`：start_date 为 None 时抛 TypeError，
    被上层吞掉后 `days_left` 变成 NaN，JSON 里出现裸 `NaN` 字面量 —— 严格
    JSON 解析器（浏览器 response.json）整页失败，前端只看到「NaN 天」。
    """
    from core.db_session import SessionLocal
    from models import Milestone

    year = client.get("/api/plan/roadmap").json()["year"]
    db = SessionLocal()
    try:
        db.add(Milestone(year=year, name="__null_start_probe__", category="测试",
                         start_date=None, importance=1, is_active=True))
        db.commit()

        for path in ("/api/plan/milestones", "/api/plan/roadmap"):
            body = client.get(path).json()
            row = next(m for m in body["milestones"] if m["name"] == "__null_start_probe__")
            assert isinstance(row["days_left"], int), (path, row["days_left"])
    finally:
        db.query(Milestone).filter(Milestone.name == "__null_start_probe__").delete()
        db.commit()
        db.close()


def _default_of(fn, name):
    """取参数默认值：FastAPI 的 ``Query(...)`` 要把 FieldInfo 解包一层。"""
    raw = inspect.signature(fn).parameters[name].default
    return getattr(raw, "default", raw)


def test_collection_refresh_has_no_frozen_year_default():
    assert _default_of(collection_refresh, "year") is None, (
        "采集年度不能写死，应由 exam_calendar 按时间推断")
    assert _default_of(collection_refresh, "max_schools") == 20, (
        "notices 源应有独立的院校数上限；历史上它拿 year 参数当 max_schools 用")


def test_plan_route_signatures_accept_optional_year():
    for fn in (get_roadmap, list_milestones):
        assert _default_of(fn, "year") is None, f"{fn.__name__} 的 year 应默认交给后端推导"
