# -*- coding: utf-8 -*-
"""review_history 脏数据防线回归（实测 5492 行事故锁）。

历史导入曾把 JSONB 的 review_history 写成 {}（对象）；API 契约 review_history
是数组。条目序列化（WordOut.review_history 的 field_validator）此前没有防线，
一行脏数据就让 GET /api/words 整体 500 —— 列表、页首词、页面预热全部失败。

锁三件事：
1. `{}` 归一为 []，GET /api/words 对这样的行返回 200；
2. {"0": {...}} 数字键形态归一为 values 组成的数组，真实历史不丢；
3. 正常 list 数据原样透传（防线不能误伤）。

隔离纪律：words 是本人数据，沿用 test_words_list_status_contract 的做法 ——
自建契约用户、uuid 命名词、用例自清。
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from database import SessionLocal
from models import User, Word
from tests.asgi_client import ASGIClient
from main import app
from utils.security import current_user

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _owner_user():
    db = SessionLocal()
    try:
        u = User(username=f"rhguard{uuid.uuid4().hex[:8]}", display_name="历史防线",
                 role="user", is_active=True)
        u.password_hash = "test-placeholder-never-used-for-login"
        db.add(u)
        db.commit()
        uid, uname = u.id, u.username
    finally:
        db.close()

    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        id=uid, username=uname, role="user",
    )
    yield uid
    # 恢复 conftest.auth_bypass 的默认桩（不能 pop，否则后续测试文件全部 401）
    from utils.security import stub_principal
    app.dependency_overrides[current_user] = lambda: stub_principal()

    db = SessionLocal()
    try:
        db.query(Word).filter(Word.user_id == uid,
                              Word.word.like("rhguard%")).delete(synchronize_session=False)
        db.query(User).filter(User.id == uid).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _make_word(owner_id: int, **kwargs) -> str:
    name = f"rhguard{uuid.uuid4().hex[:10]}"
    db = SessionLocal()
    try:
        db.add(Word(word=name, meaning="历史防线测试词", user_id=owner_id, **kwargs))
        db.commit()
    finally:
        db.close()
    return name


def test_empty_dict_history_does_not_break_list(_owner_user):
    """事故主线：{} 行必须 200，且归一为 []。"""
    name = _make_word(_owner_user, review_history={})
    r = client.get("/api/words", params={"search": name})
    assert r.status_code == 200
    item = next(w for w in r.json()["items"] if w["word"] == name)
    assert item["review_history"] == []


def test_numbered_dict_history_lossless_convert(_owner_user):
    """数字键 dict（{"0": {...}}）-> 数组，历史记录不丢。"""
    history = {"0": {"date": "2026-10-01", "grade": 3}}
    name = _make_word(_owner_user, review_history=history)
    r = client.get("/api/words", params={"search": name})
    assert r.status_code == 200
    item = next(w for w in r.json()["items"] if w["word"] == name)
    assert item["review_history"] == [
        {"date": "2026-10-01", "grade": 3},
    ]


def test_list_history_passes_through(_owner_user):
    """正常 list 数据原样透传，防线不误伤。"""
    history = [{"date": "2026-10-02", "grade": 4}, {"date": "2026-10-03", "grade": 5}]
    name = _make_word(_owner_user, review_history=history)
    r = client.get("/api/words", params={"search": name})
    assert r.status_code == 200
    item = next(w for w in r.json()["items"] if w["word"] == name)
    assert item["review_history"] == history


def test_none_history_stays_none(_owner_user):
    name = _make_word(_owner_user, review_history=None)
    r = client.get("/api/words", params={"search": name})
    assert r.status_code == 200
    item = next(w for w in r.json()["items"] if w["word"] == name)
    assert item["review_history"] is None
