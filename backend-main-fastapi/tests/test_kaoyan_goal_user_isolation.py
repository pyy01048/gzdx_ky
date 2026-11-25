# -*- coding: utf-8 -*-
"""推荐院校设目标：当前用户隔离与可选目标分契约回归。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from database import SessionLocal
from utils.security import current_user

from models import Goal, KaoyanSchool, User

UID_A = 928001
UID_B = 928002


def _principal(uid: int) -> SimpleNamespace:
    return SimpleNamespace(id=uid, username=f"goal_iso_{uid}", role="user", is_active=True)


@pytest.fixture()
def goal_iso(app_module, db_schema):  # noqa: ARG001
    db = SessionLocal()
    previous = app_module.dependency_overrides.get(current_user)
    school_ids = []
    legacy_id = None
    try:
        for uid in (UID_A, UID_B):
            if not db.query(User).filter(User.id == uid).first():
                db.add(
                    User(
                        id=uid,
                        username=f"goal_iso_{uid}",
                        password_hash="!disabled-goal-isolation-test",
                        role="user",
                        is_active=True,
                        must_change_password=False,
                        token_version=0,
                    )
                )
        db.flush()
        schools = [
            KaoyanSchool(name="目标隔离测试院校A1"),
            KaoyanSchool(name="目标隔离测试院校A2"),
            KaoyanSchool(name="目标隔离测试院校B"),
        ]
        db.add_all(schools)
        db.flush()
        school_ids = [school.id for school in schools]
        legacy = Goal(user_id=None, university="隔离测试遗留目标", total_score_target=999)
        db.add(legacy)
        db.flush()
        legacy_id = legacy.id
        db.commit()

        def login(uid: int) -> None:
            app_module.dependency_overrides[current_user] = lambda: _principal(uid)

        yield SimpleNamespace(
            login=login,
            school_ids=school_ids,
            legacy_id=legacy_id,
        )
    finally:
        if previous is None:
            app_module.dependency_overrides.pop(current_user, None)
        else:
            app_module.dependency_overrides[current_user] = previous
        db.rollback()
        db.query(Goal).filter(Goal.user_id.in_((UID_A, UID_B))).delete(synchronize_session=False)
        if legacy_id is not None:
            db.query(Goal).filter(Goal.id == legacy_id).delete(synchronize_session=False)
        if school_ids:
            db.query(KaoyanSchool).filter(KaoyanSchool.id.in_(school_ids)).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_((UID_A, UID_B))).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_recommend_goal_is_isolated_and_preserves_omitted_score(client, goal_iso):
    school_a1, school_a2, school_b = goal_iso.school_ids
    goal_iso.login(UID_A)
    first = client.post(
        f"/api/kaoyan/analysis/recommend/{school_a1}/set-goal",
        params={"target_score": 350},
    )
    assert first.status_code == 200, first.text
    assert first.json() == {
        "success": True,
        "goal_university": "目标隔离测试院校A1",
        "target_score": 350,
    }

    goal_iso.login(UID_B)
    second = client.post(f"/api/kaoyan/analysis/recommend/{school_b}/set-goal")
    assert second.status_code == 200, second.text
    assert second.json()["target_score"] is None

    goal_iso.login(UID_A)
    third = client.post(f"/api/kaoyan/analysis/recommend/{school_a2}/set-goal")
    assert third.status_code == 200, third.text
    assert third.json()["target_score"] is None

    db = SessionLocal()
    try:
        goals_a = db.query(Goal).filter(Goal.user_id == UID_A).all()
        goals_b = db.query(Goal).filter(Goal.user_id == UID_B).all()
        assert len(goals_a) == 1
        assert len(goals_b) == 1
        assert goals_a[0].university == "目标隔离测试院校A2"
        assert goals_a[0].total_score_target == 350
        assert goals_b[0].university == "目标隔离测试院校B"
        assert goals_b[0].total_score_target is None
        legacy = db.query(Goal).filter(Goal.id == goal_iso.legacy_id).one()
        assert legacy.university == "隔离测试遗留目标"
        assert legacy.total_score_target == 999
    finally:
        db.close()


def test_recommend_goal_requires_authentication(client, app_module, goal_iso):  # noqa: ARG001
    previous = app_module.dependency_overrides.pop(current_user)
    try:
        response = client.post(f"/api/kaoyan/analysis/recommend/{goal_iso.school_ids[0]}/set-goal")
        assert response.status_code == 401, response.text
    finally:
        app_module.dependency_overrides[current_user] = previous
