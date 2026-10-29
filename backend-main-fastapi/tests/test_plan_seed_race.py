# -*- coding: utf-8 -*-
"""P1-2 回归：规划页首载 /plan/roadmap 与 /plan/milestones 并发补种子时不得 500。

前端用 Promise.all 同时打两个端点；某一届尚无节点时两边都会调 ``_seed_milestones``，
后提交的一方撞 ``uq_milestone_year_name`` 唯一约束。这里用确定性的方式复现：
让另一个会话在本会话 commit 之前抢先把同一届种子写进去。
"""
from __future__ import annotations

import pytest

from models import Milestone
from routers.study.plan import MILESTONE_SPECS, _seed_milestones

RACE_YEAR = 2099


@pytest.fixture()
def sessions(db_schema):  # noqa: ARG001
    from database import SessionLocal

    a, b = SessionLocal(), SessionLocal()
    yield a, b
    for s in (a, b):
        s.rollback()
    b.query(Milestone).filter(Milestone.year == RACE_YEAR).delete()
    b.commit()
    a.close()
    b.close()


def test_losing_the_seed_race_returns_winner_rows_instead_of_raising(sessions):
    a, b = sessions
    real_commit = a.commit

    def commit_after_rival_wins():
        a.commit = real_commit
        _seed_milestones(b, RACE_YEAR)
        real_commit()

    a.commit = commit_after_rival_wins
    rows = _seed_milestones(a, RACE_YEAR)

    assert len(rows) == len(MILESTONE_SPECS)
    assert {m.name for m in rows} == {s["name"] for s in MILESTONE_SPECS}
    assert all(m.id is not None for m in rows)
    total = b.query(Milestone).filter(Milestone.year == RACE_YEAR).count()
    assert total == len(MILESTONE_SPECS), "败者不能写出重复节点"
