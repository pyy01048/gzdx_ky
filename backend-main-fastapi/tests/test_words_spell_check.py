# -*- coding: utf-8 -*-
"""拼写练习接口测试（对标「不背单词」拼写模式）。

覆盖：
1. POST /api/words/spell-check 拼写正确 → correct=True，并记录复习（reps+1、状态 learning）；
2. 拼写错误 → correct=False，lapses+1（grade=1 重来）；
3. record_review=False → 只判对错，不改变调度字段；
4. 大小写不敏感、忽略首尾空白；
5. 不存在的单词 → 404。
"""
from __future__ import annotations

import datetime
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
        u = User(username=f"spell{uuid.uuid4().hex[:8]}", display_name="拼写测试用户",
                 role="user", is_active=True)
        u.password_hash = "test-placeholder-never-used-for-login"
        db.add(u)
        db.commit()
        uid = u.id
    finally:
        db.close()

    app.dependency_overrides[current_user] = lambda: SimpleNamespace(
        id=uid, username=f"spell{uuid.uuid4().hex[:8]}", role="user",
    )
    yield uid
    from utils.security import stub_principal
    app.dependency_overrides[current_user] = lambda: stub_principal()

    db = SessionLocal()
    try:
        # B4：fsrs.schedule 会写 review_schedules（user_id 外键），先清理再删用户
        db.execute(__import__("sqlalchemy").text(
            "DELETE FROM review_schedules WHERE user_id = :uid"
        ), {"uid": uid})
        db.query(Word).filter(Word.user_id == uid,
                              Word.word.like("spelltest%")).delete(synchronize_session=False)
        db.query(User).filter(User.id == uid).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _make_word(owner_id: int, name: str = None) -> Word:
    name = name or f"spelltest{uuid.uuid4().hex[:10]}"
    db = SessionLocal()
    try:
        w = Word(word=name, meaning="拼写测试词", phonetic="/test/", pos="n.",
                 status="not_mastered", due_date=datetime.date.today(), user_id=owner_id)
        db.add(w)
        db.commit()
        db.refresh(w)
        return w
    finally:
        db.close()


def _check(word_id: int, answer: str, record_review: bool = True):
    body = {"word_id": word_id, "answer": answer}
    if not record_review:
        body["record_review"] = False
    return client.post("/api/words/spell-check", json=body)


def test_spell_correct_records_review(_owner_user):
    w = _make_word(_owner_user, "spelltestapple")
    r = _check(w.id, "SPELLTESTAPPLE")  # 大小写不敏感
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["correct"] is True
    assert body["word"] == "spelltestapple"
    assert body["meaning"] == "拼写测试词"
    # 自动记录复习：reps=1、状态 learning、lapses 不变
    assert body["review"] is not None
    assert body["review"]["reps"] == 1
    assert body["review"]["status"] == "learning"
    assert body["review"]["lapses"] == 0


def test_spell_wrong_increments_lapses(_owner_user):
    w = _make_word(_owner_user, "spelltestbanana")
    r = _check(w.id, "banana")  # 拼错
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["correct"] is False
    assert body["user_answer"] == "banana"
    # 错误=grade 1 → lapses+1；SM-2 失败时 reps 重置为 0
    assert body["review"]["lapses"] == 1
    assert body["review"]["reps"] == 0


def test_spell_no_record_review_keeps_schedule(_owner_user):
    w = _make_word(_owner_user, "spelltestcherry")
    r = _check(w.id, "spelltestcherry", record_review=False)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["correct"] is True
    assert body["review"] is None
    # 调度字段未被改动
    db = SessionLocal()
    try:
        fresh = db.query(Word).filter(Word.id == w.id).first()
        assert fresh.reps == 0
        assert fresh.status == "not_mastered"
    finally:
        db.close()


def test_spell_strips_whitespace(_owner_user):
    w = _make_word(_owner_user, "spelltestdurian")
    r = _check(w.id, "  spelltestdurian  ")
    assert r.status_code == 200, r.text
    assert r.json()["correct"] is True


def test_spell_missing_word_404(_owner_user):
    r = client.post("/api/words/spell-check", json={"word_id": 99999999, "answer": "x"})
    assert r.status_code == 404