# -*- coding: utf-8 -*-
"""知识点按章懒加载 / 服务端检索的定向回归。

用独立内存 SQLite 直接验证查询语义，不依赖真实库；路由集成用例仍由
conftest 的测试库隔离保护。覆盖精确章名、JSON 题型、数据库分页与个人三态。
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from routers.knowledge.taxonomy import list_knowledge_points
from services import kp_mastery
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from models import KnowledgePoint


@pytest.fixture()
def memory_db():
    engine = create_engine("sqlite:///:memory:")
    KnowledgePoint.__table__.create(engine)
    with Session(engine) as db:
        yield db, engine
    engine.dispose()


def _add(db, name, *, chapter="QA-精确章", subject="数学", types=None, mastery=0):
    kp = KnowledgePoint(
        name=name,
        subject=subject,
        chapter=chapter,
        question_types=types if types is not None else ["single"],
        mastery=mastery,
        difficulty=2,
        exam_frequency=3,
        description="说明-" + name,
    )
    db.add(kp)
    db.commit()
    db.refresh(kp)
    return kp


def _list(db, *, user=None, page=1, page_size=50, **filters):
    return list_knowledge_points(db=db, user=user, page=page, page_size=page_size, **filters)


def test_endpoint_is_sync():
    assert not inspect.iscoroutinefunction(list_knowledge_points)


def test_chapter_exact_match_and_database_pagination(memory_db):
    db, engine = memory_db
    _add(db, "C-考点")
    _add(db, "A-考点")
    _add(db, "B-考点")
    _add(db, "相似章不应纳入", chapter="QA-精确章扩展")
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    first = _list(db, subject="数学", chapter="QA-精确章", page=1, page_size=2)
    second = _list(db, subject="数学", chapter="QA-精确章", page=2, page_size=2)
    event.remove(engine, "before_cursor_execute", capture)

    assert first["total"] == second["total"] == 3
    assert first["total_pages"] == 2
    assert [x["name"] for x in first["items"]] == ["A-考点", "B-考点"]
    assert [x["name"] for x in second["items"]] == ["C-考点"]
    assert all(x["chapter"] == "QA-精确章" for x in first["items"] + second["items"])
    sql = "\n".join(statements).lower()
    assert "count(" in sql, "total 必须走 count query"
    assert "order by" in sql and "limit" in sql and "offset" in sql
    assert first["items"][0]["description"] == "说明-A-考点"
    assert "mastery" not in first["items"][0], "访客个人字段必须剔除"


def test_keyword_and_json_question_type_are_server_filters(memory_db):
    db, _engine = memory_db
    _add(db, "极限存在", types=["single", "judge"])
    _add(db, "左右极限", types=["single_choice"])
    _add(db, "极限相似", chapter="另一章", types=["essay"])

    by_keyword = _list(db, keyword="极限")
    assert by_keyword["total"] == 3
    assert {x["name"] for x in by_keyword["items"]} == {"极限存在", "左右极限", "极限相似"}

    by_type = _list(db, question_type="single")
    assert [x["name"] for x in by_type["items"]] == ["极限存在"], "JSON 元素必须精确匹配，不能命中 single_choice"
    combined = _list(db, keyword="左右", question_type="single_choice", chapter="QA-精确章")
    assert [x["name"] for x in combined["items"]] == ["左右极限"]


def test_uncategorized_tree_node_loads_null_and_empty_chapters(memory_db):
    db, _engine = memory_db
    _add(db, "无章节", chapter=None)
    _add(db, "空章节", chapter="")
    _add(db, "相似未归章", chapter="未归章扩展")

    result = _list(db, chapter="未归章")
    assert result["total"] == 2
    assert {x["name"] for x in result["items"]} == {"无章节", "空章节"}


def test_low_mastery_keeps_user_scoped_three_states(memory_db, monkeypatch):
    db, _engine = memory_db
    learning = _add(db, "学习中", mastery=10)
    mastered = _add(db, "已掌握", mastery=90)
    _add(db, "未学", mastery=0)
    seen_user_ids = []

    def learned(_session, user_id=None):
        seen_user_ids.append(user_id)
        return {learning.id, mastered.id}

    monkeypatch.setattr(kp_mastery, "learned_kp_ids", learned)
    user = SimpleNamespace(id=7)
    result = _list(db, user=user, low_mastery=True)
    assert seen_user_ids == [7]
    assert result["total"] == 1
    assert result["items"][0]["state"] == "learning"
    assert result["items"][0]["mastery"] == 10

    anonymous = _list(db, user=None, low_mastery=True)
    assert anonymous["total"] == 0 and anonymous["items"] == []
