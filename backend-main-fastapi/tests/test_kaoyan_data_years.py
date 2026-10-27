# -*- coding: utf-8 -*-
"""择校年度口径：年份只能从数据派生，库里没数据时不得回落到写死的 2026。

回归的缺陷（2026-10-17 收口）：heatmap / scatter / recommend 与择校问答把默认年份
写成 ``Query(2026)``，答案文案里还印死「2026 年……参考」。用户导入 2025/2027 的数据
后，页面默认值和话术仍停在 2026 —— 年份成了一个会过期的常量，而不是数据的属性。

单测用独立内存 SQLite（空库状态必须能真的造出来，共享测试库里全是别的用例的种子），
端测走 conftest 的临时库，只断言「与派生结果一致」而不钉死具体年份。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from core.models import KaoyanAdmission, KaoyanSchool, KaoyanScoreline
from services.kaoyan.data_years import available_years, resolve_year, year_range
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)


@pytest.fixture
def isolated_db():
    """只建本次涉及的三张表，得到一个真正空的院校库。"""
    eng = create_engine("sqlite:///:memory:")
    tables = [KaoyanSchool.__table__, KaoyanScoreline.__table__, KaoyanAdmission.__table__]
    Base.metadata.create_all(eng, tables=tables)
    db = sessionmaker(bind=eng)()
    try:
        yield db
    finally:
        db.close()


def _seed_two_years(db):
    db.add(KaoyanSchool(id=987001, name="测试院校A", province="测试省", level="211"))
    db.add_all([
        KaoyanScoreline(school_id=987001, year=2025, total_line=330),
        KaoyanScoreline(school_id=987001, year=2027, total_line=345),
        KaoyanAdmission(school_id=987001, year=2026, enroll_count=40, retest_ratio=1.2),
    ])
    db.commit()


def test_empty_library_yields_no_year(isolated_db):
    """空库：年份列表为空、解析为 None。端点据此走空态，而不是拿 2026 去查。"""
    assert available_years(isolated_db) == []
    assert resolve_year(isolated_db) is None
    assert year_range(isolated_db) == []


def test_years_union_of_both_tables_desc(isolated_db):
    """分数线表与招生表各自 DISTINCT 后取并集，倒序（最新在前）。"""
    _seed_two_years(isolated_db)
    assert available_years(isolated_db) == [2027, 2026, 2025]
    assert resolve_year(isolated_db) == 2027


def test_explicit_year_not_rewritten(isolated_db):
    """显式传入的年份原样使用，即使库里没有该年数据——不做「智能改写」。"""
    _seed_two_years(isolated_db)
    assert resolve_year(isolated_db, 2019) == 2019


def test_endpoints_default_to_library_latest():
    """三个图表/推荐端点：不传 year 时用库里最新年份，并回带 available_years。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        expected = available_years(db)
    finally:
        db.close()
    if not expected:
        pytest.skip("测试库里没有择校数据，无法验证「取最新年份」——由空库用例覆盖")
    latest = expected[0]

    for path in ("/api/kaoyan/analysis/scatter", "/api/kaoyan/analysis/heatmap"):
        r = client.get(path)
        assert r.status_code == 200, path
        body = r.json()
        assert body["year"] == latest, path
        assert body["available_years"] == expected, path

    r = client.get("/api/kaoyan/analysis/recommend", params={"score": 380})
    assert r.status_code == 200
    assert r.json()["year"] == latest


def test_empty_year_query_does_not_500():
    """传了库里没有的年份：返回空结果而不是报错，也不借用别的年份。"""
    r = client.get("/api/kaoyan/analysis/scatter", params={"year": 1991})
    assert r.status_code == 200
    body = r.json()
    assert body["year"] == 1991
    assert body["items"] == []
