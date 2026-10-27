"""仪表盘「近年复试线」的取数口径。

线上曾出现的错法：按年份 ``order by year desc limit 3`` 直接取原始行，
而一所院校同一年会命中几十个专业/方向的分数线，于是三根柱子全是同一年
（2026 哲学 326 / 2026 应用经济学 324 / 2026 金融 377），目标专业却一个都没对上。

这里锁两条：
1. 一年一根柱，按目标专业过滤后逐年取最低线；
2. 目标专业对不上时退回全校最低线，并如实返回 ``scope="school"``。
"""
from __future__ import annotations

import pytest

from models import KaoyanSchool, KaoyanScoreLine

MARK = "__score_lines_test_school__"


@pytest.fixture()
def db(db_schema):  # noqa: ARG001 — db_schema 负责建表
    from database import SessionLocal

    s = SessionLocal()
    old = s.query(KaoyanSchool).filter(KaoyanSchool.name == MARK).all()
    for school in old:
        s.query(KaoyanScoreLine).filter(KaoyanScoreLine.school_id == school.id).delete()
        s.delete(school)
    s.commit()

    school = KaoyanSchool(name=MARK)
    s.add(school)
    s.flush()
    rows = [
        # 2026：目标专业两行（不同院系），另有别的专业
        (2026, "085400", "电子信息", 320),
        (2026, "085400", "电子信息", 280),
        (2026, "030100", "法学", 350),
        # 全校最低与目标专业最低不同，用来区分两种口径
        (2026, "040100", "教育学", 250),
        # 2025 / 2024
        (2025, "085400", "电子信息", 300),
        (2025, "030100", "法学", 360),
        (2024, "085400", "电子信息", 290),
        (2024, "030100", "法学", 370),
        # 2023：用来验证 limit=3 只保留最近三年
        (2023, "085400", "电子信息", 200),
    ]
    s.add_all(
        [
            KaoyanScoreLine(
                school_id=school.id,
                year=year,
                major_code=code,
                major_name=name,
                total_line=total,
            )
            for year, code, name, total in rows
        ]
    )
    s.commit()
    try:
        yield s, school.id
    finally:
        s.query(KaoyanScoreLine).filter(KaoyanScoreLine.school_id == school.id).delete()
        s.query(KaoyanSchool).filter(KaoyanSchool.id == school.id).delete()
        s.commit()
        s.close()


def test_one_bar_per_year_for_target_major(db):
    from services.dashboard_service import DashboardService

    session, _ = db
    got = DashboardService._recent_score_lines(session, MARK, "电子信息（0854）")
    assert [r["year"] for r in got] == [2024, 2025, 2026]
    assert [r["total_line"] for r in got] == [290, 300, 280]
    assert {r["scope"] for r in got} == {"major"}


def test_falls_back_to_school_min_when_major_unknown(db):
    from services.dashboard_service import DashboardService

    session, _ = db
    got = DashboardService._recent_score_lines(session, MARK, "不存在的专业")
    assert [r["year"] for r in got] == [2024, 2025, 2026]
    assert [r["total_line"] for r in got] == [290, 300, 250]
    assert {r["scope"] for r in got} == {"school"}


def test_unknown_school_returns_empty(db):
    from services.dashboard_service import DashboardService

    session, _ = db
    assert DashboardService._recent_score_lines(session, "不存在的院校", "电子信息（0854）") == []
    assert DashboardService._recent_score_lines(session, None, None) == []
