"""科目配置的「未配置 = 空」契约（P1 去硬编码）。

锁住的行为
----------
`GET /api/goals/subjects` 在用户没有配置备考科目时，`exam_subjects` /
`support_subjects` 必须是**空列表**，而不是回填 `taxonomy.CORE_SUBJECTS`
（数电/模电/数学/英语/政治/真题）。

历史 bug：没有 Goal 配置时，后端把这套内置科目当成"这位用户的备考科目"下发。
前端据此渲染进度分母、科目筛选、AI 画像，于是换一个不是考数电的人来用，
界面仍然宣称他考数电；而内置目录（`all_known` / `core_defaults`）本来只该回答
"系统认识哪些科目"，不该回答"你考什么"。
"""
from __future__ import annotations

import pytest

from models import Goal


@pytest.fixture
def no_goal_config():
    """临时清空 Goal 配置，用例结束原样恢复（测试库是 session 级共享的）。

    本用例会走 PUT，set_config 在库里没有 Goal 行时会新建一行；若基线本来没有，
    结束时把新建的行删掉，避免把"尚未设置目标"状态永久改成"有目标但没科目"。
    """
    from database import SessionLocal

    db = SessionLocal()
    try:
        baseline = db.query(Goal).all()
        saved = [(g.id, g.subject_codes, g.support_subject_codes) for g in baseline]
        for g in baseline:
            g.subject_codes = None
            g.support_subject_codes = None
        db.commit()
        yield db
    finally:
        known = {gid for gid, _, _ in saved}
        for g in db.query(Goal).all():
            if g.id not in known:
                db.delete(g)
        for gid, codes, support in saved:
            row = db.get(Goal, gid)
            if row is not None:
                row.subject_codes, row.support_subject_codes = codes, support
        db.commit()
        db.close()


def test_unconfigured_returns_empty_not_builtin_default(client, no_goal_config):  # noqa: ARG001
    r = client.get("/api/goals/subjects")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["exam_subjects"] == [], f"未配置却被回填了内置科目：{body['exam_subjects']}"
    assert body["support_subjects"] == []
    assert body["active_subjects"] == []
    assert body["using_default"] is True

    # 内置目录仍然可用——它是"系统认识哪些科目"，与"你考什么"是两件事
    assert body["core_defaults"], "core_defaults 应作为建议默认值继续下发"
    assert body["all_known"], "all_known（科目目录）不能因为用户未配置就变空"


def test_clearing_all_subjects_stays_empty(client, no_goal_config):  # noqa: ARG001
    """显式清空后不能"回退默认"：用户把科目删干净，界面就该是空的。"""
    r = client.put("/api/goals/subjects", json={"exam_subjects": ["数学"], "support_subjects": ["电路"]})
    assert r.status_code == 200, r.text
    assert r.json()["exam_subjects"] == ["数学"], r.json()
    assert r.json()["using_default"] is False

    r2 = client.put("/api/goals/subjects", json={"exam_subjects": [], "support_subjects": []})
    assert r2.status_code == 200, r2.text
    assert r2.json()["exam_subjects"] == []
    assert r2.json()["support_subjects"] == []
